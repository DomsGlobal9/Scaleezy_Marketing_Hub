"""
Django settings for scaleezy_backend project.
"""

import os
import environ
from pathlib import Path

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Initialize environ
env = environ.Env(
    DEBUG=(bool, False)
)
environ.Env.read_env(os.path.join(BASE_DIR, '.env'))

SECRET_KEY = env('DJANGO_SECRET_KEY', default='django-insecure-dev-key-do-not-use-in-prod')
DEBUG = env('DEBUG')

ALLOWED_HOSTS = ['*'] # Restrict in production

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    
    # Third-party
    'rest_framework',
    'corsheaders',

    # Local apps
    'apps.users',
    'apps.workspaces',
    'apps.marketing',
    'apps.social_accounts',
    'apps.publishing',
    'apps.gemini',
    'apps.analytics',
    'apps.audit',
    'apps.common',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware', # CORS middleware
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'scaleezy_backend.urls'

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

WSGI_APPLICATION = 'scaleezy_backend.wsgi.application'


# Database
DATABASES = {
    'default': env.db('DATABASE_URL', default=f'sqlite:///{BASE_DIR}/db.sqlite3')
}


# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True


# Static files
STATIC_URL = 'static/'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# CORS Settings
CORS_ALLOW_ALL_ORIGINS = True # Restrict in production


# DRF Settings
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
        'rest_framework.authentication.BasicAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.AllowAny',
    ]
}


# Celery Settings
CELERY_BROKER_URL = env('REDIS_URL', default='redis://localhost:6379/0')
CELERY_RESULT_BACKEND = env('REDIS_URL', default='redis://localhost:6379/0')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_ALWAYS_EAGER = env.bool('CELERY_TASK_ALWAYS_EAGER', default=False)


# API Keys & Third-party configs
GEMINI_API_KEY = env('GEMINI_API_KEY', default='')

# Force reload
SUPABASE_URL = env('SUPABASE_URL', default='')
SUPABASE_SERVICE_ROLE_KEY = env('SUPABASE_SERVICE_ROLE_KEY', default='')

# OAuth Defaults (to be loaded from env)
META_CLIENT_ID = env('META_CLIENT_ID', default='')
META_CLIENT_SECRET = env('META_CLIENT_SECRET', default='')
META_REDIRECT_URI = env('META_REDIRECT_URI', default='')
