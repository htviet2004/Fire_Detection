"""Django settings for the fire/smoke monitoring backend."""

import os
from pathlib import Path

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY: Use environment variable for secret key in production
SECRET_KEY = os.getenv(
    'DJANGO_SECRET_KEY',
    'django-insecure-dev-key-change-in-production'
)

# SECURITY: Debug only in development
DEBUG = os.getenv('DEBUG', 'True').lower() in ('true', '1', 'yes')

# SECURITY: Configure allowed hosts from environment
ALLOWED_HOSTS = os.getenv(
    'ALLOWED_HOSTS',
    '127.0.0.1,localhost'
).split(',')


# Application definition

INSTALLED_APPS = [
    'daphne',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'corsheaders',
    'rest_framework',
    'axes',
    'channels',
    'monitor',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'axes.middleware.AxesMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'monitor.middleware.RateLimitMiddleware',
]

ROOT_URLCONF = 'backend.urls'

AUTHENTICATION_BACKENDS = [
    'axes.backends.AxesStandaloneBackend',
    'django.contrib.auth.backends.ModelBackend',
]

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'backend.wsgi.application'
ASGI_APPLICATION = 'backend.asgi.application'


# Database - SQLite for development, use PostgreSQL/MySQL in production
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# For production with PostgreSQL:
# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.postgresql',
#         'NAME': os.getenv('DB_NAME', 'firedb'),
#         'USER': os.getenv('DB_USER', 'fireuser'),
#         'PASSWORD': os.getenv('DB_PASSWORD', ''),
#         'HOST': os.getenv('DB_HOST', 'localhost'),
#         'PORT': os.getenv('DB_PORT', '5432'),
#         'CONN_MAX_AGE': 60,
#         'OPTIONS': {
#             'connect_timeout': 10,
#         },
#     }
# }


AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'Asia/Ho_Chi_Minh'

USE_I18N = True

USE_TZ = True


STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# SECURITY: CORS Configuration - Only allow specific origins
CORS_ALLOWED_ORIGINS = os.getenv(
    'CORS_ALLOWED_ORIGINS',
    'http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:3000,http://localhost:3000'
).split(',')

CORS_ALLOW_ALL_ORIGINS = DEBUG  # Only allow all in debug mode

CORS_ALLOW_CREDENTIALS = True

CSRF_TRUSTED_ORIGINS = os.getenv(
    'CSRF_TRUSTED_ORIGINS',
    'http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:3000,http://localhost:3000'
).split(',')

# SECURITY: Rate Limiting
RATE_LIMIT_REQUESTS = int(os.getenv('RATE_LIMIT_REQUESTS', '100'))
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv('RATE_LIMIT_WINDOW_SECONDS', '60'))

# Channel Layers - InMemory for development, Redis for production
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels.layers.InMemoryChannelLayer',
    },
}

# For production with Redis:
# CHANNEL_LAYERS = {
#     'default': {
#         'BACKEND': 'channels_redis.core.RedisChannelLayer',
#         'CONFIG': {
#             'hosts': [(os.getenv('REDIS_HOST', 'localhost'), int(os.getenv('REDIS_PORT', 6379)))],
#             'capacity': 1500,
#             'expiry': 10,
#         },
#     },
# }

# SECURITY: Axes (Brute Force Protection)
AXES_FAILURE_LIMIT = int(os.getenv('AXES_FAILURE_LIMIT', '5'))
AXES_COOLOFF_TIME = int(os.getenv('AXES_COOLOFF_TIME', '30'))  # minutes
AXES_RESET_ON_SUCCESS = True

# SECURITY: Content Security Policy
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
SECURE_BROWSER_XSS_FILTER = True

# SECURITY: HTTPS (uncomment in production)
# SECURE_SSL_REDIRECT = True
# SESSION_COOKIE_SECURE = True
# CSRF_COOKIE_SECURE = True
# SECURE_HSTS_SECONDS = 31536000
# SECURE_HSTS_INCLUDE_SUBDOMAINS = True

