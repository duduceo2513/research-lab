"""
Django settings for the standalone Research Lab backend.

All environment-specific values and every secret come from environment variables (optionally loaded
from ``.env``). See ``.env.example``.

No external services are required: the database is SQLite, research runs execute in a background
thread of the Django process (``research_lab/tasks.py``) and live WebSocket events go through the
in-memory channel layer of that same process.
"""
import sys
from datetime import timedelta

from django.core.exceptions import ImproperlyConfigured

from core.env import BASE_DIR, env_bool, env_float, env_int, env_list, env_str

TESTING = 'test' in sys.argv

# --------------------------------------------------------------------------
# Core
# --------------------------------------------------------------------------
DEBUG = env_bool('DJANGO_DEBUG', True)

SECRET_KEY = env_str('DJANGO_SECRET_KEY')
if not SECRET_KEY:
    if DEBUG or TESTING:
        SECRET_KEY = 'django-insecure-dev-only-key-do-not-use-in-production'
    else:
        raise ImproperlyConfigured('DJANGO_SECRET_KEY must be set when DEBUG is off.')

ALLOWED_HOSTS = env_list('DJANGO_ALLOWED_HOSTS', ['localhost', '127.0.0.1', '[::1]', 'testserver'])
CSRF_TRUSTED_ORIGINS = env_list('DJANGO_CSRF_TRUSTED_ORIGINS')

INSTALLED_APPS = [
    'core',  # first: its `runserver` (daphne + cleanup of interrupted runs) must win over daphne's own
    'daphne',  # must precede staticfiles so `runserver` serves ASGI (WebSockets)
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # third party
    'rest_framework',
    'rest_framework_simplejwt',
    'django_filters',
    'drf_spectacular',
    'channels',
    # project
    'accounts',
    'llm',
    'research_lab',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'core.urls'

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

WSGI_APPLICATION = 'core.wsgi.application'
ASGI_APPLICATION = 'core.asgi.application'

# --------------------------------------------------------------------------
# Database (SQLite)
#
# A research run writes from a background thread while API requests read and write too: WAL lets
# readers and the writer work side by side, IMMEDIATE transactions avoid "database is locked" upgrade
# deadlocks, and the timeout makes a writer wait for the lock instead of failing at once.
# --------------------------------------------------------------------------
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / env_str('SQLITE_PATH', 'db.sqlite3'),
        'OPTIONS': {
            'timeout': 30,
            'transaction_mode': 'IMMEDIATE',
            'init_command': 'PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;',
        },
    }
}

# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------
AUTH_USER_MODEL = 'accounts.User'
AUTHENTICATION_BACKENDS = ['accounts.backends.EmailOrUsernameBackend']

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

if TESTING:
    PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']

# Public sign-up creates TEACHER accounts (the role that can use Research Lab). Admins are created
# with `python manage.py createsuperuser`.
ALLOW_SELF_REGISTRATION = env_bool('ALLOW_SELF_REGISTRATION', True)

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=env_int('JWT_ACCESS_MINUTES', 30)),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=env_int('JWT_REFRESH_DAYS', 7)),
    'ROTATE_REFRESH_TOKENS': True,
    'AUTH_HEADER_TYPES': ('Bearer',),
    'UPDATE_LAST_LOGIN': True,
}

# --------------------------------------------------------------------------
# DRF
# --------------------------------------------------------------------------
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.IsAuthenticated'],
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ],
    'DEFAULT_PAGINATION_CLASS': 'core.pagination.DefaultPagination',
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'EXCEPTION_HANDLER': 'core.exceptions.api_exception_handler',
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': env_str('THROTTLE_ANON', '60/min'),
        'user': env_str('THROTTLE_USER', '600/min'),
    },
}
if TESTING:
    REST_FRAMEWORK['DEFAULT_THROTTLE_CLASSES'] = []

SPECTACULAR_SETTINGS = {
    'TITLE': 'Research Lab API',
    'DESCRIPTION': 'Multi-agent system that finds, reads and vets teaching material, then drafts a '
                   'lecture and an assignment.',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'COMPONENT_SPLIT_REQUEST': True,
    'ENUM_NAME_OVERRIDES': {
        'UserRoleEnum': 'accounts.models.UserRole',
        # ResearchRun.llm_mode and ModuleSettings.default_llm_mode share the same LLMMode set.
        'LlmModeEnum': 'research_lab.models.LLMMode',
    },
}

