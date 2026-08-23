"""
Django settings for scaleezy_backend project.
"""

import os
import sys
import environ
from datetime import timedelta
from pathlib import Path

from corsheaders.defaults import default_headers as default_cors_headers

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
    'rest_framework_simplejwt.token_blacklist',
    'corsheaders',

    # Local apps
    'apps.users',
    'apps.workspaces',
    'apps.marketing',
    'apps.brands',
    'apps.content',
    'apps.feedback',
    'apps.layouts',
    'apps.jobs',
    'apps.billing',
    'apps.ai',
    'apps.social_accounts',
    'apps.publishing',
    'apps.gemini',
    'apps.analytics',
    'apps.audit',
    'apps.common',
    'apps.knowledge',
    'apps.inspirations',
    'apps.learning',
    'apps.context',
    'apps.onboarding',
    'apps.universal',
    'apps.platform',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    # Serves the collected static files (Django admin CSS/JS) from the app
    # process itself, which is how a single Render web service works - there
    # is no separate static host in front of gunicorn.
    'whitenoise.middleware.WhiteNoiseMiddleware',
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
#
# Production must never fall back to SQLite: a deploy that loses DATABASE_URL
# would boot, create an empty local file database and serve 200s against it,
# which is silent data loss dressed as uptime. The fallback is kept only where
# it is genuinely wanted — local development (DEBUG) and the test runner — or
# where an operator opts in explicitly for a throwaway environment.
_RUNNING_TESTS = 'test' in sys.argv
_DATABASE_URL = env('DATABASE_URL', default='')
if _DATABASE_URL:
    DATABASES = {'default': env.db_url('DATABASE_URL')}
elif DEBUG or _RUNNING_TESTS or env.bool('ALLOW_SQLITE_FALLBACK', default=False):
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }
else:
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured(
        "DATABASE_URL is not set and DEBUG is off. Production requires the real "
        "database; set DATABASE_URL (or ALLOW_SQLITE_FALLBACK=True for a local "
        "non-debug experiment)."
    )

# Run the suite against a disposable in-memory SQLite database.
# Without this, `manage.py test` creates and drops a real database on the shared
# Supabase instance — slow, and the connection pooler holds sessions open which
# makes the teardown DROP fail.
if _RUNNING_TESTS:
    DATABASES['default'] = {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
    # Storage is stubbed under test for the same reason the database is.
    # Without this, any developer with a real .env runs the suite against the
    # live Supabase bucket: the brand-logo and poster-composition tests each
    # upload a file, and those files stay there. SupabaseStorageService reads
    # this flag and returns a deterministic URL without touching the network.
    STORAGE_TEST_MODE = True


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
# Where collectstatic gathers files at deploy time. Only the admin uses
# statics today, but the build fails without a target directory.
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    # Compressed but NOT manifest storage: manifest mode hard-fails the whole
    # deploy if any template references a static file that is missing, which
    # is a worse failure mode than an uncompressed asset.
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedStaticFilesStorage'},
}
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# CORS Settings
# Wide open in local development only. Production must supply an explicit
# allowlist via CORS_ALLOWED_ORIGINS (comma-separated) — an open CORS policy in
# front of encrypted OAuth tokens is not acceptable once deployed.
CORS_ALLOWED_ORIGINS = env.list('CORS_ALLOWED_ORIGINS', default=[])
CORS_ALLOW_ALL_ORIGINS = DEBUG and not CORS_ALLOWED_ORIGINS
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_HEADERS = list(default_cors_headers) + ['x-workspace-id']


