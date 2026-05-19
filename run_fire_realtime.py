import argparse
import ctypes
import os
import time
from pathlib import Path

import cv2
from ultralytics import YOLO


def to_short_path_if_possible(path: Path) -> str:
    resolved = path.resolve()
    if os.name != "nt":
        return str(resolved)

    required_len = ctypes.windll.kernel32.GetShortPathNameW(str(resolved), None, 0)
    if required_len <= 0:
        return str(resolved)

    short_buffer = ctypes.create_unicode_buffer(required_len)
    result_len = ctypes.windll.kernel32.GetShortPathNameW(str(resolved), short_buffer, required_len)
    if result_len <= 0:
        return str(resolved)
    return short_buffer.value


def normalize_output_path(output_path: Path) -> str:
    resolved = output_path.expanduser().resolve()
    if os.name != "nt":
        return str(resolved)

    short_parent = Path(to_short_path_if_possible(resolved.parent))
    return str(short_parent / resolved.name)


def is_stream_source(source: str) -> bool:
    return source.startswith(("rtsp://", "http://", "https://"))


def parse_source(source: str):
    if source.isdigit():
        return int(source)

    if is_stream_source(source):
        return source

    source_path = Path(source).expanduser()
    if not source_path.exists():
        raise FileNotFoundError(f"Source not found: {source}")
    return to_short_path_if_possible(source_path)


def create_writer(capture: cv2.VideoCapture, output_path: Path, fps: float) -> cv2.VideoWriter:
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    normalized_output = normalize_output_path(output_path)
    return cv2.VideoWriter(normalized_output, fourcc, fps, (width, height))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Realtime fire/smoke detection with a trained YOLO11 model."
    )
    parser.add_argument("--weights", default="YOLO-FIRE/weights/best.pt", help="Path to .pt model")
    parser.add_argument(
        "--source",
        default="0",
        help="Webcam index (0, 1, ...) or video path",
    )
    parser.add_argument("--conf", type=float, default=0.30, help="Confidence threshold")
    parser.add_argument("--iou", type=float, default=0.50, help="NMS IoU threshold")
    parser.add_argument("--imgsz", type=int, default=640, help="Inference image size")
    parser.add_argument("--device", default=None, help="cpu or gpu index, for example 0")
    parser.add_argument("--save", action="store_true", help="Save output video")
    parser.add_argument("--output", default="output_fire_detect.mp4", help="Saved video path")
    parser.add_argument(
        "--view-scale",
        type=float,
        default=1.0,
        help="Resize display window (for example 0.75)",
    )
    args = parser.parse_args()

    weights_path = Path(args.weights)
    if not weights_path.exists():
        raise FileNotFoundError(f"Model not found: {weights_path}")

    source = parse_source(args.source)

    model = YOLO(to_short_path_if_possible(weights_path))
    capture = cv2.VideoCapture(source)
    if not capture.isOpened():
        raise RuntimeError(f"Cannot open source: {args.source}")

    source_fps = capture.get(cv2.CAP_PROP_FPS)
    if source_fps is None or source_fps <= 1:
        source_fps = 25.0

    writer = None
    if args.save:
        Path(args.output).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        writer = create_writer(capture, Path(args.output), source_fps)

    prev_time = time.perf_counter()
    smooth_fps = 0.0

    window_name = "YOLO11 Fire/Smoke Detection"

    try:
        while True:
            success, frame = capture.read()
            if not success:
                break

            result = model.predict(
                source=frame,
                conf=args.conf,
                iou=args.iou,
                imgsz=args.imgsz,
                device=args.device,
                verbose=False,
            )[0]

            annotated = result.plot()

            now = time.perf_counter()
            instant_fps = 1.0 / max(now - prev_time, 1e-6)
            prev_time = now
            smooth_fps = instant_fps if smooth_fps == 0.0 else (0.9 * smooth_fps + 0.1 * instant_fps)

            cv2.putText(
                annotated,
                f"FPS: {smooth_fps:.1f}",
                (12, 32),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.9,
                (0, 255, 0),
                2,
                cv2.LINE_AA,
            )

            frame_to_show = annotated
            if args.view_scale != 1.0:
                frame_to_show = cv2.resize(
                    annotated,
                    dsize=None,
                    fx=args.view_scale,
                    fy=args.view_scale,
                    interpolation=cv2.INTER_AREA,
                )

            cv2.imshow(window_name, frame_to_show)

            if writer is not None:
                writer.write(annotated)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        capture.release()
        if writer is not None:
            writer.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()