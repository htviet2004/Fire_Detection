"""Django settings for the fire/smoke monitoring backend."""

import os
from pathlib import Path

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


SECRET_KEY = 'django-insecure-8b(u^$t2nntoc$!t^%h^fumi0me$d0919f7=o#^2z$&=-sb8&$'

DEBUG = True

ALLOWED_HOSTS = ['127.0.0.1', 'localhost', 'testserver']


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
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'backend.urls'

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


DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}


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

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

CORS_ALLOWED_ORIGINS = [
    'http://127.0.0.1:5173',
    'http://localhost:5173',
]

CSRF_TRUSTED_ORIGINS = [
    'http://127.0.0.1:5173',
    'http://localhost:5173',
]

CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels.layers.InMemoryChannelLayer',
    },
}

YOLO_WEIGHTS_PATH = os.getenv(
    'YOLO_WEIGHTS_PATH',
    str(BASE_DIR.parent / 'YOLO-FIRE' / 'weights' / 'best.pt'),
)
DEFAULT_CAMERA_SOURCE = os.getenv('CAMERA_SOURCE', '0')
YOLO_CONF = float(os.getenv('YOLO_CONF', '0.30'))
YOLO_IOU = float(os.getenv('YOLO_IOU', '0.50'))
YOLO_IMGSZ = int(os.getenv('YOLO_IMGSZ', '416'))
YOLO_DEVICE = os.getenv('YOLO_DEVICE', '')
YOLO_INFER_INTERVAL = float(os.getenv('YOLO_INFER_INTERVAL', '0.12'))
STREAM_JPEG_QUALITY = int(os.getenv('STREAM_JPEG_QUALITY', '72'))
STREAM_TARGET_FPS = float(os.getenv('STREAM_TARGET_FPS', '20'))
STREAM_INPUT_MAX_WIDTH = int(os.getenv('STREAM_INPUT_MAX_WIDTH', '960'))

FIRE_LABEL_KEYWORDS = ('fire', 'flame')
SMOKE_LABEL_KEYWORDS = ('smoke',)
EVENT_COOLDOWN_SECONDS = float(os.getenv('EVENT_COOLDOWN_SECONDS', '5'))

UPLOADED_VIDEO_DIR = str(BASE_DIR / 'uploaded_videos')
MAX_VIDEO_UPLOAD_MB = int(os.getenv('MAX_VIDEO_UPLOAD_MB', '500'))

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'WARNING',
            'propagate': False,
        },
        'django.server': {
            'handlers': ['console'],
            'level': 'ERROR',
            'propagate': False,
        },
        'monitor': {
            'handlers': ['console'],
            'level': 'WARNING',
            'propagate': False,
        },
        'daphne': {
            'handlers': ['console'],
            'level': 'ERROR',
            'propagate': False,
        },
        'daphne.http_protocol': {
            'handlers': ['console'],
            'level': 'ERROR',
            'propagate': False,
        },
        'asyncio': {
            'handlers': ['console'],
            'level': 'ERROR',
            'propagate': False,
        },
    },
}