# DRF Settings
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ],
    # Authenticated by default. Endpoints that must stay open (auth login and
    # refresh, the OAuth callback) opt out explicitly, so a newly added view is
    # closed unless someone deliberately opens it.
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    # Only views that set throttle_classes are throttled; today that is public
    # signup. Rates live in env so an abuse wave is a config change.
    'DEFAULT_THROTTLE_RATES': {
        'signup': env('SIGNUP_THROTTLE_RATE', default='5/hour'),
    },
    # Render (and any reverse proxy) puts the client in X-Forwarded-For and
    # the proxy in REMOTE_ADDR. With this unset every throttled caller shares
    # the proxy's IP and one bucket. One trusted hop; DRF takes the address
    # that hop appended, so a client-supplied header cannot spoof it.
    'NUM_PROXIES': env.int('NUM_PROXIES', default=1),
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=env.int('JWT_ACCESS_MINUTES', default=60)),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=env.int('JWT_REFRESH_DAYS', default=7)),
    'ROTATE_REFRESH_TOKENS': True,
    # Deliberately False. Logout blacklists explicitly (see LogoutView), which
    # is what makes sign-out real. Blacklisting on *rotation* as well would
    # break multi-tab use: two tabs refreshing at once each invalidate the
    # other's token and one gets logged out at random. Enable only after
    # cross-tab refresh coordination exists.
    'BLACKLIST_AFTER_ROTATION': False,
    'UPDATE_LAST_LOGIN': True,
    'AUTH_HEADER_TYPES': ('Bearer',),
    'SIGNING_KEY': SECRET_KEY,
}


# Background tasks
# Durable, database-backed, run by `manage.py run_tasks`. Django ships only an
# immediate backend, which executes inside the enqueueing request and so
# cannot outlive it or defer.
TASKS = {
    'default': {
        'BACKEND': 'apps.jobs.backend.DatabaseBackend',
        'OPTIONS': {'MAX_ATTEMPTS': env.int('TASK_MAX_ATTEMPTS', default=3)},
    }
}


# API Keys & Third-party configs
GEMINI_API_KEY = env('GEMINI_API_KEY', default='')
OPENAI_API_KEY = env('OPENAI_API_KEY', default='')
OPENAI_API_BASE_URL = env(
    'OPENAI_API_BASE_URL', default='https://api.openai.com/v1'
).rstrip('/')
OPENAI_REQUEST_TIMEOUT = env.float('OPENAI_REQUEST_TIMEOUT', default=60.0)

# Generation with no credential used to return canned copy, which the router
# then logged as a successful Gemini call and the API persisted as a real
# ContentItem - fabricated marketing copy, indistinguishable from the genuine
# article, sitting in a review queue. Mock output is now an explicit opt-in.
#
# Forced off outside DEBUG and the test runner rather than merely defaulting
# off: the whole point is that production cannot fabricate content, and a
# stray environment variable must not be able to switch that back on. Ignored
# rather than raised so a typo cannot take the site down.
GEMINI_MOCK_MODE = env.bool('GEMINI_MOCK_MODE', default=False) and (DEBUG or _RUNNING_TESTS)

# Force reload
SUPABASE_URL = env('SUPABASE_URL', default='')
SUPABASE_SERVICE_ROLE_KEY = env('SUPABASE_SERVICE_ROLE_KEY', default='')

# OAuth Defaults (to be loaded from env)
META_CLIENT_ID = env('META_CLIENT_ID', default='')
META_CLIENT_SECRET = env('META_CLIENT_SECRET', default='')
META_REDIRECT_URI = env('META_REDIRECT_URI', default='')
META_API_VERSION = env('META_API_VERSION', default='v20.0')
META_SCOPES = env('META_SCOPES', default='pages_show_list,pages_read_engagement,pages_manage_posts,instagram_basic,instagram_content_publish')

# LinkedIn OAuth
LINKEDIN_CLIENT_ID = env('LINKEDIN_CLIENT_ID', default='')
LINKEDIN_CLIENT_SECRET = env('LINKEDIN_CLIENT_SECRET', default='')
LINKEDIN_REDIRECT_URI = env('LINKEDIN_REDIRECT_URI', default='')
LINKEDIN_API_VERSION = env('LINKEDIN_API_VERSION', default='202408')
LINKEDIN_SCOPES = env('LINKEDIN_SCOPES', default='openid profile email w_member_social')

# YouTube OAuth
YOUTUBE_CLIENT_ID = env('YOUTUBE_CLIENT_ID', default='')
YOUTUBE_CLIENT_SECRET = env('YOUTUBE_CLIENT_SECRET', default='')
YOUTUBE_REDIRECT_URI = env('YOUTUBE_REDIRECT_URI', default='')
YOUTUBE_SCOPES = env('YOUTUBE_SCOPES', default='https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly')
