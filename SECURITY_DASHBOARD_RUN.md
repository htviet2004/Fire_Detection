# Fire/Smoke Security Dashboard (Django + React)

## 1) Start backend (Django + YOLOv11)

From workspace root:

```powershell
.\.venv\Scripts\python.exe .\backend\manage.py migrate
.\.venv\Scripts\python.exe .\backend\manage.py runserver 127.0.0.1:8000 --noreload
```

If you want Django auto-reload after code edits, run without `--noreload`:

```powershell
.\.venv\Scripts\python.exe .\backend\manage.py runserver 127.0.0.1:8000
```

Backend APIs:
- `GET /api/stream/` -> MJPEG stream with YOLO bounding boxes
- `GET /api/status/` -> current status (`SAFE`, `SMOKE DETECTED`, `FIRE ALERT`)
- `GET /api/events/?limit=120` -> event logs
- `POST /api/source/` -> switch source (`{"source": "0"}` or RTSP URL)
- `POST /api/upload-video/` -> upload video file to backend and start detect
- WebSocket: `ws://127.0.0.1:8000/ws/alerts/`

Note:
- Dashboard stream URL stays stable (`/api/stream/`).
- Source switching is done via UI forms (`Camera Source`, `Video Link`, `Upload Video`) or `POST /api/source/`.

## 2) Start frontend (React dashboard)

In another terminal:

```powershell
cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```

Open:
- `http://127.0.0.1:5173`

Dashboard source options:
- Camera Source: webcam index (`0`) or local video path
- Video Link: direct MP4/HTTP URL or RTSP URL
- Upload Video: choose a local video file, backend uploads and starts detection

## 3) Model path

Default model path is:
- `YOLO-FIRE/weights/best.pt`

You can override with environment variable before running backend:

```powershell
$env:YOLO_WEIGHTS_PATH="C:/path/to/best.pt"
```

## 4) Camera source examples

- Webcam:
  - `0`
- IP Camera (RTSP):
  - `rtsp://username:password@192.168.1.100:554/stream1`
- Local video file:
  - `D:/videos/fire_test.mp4`

## 5) Optional tuning

```powershell
$env:YOLO_CONF="0.30"
$env:YOLO_IOU="0.50"
$env:YOLO_IMGSZ="640"
$env:YOLO_DEVICE="0"
```

Then run backend again.

## 6) Upload video via API (optional)

Example with PowerShell:

```powershell
curl.exe -X POST -F "video=@D:/videos/fire_test.mp4" http://127.0.0.1:8000/api/upload-video/
```

## 7) Troubleshooting (Dev Logs)

- Repeated `WebSocket CONNECT` and `WebSocket DISCONNECT` in development is normal when the React page reloads.
- `Application instance ... /api/stream ... took too long to shut down` may appear during Django auto-reload while stream is active.
- To reduce this log, run backend with `--noreload` while testing stream.
- If stream is black after upload, the file may be corrupted or codec is unsupported by OpenCV. Re-upload using MP4 (H.264) and check the `Message` field on dashboard state panel.
- If API returns `Source not found`, verify the local file path exists or switch source back to webcam (`0`).
