from __future__ import annotations

import atexit
import ctypes
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import cv2
import numpy as np
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.utils import timezone

from .models import FireEvent

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ultralytics import YOLO


def to_short_path_if_possible(path: Path) -> str:
    resolved = path.resolve()
    if os.name != 'nt':
        return str(resolved)

    required_len = ctypes.windll.kernel32.GetShortPathNameW(str(resolved), None, 0)
    if required_len <= 0:
        return str(resolved)

    short_buffer = ctypes.create_unicode_buffer(required_len)
    result_len = ctypes.windll.kernel32.GetShortPathNameW(str(resolved), short_buffer, required_len)
    if result_len <= 0:
        return str(resolved)
    return short_buffer.value


def normalize_camera_source(source: str) -> int | str:
    text = str(source).strip()
    if text.isdigit():
        return int(text)

    if text.startswith(('rtsp://', 'http://', 'https://')):
        return text

    local_path = Path(text).expanduser()
    if local_path.exists():
        return to_short_path_if_possible(local_path)

    raise ValueError(f'Source not found: {source}')


class DetectionManager:
    VIDEO_SUFFIXES = {
        '.mp4',
        '.avi',
        '.mov',
        '.mkv',
        '.wmv',
        '.m4v',
        '.webm',
    }

    def __init__(self) -> None:
        self._model: YOLO | None = None
        self._capture: cv2.VideoCapture | None = None
        self._capture_lock = threading.Lock()
        self._state_lock = threading.Lock()

        self._running = False
        self._worker: threading.Thread | None = None

        self._source_text = str(settings.DEFAULT_CAMERA_SOURCE)
        self._source_value = normalize_camera_source(self._source_text)

        self._conf = settings.YOLO_CONF
        self._iou = settings.YOLO_IOU
        self._imgsz = settings.YOLO_IMGSZ
        self._device = settings.YOLO_DEVICE or None
        self._infer_interval = float(getattr(settings, 'YOLO_INFER_INTERVAL', 0.12))
        self._jpeg_quality = int(getattr(settings, 'STREAM_JPEG_QUALITY', 72))
        self._target_fps = max(1.0, float(getattr(settings, 'STREAM_TARGET_FPS', 20.0)))
        self._input_max_width = int(getattr(settings, 'STREAM_INPUT_MAX_WIDTH', 960))
        self._fire_keywords = tuple(k.lower() for k in settings.FIRE_LABEL_KEYWORDS)
        self._smoke_keywords = tuple(k.lower() for k in settings.SMOKE_LABEL_KEYWORDS)
        self._event_cooldown = float(settings.EVENT_COOLDOWN_SECONDS)

        self._last_alert_at = {
            FireEvent.SMOKE_DETECTED: 0.0,
            FireEvent.FIRE_ALERT: 0.0,
        }
        self._last_status_emit = 0.0

        self._latest_frame = self._build_placeholder_frame('Waiting for camera stream...')
        self._status = {
            'state': FireEvent.SAFE,
            'source': self._source_text,
            'label': '',
            'confidence': 0.0,
            'message': FireEvent.SAFE,
            'updated_at': timezone.now().isoformat(),
        }

    def _get_model(self) -> YOLO:
        if self._model is None:
            logger.info("_get_model: loading YOLO model...")
            from ultralytics import YOLO

            weights_path = Path(settings.YOLO_WEIGHTS_PATH)
            if not weights_path.exists():
                raise FileNotFoundError(f'Model not found: {weights_path}')
            logger.info(f"_get_model: YOLO path: {weights_path}")
            logger.info("_get_model: initializing YOLO...")
            self._model = YOLO(to_short_path_if_possible(weights_path))
            logger.info("_get_model: YOLO model loaded successfully")
        return self._model

    def _is_local_video_source(self) -> bool:
        if isinstance(self._source_value, int):
            return False

        source = str(self._source_text)
        if source.startswith(('rtsp://', 'http://', 'https://')):
            return False

        suffix = Path(source).suffix.lower()
        return suffix in self.VIDEO_SUFFIXES

    def _try_restart_video_file_locked(self) -> tuple[bool, Any]:
        if self._capture is None or not self._is_local_video_source():
            return False, None

        self._capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
        return self._capture.read()

    def _build_placeholder_frame(self, message: str) -> bytes:
        frame = np.zeros((360, 640, 3), dtype=np.uint8)
        cv2.putText(
            frame,
            'YOLO FIRE MONITOR',
            (24, 56),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (0, 190, 255),
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            frame,
            message,
            (24, 108),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.72,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )

        ok, encoded = cv2.imencode('.jpg', frame)
        return encoded.tobytes() if ok else b''

    def _release_capture_locked(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None

    def _open_capture_locked(self) -> bool:
        self._release_capture_locked()
        self._capture = cv2.VideoCapture(self._source_value)
        if self._capture is None or not self._capture.isOpened():
            self._release_capture_locked()
            return False
        # Keep capture buffer shallow so stream follows newest frame.
        self._capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return True

    def _downscale_for_processing(self, frame: np.ndarray) -> np.ndarray:
        if self._input_max_width <= 0:
            return frame
        height, width = frame.shape[:2]
        if width <= self._input_max_width:
            return frame
        ratio = self._input_max_width / float(width)
        new_size = (self._input_max_width, max(1, int(height * ratio)))
        return cv2.resize(frame, new_size, interpolation=cv2.INTER_AREA)

    def start(self) -> None:
        if sys.is_finalizing():
            return

        with self._state_lock:
            if self._running:
                logger.info("Detection manager already running")
                return
            self._running = True
            logger.info("Starting detection manager...")

        self._worker = threading.Thread(target=self._run_loop, daemon=True, name='yolo-monitor')
        self._worker.start()
        logger.info("Detection worker thread started")

    def stop(self) -> None:
        with self._state_lock:
            self._running = False
            worker = self._worker
            self._worker = None

        with self._capture_lock:
            self._release_capture_locked()

        if worker is not None and worker.is_alive() and worker is not threading.current_thread():
            worker.join(timeout=1.0)

    def set_source(self, source: str) -> dict[str, Any]:
        source_text = str(source).strip()
        if not source_text:
            raise ValueError('source cannot be empty')

        source_value = normalize_camera_source(source_text)
        with self._capture_lock:
            self._source_text = source_text
            self._source_value = source_value
            self._release_capture_locked()

        self._push_status(FireEvent.SAFE, '', 0.0, message='Switching camera source...')
        return self.get_status()

    def get_status(self) -> dict[str, Any]:
        with self._state_lock:
            return dict(self._status)

    def get_frame(self) -> bytes:
        with self._state_lock:
            frame = bytes(self._latest_frame)
            if len(frame) > 1000:
                logger.debug(f"get_frame returning {len(frame)} bytes")
            return frame

    def get_events(self, limit: int = 50) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 200))
        events = FireEvent.objects.order_by('-created_at')[:safe_limit]
        return [event.to_payload() for event in events]

    def _broadcast(self, payload: dict[str, Any]) -> None:
        if sys.is_finalizing():
            return

        channel_layer = get_channel_layer()
        if channel_layer is None:
            return
        try:
            async_to_sync(channel_layer.group_send)(
                'alerts',
                {
                    'type': 'alert_message',
                    'payload': payload,
                },
            )
        except RuntimeError:
            # Can happen while the Python interpreter is shutting down.
            return
        except Exception:
            return

    def _classify_result(self, result: Any) -> tuple[str, str, float]:
        fire_conf = 0.0
        smoke_conf = 0.0
        fire_label = ''
        smoke_label = ''

        names = result.names or {}
        boxes = result.boxes
        if boxes is None or len(boxes) == 0:
            return FireEvent.SAFE, '', 0.0

        for box in boxes:
            cls_idx = int(box.cls[0].item())
            conf = float(box.conf[0].item())
            label = str(names.get(cls_idx, cls_idx)).lower()

            if any(keyword in label for keyword in self._fire_keywords) and conf > fire_conf:
                fire_conf = conf
                fire_label = label

            if any(keyword in label for keyword in self._smoke_keywords) and conf > smoke_conf:
                smoke_conf = conf
                smoke_label = label

        if fire_conf >= self._conf:
            return FireEvent.FIRE_ALERT, fire_label, fire_conf
        if smoke_conf >= self._conf:
            return FireEvent.SMOKE_DETECTED, smoke_label, smoke_conf
        return FireEvent.SAFE, '', 0.0

    def _draw_status_overlay(self, frame: np.ndarray, state: str, confidence: float) -> None:
        if state == FireEvent.FIRE_ALERT:
            color = (0, 0, 255)
        elif state == FireEvent.SMOKE_DETECTED:
            color = (0, 165, 255)
        else:
            color = (0, 200, 0)

        label = state if state == FireEvent.SAFE else f'{state} ({confidence:.2f})'
        cv2.rectangle(frame, (0, 0), (frame.shape[1], 48), (22, 22, 22), -1)
        cv2.putText(frame, label, (12, 33), cv2.FONT_HERSHEY_SIMPLEX, 0.85, color, 2, cv2.LINE_AA)

    def _should_log_event(self, state: str) -> bool:
        if state not in (FireEvent.SMOKE_DETECTED, FireEvent.FIRE_ALERT):
            return False

        now = time.time()
        last = self._last_alert_at.get(state, 0.0)
        if now - last < self._event_cooldown:
            return False

        self._last_alert_at[state] = now
        return True

    def _persist_event(self, state: str, label: str, confidence: float) -> FireEvent | None:
        try:
            return FireEvent.objects.create(
                source=self._source_text,
                status=state,
                label=label,
                confidence=confidence,
                details={'source': self._source_text},
            )
        except Exception:
            return None

    def _push_status(self, state: str, label: str, confidence: float, message: str | None = None) -> None:
        now_iso = timezone.now().isoformat()
        with self._state_lock:
            previous_state = self._status.get('state', FireEvent.SAFE)
            previous_label = self._status.get('label', '')
            self._status = {
                'state': state,
                'source': self._source_text,
                'label': label,
                'confidence': round(confidence, 4),
                'message': message or state,
                'updated_at': now_iso,
            }

        now = time.time()
        changed = previous_state != state or previous_label != label
        if changed or (now - self._last_status_emit >= 1.5):
            self._last_status_emit = now
            self._broadcast({'type': 'status_update', 'status': self.get_status()})

        if self._should_log_event(state):
            event = self._persist_event(state, label, confidence)
            if event is not None:
                self._broadcast({'type': 'event_log', 'event': event.to_payload()})

    def _run_loop(self) -> None:
        logger.info("_run_loop started")
        last_infer_at = 0.0
        latest_state = FireEvent.SAFE
        latest_label = ''
        latest_confidence = 0.0
        try:
            while True:
                with self._state_lock:
                    if not self._running:
                        logger.info("_run_loop: _running set to False, breaking")
                        break

                if sys.is_finalizing():
                    logger.info("_run_loop: sys is finalizing, breaking")
                    break

                try:
                    logger.debug("_run_loop: loading model...")
                    model = self._get_model()
                    logger.debug("_run_loop: model loaded")
                except Exception as error:
                    logger.error(f"_run_loop: model load error: {error}", exc_info=True)
                    with self._state_lock:
                        self._latest_frame = self._build_placeholder_frame(str(error))
                    self._push_status(FireEvent.SAFE, '', 0.0, message='Model not available')
                    time.sleep(1.0)
                    continue

                with self._capture_lock:
                    if self._capture is None or not self._capture.isOpened():
                        opened = self._open_capture_locked()
                    else:
                        opened = True

                    if not opened or self._capture is None:
                        frame_ok = False
                        frame = None
                    else:
                        # Drop stale buffered frames to reduce end-to-end latency.
                        for _ in range(2):
                            self._capture.grab()
                        frame_ok, frame = self._capture.read()
                        if not frame_ok or frame is None:
                            frame_ok, frame = self._try_restart_video_file_locked()

                if not frame_ok or frame is None:
                    with self._state_lock:
                        self._latest_frame = self._build_placeholder_frame('No signal from camera source')
                    self._push_status(FireEvent.SAFE, '', 0.0, message='No signal from camera source')
                    time.sleep(0.35)
                    continue

                now = time.time()
                should_infer = (now - last_infer_at) >= self._infer_interval
                frame_for_processing = self._downscale_for_processing(frame)

                if should_infer:
                    try:
                        result = model.predict(
                            source=frame_for_processing,
                            conf=self._conf,
                            iou=self._iou,
                            imgsz=self._imgsz,
                            device=self._device,
                            verbose=False,
                        )[0]
                        latest_state, latest_label, latest_confidence = self._classify_result(result)
                        annotated = result.plot()
                        last_infer_at = now
                    except Exception:
                        with self._state_lock:
                            self._latest_frame = self._build_placeholder_frame('Inference error, retrying...')
                        self._push_status(FireEvent.SAFE, '', 0.0, message='Inference error')
                        time.sleep(0.2)
                        continue
                else:
                    annotated = frame_for_processing.copy()

                state, label, confidence = latest_state, latest_label, latest_confidence
                self._draw_status_overlay(annotated, state, confidence)

                ok, encoded = cv2.imencode(
                    '.jpg',
                    annotated,
                    [int(cv2.IMWRITE_JPEG_QUALITY), self._jpeg_quality],
                )
                if ok:
                    with self._state_lock:
                        self._latest_frame = encoded.tobytes()

                self._push_status(state, label, confidence)
                elapsed = time.time() - now
                frame_interval = 1.0 / self._target_fps
                if elapsed < frame_interval:
                    time.sleep(frame_interval - elapsed)
        except Exception as e:
            logger.error(f"_run_loop exception: {e}", exc_info=True)
        finally:
            logger.info("_run_loop finally block")
            with self._state_lock:
                self._running = False

            with self._capture_lock:
                self._release_capture_locked()
            
            logger.info("_run_loop ended")


detection_manager = DetectionManager()
atexit.register(detection_manager.stop)