# --------------------------------------------------------------------------
# Channels (WebSocket). In-memory layer: events are produced by the research thread inside this same
# process, so no Redis is needed. Run a single server process.
# --------------------------------------------------------------------------
CHANNEL_LAYERS = {'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}}

# --------------------------------------------------------------------------
# i18n / static / media
# --------------------------------------------------------------------------
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / env_str('MEDIA_ROOT_DIR', 'media')

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024

# --------------------------------------------------------------------------
# LLM providers. API keys are NEVER stored in settings/DB: providers read them from the environment
# variable named in LLMProvider.secret_env_name (OPENAI_API_KEY, ANTHROPIC_API_KEY, ...).
# --------------------------------------------------------------------------
LOCAL_LLM_BASE_URL = env_str('LOCAL_LLM_BASE_URL', 'http://localhost:11434/v1')
LLM_REQUEST_TIMEOUT_SECONDS = env_float('LLM_REQUEST_TIMEOUT_SECONDS', 120.0)

# --------------------------------------------------------------------------
# Research Lab (see docs/ARCHITECTURE.md)
# --------------------------------------------------------------------------
RESEARCH_LAB_ENABLED = env_bool('RESEARCH_LAB_ENABLED', True)
# Tests run a research run inline in the request instead of in a background thread.
RESEARCH_LAB_RUN_INLINE = TESTING or env_bool('RESEARCH_LAB_RUN_INLINE', False)

RESEARCH_LAB_MAX_SEARCH_QUERIES = env_int('RESEARCH_LAB_MAX_SEARCH_QUERIES', 4)  # each is one paid Bright Data request
RESEARCH_LAB_MAX_RESULTS_PER_QUERY = env_int('RESEARCH_LAB_MAX_RESULTS_PER_QUERY', 10)
RESEARCH_LAB_MAX_DOCUMENTS = env_int('RESEARCH_LAB_MAX_DOCUMENTS', 20)
RESEARCH_LAB_MAX_RUNTIME_SECONDS = env_int('RESEARCH_LAB_MAX_RUNTIME_SECONDS', 30 * 60)
RESEARCH_LAB_MAX_REVISION_CYCLES = env_int('RESEARCH_LAB_MAX_REVISION_CYCLES', 2)
RESEARCH_LAB_MAX_LECTURE_REVISIONS = env_int('RESEARCH_LAB_MAX_LECTURE_REVISIONS', 2)
RESEARCH_LAB_MAX_DOWNLOAD_MB = env_int('RESEARCH_LAB_MAX_DOWNLOAD_MB', 20)
RESEARCH_LAB_FETCH_TIMEOUT_SECONDS = env_float('RESEARCH_LAB_FETCH_TIMEOUT_SECONDS', 20.0)
# Lectures/assignments are long JSON documents: a config tuned for short chat answers (e.g. 1024 tokens)
# would cut them off mid-string and make them unparsable, so agent calls get at least this many.
RESEARCH_LAB_MIN_OUTPUT_TOKENS = env_int('RESEARCH_LAB_MIN_OUTPUT_TOKENS', 8192)
# How much source text (characters, ~4 per token) one writer/reviewer prompt may carry in total. Long
# documents are never sent whole: the passages most relevant to the topic are picked without a model.
RESEARCH_LAB_CONTEXT_CHARS = env_int('RESEARCH_LAB_CONTEXT_CHARS', 30000)
RESEARCH_LAB_VALIDATION_EXCERPT_CHARS = env_int('RESEARCH_LAB_VALIDATION_EXCERPT_CHARS', 6000)
# Sources judged per validator request (1 = one request per source).
RESEARCH_LAB_VALIDATION_BATCH = env_int('RESEARCH_LAB_VALIDATION_BATCH', 4)
RESEARCH_LAB_FETCH_USER_AGENT = env_str('RESEARCH_LAB_FETCH_USER_AGENT', 'ResearchLab/1.0')

# Web search (SERP) — see research_lab/providers/search/brightdata.py.
BRIGHTDATA_API_TOKEN = env_str('BRIGHTDATA_API_TOKEN', '')
BRIGHTDATA_SERP_ZONE = env_str('BRIGHTDATA_SERP_ZONE', '') or env_str('BRIGHTDATA_ZONE', '')

# Academic providers — all keyless by design; a key (where supported) only raises rate limits.
OPENALEX_API_KEY = env_str('OPENALEX_API_KEY', '')
API_CONTACT_EMAIL = env_str('API_CONTACT_EMAIL', '')  # shared contact for the "polite pool" of public APIs
OPENALEX_MAILTO = env_str('OPENALEX_MAILTO', '') or API_CONTACT_EMAIL
SEMANTIC_SCHOLAR_API_KEY = env_str('SEMANTIC_SCHOLAR_API_KEY', '')
CROSSREF_MAILTO = env_str('CROSSREF_MAILTO', '') or API_CONTACT_EMAIL
GOOGLE_BOOKS_API_KEY = env_str('GOOGLE_BOOKS_API_KEY', '')
# Keyed sources: unusable (and shown as "API key missing") until the key is set.
CORE_API_KEY = env_str('CORE_API_KEY', '')
YOUTUBE_API_KEY = env_str('YOUTUBE_API_KEY', '')
# Document download policy: at most this many download attempts per source in one search.
RESEARCH_LAB_FETCH_PER_PROVIDER = env_int('RESEARCH_LAB_FETCH_PER_PROVIDER', 5)

# --------------------------------------------------------------------------
# Logging (secrets are scrubbed by RedactSecretsFilter)
# --------------------------------------------------------------------------
LOG_LEVEL = env_str('LOG_LEVEL', 'INFO')

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'filters': {
        'redact': {'()': 'core.logging_filters.RedactSecretsFilter'},
    },
    'formatters': {
        'verbose': {'format': '{asctime} {levelname} {name} {message}', 'style': '{'},
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
            'filters': ['redact'],
        },
    },
    'root': {'handlers': ['console'], 'level': LOG_LEVEL},
    'loggers': {
        'django.request': {'handlers': ['console'], 'level': 'WARNING', 'propagate': False},
        # Access logs may contain ?token=<jwt> for WebSockets; keep them quiet.
        'daphne.access': {'handlers': ['console'], 'level': 'WARNING', 'propagate': False},
        'llm': {'level': LOG_LEVEL},
        'research_lab': {'level': LOG_LEVEL},
    },
}
if TESTING:
    LOGGING['root']['level'] = 'CRITICAL'
    for _logger in LOGGING['loggers'].values():
        _logger['level'] = 'CRITICAL'
