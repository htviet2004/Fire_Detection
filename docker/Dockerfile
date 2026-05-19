FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    libgl1-mesa-glx \
    libglib2.0-0 \
    ffmpeg \
    libsm6 \
    libxext6 \
    libxrender-dev \
    && rm -rf /var/lib/apt/lists/*

# Set work directory
WORKDIR /app

# Install Python dependencies
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install system packages for YOLO/OpenCV
RUN pip install --no-cache-dir ultralytics opencv-python-headless

# Copy application code
COPY backend/ .
COPY YOLO-FIRE/ /app/YOLO-FIRE/

# Create directories
RUN mkdir -p /app/media/uploads /app/logs /app/staticfiles

# Set permissions
RUN chmod -R 755 /app/media /app/logs

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/api/health/ || exit 1

# Run migrations and start server
CMD ["sh", "-c", "python manage.py migrate && daphne -b 0.0.0.0 -p 8000 backend.asgi:application"]
