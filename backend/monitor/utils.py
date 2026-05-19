"""Utility functions for the monitor app."""

import hashlib
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def get_system_info() -> dict[str, Any]:
    """Get system information for diagnostics."""
    import platform

    info = {
        'platform': platform.system(),
        'platform_release': platform.release(),
        'platform_version': platform.version(),
        'architecture': platform.machine(),
        'processor': platform.processor(),
        'python_version': sys.version,
    }

    try:
        import psutil

        info.update({
            'cpu_count': psutil.cpu_count(),
            'cpu_percent': psutil.cpu_percent(interval=0.1),
            'memory_total_gb': round(psutil.virtual_memory().total / (1024**3), 2),
            'memory_available_gb': round(psutil.virtual_memory().available / (1024**3), 2),
            'memory_percent': psutil.virtual_memory().percent,
        })
    except ImportError:
        logger.debug("psutil not available, skipping system info")

    return info


def validate_rtsp_url(url: str) -> bool:
    """Validate RTSP URL format."""
    rtsp_pattern = r'^rtsp://[\w\-\.]+(:\d+)?(/.*)?$'
    return bool(re.match(rtsp_pattern, url, re.IGNORECASE))


def validate_http_url(url: str) -> bool:
    """Validate HTTP/HTTPS URL format."""
    http_pattern = r'^https?://[\w\-\.]+(:\d+)?(/.*)?$'
    return bool(re.match(http_pattern, url, re.IGNORECASE))


def get_file_hash(file_path: Path, algorithm: str = 'sha256') -> str:
    """Calculate file hash."""
    hash_func = hashlib.new(algorithm)
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            hash_func.update(chunk)
    return hash_func.hexdigest()


def cleanup_old_files(directory: Path, max_age_hours: int = 24, extensions: set[str] | None = None) -> int:
    """Remove files older than max_age_hours."""
    import time

    if not directory.exists():
        return 0

    if extensions is None:
        extensions = {'.mp4', '.avi', '.mov', '.mkv', '.webm'}

    cutoff_time = time.time() - (max_age_hours * 3600)
    removed_count = 0

    for file_path in directory.iterdir():
        if file_path.is_file() and file_path.suffix.lower() in extensions:
            if file_path.stat().st_mtime < cutoff_time:
                try:
                    file_path.unlink()
                    removed_count += 1
                    logger.info(f"Removed old file: {file_path}")
                except OSError as e:
                    logger.warning(f"Failed to remove {file_path}: {e}")

    return removed_count


def ensure_directory(path: Path | str, mode: int = 0o755) -> Path:
    """Ensure directory exists with proper permissions."""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True, mode=mode)
    return path


def get_video_info(video_path: Path) -> dict[str, Any] | None:
    """Get video metadata using OpenCV."""
    import cv2

    if not video_path.exists():
        return None

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return None

    info = {
        'width': int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        'height': int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        'fps': round(cap.get(cv2.CAP_PROP_FPS), 2),
        'frame_count': int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
        'duration_seconds': round(int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) / cap.get(cv2.CAP_PROP_FPS), 2)
        if cap.get(cv2.CAP_PROP_FPS) > 0
        else 0,
        'codec': '',
    }

    cap.release()
    return info


def is_gpu_available() -> bool:
    """Check if GPU is available for YOLO."""
    try:
        import torch

        return torch.cuda.is_available()
    except ImportError:
        pass

    try:
        import subprocess

        result = subprocess.run(
            ['nvidia-smi', '--query-gpu=name', '--format=csv,noheader'],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return False


def get_gpu_info() -> dict[str, Any] | None:
    """Get GPU information."""
    try:
        import torch

        if torch.cuda.is_available():
            return {
                'name': torch.cuda.get_device_name(0),
                'memory_total_mb': torch.cuda.get_device_properties(0).total_memory / (1024**2),
                'memory_allocated_mb': torch.cuda.memory_allocated(0) / (1024**2),
                'memory_reserved_mb': torch.cuda.memory_reserved(0) / (1024**2),
            }
    except ImportError:
        pass

    try:
        import subprocess

        result = subprocess.run(
            ['nvidia-smi', '--query-gpu=name,memory.total,memory.used', '--format=csv,noheader,nounits'],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            parts = result.stdout.strip().split(',')
            if len(parts) >= 3:
                return {
                    'name': parts[0].strip(),
                    'memory_total_mb': float(parts[1].strip()),
                    'memory_used_mb': float(parts[2].strip()),
                }
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
        pass

    return None