# YOLO Configuration
YOLO_WEIGHTS_PATH = os.getenv(
    'YOLO_WEIGHTS_PATH',
    str(BASE_DIR.parent / 'YOLO-FIRE' / 'weights' / 'best.pt'),
)
DEFAULT_CAMERA_SOURCE = os.getenv('CAMERA_SOURCE', '0')
YOLO_CONF = float(os.getenv('YOLO_CONF', '0.30'))
YOLO_IOU = float(os.getenv('YOLO_IOU', '0.45'))
YOLO_IMGSZ = int(os.getenv('YOLO_IMGSZ', '320'))
YOLO_DEVICE = os.getenv('YOLO_DEVICE', '')
YOLO_INFER_INTERVAL = float(os.getenv('YOLO_INFER_INTERVAL', '0.05'))
# YOLO Performance Optimization
YOLO_WARMUP_ITERATIONS = int(os.getenv('YOLO_WARMUP_ITERATIONS', '3'))
YOLO_USE_FP16 = os.getenv('YOLO_USE_FP16', 'False').lower() in ('true', '1', 'yes')

STREAM_JPEG_QUALITY = int(os.getenv('STREAM_JPEG_QUALITY', '75'))
STREAM_TARGET_FPS = float(os.getenv('STREAM_TARGET_FPS', '30'))
STREAM_INPUT_MAX_WIDTH = int(os.getenv('STREAM_INPUT_MAX_WIDTH', '640'))
STREAM_FRAME_SKIP = int(os.getenv('STREAM_FRAME_SKIP', '0'))

FIRE_LABEL_KEYWORDS = ('fire', 'flame')
SMOKE_LABEL_KEYWORDS = ('smoke',)
EVENT_COOLDOWN_SECONDS = float(os.getenv('EVENT_COOLDOWN_SECONDS', '5'))

# File Upload Security
UPLOADED_VIDEO_DIR = str(BASE_DIR / 'media' / 'uploads')
MAX_VIDEO_UPLOAD_MB = int(os.getenv('MAX_VIDEO_UPLOAD_MB', '100'))  # Reduced from 500MB
ALLOWED_VIDEO_EXTENSIONS = {'.mp4', '.avi', '.mov', '.mkv', '.wmv', '.m4v', '.webm'}
ALLOWED_VIDEO_MIMETYPES = {
    'video/mp4',
    'video/x-msvideo',
    'video/quicktime',
    'video/x-matroska',
    'video/x-ms-wmv',
    'video/x-m4v',
    'video/webm',
}

# Logging Configuration
LOG_DIR = BASE_DIR / 'logs'
LOG_DIR.mkdir(parents=True, exist_ok=True)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{asctime} [{levelname}] {name} - {message}',
            'style': '{',
        },
        'simple': {
            'format': '{asctime} [{levelname}] {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
        'file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOG_DIR / 'app.log',
            'maxBytes': 10 * 1024 * 1024,  # 10MB
            'backupCount': 5,
            'formatter': 'verbose',
        },
        'error_file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOG_DIR / 'error.log',
            'maxBytes': 10 * 1024 * 1024,  # 10MB
            'backupCount': 5,
            'level': 'ERROR',
            'formatter': 'verbose',
        },
        'security_file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOG_DIR / 'security.log',
            'maxBytes': 10 * 1024 * 1024,  # 10MB
            'backupCount': 10,
            'level': 'WARNING',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console', 'file'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console', 'file'],
            'level': 'WARNING',
            'propagate': False,
        },
        'django.server': {
            'handlers': ['console', 'error_file'],
            'level': 'ERROR',
            'propagate': False,
        },
        'django.security': {
            'handlers': ['console', 'security_file'],
            'level': 'WARNING',
            'propagate': False,
        },
        'monitor': {
            'handlers': ['console', 'file'],
            'level': 'DEBUG' if DEBUG else 'INFO',
            'propagate': False,
        },
        'daphne': {
            'handlers': ['console', 'error_file'],
            'level': 'ERROR',
            'propagate': False,
        },
        'daphne.http_protocol': {
            'handlers': ['console', 'error_file'],
            'level': 'ERROR',
            'propagate': False,
        },
        'asyncio': {
            'handlers': ['console', 'error_file'],
            'level': 'ERROR',
            'propagate': False,
        },
    },
}

# REST Framework Configuration
REST_FRAMEWORK = {
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': f'{RATE_LIMIT_REQUESTS // 2} per {RATE_LIMIT_WINDOW_SECONDS} second',
        'user': f'{RATE_LIMIT_REQUESTS} per {RATE_LIMIT_WINDOW_SECONDS} second',
    },
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticatedOrReadOnly',
    ],
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
}

# Prometheus Metrics (for monitoring)
ENABLE_PROMETHEUS_METRICS = os.getenv('ENABLE_PROMETHEUS_METRICS', 'False').lower() in ('true', '1', 'yes')
