from __future__ import annotations

import atexit
import ctypes
import gc
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import cv2
import numpy as np
import pygame
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
        self._model_warmed_up = False
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
        self._frame_skip = max(0, int(getattr(settings, 'STREAM_FRAME_SKIP', 0)))
        self._use_fp16 = bool(getattr(settings, 'YOLO_USE_FP16', False))
        self._warmup_iterations = max(1, int(getattr(settings, 'YOLO_WARMUP_ITERATIONS', 3)))

        self._fire_keywords = tuple(k.lower() for k in settings.FIRE_LABEL_KEYWORDS)
        self._smoke_keywords = tuple(k.lower() for k in settings.SMOKE_LABEL_KEYWORDS)
        self._event_cooldown = float(settings.EVENT_COOLDOWN_SECONDS)

        self._last_alert_at = {
            FireEvent.SMOKE_DETECTED: 0.0,
            FireEvent.FIRE_ALERT: 0.0,
        }
        self._last_status_emit = 0.0

        # Performance metrics
        self._frame_count = 0
        self._inference_count = 0
        self._start_time = None
        self._last_cleanup_time = 0.0

        self._latest_frame = self._build_placeholder_frame('Waiting for camera stream...')
        self._status = {
            'state': FireEvent.SAFE,
            'source': self._source_text,
            'label': '',
            'confidence': 0.0,
            'message': FireEvent.SAFE,
        }
        self._alert_sound: pygame.mixer.Sound | None = None
        self._alert_sound_path = str(settings.BASE_DIR / 'media' / 'alert.mp3')
        if Path(self._alert_sound_path).exists():
            try:
                pygame.mixer.init()
                self._alert_sound = pygame.mixer.Sound(self._alert_sound_path)
            except Exception as e:
                logger.warning(f"Could not load alert sound: {e}")

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

            # Warmup model for faster first inference
            if not self._model_warmed_up:
                self._warmup_model()

        return self._model

    def _warmup_model(self) -> None:
        """Warmup YOLO model with dummy inference for faster subsequent inference."""
        logger.info(f"_warmup_model: starting warmup with {self._warmup_iterations} iterations...")
        try:
            warmup_frame = np.zeros((self._imgsz, self._imgsz, 3), dtype=np.uint8)
            predict_kwargs = {
                'source': warmup_frame,
                'conf': 0.25,
                'iou': 0.45,
                'imgsz': self._imgsz,
                'device': self._device,
                'verbose': False,
            }
            if self._use_fp16:
                predict_kwargs['half'] = True

            for i in range(self._warmup_iterations):
                self._model.predict(**predict_kwargs)
                if i == 0:
                    logger.info("_warmup_model: first warmup iteration complete")

            self._model_warmed_up = True
            logger.info("_warmup_model: warmup complete")
        except Exception as e:
            logger.warning(f"_warmup_model: warmup failed: {e}")

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

        ok, encoded = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), self._jpeg_quality])
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

    def _cleanup_resources(self) -> None:
        """Periodic cleanup to prevent memory leaks."""
        current_time = time.time()
        if current_time - self._last_cleanup_time > 300:  # Every 5 minutes
            self._last_cleanup_time = current_time
            gc.collect()
            logger.debug("_cleanup_resources: garbage collection completed")

    def get_metrics(self) -> dict[str, Any]:
        """Get performance metrics."""
        with self._state_lock:
            uptime = time.time() - self._start_time if self._start_time else 0
            return {
                'frame_count': self._frame_count,
                'inference_count': self._inference_count,
                'uptime_seconds': round(uptime, 1),
                'fps': round(self._frame_count / uptime, 2) if uptime > 0 else 0,
                'inference_fps': round(self._inference_count / uptime, 2) if uptime > 0 else 0,
                'model_loaded': self._model is not None,
                'model_warmed_up': self._model_warmed_up,
            }

    def start(self) -> None:
        if sys.is_finalizing():
            return

        with self._state_lock:
            if self._running:
                logger.info("Detection manager already running")
                return
            self._running = True
            if self._start_time is None:
                self._start_time = time.time()
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
            worker.join(timeout=2.0)
            logger.info("Detection worker thread stopped")

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

        # Always report fire/smoke detection regardless of confidence threshold
        if fire_conf > 0:
            return FireEvent.FIRE_ALERT, fire_label, fire_conf
        if smoke_conf > 0:
            return FireEvent.SMOKE_DETECTED, smoke_label, smoke_conf
        return FireEvent.SAFE, '', 0.0

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

        # Play alert sound when fire/smoke detected (only on state change)
        if changed and state in (FireEvent.FIRE_ALERT, FireEvent.SMOKE_DETECTED) and self._alert_sound is not None:
            try:
                self._alert_sound.play()
            except Exception as e:
                logger.warning(f"Could not play alert sound: {e}")

    def _run_loop(self) -> None:
        logger.info("_run_loop started")
        last_infer_at = 0.0
        latest_state = FireEvent.SAFE
        latest_label = ''
        latest_confidence = 0.0
        frame_skip_counter = 0
        model = None

        try:
            while True:
                with self._state_lock:
                    if not self._running:
                        logger.info("_run_loop: _running set to False, breaking")
                        break

                if sys.is_finalizing():
                    logger.info("_run_loop: sys is finalizing, breaking")
                    break

                # Periodic cleanup
                self._cleanup_resources()

                # Frame skip logic
                if self._frame_skip > 0:
                    frame_skip_counter += 1
                    if frame_skip_counter <= self._frame_skip:
                        time.sleep(0.01)
                        continue
                    frame_skip_counter = 0

                try:
                    if model is None:
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
                        # Drop stale buffered frames
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
                self._frame_count += 1
                should_infer = (now - last_infer_at) >= self._infer_interval
                frame_for_processing = self._downscale_for_processing(frame)

                if should_infer:
                    try:
                        predict_kwargs = {
                            'source': frame_for_processing,
                            'conf': self._conf,
                            'iou': self._iou,
                            'imgsz': self._imgsz,
                            'device': self._device,
                            'verbose': False,
                        }
                        if self._use_fp16:
                            predict_kwargs['half'] = True

                        result = model.predict(**predict_kwargs)[0]
                        latest_state, latest_label, latest_confidence = self._classify_result(result)
                        annotated = result.plot()
                        last_infer_at = now
                        self._inference_count += 1
                    except Exception:
                        with self._state_lock:
                            self._latest_frame = self._build_placeholder_frame('Inference error, retrying...')
                        self._push_status(FireEvent.SAFE, '', 0.0, message='Inference error')
                        time.sleep(0.2)
                        continue
                else:
                    annotated = frame_for_processing.copy()

                state, label, confidence = latest_state, latest_label, latest_confidence

                ok, encoded = cv2.imencode(
                    '.jpg',
                    annotated,
                    [int(cv2.IMWRITE_JPEG_QUALITY), self._jpeg_quality],
                )
                if ok:
                    with self._state_lock:
                        self._latest_frame = encoded.tobytes()

                self._push_status(state, label, confidence)

                # Draw alert box on frame
                if state == FireEvent.FIRE_ALERT:
                    cv2.rectangle(annotated, (0, 0), (annotated.shape[1], annotated.shape[0]), (0, 0, 255), 8)
                    cv2.rectangle(annotated, (10, 10), (340, 70), (0, 0, 0), -1)
                    cv2.putText(annotated, f'FIRE ALERT ({confidence:.2f})', (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2, cv2.LINE_AA)
                elif state == FireEvent.SMOKE_DETECTED:
                    cv2.rectangle(annotated, (0, 0), (annotated.shape[1], annotated.shape[0]), (0, 165, 255), 8)
                    cv2.rectangle(annotated, (10, 10), (360, 70), (0, 0, 0), -1)
                    cv2.putText(annotated, f'SMOKE ({confidence:.2f})', (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 165, 255), 2, cv2.LINE_AA)

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
