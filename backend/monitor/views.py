import asyncio
import json
import logging
import time
from pathlib import Path
from uuid import uuid4

import cv2
from django.conf import settings
from django.http import HttpResponse, JsonResponse, StreamingHttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .services import detection_manager

logger = logging.getLogger(__name__)


ALLOWED_VIDEO_SUFFIXES = getattr(settings, 'ALLOWED_VIDEO_EXTENSIONS', {
    '.mp4',
    '.avi',
    '.mov',
    '.mkv',
    '.wmv',
    '.m4v',
    '.webm',
})

ALLOWED_VIDEO_MIMETYPES = getattr(settings, 'ALLOWED_VIDEO_MIMETYPES', {
    'video/mp4',
    'video/x-msvideo',
    'video/quicktime',
    'video/x-matroska',
    'video/webm',
})


def _save_uploaded_video(uploaded_file) -> Path:
    destination_root = Path(settings.UPLOADED_VIDEO_DIR)
    destination_root.mkdir(parents=True, exist_ok=True)

    original_name = str(uploaded_file.name or '').strip()
    suffix = Path(original_name).suffix.lower()

    # Validate extension
    if suffix not in ALLOWED_VIDEO_SUFFIXES:
        raise ValueError(f'Unsupported file type "{suffix}". Allowed: {", ".join(sorted(ALLOWED_VIDEO_SUFFIXES))}')

    # Validate size
    max_bytes = int(settings.MAX_VIDEO_UPLOAD_MB) * 1024 * 1024
    if uploaded_file.size and uploaded_file.size > max_bytes:
        raise ValueError(f'Video file too large. Limit: {settings.MAX_VIDEO_UPLOAD_MB} MB')

    # Generate safe filename
    safe_name = f'{uuid4().hex}{suffix}'
    destination = destination_root / safe_name

    # Save file
    with destination.open('wb') as output:
        for chunk in uploaded_file.chunks():
            output.write(chunk)

    logger.info(f"Saved uploaded video: {destination}")
    return destination


def _validate_uploaded_video(path: Path) -> None:
    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            raise ValueError('Cannot open uploaded video. Please use a playable MP4/AVI file.')

        ok, _ = capture.read()
        if not ok:
            raise ValueError('Uploaded video is corrupted or codec is not supported by OpenCV.')

        # Get video info
        fps = capture.get(cv2.CAP_PROP_FPS)
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))

        logger.info(f"Video validated: {width}x{height}, {fps:.2f}fps, {frame_count} frames")
    finally:
        capture.release()


def _mjpeg_frame_generator():
    frame_count = 0
    logger.info("_mjpeg_frame_generator started, waiting for first frame...")
    try:
        logger.info("_mjpeg_frame_generator: waiting for initial frame...")
        first_frame_acquired = False
        for attempt in range(200):
            frame = detection_manager.get_frame()
            if frame:
                logger.info(f"_mjpeg_frame_generator: got initial frame on attempt {attempt}, size={len(frame)}")
                frame_count = 1
                frame_len = len(frame)

                header = f'--frame\r\nContent-Type: image/jpeg\r\nContent-Length: {frame_len}\r\n\r\n'.encode()
                boundary = b'\r\n--frame\r\n'
                chunk = header + frame + boundary
                logger.info(f"_mjpeg_frame_generator: yielding initial chunk of {len(chunk)} bytes")
                yield chunk
                first_frame_acquired = True
                break
            time.sleep(0.05)

        if not first_frame_acquired:
            logger.error("_mjpeg_frame_generator: timeout waiting for first frame")
            return

        while True:
            frame = detection_manager.get_frame()
            if not frame:
                time.sleep(0.01)
                continue

            frame_count += 1
            if frame_count % 30 == 0:
                logger.debug(f"Streaming frame #{frame_count}, size={len(frame)}")

            frame_len = len(frame)
            header = f'Content-Type: image/jpeg\r\nContent-Length: {frame_len}\r\n\r\n'.encode()
            boundary = b'\r\n--frame\r\n'
            chunk = header + frame + boundary
            logger.debug(f"_mjpeg_frame_generator: yielding chunk {frame_count}")
            yield chunk
            time.sleep(0.01)
    except (GeneratorExit, BrokenPipeError, ConnectionResetError) as e:
        logger.info(f"Stream ended: {type(e).__name__} after {frame_count} frames")
        return
    except Exception as e:
        logger.error(f"Stream error: {e}", exc_info=True)
        return


async def _async_mjpeg_frame_generator():
    frame_count = 0
    logger.info("_async_mjpeg_frame_generator started")
    try:
        logger.info("_async_mjpeg_frame_generator: waiting for initial frame...")
        for attempt in range(200):
            frame = detection_manager.get_frame()
            if frame:
                logger.info(f"_async_mjpeg_frame_generator: got initial frame, size={len(frame)}")
                frame_count = 1
                frame_len = len(frame)
                header = f'--frame\r\nContent-Type: image/jpeg\r\nContent-Length: {frame_len}\r\n\r\n'.encode()
                boundary = b'\r\n--frame\r\n'
                chunk = header + frame + boundary
                logger.info(f"_async_mjpeg_frame_generator: yielding initial chunk of {len(chunk)} bytes")
                yield chunk
                break
            await asyncio.sleep(0.05)
        else:
            logger.error("_async_mjpeg_frame_generator: timeout waiting for first frame")
            return

        while True:
            frame = detection_manager.get_frame()
            if not frame:
                await asyncio.sleep(0.01)
                continue

            frame_count += 1

            frame_len = len(frame)
            header = f'Content-Type: image/jpeg\r\nContent-Length: {frame_len}\r\n\r\n'.encode()
            boundary = b'\r\n--frame\r\n'
            chunk = header + frame + boundary
            yield chunk
            await asyncio.sleep(0.005)
    except (GeneratorExit, BrokenPipeError, ConnectionResetError, asyncio.CancelledError) as e:
        logger.info(f"Stream ended: {type(e).__name__} after {frame_count} frames")
        return
    except Exception as e:
        logger.error(f"Stream error: {e}", exc_info=True)
        return


