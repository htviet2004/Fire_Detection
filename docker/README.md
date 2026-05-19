# Fire/Smoke Security Dashboard

Production-ready Docker setup for the Fire/Smoke detection system.

## Quick Start

### Development

```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f backend

# Stop services
docker-compose down
```

### Production

```bash
# Build and start with production settings
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Browser   │────▶│   Nginx     │────▶│  Daphne     │
│   (React)   │◀────│  (Reverse   │◀────│  (ASGI)     │
└─────────────┘     │   Proxy)    │     └─────────────┘
                    └─────────────┘            │
                                               │
                    ┌─────────────┐             │
                    │   Redis     │◀────────────┤
                    │  (Channels) │             │
                    └─────────────┘             │
                                               ▼
                                        ┌─────────────┐
                                        │   YOLO      │
                                        │   Model     │
                                        └─────────────┘
```

## Services

- **frontend**: React + Vite static files (served by Nginx)
- **backend**: Django + Daphne ASGI server
- **redis**: Redis for Django Channels (production)
- **nginx**: Reverse proxy and static file server

## Environment Variables

Create `.env` file based on `.env.example`:

```bash
# Django
DJANGO_SECRET_KEY=your-secret-key-here
DEBUG=False
ALLOWED_HOSTS=your-domain.com

# Database
DB_ENGINE=postgresql
DB_NAME=firedb
DB_USER=fireuser
DB_PASSWORD=strongpassword
DB_HOST=db
DB_PORT=5432

# Redis
REDIS_HOST=redis
REDIS_PORT=6379

# YOLO
YOLO_WEIGHTS_PATH=/app/YOLO-FIRE/weights/best.pt
CAMERA_SOURCE=0

# CORS
CORS_ALLOWED_ORIGINS=https://your-domain.com
```

## Ports

| Service   | Port | Description            |
|-----------|------|------------------------|
| nginx     | 80   | HTTP (redirects to 443)|
| nginx     | 443  | HTTPS                  |
| backend   | 8000 | Daphne ASGI            |
| redis     | 6379 | Redis                  |
| postgres  | 5432 | PostgreSQL             |

## Volume Mounts

- `./YOLO-FIRE:/app/YOLO-FIRE` - YOLO model weights
- `./backend/media:/app/media` - Uploaded files
- `./backend/logs:/app/logs` - Application logs
- `./ssl:/etc/nginx/ssl` - SSL certificates

## Health Checks

```bash
# Backend health
curl http://localhost/api/health/

# Prometheus metrics
curl http://localhost/api/metrics/

# Nginx status
curl http://localhost/nginx_status
```
