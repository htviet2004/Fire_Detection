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


ALLOWED_VIDEO_SUFFIXES = {
    '.mp4',
    '.avi',
    '.mov',
    '.mkv',
    '.wmv',
    '.m4v',
    '.webm',
}


def _save_uploaded_video(uploaded_file) -> Path:
    destination_root = Path(settings.UPLOADED_VIDEO_DIR)
    destination_root.mkdir(parents=True, exist_ok=True)

    original_name = str(uploaded_file.name or '').strip()
    suffix = Path(original_name).suffix.lower()
    if suffix not in ALLOWED_VIDEO_SUFFIXES:
        raise ValueError('Unsupported file type. Please upload a valid video file.')

    max_bytes = int(settings.MAX_VIDEO_UPLOAD_MB) * 1024 * 1024
    if uploaded_file.size and uploaded_file.size > max_bytes:
        raise ValueError(f'Video file too large. Limit: {settings.MAX_VIDEO_UPLOAD_MB} MB')

    safe_name = f'{uuid4().hex}{suffix}'
    destination = destination_root / safe_name

    with destination.open('wb') as output:
        for chunk in uploaded_file.chunks():
            output.write(chunk)

    return destination


def _validate_uploaded_video(path: Path) -> None:
    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            raise ValueError('Cannot open uploaded video. Please use a playable MP4/AVI file.')

        ok, _ = capture.read()
        if not ok:
            raise ValueError('Uploaded video is corrupted or codec is not supported by OpenCV.')
    finally:
        capture.release()


def _mjpeg_frame_generator():
	frame_count = 0
	logger.info("_mjpeg_frame_generator started, waiting for first frame...")
	try:
		# Wait for first frame with timeout
		logger.info("_mjpeg_frame_generator: waiting for initial frame...")
		first_frame_acquired = False
		for attempt in range(200):  # Wait up to 10 seconds
			frame = detection_manager.get_frame()
			if frame:
				logger.info(f"_mjpeg_frame_generator: got initial frame on attempt {attempt}, size={len(frame)}")
				frame_count = 1
				frame_len = len(frame)
				
				# Yield initial boundary + frame
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
		
		# Stream remaining frames
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
	"""Async generator for MJPEG streaming"""
	frame_count = 0
	logger.info("_async_mjpeg_frame_generator started")
	try:
		# Wait for first frame
		logger.info("_async_mjpeg_frame_generator: waiting for initial frame...")
		for attempt in range(200):  # 10 seconds max
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
		
		# Stream remaining frames
		while True:
			frame = detection_manager.get_frame()
			if not frame:
				await asyncio.sleep(0.01)
				continue
			
			frame_count += 1
			if frame_count % 30 == 0:
				logger.debug(f"Streaming frame #{frame_count}, size={len(frame)}")
			
			frame_len = len(frame)
			header = f'Content-Type: image/jpeg\r\nContent-Length: {frame_len}\r\n\r\n'.encode()
			boundary = b'\r\n--frame\r\n'
			chunk = header + frame + boundary
			yield chunk
			await asyncio.sleep(0.01)
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
	return JsonResponse({'ok': True})