@require_GET
async def stream_video(request):
    logger.info(f"Stream request from {request.META.get('REMOTE_ADDR')}")
    source = request.GET.get('source')
    if source:
        try:
            detection_manager.set_source(source)
        except ValueError:
            pass

    detection_manager.start()
    logger.info("Detection manager started, creating async response")

    response = StreamingHttpResponse(
        _async_mjpeg_frame_generator(),
        content_type='multipart/x-mixed-replace; boundary=frame',
    )
    response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response['Access-Control-Allow-Origin'] = '*'
    response['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
    response['Access-Control-Allow-Headers'] = 'Content-Type'
    logger.info("Async stream response ready")
    return response


@require_GET
def status_snapshot(request):
    detection_manager.start()
    return JsonResponse(detection_manager.get_status())


@require_GET
def event_logs(request):
    detection_manager.start()
    try:
        limit = int(request.GET.get('limit', '50'))
    except ValueError:
        limit = 50

    return JsonResponse({'items': detection_manager.get_events(limit=limit)})


@csrf_exempt
@require_POST
def set_camera_source(request):
    payload = {}
    if request.body:
        try:
            payload = json.loads(request.body.decode('utf-8'))
        except json.JSONDecodeError:
            payload = {}

    source = str(payload.get('source') or request.POST.get('source', '')).strip()
    if not source:
        return JsonResponse({'error': 'source is required'}, status=400)

    try:
        status = detection_manager.set_source(source)
    except ValueError as error:
        return JsonResponse({'error': str(error)}, status=400)

    detection_manager.start()
    return JsonResponse({'ok': True, 'status': status})


@csrf_exempt
@require_POST
def upload_video(request):
    uploaded_file = request.FILES.get('video')
    if uploaded_file is None:
        return JsonResponse({'error': 'video file is required'}, status=400)

    # Validate MIME type
    content_type = getattr(uploaded_file, 'content_type', '')
    if content_type and content_type not in ALLOWED_VIDEO_MIMETYPES:
        logger.warning(f"Upload rejected: invalid content type {content_type}")
        return JsonResponse({'error': f'Invalid file type. Allowed: video/*'}, status=400)

    destination = None
    try:
        destination = _save_uploaded_video(uploaded_file)
        _validate_uploaded_video(destination)
    except ValueError as error:
        if destination is not None and destination.exists():
            destination.unlink(missing_ok=True)
        return JsonResponse({'error': str(error)}, status=400)
    except OSError:
        if destination is not None and destination.exists():
            destination.unlink(missing_ok=True)
        return JsonResponse({'error': 'Failed to save uploaded video'}, status=500)

    status = detection_manager.set_source(str(destination))
    detection_manager.start()
    return JsonResponse(
        {
            'ok': True,
            'status': status,
            'source': str(destination),
            'filename': uploaded_file.name,
        }
    )


@require_GET
def health(request):
    """Health check endpoint with detailed status."""
    try:
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')

        metrics = detection_manager.get_metrics()

        return JsonResponse({
            'ok': True,
            'status': 'healthy',
            'database': 'connected',
            'detection': {
                'running': detection_manager._running if hasattr(detection_manager, '_running') else False,
                'source': detection_manager._source_text if hasattr(detection_manager, '_source_text') else None,
                'model_loaded': metrics.get('model_loaded', False),
                'model_warmed_up': metrics.get('model_warmed_up', False),
            },
            'metrics': metrics,
            'timestamp': time.time(),
        })
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return JsonResponse(
            {
                'ok': False,
                'status': 'unhealthy',
                'error': str(e),
                'timestamp': time.time(),
            },
            status=503,
        )


@require_GET
def metrics(request):
    """Prometheus-style metrics endpoint."""
    metrics = detection_manager.get_metrics()

    output = f"""# HELP fire_monitor_up Whether the detection monitor is running
# TYPE fire_monitor_up gauge
fire_monitor_up {1 if metrics.get('model_loaded') else 0}

# HELP fire_monitor_frame_count Total frames processed
# TYPE fire_monitor_frame_count counter
fire_monitor_frame_count {metrics.get('frame_count', 0)}

# HELP fire_monitor_inference_count Total inference runs
# TYPE fire_monitor_inference_count counter
fire_monitor_inference_count {metrics.get('inference_count', 0)}

# HELP fire_monitor_fps Current FPS
# TYPE fire_monitor_fps gauge
fire_monitor_fps {metrics.get('fps', 0)}

# HELP fire_monitor_inference_fps Inference FPS
# TYPE fire_monitor_inference_fps gauge
fire_monitor_inference_fps {metrics.get('inference_fps', 0)}

# HELP fire_monitor_uptime_seconds Monitor uptime in seconds
# TYPE fire_monitor_uptime_seconds counter
fire_monitor_uptime_seconds {metrics.get('uptime_seconds', 0)}
"""

    return HttpResponse(output, content_type='text/plain')
