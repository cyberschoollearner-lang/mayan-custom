# Mayan EDMS — Повна інструкція розгортання

> Версія: Mayan EDMS s4.11 | Python 3.13 | PostgreSQL 15 | Docker

---

## Зміст

1. [Структура проєкту](#структура-проєкту)
2. [Підготовка сервера](#підготовка-сервера)
3. [Docker Compose](#docker-compose)
4. [Конфігурація (.env, config.yml, local.py)](#конфігурація)
5. [Custom Django додаток](#custom-django-додаток)
6. [Скрипти імпорту та синхронізації](#скрипти)
7. [Порядок розгортання](#порядок-розгортання)
8. [Управління користувачами](#управління-користувачами)
9. [Бекап та відновлення](#бекап-та-відновлення)
10. [Корисні команди](#корисні-команди)

---

## Структура проєкту

```
/opt/mayan/
├── docker-compose.yml
├── .env
├── .env-local
├── settings/
│   └── local.py
├── custom/
│   ├── __init__.py
│   ├── apps.py
│   ├── middleware.py
│   ├── signals.py
│   ├── views.py
│   ├── urls.py
│   └── templates/
│       └── appearance/
│           └── menus/
│               └── topbar.html
├── sync_clients.sh
└── sync_clinic.sh

/mnt/cephfs/mayan/
├── config.yml
├── login_bg.jpg
├── import_clinic.py
├── sync_users_from_mysql.py
└── document_storage/

/mnt/cephfs/clinic/
├── 0101/
├── 0102/
└── ...
```

---

## Підготовка сервера

```bash
# Docker
curl -fsSL https://get.docker.com | sh

# Директорії
mkdir -p /opt/mayan/{custom/templates/appearance/menus,settings}
mkdir -p /mnt/cephfs/mayan/document_storage
mkdir -p /mnt/cephfs/clinic
mkdir -p /mnt/cephfs/backup

# SSH ключі для remote серверів (якщо потрібно)
ssh-keygen -t ed25519
ssh-copy-id root@xxx.xxx.xxx.5
ssh-copy-id root@zzz.zzz.zzz.55
```

---

## Docker Compose

### `/opt/mayan/docker-compose.yml`

```yaml
x-mayan-depends_on-basic:
  &mayan-depends_on-basic
  depends_on:
    elasticsearch:
      condition: service_healthy
      required: false
    postgresql:
      condition: service_healthy
      required: false
    rabbitmq:
      condition: service_healthy
      required: false
    redis:
      condition: service_healthy
      required: false

x-mayan-depends_on-advanced:
  &mayan-depends_on-advanced
  depends_on:
    elasticsearch:
      condition: service_healthy
      required: false
    postgresql:
      condition: service_healthy
      required: false
    rabbitmq:
      condition: service_healthy
      required: false
    redis:
      condition: service_healthy
      required: false
    setup_or_upgrade:
      condition: service_completed_successfully
      required: false

x-mayan-environment:
  &mayan-environment
  MAYAN_CELERY_BROKER_URL: amqp://${MAYAN_RABBITMQ_USER:-mayan}:${MAYAN_RABBITMQ_PASSWORD:-mayanrabbitpass}@${MAYAN_DOCKER_RABBITMQ_HOSTNAME:-rabbitmq}:${MAYAN_DOCKER_RABBITMQ_PORT:-5672}/${MAYAN_RABBITMQ_VHOST:-mayan}
  MAYAN_CELERY_RESULT_BACKEND: redis://:${MAYAN_REDIS_PASSWORD:-mayanredispassword}@${MAYAN_DOCKER_REDIS_HOSTNAME:-redis}:${MAYAN_DOCKER_REDIS_PORT:-6379}/${MAYAN_REDIS_RESULT_DATABASE:-1}
  MAYAN_DATABASES: "{'default':{'ENGINE':'django.db.backends.postgresql','NAME':'${MAYAN_DATABASE_NAME:-mayan}','PASSWORD':'${MAYAN_DATABASE_PASSWORD:-mayandbpass}','USER':'${MAYAN_DATABASE_USER:-mayan}','HOST':'${MAYAN_DATABASE_HOST:-postgresql}','PORT':${MAYAN_DATABASE_PORT:-},'CONN_MAX_AGE':${MAYAN_DATABASE_CONN_MAX_AGE:-0},${MAYAN_DATABASE_EXTRA_OPTIONS:-}}}"
  MAYAN_LOCK_MANAGER_BACKEND: mayan.apps.lock_manager.backends.redis_lock.RedisLock
  MAYAN_LOCK_MANAGER_BACKEND_ARGUMENTS: "{'redis_url':'redis://:${MAYAN_REDIS_PASSWORD:-mayanredispassword}@${MAYAN_DOCKER_REDIS_HOSTNAME:-redis}:${MAYAN_DOCKER_REDIS_PORT:-6379}/${MAYAN_REDIS_LOCK_MANAGER_DATABASE:-2}'}"
  MAYAN_COMMON_EXTRA_APPS: "['custom.apps.CustomConfig']"
  MAYAN_AUTHENTICATION_BACKEND: "mayan.apps.authentication_otp.authentication_backends.AuthenticationBackendModelUsernamePasswordTOTP"

x-mayan-container:
  &mayan-container
  <<: [*mayan-depends_on-basic]
  env_file:
    - ${MAYAN_DOCKER_ENV_FILE:-.env}
    - path: .env-local
      required: false
  environment:
    <<: [*mayan-environment]
  image: ${MAYAN_DOCKER_IMAGE_NAME:-mayanedms/mayanedms}:${MAYAN_DOCKER_IMAGE_TAG:-s4.11}
  logging:
    driver: "json-file"
    options:
      max-size: "100m"
      max-file: "3"
      mode: "non-blocking"
  networks:
    - mayan
  restart: unless-stopped
  volumes:
    - /mnt/cephfs/mayan:/var/lib/mayan
    - /opt/mayan/custom:/opt/mayan-edms/lib/python3.13/site-packages/custom
    - /mnt/cephfs:/mnt/cephfs
    - /mnt/cephfs/mayan/login_bg.jpg:/opt/mayan-edms/static/authentication/images/login-top.6001694fb0e6.jpg
    - /mnt/cephfs/mayan/login_bg.jpg:/opt/mayan-edms/static/authentication/images/login-top.jpg
    - /opt/mayan/custom/templates/appearance/menus/topbar.html:/opt/mayan-edms/lib/python3.13/site-packages/mayan/apps/appearance_bootstrap/templates/appearance/menus/topbar.html
    - /opt/mayan/settings/local.py:/opt/mayan-edms/lib/python3.13/site-packages/mayan/settings/local.py

x-mayan-frontend-ports:
  &mayan-frontend-ports
  ports:
    - "${MAYAN_FRONTEND_HTTP_PORT:-80}:8000"

x-mayan-healthcheck:
  &mayan-healthcheck
  healthcheck:
    test: ["CMD-SHELL", "/opt/mayan-edms/bin/python -c \"import sys,urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8000/', timeout=5); sys.exit(0 if r.status<400 else 1)\""]
    interval: 30s
    timeout: 5s
    retries: 10
    start_period: 30s

x-mayan-traefik-labels:
  &mayan-traefik-labels
  labels:
    - "traefik.enable=${MAYAN_TRAEFIK_FRONTEND_ENABLE:-false}"

networks:
  mayan:
    driver: bridge
    internal: false
  traefik: {}

services:
  app:
    <<: [*mayan-container, *mayan-healthcheck, *mayan-traefik-labels, *mayan-frontend-ports]
    profiles:
      - all_in_one

  postgresql:
    command:
      - "postgres"
      - "-c"
      - "default_statistics_target=200"
      - "-c"
      - "max_connections=${MAYAN_DOCKER_POSTGRESQL_MAX_CONNECTIONS:-150}"
      - "-c"
      - "shared_buffers=2GB"
      - "-c"
      - "effective_cache_size=32GB"
      - "-c"
      - "work_mem=64MB"
      - "-c"
      - "maintenance_work_mem=1GB"
      - "-c"
      - "random_page_cost=1.1"
      - "-c"
      - "checkpoint_completion_target=0.9"
      - "-c"
      - "max_wal_size=2GB"
      - "-c"
      - "min_wal_size=512MB"
      - "-c"
      - "wal_buffers=16MB"
      - "-c"
      - "idle_in_transaction_session_timeout=5min"
      - "-c"
      - "lock_timeout=30s"
      - "-c"
      - "statement_timeout=10min"
    environment:
      POSTGRES_DB: ${MAYAN_DATABASE_NAME:-mayan}
      POSTGRES_PASSWORD: ${MAYAN_DATABASE_PASSWORD:-mayandbpass}
      POSTGRES_USER: ${MAYAN_DATABASE_USER:-mayan}
    healthcheck:
      test: ["CMD", "pg_isready", "--dbname", "${MAYAN_DATABASE_NAME:-mayan}", "--username", "${MAYAN_DATABASE_USER:-mayan}"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s
    image: ${MAYAN_DOCKER_POSTGRESQL_IMAGE:-postgres}:${MAYAN_DOCKER_POSTGRESQL_TAG:-15.17}
    networks:
      - mayan
    profiles:
      - postgresql
    restart: unless-stopped
    shm_size: 128m
    volumes:
      - ${MAYAN_POSTGRESQL_VOLUME:-postgres}:/var/lib/postgresql/data
      - ${MAYAN_POSTGRESQL_VOLUME_INITDB:-postgres-initdb}:/docker-entrypoint-initdb.d/

  rabbitmq:
    environment:
      RABBITMQ_DEFAULT_USER: ${MAYAN_RABBITMQ_USER:-mayan}
      RABBITMQ_DEFAULT_PASS: ${MAYAN_RABBITMQ_PASSWORD:-mayanrabbitpass}
      RABBITMQ_DEFAULT_VHOST: ${MAYAN_RABBITMQ_VHOST:-mayan}
    healthcheck:
      test: ["CMD", "rabbitmq-diagnostics", "ping"]
      interval: 30s
      timeout: 30s
      retries: 5
      start_period: 20s
    hostname: ${MAYAN_DOCKER_RABBITMQ_HOSTNAME:-rabbitmq}
    image: ${MAYAN_DOCKER_RABBITMQ_IMAGE:-rabbitmq}:${MAYAN_DOCKER_RABBITMQ_TAG:-4.1.8-management}
    networks:
      - mayan
    profiles:
      - rabbitmq
    restart: unless-stopped
    volumes:
      - ${MAYAN_RABBITMQ_VOLUME:-rabbitmq}:/var/lib/rabbitmq

  redis:
    command:
      - redis-server
      - --appendonly
      - "no"
      - --databases
      - "3"
      - --maxmemory
      - "100mb"
      - --maxmemory-policy
      - "allkeys-lru"
      - --requirepass
      - "${MAYAN_REDIS_PASSWORD:-mayanredispassword}"
    healthcheck:
      test: ["CMD", "redis-cli", "-a", "${MAYAN_REDIS_PASSWORD:-mayanredispassword}", "ping | grep PONG"]
      interval: 5s
      timeout: 5s
      retries: 5
    image: ${MAYAN_DOCKER_REDIS_IMAGE:-redis}:${MAYAN_DOCKER_REDIS_TAG:-7.4.8}
    networks:
      - mayan
    profiles:
      - redis
    restart: unless-stopped
    volumes:
      - ${MAYAN_REDIS_VOLUME:-redis}:/data

  setup_or_upgrade:
    <<: *mayan-container
    command:
      - run_initial_setup_or_perform_upgrade
    profiles:
      - extra_setup_or_upgrade
      - multi_container
    restart: "no"

volumes:
  app:
  postgres:
  postgres-backups:
  postgres-initdb:
  rabbitmq:
  redis:
```

---

## Конфігурація

### `/opt/mayan/.env`

```bash
COMPOSE_PROJECT_NAME=mayan
COMPOSE_PROFILES=all_in_one,postgresql,rabbitmq,redis
MAYAN_COMMON_EXTRA_APPS=custom.apps.CustomConfig
MAYAN_DOCKER_WAIT="postgresql:5432 rabbitmq:5672 redis:6379"
MAYAN_WORKER_CUSTOM_QUEUE_LIST=
MAYAN_TRAEFIK_LETS_ENCRYPT_EMAIL=
MAYAN_TRAEFIK_EXTERNAL_DOMAIN=
MAYAN_TRAEFIK_DASHBOARD_ENABLE=false
MAYAN_TRAEFIK_FRONTEND_ENABLE=false
MAYAN_TRAEFIK_RABBITMQ_ENABLE=false
```

### `/opt/mayan/.env-local`

```bash
MAYAN_LANGUAGE_CODE=uk
MAYAN_TIME_ZONE=Europe/Kyiv
```

### `/opt/mayan/settings/local.py`

```python
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 10}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

COMMON_PROJECT_TITLE = 'Медичний архів'

LOGIN_REDIRECT_URL = '/custom/home/'

MIDDLEWARE = [
    'mayan.apps.logging.middleware.error_logging.ErrorLoggingMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'mayan.apps.locales.middleware.locales.UserLocaleProfileMiddleware',
    'mayan.apps.authentication.middleware.impersonate.ImpersonateMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'stronghold.middleware.LoginRequiredMiddleware',
    'mayan.apps.views.middleware.ajax_redirect.AjaxRedirect',
    'custom.middleware.CurrentUserMiddleware',
]
```

### `/mnt/cephfs/mayan/config.yml` (ключові параметри)

```yaml
COMMON_EXTRA_APPS:
- custom.apps.CustomConfig

COMMON_HOME_VIEW: custom:home_redirect
LOGIN_REDIRECT_URL: /custom/home/
LOGOUT_REDIRECT_URL: authentication:login_view

ORGANIZATIONS_INSTALLATION_URL: http://YOUR_SERVER_IP

SEARCH_BACKEND: mayan.apps.dynamic_search.backends.django.DjangoSearchBackend

DOCUMENTS_FILE_STORAGE_BACKEND: django.core.files.storage.FileSystemStorage
DOCUMENTS_FILE_STORAGE_BACKEND_ARGUMENTS:
  location: /var/lib/mayan/document_storage

DOWNLOAD_FILE_EXPIRATION_INTERVAL: 1800

LANGUAGE_CODE: uk
TIME_ZONE: Europe/Kyiv
LOCALES_USER_DEFAULT_LANGUAGE: uk
LOCALES_USER_DEFAULT_TIMEZONE: Europe/Kyiv

AUTHENTICATION_BACKEND: mayan.apps.authentication_otp.authentication_backends.AuthenticationBackendModelUsernamePasswordTOTP
AUTHENTICATION_BACKEND_ARGUMENTS:
  maximum_session_length: 2592000
```

---

## Custom Django додаток

### `/opt/mayan/custom/__init__.py`

```python
default_app_config = 'custom.apps.CustomConfig'
```

### `/opt/mayan/custom/apps.py`

```python
from mayan.apps.app_manager.apps import MayanAppConfig
import os


class CustomConfig(MayanAppConfig):
    name = 'custom'
    app_url = 'custom'
    app_namespace = 'custom'

    def ready(self):
        super().ready()
        import custom.signals  # noqa
        self._remove_columns()
        self._remove_duplicate_backend_label()

    def _remove_columns(self):
        try:
            from mayan.apps.navigation.source_columns import SourceColumn
            from mayan.apps.documents.models import (
                Document, DocumentFile, DocumentVersion,
                DocumentFilePage, DocumentVersionPage
            )
            REMOVE_LABELS = {
                'Thumbnail', 'Type', 'Metadata', 'Pages', 'Tags',
            }
            for source in (Document, DocumentFile, DocumentVersion,
                           DocumentFilePage, DocumentVersionPage):
                if source in SourceColumn._registry:
                    SourceColumn._registry[source] = [
                        col for col in SourceColumn._registry[source]
                        if col.__dict__.get('label', '') not in REMOVE_LABELS
                    ]
        except Exception as e:
            print(f'[CUSTOM] remove_columns error: {e}')

    def _remove_duplicate_backend_label(self):
        # Прибираємо DuplicateBackendLabel з реєстру backend-класів,
        # щоб Mayan не пересинхронізовував його назад у StoredDuplicateBackend
        # після кожного імпорту/завантаження документа.
        # Залишається лише DuplicateBackendFileChecksum (перевірка по чексумі).
        try:
            from mayan.apps.duplicates.classes import DuplicateBackendMetaclass

            label_key = (
                'mayan.apps.duplicates.duplicate_backends.'
                'DuplicateBackendLabel'
            )
            DuplicateBackendMetaclass._registry.pop(label_key, None)
        except Exception as e:
            print(f'[CUSTOM] remove_duplicate_backend_label error: {e}')

    @classmethod
    def get_template_dirs(cls):
        return [os.path.join(os.path.dirname(__file__), 'templates')]
```

### `/opt/mayan/custom/middleware.py`

```python
import threading
from django.shortcuts import redirect
from django.urls import reverse

_thread_local = threading.local()


def get_current_user():
    return getattr(_thread_local, 'current_user', None)


class CurrentUserMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        _thread_local.current_user = getattr(request, 'user', None)
        response = self.get_response(request)
        return response


class CabinetRedirectMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        if (
            response.status_code == 302
            and request.path == '/authentication/login/'
            and request.user.is_authenticated
            and not request.user.is_superuser
        ):
            try:
                from mayan.apps.cabinets.models import Cabinet
                cabinet = Cabinet.objects.filter(
                    label=request.user.username,
                    parent=None
                ).first()

                if cabinet:
                    url = reverse(
                        'cabinets:cabinet_view',
                        kwargs={'cabinet_id': cabinet.pk}
                    )
                    return redirect(url)
            except Exception:
                pass

        return response
```

### `/opt/mayan/custom/signals.py`

```python
from actstream.models import Action
from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver
from django.contrib.contenttypes.models import ContentType
import os

from mayan.apps.documents.models import DocumentFile
from mayan.apps.documents.models import Document
from mayan.apps.cabinets.models import Cabinet
from mayan.apps.acls.models import AccessControlList
from mayan.apps.permissions.models import StoredPermission, Role


DOCUMENT_PERMISSIONS = [
    'document_view',
    'document_file_view',
    'document_version_view',
    'document_file_download',
    'document_file_print',
]

SKIP_USERS = {'admin', 'system', '_system_'}


@receiver(post_save, sender=Action)
def on_action_created(sender, instance, created, **kwargs):
    if not created:
        return
    if instance.verb != 'documents.document_create':
        return
    target = instance.target
    if not isinstance(target, Document):
        return
    actor = instance.actor
    username = getattr(actor, 'username', None)
    if not username or username in SKIP_USERS:
        return
    if getattr(actor, 'is_superuser', False):
        return

    document = target
    cabinet, _ = Cabinet.objects.get_or_create(label=username)
    cabinet.documents.add(document)

    try:
        role = Role.objects.get(label=f'role_{username}')
    except Role.DoesNotExist:
        print(f'[CABINET] WARNING: role_{username} not found')
        return

    doc_ct = ContentType.objects.get_for_model(document)
    acl, _ = AccessControlList.objects.get_or_create(
        content_type=doc_ct,
        object_id=document.pk,
        role=role
    )
    acl.permissions.add(
        *StoredPermission.objects.filter(name__in=DOCUMENT_PERMISSIONS)
    )
    print(f'[CABINET] {username} -> {document.label} OK')


@receiver(pre_delete, sender=DocumentFile)
def delete_hardlink_original(sender, instance, **kwargs):
    try:
        from custom.middleware import get_current_user
        current_user = get_current_user()

        if current_user is None:
            return
        if not getattr(current_user, 'is_superuser', False):
            return

        storage_path = instance.file.path
        parts = storage_path.split('/')
        filename = parts[-1]
        clinic_id = parts[-2]
        base = f'/mnt/cephfs/clinic/{clinic_id}'

        for root, dirs, files in os.walk(base):
            if filename in files:
                original = os.path.join(root, filename)
                os.remove(original)
                print(f'[DELETE] {original}')
                break

    except Exception as e:
        print(f'[DELETE ERROR] {e}')
```

### `/opt/mayan/custom/views.py`

```python
from django.http import HttpResponse, HttpResponseRedirect
from django.urls import reverse
from django.contrib.auth.decorators import login_required


@login_required
def home_redirect(request):
    if request.user.is_superuser:
        target_url = reverse('common:home')
    else:
        target_url = reverse('common:home')
        try:
            from mayan.apps.cabinets.models import Cabinet
            cabinet = Cabinet.objects.filter(
                label=request.user.username,
                parent=None
            ).first()
            if cabinet:
                target_url = reverse(
                    'cabinets:cabinet_view',
                    kwargs={'cabinet_id': cabinet.pk}
                )
        except Exception as e:
            print(f'[home_redirect] error: {e}')

    is_ajax = (
        request.META.get('HTTP_X_REQUESTED_WITH') == 'XMLHttpRequest'
        or request.META.get('HTTP_X_ALT_REFERER')
    )

    if is_ajax:
        response = HttpResponse(status=278)
        response['Location'] = target_url
        return response
    else:
        return HttpResponseRedirect(target_url)
```

### `/opt/mayan/custom/urls.py`

```python
from django.urls import re_path
from . import views

urlpatterns = [
    re_path(
        route=r'^home/$',
        name='home_redirect',
        view=views.home_redirect
    ),
]
```

### `/opt/mayan/custom/templates/appearance/menus/topbar.html`

```html
{% load i18n %}
{% load appearance_tags %}
{% load common_tags %}
{% load navigation_tags %}
{% spaceless %}
    <nav class="navbar navbar-default navbar-fixed-top">
        <div class="container-fluid">
            <div class="navbar-header">
                <button aria-expanded="false" aria-controls="navbar" class="navbar-toggle collapsed" data-toggle="collapse" data-target="#navbar" type="button">
                    <span class="sr-only">{% trans 'Toggle navigation' %}</span>
                    <span class="icon-bar"></span>
                    <span class="icon-bar"></span>
                    <span class="icon-bar"></span>
                </button>
                <div id="ajax-spinner" style="display: none;"></div>
                <a class="navbar-brand" href="{% url home_view %}"><span class="icon-mayan-edms-logo"></span> INSIDDEN</a>
            </div>
            <div class="collapse navbar-collapse" id="navbar">
                <ul class="nav navbar-nav navbar-right">
                    {% navigation_resolve_menu name='topbar' as topbar_menus_results %}
                    {% for tobpar_menu_result in topbar_menus_results %}
                        {% for link_group in tobpar_menu_result.link_groups %}
                            {% for link in link_group.links %}
                                {% with 'true' as as_li %}
                                {% with 'true' as hide_active_anchor %}
                                {% with 'active' as li_class_active %}
                                {% with 'first' as li_class_first %}
                                {% with ' ' as link_classes %}
                                    {% include 'navigation/generic_subnavigation.html' %}
                                {% endwith %}
                                {% endwith %}
                                {% endwith %}
                                {% endwith %}
                                {% endwith %}
                            {% endfor %}
                        {% endfor %}
                    {% endfor %}

                    {% if request.user.is_authenticated %}
                    <li>
                        <a id="download-btn" href="/storage/downloads/" title="{% trans 'Downloads' %}" style="padding:15px 12px; position:relative;">
                            <span class="fa fa-download" style="font-size:16px;"></span>
                            <span id="download-badge" style="
                                display:none;
                                position:absolute;
                                top:8px; right:4px;
                                background:#5cb85c;
                                color:#fff;
                                border-radius:8px;
                                font-size:10px;
                                font-weight:bold;
                                padding:1px 5px;
                                line-height:14px;
                            "></span>
                        </a>
                    </li>
                    {% endif %}

                </ul>
                {% appearance_app_templates template_name='topbar' %}
            </div>
        </div>
    </nav>
<style>
    /* Розширення полів пошуку: "Filter terms" (список документів) і "Search terms" (навбар) */
    #search-filter-input-terms {
        width: 100% !important;
        min-width: 320px;
    }
    .btn-toolbar-search-filter,
    .btn-toolbar-search-filter .form-group,
    .btn-toolbar-search-filter form {
        width: 100%;
    }
    #search-navbar-form-input-terms {
        width: 320px !important;
    }
    @media (min-width: 1200px) {
        #search-navbar-form-input-terms {
            width: 450px !important;
        }
    }
</style>

{% endspaceless %}

{% if request.user.is_authenticated %}
<script>
(function() {
    var CHECK_INTERVAL = 5000;
    var STORAGE_KEY = 'mayan_last_download_id';

    function getLastSeenId() {
        try { return parseInt(localStorage.getItem(STORAGE_KEY) || '0'); }
        catch(e) { return 0; }
    }

    function setLastSeenId(id) {
        try { localStorage.setItem(STORAGE_KEY, id); }
        catch(e) {}
    }

    function checkDownloads() {
        fetch('/api/v4/downloads/', {credentials: 'same-origin'})
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var results = data.results || [];
            var count = data.count || 0;
            var badge = document.getElementById('download-badge');
            var btn = document.getElementById('download-btn');

            if (count > 0) {
                badge.style.display = 'inline-block';
                badge.textContent = count;
                btn.style.color = '#5cb85c';

                var maxId = 0;
                for (var i = 0; i < results.length; i++) {
                    if (results[i].id > maxId) maxId = results[i].id;
                }

                var lastSeenId = getLastSeenId();
                if (maxId > lastSeenId) {
                    setLastSeenId(maxId);
                    // Автоматично завантажуємо файл
                    window.open(results[0].download_url, '_blank');
                }
            } else {
                badge.style.display = 'none';
                btn.style.color = '';
            }
        })
        .catch(function() {});
    }

    setTimeout(function() {
        checkDownloads();
        setInterval(checkDownloads, CHECK_INTERVAL);
    }, 2000);
})();
</script>
{% endif %}
```

---

## Скрипти

### `/mnt/cephfs/mayan/import_clinic.py`

```python
import os, sys, django
from datetime import datetime
import uuid
import hashlib

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mayan.settings.production')
django.setup()

from django.contrib.contenttypes.models import ContentType
from django.db.models import Model
from django.utils import timezone
from mayan.apps.documents.models import Document, DocumentType, DocumentFile
from mayan.apps.documents.literals import DEFAULT_DOCUMENT_FILE_ACTION_NAME
from mayan.apps.cabinets.models import Cabinet
from mayan.apps.acls.models import AccessControlList
from mayan.apps.permissions.models import StoredPermission, Role

CLINIC_ID     = sys.argv[1]
CLINIC_DIR    = f'/mnt/cephfs/clinic/{CLINIC_ID}'
MAYAN_STORAGE = '/mnt/cephfs/mayan/document_storage'

DOCUMENT_PERMISSIONS = [
    'document_view',
    'document_file_view',
    'document_version_view',
    'document_file_download',
    'document_file_print',
]

try:
    role = Role.objects.get(label=f'role_{CLINIC_ID}')
except Role.DoesNotExist:
    print(f'[ERROR] role_{CLINIC_ID} not found')
    sys.exit(1)

doc_type, _ = DocumentType.objects.get_or_create(label='Clinic Documents')
doc_ct       = ContentType.objects.get_for_model(Document)
counter      = {'ok': 0, 'skip': 0, 'linked': 0, 'error': 0}


def clean_filename(filename):
    return filename.encode('utf-8', errors='replace').decode('utf-8')


def sha256_file(filepath, block_size=65536):
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        while True:
            block = f.read(block_size)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def add_to_cabinet_with_acl(document, cabinet):
    cabinet.documents.add(document)
    acl, _ = AccessControlList.objects.get_or_create(
        content_type=doc_ct,
        object_id=document.pk,
        role=role,
    )
    acl.permissions.add(
        *StoredPermission.objects.filter(name__in=DOCUMENT_PERMISSIONS)
    )


def register_via_hardlink(filepath, filename, document):
    file_uuid = str(uuid.uuid4())
    dest_path = os.path.join(MAYAN_STORAGE, file_uuid)
    os.link(filepath, dest_path)

    try:
        doc_file = DocumentFile(
            document=document,
            comment='',
            filename=filename,
        )
        doc_file.file.name = file_uuid
        doc_file._event_actor = None
        doc_file._event_ignore = True
        Model.save(doc_file)

        document.file_latest = doc_file
        document.is_stub = False
        document.save(update_fields=('file_latest', 'is_stub'))

        doc_file._introspect()
        doc_file.versions_new(
            action_name=DEFAULT_DOCUMENT_FILE_ACTION_NAME,
            comment='',
            user=None,
        )

    except Exception:
        if os.path.exists(dest_path):
            os.remove(dest_path)
        raise

    return dest_path


def import_file(filepath, cabinet):
    raw_filename = os.path.basename(filepath)
    filename = clean_filename(raw_filename).strip()
    if not filename:
        return

    checksum = sha256_file(filepath)
    existing_file = DocumentFile.objects.filter(checksum=checksum).first()

    if existing_file:
        document = existing_file.document
        already_in_cabinet = cabinet.documents.filter(pk=document.pk).exists()
        if already_in_cabinet:
            counter['skip'] += 1
            print(f'[SKIP] {filename} вже в кабінеті', flush=True)
        else:
            add_to_cabinet_with_acl(document, cabinet)
            counter['linked'] += 1
            print(f'[LINK] {filename} → pk:{document.pk}', flush=True)
        os.remove(filepath)
        return

    document  = None
    dest_path = None

    try:
        file_mtime = os.path.getmtime(filepath)
        file_date  = timezone.make_aware(datetime.fromtimestamp(file_mtime))

        document = Document.objects.create(
            document_type=doc_type,
            label=filename,
            datetime_created=file_date,
        )

        dest_path = register_via_hardlink(filepath, filename, document)
        Document.objects.filter(pk=document.pk).update(datetime_created=file_date)
        add_to_cabinet_with_acl(document, cabinet)

        counter['ok'] += 1
        print(f'[OK {counter["ok"]}] {filename} ({file_date.strftime("%Y-%m-%d")})', flush=True)
        os.remove(filepath)

    except Exception as e:
        counter['error'] += 1
        print(f'[ERROR] {filepath}: {str(e).encode("utf-8", errors="replace").decode("utf-8")}', flush=True)
        if document:
            try:
                document.delete()
            except Exception:
                pass
        if dest_path and os.path.exists(dest_path):
            try:
                os.remove(dest_path)
            except Exception:
                pass


def get_or_create_sub(parent, label):
    sub, _ = Cabinet.objects.get_or_create(label=label, parent=parent)
    return sub


def cleanup_empty_dirs(path):
    for root, dirs, files in os.walk(path, topdown=False):
        for d in dirs:
            dirpath = os.path.join(root, d)
            if not os.listdir(dirpath):
                os.rmdir(dirpath)
                print(f'[RMDIR] {dirpath}')
    if os.path.isdir(path) and not os.listdir(path):
        os.rmdir(path)
        print(f'[RMDIR] {path}')
    elif os.path.isdir(path):
        remaining = sum(len(f) for _, _, f in os.walk(path))
        print(f'[INFO] Залишилось файлів: {remaining}')


def main():
    if not os.path.isdir(CLINIC_DIR):
        print(f'[ERROR] {CLINIC_DIR} not found')
        sys.exit(1)

    total = sum(len(files) for _, _, files in os.walk(CLINIC_DIR))
    print(f'[INFO] Всього файлів: {total}', flush=True)

    root_cabinet, _ = Cabinet.objects.get_or_create(label=CLINIC_ID)

    for fname in sorted(os.listdir(CLINIC_DIR)):
        fpath = os.path.join(CLINIC_DIR, fname)
        if os.path.isfile(fpath):
            import_file(fpath, root_cabinet)

    for year_dir in sorted(os.listdir(CLINIC_DIR)):
        year_path = os.path.join(CLINIC_DIR, year_dir)
        if not os.path.isdir(year_path):
            continue
        print(f'[DIR] {year_dir}', flush=True)
        year_cabinet = get_or_create_sub(root_cabinet, year_dir)
        for fname in sorted(os.listdir(year_path)):
            fpath = os.path.join(year_path, fname)
            if os.path.isfile(fpath):
                import_file(fpath, year_cabinet)

    print(f'\n=== {CLINIC_ID} ЗАВЕРШЕНО ===', flush=True)
    print(f'OK: {counter["ok"]} | LINK: {counter["linked"]} | SKIP: {counter["skip"]} | ERROR: {counter["error"]}')
    print(f'\n[CLEANUP] Видаляємо порожні папки...', flush=True)
    cleanup_empty_dirs(CLINIC_DIR)


main()
```

### `/opt/mayan/sync_clinic.sh`

```bash
#!/bin/bash
# sync_clinic.sh — rsync файлів клінік 0101-0999 з remote серверів
#
# Використання:
#   ./sync_clinic.sh          — всі клініки
#   ./sync_clinic.sh 0101     — одна клініка
#   ./sync_clinic.sh 0101 0102 0103

REMOTE_HOST1="xxx.xxx.xxx.5"
REMOTE_PATHS1=(
    "/var/snap/public"
    "/var/snap/yyy.yyy.yyy.yyy/new/public"
    "/var/snap/yyy.yyy.yyy.yyy/public"
)

REMOTE_HOST2="zzz.zzz.zzz.55"
REMOTE_PATHS2=(
    "/public"
)

LOCAL_BASE="/mnt/cephfs/clinic"

RSYNC_OPTS=(
    --archive
    --times
    --recursive
    --ignore-existing
    --no-perms
    --omit-dir-times
    --progress
    --human-readable
    --stats
)

sync_from_host() {
    local HOST="$1"
    local CLINIC_ID="$2"
    local LOCAL_DIR="$3"
    shift 3
    local PATHS=("$@")

    for REMOTE_DIR in "${PATHS[@]}"; do
        FULL_REMOTE="${REMOTE_DIR}/${CLINIC_ID}"
        if ssh "$HOST" "[ -d '$FULL_REMOTE' ]"; then
            echo "--- ${HOST}:${FULL_REMOTE} → ${LOCAL_DIR} ---"
            rsync "${RSYNC_OPTS[@]}" "${HOST}:${FULL_REMOTE}/" "${LOCAL_DIR}/"
        else
            echo "--- Пропускаємо ${HOST}:${FULL_REMOTE} (не існує) ---"
        fi
    done
}

sync_clinic() {
    local CLINIC_ID="$1"
    local LOCAL_DIR="$LOCAL_BASE/$CLINIC_ID"
    mkdir -p "$LOCAL_DIR"

    echo ""
    echo "════════════════════════════════════"
    echo "  Клініка: $CLINIC_ID"
    echo "════════════════════════════════════"

    sync_from_host "$REMOTE_HOST1" "$CLINIC_ID" "$LOCAL_DIR" "${REMOTE_PATHS1[@]}"
    sync_from_host "$REMOTE_HOST2" "$CLINIC_ID" "$LOCAL_DIR" "${REMOTE_PATHS2[@]}"

    echo "✔ $CLINIC_ID готово | файлів: $(find "$LOCAL_DIR" -type f | wc -l)"
}

get_all_clinics() {
    echo "Шукаємо всі клініки..."
    CLINICS1=$(ssh "$REMOTE_HOST1" "
        find /var/snap -mindepth 2 -maxdepth 3 -type d \
        | grep -oP '(?<=/public/)\d{4}' | sort -u
    ")
    CLINICS2=$(ssh "$REMOTE_HOST2" "
        find /public -mindepth 1 -maxdepth 1 -type d \
        | grep -oP '\d{4}$' | sort -u
    ")
    echo -e "${CLINICS1}\n${CLINICS2}" | sort -u | grep -v '^$'
}

if [ $# -gt 0 ]; then
    for CLINIC in "$@"; do
        sync_clinic "$CLINIC"
    done
else
    CLINICS=$(get_all_clinics)
    if [ -z "$CLINICS" ]; then
        echo "Клінік не знайдено"
        exit 1
    fi
    echo "Знайдено: $(echo "$CLINICS" | wc -l) клінік"
    for CLINIC in $CLINICS; do
        sync_clinic "$CLINIC"
    done
fi

echo ""
echo "=== СИНХРОНІЗАЦІЯ ЗАВЕРШЕНА ==="
```

### `/mnt/cephfs/mayan/sync_users_from_mysql.py`

```python
#!/usr/bin/env python3
"""
sync_users_from_mysql.py
MySQL login 1001 → Mayan login 01001 (5 знаків)

Режими:
    --import-all   імпорт всіх
    --once         одна перевірка (для cron)
    --daemon       демон
"""

import os, sys, django, time, argparse
import pymysql.cursors
import pymysql

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mayan.settings.production')
django.setup()

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType
from mayan.apps.permissions.models import Role, StoredPermission
from mayan.apps.cabinets.models import Cabinet
from mayan.apps.acls.models import AccessControlList
from mayan.apps.events.models import EventSubscription
from mayan.apps.events.classes import EventType
from mayan.apps.views.models import UserViewMode

DB_CONFIG = {
    'host':      '127.0.0.1',
    'port':      3306,
    'user':      '<DB_USER>',
    'password':  '<DB_PASSWORD>',
    'database':  '<DB_NAME>',
    'charset':   'utf8mb4',
    'cursorclass': pymysql.cursors.DictCursor,
}
DB_TABLE = 'main_db'

GLOBAL_PERMS = [
    'document_view', 'document_file_view', 'document_version_view',
    'document_file_download', 'document_file_print',
    'message_create', 'message_delete', 'message_edit', 'message_view',
]

CABINET_PERMS = [
    'cabinet_view', 'document_view', 'document_file_view',
    'document_file_download', 'document_version_view',
]

SUBSCRIBE_EVENTS = ['download_files.downloaded', 'download_files.created']

LIST_VIEW_NAMES = [
    'documents:document_list', 'cabinets:cabinet_view', 'cabinets:cabinet_list',
]

User = get_user_model()


def to_mayan_login(mysql_login):
    return f'{int(mysql_login):05d}'


def db_connect():
    return pymysql.connect(**DB_CONFIG)


def get_all_users(conn):
    with conn.cursor() as cur:
        cur.execute(f"""
            SELECT login, pass, fio, addr, phone, email, state,
                   add_user_stats, del_user_stats, ch_pwd
            FROM {DB_TABLE}
            WHERE login REGEXP '^[0-9]+$'
              AND CAST(login AS UNSIGNED) BETWEEN 1000 AND 9999
        """)
        return cur.fetchall()


def get_pending_users(conn):
    with conn.cursor() as cur:
        cur.execute(f"""
            SELECT login, pass, fio, addr, phone, email, state,
                   add_user_stats, del_user_stats, ch_pwd
            FROM {DB_TABLE}
            WHERE login REGEXP '^[0-9]+$'
              AND CAST(login AS UNSIGNED) BETWEEN 1000 AND 9999
              AND add_user_stats = 1
        """)
        return cur.fetchall()


def setup_list_mode(user):
    for view_name in LIST_VIEW_NAMES:
        namespace = view_name.split(':')[0]
        UserViewMode.objects.get_or_create(
            defaults={'namespace': namespace, 'value': 'list'},
            name=view_name, user=user,
        )


def subscribe_user(user):
    for event_id in SUBSCRIBE_EVENTS:
        try:
            event = EventType.get(id=event_id)
            EventSubscription.objects.get_or_create(
                user=user, stored_event_type=event.stored_event_type,
            )
        except Exception as e:
            print(f'  [WARN] {event_id}: {e}')


def create_or_update_user(row):
    mysql_login = str(row['login']).strip()
    username    = to_mayan_login(mysql_login)
    password    = str(row['pass']).strip()
    fio         = str(row['fio'] or '').strip()
    email       = str(row['email'] or '').strip()
    del_user    = bool(row['del_user_stats'])
    ch_pwd      = bool(row['ch_pwd'])

    parts      = fio.split(None, 1)
    last_name  = parts[0] if parts else ''
    first_name = parts[1] if len(parts) > 1 else ''

    user, created = User.objects.get_or_create(username=username)

    if created:
        user.set_password(password)
        user.first_name = first_name
        user.last_name  = last_name
        user.email      = email
        user.is_active  = not del_user
        user.save()
        print(f'  [NEW] {username} (MySQL:{mysql_login}) / {fio}')
    else:
        changed = False
        if ch_pwd:
            user.set_password(password)
            changed = True
            print(f'  [PWD] {username}')
        if user.is_active == del_user:
            user.is_active = not del_user
            changed = True
            print(f'  [STATE] {username} {"деактивовано" if del_user else "активовано"}')
        if changed:
            user.save()
        else:
            print(f'  [SKIP] {username}')
        return None

    group, _ = Group.objects.get_or_create(name=f'group_{username}')
    role, _  = Role.objects.get_or_create(label=f'role_{username}')
    role.groups.add(group)
    role.permissions.add(*StoredPermission.objects.filter(name__in=GLOBAL_PERMS))
    group.user_set.add(user)
    subscribe_user(user)
    setup_list_mode(user)

    cabinet, _ = Cabinet.objects.get_or_create(label=username)
    cabinet_ct = ContentType.objects.get_for_model(Cabinet)
    acl, _ = AccessControlList.objects.get_or_create(
        content_type=cabinet_ct, object_id=cabinet.pk, role=role,
    )
    acl.permissions.add(*StoredPermission.objects.filter(name__in=CABINET_PERMS))
    return username


def import_all():
    print('=== Імпорт всіх клієнтів 1000-9999 ===')
    conn = db_connect()
    rows = get_all_users(conn)
    conn.close()
    for row in rows:
        try:
            create_or_update_user(row)
        except Exception as e:
            print(f'  [ERROR] {row["login"]}: {e}')
    print('=== ГОТОВО ===')


def sync_once():
    conn = db_connect()
    rows = get_pending_users(conn)
    conn.close()
    if not rows:
        return []
    print(f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] Нових/змінених: {len(rows)}')
    new_clients = []
    for row in rows:
        try:
            result = create_or_update_user(row)
            if result:
                new_clients.append({
                    'mysql_login': str(row['login']).strip(),
                    'mayan_id': result
                })
        except Exception as e:
            print(f'  [ERROR] {row["login"]}: {e}')
    return new_clients


def run_daemon(interval=60):
    print(f'=== Демон запущено, інтервал {interval}с ===')
    while True:
        try:
            sync_once()
        except Exception as e:
            print(f'[ERROR] {e}')
        time.sleep(interval)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--import-all', action='store_true')
    parser.add_argument('--daemon',     action='store_true')
    parser.add_argument('--once',       action='store_true')
    parser.add_argument('--interval',   type=int, default=60)
    args = parser.parse_args()

    if args.import_all:
        import_all()
    elif args.daemon:
        run_daemon(interval=args.interval)
    elif args.once:
        new = sync_once()
        for c in new:
            print(f'NEW_CLIENT:{c["mysql_login"]}:{c["mayan_id"]}')
    else:
        parser.print_help()
```

### `/opt/mayan/sync_clients.sh`

```bash
#!/bin/bash
# sync_clients.sh — синхронізація клієнтів 1000-9999 (→ 01000-09999)
#
# Використання:
#   ./sync_clients.sh                      # cron
#   ./sync_clients.sh --no-rsync           # без rsync
#   ./sync_clients.sh --manual 1001        # ручний запуск
#   ./sync_clients.sh --manual 1001 --no-rsync
#   ./sync_clients.sh --import-only        # тільки імпорт

REMOTE_HOST1="xxx.xxx.xxx.5"
REMOTE_PATHS1=(
    "/var/snap/public"
    "/var/snap/yyy.yyy.yyy.yyy/new/public"
    "/var/snap/yyy.yyy.yyy.yyy/public"
)

REMOTE_HOST2="zzz.zzz.zzz.55"
REMOTE_PATHS2=(
    "/public"
    "/backup/public"
)

LOCAL_BASE="/mnt/cephfs/clinic"
MAYAN_PYTHON="/opt/mayan-edms/bin/python"
MAYAN_SCRIPT="/var/lib/mayan/import_clinic.py"
MAYAN_SYNC="/var/lib/mayan/sync_users_from_mysql.py"
MAYAN_CONTAINER="mayan-app-1"
LOG_FILE="/var/log/sync_clients.log"
CURRENT_YEAR=$(date +%Y)

DO_RSYNC=true
MANUAL_CLIENT=""
IMPORT_ONLY=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-rsync)    DO_RSYNC=false; shift ;;
        --import-only) IMPORT_ONLY=true; DO_RSYNC=false; shift ;;
        --manual)      MANUAL_CLIENT="$2"; shift 2 ;;
        *) shift ;;
    esac
done

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

to_mayan_id() {
    printf '%05d' "$1"
}

rsync_from_host() {
    local HOST="$1"
    local CLIENT_ID="$2"
    local LOCAL_DIR="$3"
    shift 3
    local PATHS=("$@")

    local RSYNC_OPTS=(--archive --times --recursive --ignore-existing
                      --no-perms --omit-dir-times --quiet)

    for RPATH in "${PATHS[@]}"; do
        REMOTE_DIR="${RPATH}/${CLIENT_ID}"
        if ssh -o ConnectTimeout=5 "$HOST" "[ -d '$REMOTE_DIR' ]" 2>/dev/null; then
            log "  rsync ${HOST}:${REMOTE_DIR}/ → ${LOCAL_DIR}/"
            rsync "${RSYNC_OPTS[@]}" "${HOST}:${REMOTE_DIR}/" "${LOCAL_DIR}/"
        fi
    done
}

rsync_client() {
    local CLIENT_ID="$1"
    local MAYAN_ID="$2"
    local LOCAL_DIR="$LOCAL_BASE/$MAYAN_ID"
    mkdir -p "$LOCAL_DIR"
    rsync_from_host "$REMOTE_HOST1" "$CLIENT_ID" "$LOCAL_DIR" "${REMOTE_PATHS1[@]}"
    rsync_from_host "$REMOTE_HOST2" "$CLIENT_ID" "$LOCAL_DIR" "${REMOTE_PATHS2[@]}"
}

sort_by_year() {
    local LOCAL_DIR="$1"
    [ -d "$LOCAL_DIR" ] || return
    local moved=0
    for fpath in "$LOCAL_DIR"/*; do
        [ -f "$fpath" ] || continue
        fname=$(basename "$fpath")
        year=$(date -r "$fpath" +%Y 2>/dev/null)
        [ -z "$year" ] && continue
        [ "$year" = "$CURRENT_YEAR" ] && continue
        year_dir="$LOCAL_DIR/$year"
        mkdir -p "$year_dir"
        mv "$fpath" "$year_dir/$fname"
        log "  [SORT] $fname → $year/"
        moved=$((moved + 1))
    done
    [ $moved -gt 0 ] && log "  [SORT] Переміщено: $moved"
}

import_to_mayan() {
    local MAYAN_ID="$1"
    log "  [IMPORT] $MAYAN_ID"
    docker exec "$MAYAN_CONTAINER" \
        "$MAYAN_PYTHON" "$MAYAN_SCRIPT" "$MAYAN_ID" 2>&1 | tee -a "$LOG_FILE"
}

process_client() {
    local CLIENT_ID="$1"
    local MAYAN_ID
    MAYAN_ID=$(to_mayan_id "$CLIENT_ID")
    log "=== Клієнт: $CLIENT_ID → $MAYAN_ID ==="
    $DO_RSYNC && rsync_client "$CLIENT_ID" "$MAYAN_ID"
    sort_by_year "$LOCAL_BASE/$MAYAN_ID"
    import_to_mayan "$MAYAN_ID"
}

sync_from_mysql() {
    log "Перевірка MySQL..."
    docker exec "$MAYAN_CONTAINER" \
        "$MAYAN_PYTHON" "$MAYAN_SYNC" --once 2>&1 | tee -a "$LOG_FILE"
}

if [ -n "$MANUAL_CLIENT" ]; then
    log "=== РУЧНИЙ ЗАПУСК: $MANUAL_CLIENT ==="
    process_client "$MANUAL_CLIENT"
    log "=== ГОТОВО ==="
    exit 0
fi

if $IMPORT_ONLY; then
    log "=== IMPORT ONLY ==="
    for dir in "$LOCAL_BASE"/0[1-9][0-9][0-9][0-9]; do
        [ -d "$dir" ] || continue
        MAYAN_ID=$(basename "$dir")
        num=${MAYAN_ID#0}
        if [ "$num" -ge 1000 ] 2>/dev/null && [ "$num" -le 9999 ] 2>/dev/null; then
            sort_by_year "$dir"
            import_to_mayan "$MAYAN_ID"
        fi
    done
    log "=== ГОТОВО ==="
    exit 0
fi

# Cron режим
NEW_CLIENTS=$(sync_from_mysql | grep "^NEW_CLIENT:")

if [ -z "$NEW_CLIENTS" ]; then
    exit 0
fi

while IFS=: read -r _ CLIENT_ID MAYAN_ID; do
    [ -n "$CLIENT_ID" ] || continue
    process_client "$CLIENT_ID"
done <<< "$NEW_CLIENTS"

log "=== СИНХРОНІЗАЦІЯ ЗАВЕРШЕНА ==="
```

### `import_clinics_from_csv.sh`

```bash
docker exec -i mayan-app-1 /opt/mayan-edms/bin/mayan-edms.py shell << 'PYEOF'
import csv, secrets, string
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType
from mayan.apps.permissions.models import Role, StoredPermission
from mayan.apps.cabinets.models import Cabinet
from mayan.apps.acls.models import AccessControlList
from mayan.apps.events.models import EventSubscription
from mayan.apps.events.classes import EventType

GLOBAL_PERMS = [
    "document_create", "document_type_view", "sources_setup_view", "sources_view",
    "document_view", "document_file_view", "document_version_view",
    "document_file_download", "document_file_print",
    "message_create", "message_delete", "message_edit", "message_view",
]

CABINET_PERMS = [
    "cabinet_view", "document_view", "document_file_view",
    "document_file_download", "document_version_view",
]

SUBSCRIBE_EVENTS = ['download_files.downloaded', 'download_files.created']

User = get_user_model()
log = open('/var/lib/mayan/users_created.csv', 'w')
log.write('login,password,description\n')

def gen_password(length=12):
    return ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(length))

def subscribe_user(user):
    for event_id in SUBSCRIBE_EVENTS:
        try:
            event = EventType.get(id=event_id)
            EventSubscription.objects.get_or_create(
                user=user, stored_event_type=event.stored_event_type,
            )
        except Exception as e:
            print(f"  [WARN] {event_id}: {e}")

with open('/var/lib/mayan/clinics.csv', newline='', encoding='utf-8') as f:
    for row in csv.reader(f):
        if not row:
            continue
        USERNAME    = row[0].strip()
        DESCRIPTION = row[2].strip() if len(row) > 2 else ''
        PASSWORD    = gen_password()

        group, _ = Group.objects.get_or_create(name=f"group_{USERNAME}")
        role, _  = Role.objects.get_or_create(label=f"role_{USERNAME}")
        role.groups.add(group)
        role.permissions.add(*StoredPermission.objects.filter(name__in=GLOBAL_PERMS))

        user, created = User.objects.get_or_create(username=USERNAME)
        if created:
            user.set_password(PASSWORD)
            user.first_name = DESCRIPTION
            user.save()
        else:
            PASSWORD = '*** exists ***'
        group.user_set.add(user)
        subscribe_user(user)

        cabinet, _ = Cabinet.objects.get_or_create(label=USERNAME)
        cabinet_ct = ContentType.objects.get_for_model(cabinet)
        acl, _ = AccessControlList.objects.get_or_create(
            content_type=cabinet_ct, object_id=cabinet.pk, role=role
        )
        acl.permissions.add(*StoredPermission.objects.filter(name__in=CABINET_PERMS))

        print(f"{USERNAME},{PASSWORD},{DESCRIPTION}")
        log.write(f"{USERNAME},{PASSWORD},{DESCRIPTION}\n")

log.close()
print("\n=== ГОТОВО === паролі: /var/lib/mayan/users_created.csv")
PYEOF
```

### `step-1-create-user.sh`

```bash
docker exec -i mayan-app-1 /opt/mayan-edms/bin/mayan-edms.py shell << 'PYEOF'
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType
from mayan.apps.permissions.models import Role, StoredPermission
from mayan.apps.cabinets.models import Cabinet
from mayan.apps.acls.models import AccessControlList
from mayan.apps.events.models import EventSubscription
from mayan.apps.events.classes import EventType

# =========================
USERS    = ["0101", "0102"]  # <-- редагуй тут
PASSWORD = "ChangeMe123!"
# =========================

GLOBAL_PERMS = [
    "document_create", "document_type_view", "sources_setup_view", "sources_view",
    "document_view", "document_file_view", "document_version_view",
    "document_file_download", "document_file_print",
    "message_create", "message_delete", "message_edit", "message_view",
]

CABINET_PERMS = [
    "cabinet_view", "document_view", "document_file_view",
    "document_file_download", "document_version_view",
]

SUBSCRIBE_EVENTS = ['download_files.downloaded', 'download_files.created']

User = get_user_model()

for USERNAME in USERS:
    group, _ = Group.objects.get_or_create(name=f"group_{USERNAME}")
    role, _  = Role.objects.get_or_create(label=f"role_{USERNAME}")
    role.groups.add(group)
    role.permissions.add(*StoredPermission.objects.filter(name__in=GLOBAL_PERMS))

    user, created = User.objects.get_or_create(username=USERNAME)
    if created:
        user.set_password(PASSWORD)
        user.save()
    group.user_set.add(user)

    for event_id in SUBSCRIBE_EVENTS:
        try:
            event = EventType.get(id=event_id)
            EventSubscription.objects.get_or_create(
                user=user, stored_event_type=event.stored_event_type,
            )
        except Exception as e:
            print(f"  [WARN] {event_id}: {e}")

    cabinet, _ = Cabinet.objects.get_or_create(label=USERNAME)
    cabinet_ct = ContentType.objects.get_for_model(cabinet)
    acl, _ = AccessControlList.objects.get_or_create(
        content_type=cabinet_ct, object_id=cabinet.pk, role=role
    )
    acl.permissions.add(*StoredPermission.objects.filter(name__in=CABINET_PERMS))
    print(f"[OK] {USERNAME}")

print("\n=== ГОТОВО ===")
PYEOF
```

---

## Порядок розгортання

```bash
# 1. Клонуємо/копіюємо всі файли
cp -r custom/ /opt/mayan/custom/
cp docker-compose.yml /opt/mayan/
cp .env /opt/mayan/
cp .env-local /opt/mayan/
cp settings/local.py /opt/mayan/settings/
cp import_clinic.py /mnt/cephfs/mayan/
cp sync_users_from_mysql.py /mnt/cephfs/mayan/
cp sync_clinic.sh /opt/mayan/ && chmod +x /opt/mayan/sync_clinic.sh
cp sync_clients.sh /opt/mayan/ && chmod +x /opt/mayan/sync_clients.sh

# 2. Стартуємо
cd /opt/mayan
docker compose up -d

# 3. Чекаємо (~3 хвилини)
docker logs -f mayan-app-1 | grep -E "ready|error|ERROR"

# 4. Копіюємо скрипти в контейнер
docker cp /mnt/cephfs/mayan/import_clinic.py mayan-app-1:/var/lib/mayan/
docker cp /mnt/cephfs/mayan/sync_users_from_mysql.py mayan-app-1:/var/lib/mayan/

# 5. Створюємо клініки
docker cp clinics.csv mayan-app-1:/var/lib/mayan/
bash /opt/mayan-project/scripts/import_clinics_from_csv.sh

# 6. rsync і імпорт файлів
./sync_clinic.sh 0101
docker exec mayan-app-1 /opt/mayan-edms/bin/python \
  /var/lib/mayan/import_clinic.py 0101

# 7. Імпорт клієнтів з MySQL
docker exec mayan-app-1 /opt/mayan-edms/bin/python \
  /var/lib/mayan/sync_users_from_mysql.py --import-all

# 8. Cron для автосинхронізації
crontab -e
# Додати:
* * * * * /opt/mayan/sync_clients.sh >> /var/log/sync_clients.log 2>&1
```

---

## Управління користувачами

### Права доступу

| Тип | Глобально | На документ (ACL) | На кабінет (ACL) |
|-----|-----------|-------------------|------------------|
| **Клініки** 0101-0999 | document_create, document_type_view, sources_*, message_* | document_view, document_file_view, document_file_download, document_version_view | cabinet_view + doc perms |
| **Клієнти** 01000-09999 | message_* | document_view, document_file_view, document_file_download, document_version_view | cabinet_view + doc perms |

### Виправлення прав для існуючих юзерів

```bash
docker exec mayan-app-1 /opt/mayan-edms/bin/python -c "
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mayan.settings.production')
django.setup()
from mayan.apps.permissions.models import Role, StoredPermission

perms = StoredPermission.objects.filter(name__in=[
    'document_file_download', 'document_file_print', 'document_version_view',
    'message_view', 'message_create', 'message_delete', 'message_edit',
])
for role in Role.objects.filter(label__startswith='role_'):
    role.permissions.add(*perms)
    print(role.label)
"
```

### Підписка на події завантаження

```bash
docker exec mayan-app-1 /opt/mayan-edms/bin/python -c "
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mayan.settings.production')
django.setup()
from django.contrib.auth import get_user_model
from mayan.apps.events.models import EventSubscription
from mayan.apps.events.classes import EventType

User = get_user_model()
for event_id in ['download_files.downloaded', 'download_files.created']:
    event = EventType.get(id=event_id)
    for user in User.objects.exclude(is_superuser=True):
        EventSubscription.objects.get_or_create(
            user=user, stored_event_type=event.stored_event_type,
        )
print('ГОТОВО')
"
```

---

## Бекап та відновлення

### `backups.sh`

```bash
#!/bin/bash
# backups.sh — бекап всіх важливих файлів Mayan EDMS + коміт у git
#
# Використання:
#   ./backups.sh              # повний бекап + git commit + push
#   ./backups.sh --no-git     # тільки бекап, без git

DO_GIT=true
[[ "$1" == "--no-git" ]] && DO_GIT=false

BACKUP_DIR="/mnt/cephfs/backup/$(date +%Y%m%d_%H%M)"
PROJECT_DIR="/opt/mayan-project"
mkdir -p "$BACKUP_DIR"/{custom,settings,scripts,config}

echo "=== Бекап в $BACKUP_DIR ==="

# 1. БД PostgreSQL
echo "--- БД ---"
docker exec mayan-postgresql-1 pg_dump -U mayan mayan | gzip \
  > "$BACKUP_DIR/mayan_db.sql.gz"
ls -lh "$BACKUP_DIR/mayan_db.sql.gz"

# 2. Docker конфіг
echo "--- Docker ---"
cp /opt/mayan/docker-compose.yml "$BACKUP_DIR/config/"
cp /opt/mayan/.env               "$BACKUP_DIR/config/"
cp /opt/mayan/.env-local         "$BACKUP_DIR/config/" 2>/dev/null || true

# 3. Mayan config.yml
echo "--- config.yml ---"
cp /mnt/cephfs/mayan/config.yml "$BACKUP_DIR/config/"

# 4. Custom додаток
echo "--- Custom app ---"
cp /opt/mayan/custom/__init__.py   "$BACKUP_DIR/custom/"
cp /opt/mayan/custom/apps.py       "$BACKUP_DIR/custom/"
cp /opt/mayan/custom/middleware.py "$BACKUP_DIR/custom/"
cp /opt/mayan/custom/signals.py    "$BACKUP_DIR/custom/"
cp /opt/mayan/custom/views.py      "$BACKUP_DIR/custom/" 2>/dev/null || true
cp /opt/mayan/custom/urls.py       "$BACKUP_DIR/custom/" 2>/dev/null || true
mkdir -p "$BACKUP_DIR/custom/templates/appearance/menus"
cp /opt/mayan/custom/templates/appearance/menus/topbar.html \
   "$BACKUP_DIR/custom/templates/appearance/menus/"

# 5. Settings
echo "--- Settings ---"
cp /opt/mayan/settings/local.py "$BACKUP_DIR/settings/" 2>/dev/null || true

# 6. Скрипти
echo "--- Скрипти ---"
cp /mnt/cephfs/mayan/import_clinic.py         "$BACKUP_DIR/scripts/"
cp /mnt/cephfs/mayan/sync_users_from_mysql.py "$BACKUP_DIR/scripts/" 2>/dev/null || true
cp /opt/mayan/sync_clients.sh                 "$BACKUP_DIR/scripts/" 2>/dev/null || true
cp /opt/mayan/sync_clinic.sh                  "$BACKUP_DIR/scripts/" 2>/dev/null || true
cp /mnt/cephfs/mayan/rotate_cabinets.py       "$BACKUP_DIR/scripts/" 2>/dev/null || true
cp /opt/mayan/sync_and_import.sh              "$BACKUP_DIR/scripts/" 2>/dev/null || true
cp /mnt/cephfs/backup/backups.sh              "$BACKUP_DIR/scripts/" 2>/dev/null || true

# 7. Медіа
echo "--- Медіа ---"
cp /mnt/cephfs/mayan/login_bg.jpg "$BACKUP_DIR/" 2>/dev/null || true

echo ""
echo "=== ГОТОВО ==="
echo "Розмір бекапу:"
du -sh "$BACKUP_DIR"
ls -lh "$BACKUP_DIR/"
ls -lh "$BACKUP_DIR/custom/"
ls -lh "$BACKUP_DIR/scripts/"
ls -lh "$BACKUP_DIR/config/"

# 8. Синхронізація в git-проєкт і коміт
if $DO_GIT; then
    echo ""
    echo "--- Git sync ---"
    cp /opt/mayan/custom/*.py "$PROJECT_DIR/custom/" 2>/dev/null
    cp /opt/mayan/custom/templates/appearance/menus/topbar.html \
       "$PROJECT_DIR/custom/templates/appearance/menus/"
    cp /opt/mayan/settings/local.py "$PROJECT_DIR/settings/" 2>/dev/null
    cp /opt/mayan/docker-compose.yml "$PROJECT_DIR/"
    cp /mnt/cephfs/mayan/import_clinic.py "$PROJECT_DIR/scripts/"
    cp /mnt/cephfs/mayan/sync_users_from_mysql.py "$PROJECT_DIR/scripts/" 2>/dev/null
    cp /mnt/cephfs/mayan/rotate_cabinets.py "$PROJECT_DIR/scripts/" 2>/dev/null
    cp /opt/mayan/sync_clinic.sh "$PROJECT_DIR/scripts/" 2>/dev/null
    cp /opt/mayan/sync_clients.sh "$PROJECT_DIR/scripts/" 2>/dev/null
    cp /opt/mayan/sync_and_import.sh "$PROJECT_DIR/scripts/" 2>/dev/null
    cp "$0" "$PROJECT_DIR/scripts/backups.sh"

    cd "$PROJECT_DIR"
    git add -A
    if ! git diff --cached --quiet; then
        git commit -m "sync: автобекап $(date +%Y-%m-%d\ %H:%M) — оновлені скрипти й конфіги"
        git push
        echo "=== Закомічено і запушено ==="
    else
        echo "=== Змін немає, коміт не потрібен ==="
    fi
fi
```

### Відновлення БД

```bash
# Зупиняємо app
docker stop mayan-app-1

# Відновлюємо
gunzip -c /mnt/cephfs/backup/YYYYMMDD_HHMM/mayan_db.sql.gz | \
  docker exec -i mayan-postgresql-1 psql -U mayan mayan

# Стартуємо
docker start mayan-app-1
```

---

## Корисні команди

```bash
# Перезапуск
docker restart mayan-app-1

# Логи
docker logs -f mayan-app-1 --tail=100

# Очистити кеш Python
find /opt/mayan/custom -name "*.pyc" -delete
find /opt/mayan/custom -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null
docker restart mayan-app-1

# Статистика
docker exec mayan-app-1 /opt/mayan-edms/bin/python -c "
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mayan.settings.production')
django.setup()
from mayan.apps.documents.models import Document
from mayan.apps.cabinets.models import Cabinet
from django.contrib.auth import get_user_model
User = get_user_model()
print('Документів:', Document.objects.count())
print('Кабінетів:', Cabinet.objects.count())
print('Юзерів:', User.objects.count())
"

# Перебудова пошукового індексу
docker exec mayan-app-1 /opt/mayan-edms/bin/mayan-edms.py search_reindex

# Очистка storage від файлів без документів
find /mnt/cephfs/mayan/document_storage -type f | wc -l
```
---

## Antivirus (ClamAV) — вимкнення та очищення черги

### Проблема

File metadata app (з версії 4.6) включає ClamAV як driver для антивірусного сканування документів.
Оскільки `clamscan` — це CLI-утиліта (не демон `clamd`), вона перезавантажує повну базу сигнатур
(~200+ МБ) **при кожному виклику**, що дає ~10 секунд накладних витрат на документ незалежно від
його розміру. При великій кількості документів (десятки/сотні тисяч) це створює величезний backlog
у черзі `file_metadata` (RabbitMQ) і 100% завантаження CPU одним ядром на довгий час.

Симптом: `ps -ax | grep clamscan` постійно показує активний процес, що сканує різні документи по черзі,
навіть після рестарту docker-стеку (Celery-задачі персистентні в RabbitMQ).

### Вимкнення ClamAV-driver

Через UI: **System → Document types → [конкретний тип] → File metadata drivers** →
зняти галочку `Enabled` навпроти `ClamScan`. Робити для **кожного** document type окремо
(EXIFTool та інші drivers залишити увімкненими).

### Очищення накопиченої черги

Вимкнення driver'а зупиняє появу нових задач, але не чистить вже накопичений backlog.
Перевірити довжину черги та vhost:

```bash
docker exec mayan-rabbitmq-1 rabbitmqctl eval \
  'lists:map(fun(Q) -> amqqueue:get_name(Q) end, rabbit_amqqueue:list()).'
```

Черга називається `file_metadata`, vhost — `mayan` (не `/`). Перевірити кількість задач:

```bash
docker exec mayan-rabbitmq-1 rabbitmqctl eval \
  'rabbit_amqqueue:info(element(2, rabbit_amqqueue:lookup(rabbit_misc:r(<<"mayan">>, queue, <<"file_metadata">>))), [name, messages, consumers]).'
```

Якщо кількість критична (у нашому випадку — 970 619 задач, ~112 днів обробки при поточному темпі) —
очистити чергу:

```bash
docker exec mayan-rabbitmq-1 rabbitmqctl purge_queue file_metadata -p mayan
```

> ⚠️ Це видаляє всі задачі file_metadata (включно з EXIFTool), не тільки ClamAV. Це не критично —
> EXIF-метадані підтягуються заново при новому завантаженні файлу, а для існуючих документів їх
> можна перегенерувати вручну: **Documents → вибрати всі → Actions → Submit for file metadata processing**
> (уже без ClamAV, набагато швидше).

### Примітка: `rabbitmqctl list_queues` може підвисати

Стандартна команда `rabbitmqctl list_queues name messages consumers` синхронно опитує статистику
кожної черги і може підвисати на сотні секунд навіть при здоровому RabbitMQ (без alarms, з нормальними
ресурсами). Це не ознака проблеми з брокером — просто використовуйте `rabbitmqctl eval` замість
`list_queues`, як показано вище.

---

## Налаштування дублікатів (тільки по checksum)

За замовчуванням Mayan вважає дублікатами документи з однаковою **назвою** АБО однаковою **checksum**. Нам потрібно тільки по checksum — файли з різними назвами але однаковим вмістом є дублікатами, а файли з однаковою назвою але різним вмістом — ні.

```bash
docker exec mayan-app-1 /opt/mayan-edms/bin/python -c "
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mayan.settings.production')
django.setup()
from mayan.apps.duplicates.models import StoredDuplicateBackend

# Видаляємо бекенд по імені
StoredDuplicateBackend.objects.filter(
    backend_path='mayan.apps.duplicates.duplicate_backends.DuplicateBackendLabel'
).delete()

# Перевіряємо
for b in StoredDuplicateBackend.objects.all():
    print('Активний:', b.backend_path)
"
```

Після цього в розділі **Documents with duplicates** будуть показуватись тільки файли з однаковим вмістом (checksum), незалежно від назви.

> **Важливо:** Mayan автоматично реєструє `DuplicateBackendLabel` назад у реєстр (`DuplicateBackendMetaclass._registry`) при кожному скануванні документа (імпорт, веб-завантаження), тому одноразове видалення з БД не є стійким. Постійний фікс зроблено в `custom/apps.py` методом `_remove_duplicate_backend_label()` (див. вище) — він прибирає клас з реєстру при кожному старті додатку, і Mayan більше не може пересинхронізувати його назад.
---

## Індексація пошуку (PostgreSQL pg_trgm)

### Проблема

Пошук по назві файлу (`label ILIKE '%текст%'`) на таблиці `documents_document` з ~700k+ рядків
виконував **Seq Scan** — повний перебір усієї таблиці, ~900ms на запит у БД і до хвилини у
веб-інтерфейсі (Django ORM + рендеринг додають накладні витрати).

### Рішення — GIN-індекс на тригramах

```bash
# Розширення (виконати один раз)
docker exec mayan-postgresql-1 psql -U mayan \
  -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"

# Індекс — CONCURRENTLY не блокує таблицю і безпечний під час активного імпорту,
# але НЕ можна виконувати в тій самій транзакції, що й CREATE EXTENSION
docker exec mayan-postgresql-1 psql -U mayan \
  -c "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_document_label_trgm ON documents_document USING gin (label gin_trgm_ops);"
```

Побудова індексу на ~700k рядків займає 5–10 хвилин і не заважає паралельному імпорту документів.

### Результат

| | До індексу | Після індексу |
|---|---|---|
| Метод | Seq Scan (повний перебір) | Bitmap Index Scan |
| Рядків перебрано | 709 103 | 12 005 |
| Execution Time (БД) | 894 ms | 68 ms |
| Реальний час запиту | 1.08 s | 0.22 s |

Приблизно **у 13 разів швидше**. Перевірити план запиту:

```bash
docker exec mayan-postgresql-1 psql -U mayan -c "
EXPLAIN ANALYZE
SELECT id, label FROM documents_document
WHERE label ILIKE '%частина_назви%'
LIMIT 10;
"
```
Очікуваний план — `Bitmap Index Scan on idx_document_label_trgm`, а не `Seq Scan`.

---

## sync_and_import.sh — об'єднаний rsync + імпорт

Об'єднує `sync_clinic.sh` (rsync з remote-серверів) та `import_clinic.py` (імпорт у Mayan)
в один прохід по списку клінік, з низьким пріоритетом CPU для імпорту.

### `/opt/mayan/sync_and_import.sh`

```bash
#!/bin/bash
# sync_and_import.sh — rsync + імпорт клінік в один прохід
#
# Використання:
#   ./sync_and_import.sh 0120 0121 0122 0123   # список клінік
#   ./sync_and_import.sh --all                 # всі клініки з remote
#   ./sync_and_import.sh --no-rsync 0120 0121  # тільки імпорт
#   ./sync_and_import.sh --no-import 0120 0121 # тільки rsync

MAYAN_CONTAINER="mayan-app-1"
LOG_DIR="/mnt/cephfs/mayan/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/sync_import_$(date +%Y%m%d_%H%M%S).log"

DO_RSYNC=true
DO_IMPORT=true
CLINICS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-rsync)  DO_RSYNC=false; shift ;;
        --no-import) DO_IMPORT=false; shift ;;
        --all)       CLINICS=($(bash /opt/mayan/sync_clinic.sh --list-all 2>/dev/null)); shift ;;
        *)           CLINICS+=("$1"); shift ;;
    esac
done

for CLINIC in "${CLINICS[@]}"; do
    echo "=== $CLINIC ===" | tee -a "$LOG_FILE"

    if $DO_RSYNC; then
        bash /opt/mayan/sync_clinic.sh "$CLINIC" 2>&1 | tee -a "$LOG_FILE"
    fi

    if $DO_IMPORT; then
        docker exec "$MAYAN_CONTAINER" nice -n 19 /opt/mayan-edms/bin/python \
          /var/lib/mayan/import_clinic.py "$CLINIC" 2>&1 | tee -a "$LOG_FILE"
    fi
done

echo "=== ВСІ КЛІНІКИ ОБРОБЛЕНО ===" | tee -a "$LOG_FILE"
```

### Використання

```bash
chmod +x /opt/mayan/sync_and_import.sh

# Список клінік
./sync_and_import.sh 0120 0121 0122 0123

# Тільки імпорт вже синхронізованих файлів
./sync_and_import.sh --no-rsync 0120 0121
```

`nice -n 19` — імпорт іде з найнижчим пріоритетом CPU, не заважає іншим процесам на сервері.
Лог кожного запуску зберігається окремим файлом у `/mnt/cephfs/mayan/logs/`.

> ⚠️ Не рестартуйте `mayan-app-1` поки триває імпорт — процес `import_clinic.py` виконується
> всередині контейнера; рестарт обірве поточний файл на середині й може лишити документ
> у напівстані (Document створено, DocumentFile — ні). Перевірити активний імпорт:
> `ps -ax | grep import_clinic`.

---
## Розширення полів пошуку (Filter terms / Search terms)

За замовчуванням Bootstrap-навбар звужує `.form-control` до вузької ширини. Поле **Filter terms**
(список документів, `dynamic_search/app/list_toolbar.html`) і **Search terms** (навбар,
`dynamic_search/search_box_toolbar.html`) — обидва прив'язані до реального search backend
(не client-side фільтр), тому обмеження стосується лише візуальної ширини.

Розширено через CSS-override у `custom/templates/appearance/menus/topbar.html`:

```css
#search-filter-input-terms { width: 100% !important; min-width: 320px; }
#search-navbar-form-input-terms { width: 320px !important; }
@media (min-width: 1200px) {
    #search-navbar-form-input-terms { width: 450px !important; }
}
```

---

## Затримка індексації після імпорту

Документи, додані через `import_clinic.py` (в т.ч. `[LINK]` — прив'язка існуючого документа
до нового кабінету по checksum), можуть не з'являтись у результатах пошуку одразу — індексація
йде асинхронно через Celery. Це очікувана поведінка, не помилка.

---

## HTTPS

### Етап 1 — самопідписний сертифікат

```bash
# Генеруємо сертифікат
mkdir -p /opt/mayan/ssl

openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
  -keyout /opt/mayan/ssl/mayan.key \
  -out /opt/mayan/ssl/mayan.crt \
  -subj "/C=UA/ST=Kyiv/L=Kyiv/O=Medical/CN=YOUR_SERVER_IP"
```

### `/opt/mayan/nginx.conf` (самопідписний)

```nginx
server {
    listen 80;
    server_name _;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name _;

    ssl_certificate     /etc/nginx/ssl/mayan.crt;
    ssl_certificate_key /etc/nginx/ssl/mayan.key;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;

    client_max_body_size 0;

    location / {
        proxy_pass         http://app:8000;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }
}
```

### Додати nginx в `docker-compose.yml`

В секцію `services:` додати:

```yaml
  nginx:
    image: nginx:alpine
    ports:
      - "443:443"
      - "80:80"
    volumes:
      - /opt/mayan/ssl:/etc/nginx/ssl:ro
      - /opt/mayan/nginx.conf:/etc/nginx/conf.d/default.conf:ro
    networks:
      - mayan
    restart: unless-stopped
    profiles:
      - all_in_one
```

І прибрати порти з `x-mayan-frontend-ports`:
```yaml
x-mayan-frontend-ports:
  &mayan-frontend-ports
  ports: []
```

### В `config.yml` додати:

```yaml
CSRF_COOKIE_SECURE: true
SESSION_COOKIE_SECURE: true
USE_X_FORWARDED_HOST: true
SECURE_PROXY_SSL_HEADER:
  - HTTP_X_FORWARDED_PROTO
  - https
```

```bash
cd /opt/mayan && docker compose up -d
# Перевірка (ігноруємо помилку самопідписного)
curl -k https://YOUR_SERVER_IP/
```

---

### Етап 2 — Let's Encrypt (після підключення домену)

```bash
# Встановлюємо certbot
apt-get install -y certbot

# Зупиняємо nginx щоб звільнити порт 80
docker stop mayan-nginx-1

# Отримуємо сертифікат
certbot certonly --standalone \
  -d your.domain.com \
  --email your@email.com \
  --agree-tos

# Стартуємо назад
docker start mayan-nginx-1
```

### `/opt/mayan/nginx.conf` (Let's Encrypt)

```nginx
server {
    listen 80;
    server_name your.domain.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name your.domain.com;

    ssl_certificate     /etc/letsencrypt/live/your.domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your.domain.com/privkey.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;

    client_max_body_size 0;

    location / {
        proxy_pass         http://app:8000;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }
}
```

### Додати сертифікати в nginx контейнер (`docker-compose.yml`)

```yaml
  nginx:
    volumes:
      - /etc/letsencrypt:/etc/letsencrypt:ro
      - /opt/mayan/nginx.conf:/etc/nginx/conf.d/default.conf:ro
```

### Автооновлення сертифікату

```bash
crontab -e
# Додати:
0 3 * * * certbot renew \
  --pre-hook "docker stop mayan-nginx-1" \
  --post-hook "docker start mayan-nginx-1" \
  --quiet
```

### Оновити URL в `config.yml`

```bash
sed -i 's|ORGANIZATIONS_INSTALLATION_URL: http://.*|ORGANIZATIONS_INSTALLATION_URL: https://your.domain.com|' \
  /mnt/cephfs/mayan/config.yml

docker restart mayan-app-1
```

---

## Оновлений signals.py з перевіркою дублікатів

При завантаженні файлу через веб-інтерфейс `signals.py` автоматично перевіряє checksum і якщо знаходить дублікат — видаляє новий документ і додає оригінал в потрібний кабінет.

Файл: `/opt/mayan/custom/signals.py` — див. розділ [Custom Django додаток](#custom-django-додаток).


---

## Логування спроб входу і захист fail2ban

### Проблема

За замовчуванням Mayan не логує спроби автентифікації в зручному для парсингу форматі,
тому неможливо було виявляти брутфорс через стандартні логи.

### Логування через Django auth-сигнали

`custom/signals.py` підписується на `user_logged_in`, `user_logged_out`, `user_login_failed`
і пише окремий лог `/var/lib/mayan/logs/auth.log` (на хості — `/mnt/cephfs/mayan/logs/auth.log`)
з ротацією через `RotatingFileHandler` (10×10MB, незалежно від `logrotate`):


**Важливо:** папку `logs/` потрібно створити заздалегідь на хості з правильним власником —
інакше контейнер падає в циклічний рестарт з `PermissionError`:

```bash
mkdir -p /mnt/cephfs/mayan/logs
chown -R 1000:1000 /mnt/cephfs/mayan/logs
chmod 755 /mnt/cephfs/mayan/logs
docker restart mayan-app-1
```

### fail2ban

```bash
cat > /etc/fail2ban/filter.d/mayan.conf << 'EOF'
[Definition]
failregex = ^.* \[AUTH FAIL\] user=.* ip=<HOST>$
ignoreregex =
EOF

cat > /etc/fail2ban/jail.d/mayan.conf << 'EOF'
[mayan]
enabled  = true
port     = http,https
filter   = mayan
logpath  = /mnt/cephfs/mayan/logs/auth.log
maxretry = 5
findtime = 300
bantime  = 3600
EOF

systemctl restart fail2ban
fail2ban-client status mayan
```

5 невдалих спроб за 5 хвилин з одного IP → бан на годину.

### Ротація auth.log через logrotate (додатково до вбудованої)

```bash
cat > /etc/logrotate.d/mayan << 'EOF'
/mnt/cephfs/mayan/logs/*.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
    dateext
    dateformat -%Y%m%d
}
EOF
```

---

## Права власника document_storage (PermissionError при видаленні/завантаженні)

### Симптом

- "Empty trash" в UI не видаляє документи — Celery падає з `PermissionError: [Errno 13]
  Permission denied: '/var/lib/mayan/document_storage/<uuid>'`.
- Веб-завантаження документа мовчки завершується документом-заглушкою (`is_stub=True`,
  `file_latest=None`, 0 записів `DocumentFile`) — у логах `_create() ... Error creating new
  document file ... Permission denied`.

### Причина

Каталог `/var/lib/mayan/document_storage` (на хості — `/mnt/cephfs/mayan/document_storage`)
опинився у власності `root:root` замість `mayan:mayan` (uid/gid 1000). Celery-воркери
(`worker_a`...`worker_e`) працюють під користувачем `mayan`, тому не мають права писати
чи видаляти файли в цьому каталозі — незалежно від власника самого файлу.

Перевірка через `docker exec` **без** `-u mayan` вводить в оману: за замовчуванням `docker exec`
виконується від `root`, який має доступ до каталогу і може видаляти/писати файли навіть коли
реальний production-процес (Celery) — ні. Тестувати права потрібно саме так:

```bash
docker exec -u mayan mayan-app-1 rm -v /var/lib/mayan/document_storage/<uuid>
```

### Фікс

```bash
docker exec mayan-app-1 chown mayan:mayan /var/lib/mayan/document_storage
docker exec mayan-app-1 stat /var/lib/mayan/document_storage   # Uid має бути (1000/mayan)
```

Якщо власника файлів усередині теж треба масово виправити (наприклад, після `docker cp` чи
міграції даних):

```bash
docker exec mayan-app-1 sh -c "find /var/lib/mayan/document_storage -maxdepth 1 -type f -not -user mayan | wc -l"
docker exec mayan-app-1 chown -R mayan:mayan /var/lib/mayan/document_storage
```

### Профілактика в коді

`custom/apps.py` метод `_ensure_storage_permissions()` перевіряє власника `document_storage`
при кожному старті контейнера і виводить попередження в `docker logs`, якщо він не `mayan`
(автоматичний `chown -R` на старті навмисно не робиться — на 900k+ файлів це небезпечно і
повільно виконувати мовчки).

`scripts/import_clinic.py` тепер явно виставляє `os.chown(dest_path, 1000, 1000)` одразу
після `os.link()` — хардлінк інакше успадковує власника оригінального файлу з `/mnt/cephfs/clinic/`
(часто `root`, бо `rsync` виконується з хоста), і кожен новий імпорт продовжував би плодити
файли з неправильним власником.


---

## Захист від паралельного запуску import_clinic.py

### Проблема

Одночасний запуск `import_clinic.py` на ту саму клініку (наприклад, збіг cron-задачі
і ручного запуску, або повторний запуск до завершення попереднього) призводив до перегонів:
один процес видаляв оригінальний файл після успішного імпорту (`os.remove(filepath)`),
а другий процес, що вже прочитав список файлів через `os.listdir()`, намагався обробити
файл, якого вже нема:

```text
[OK 1] _A_P_13_08_1953.rar (2025-03-18)
[ERROR] /mnt/cephfs/clinic/0501/2025/_A_P_13_08_1953.rar: [Errno 2] No such file or directory
```

Також виявлено осиротілий синтаксично невалідний дублікат `register_via_hardlink()` —
залишок незавершеного ручного редагування (частина старого блоку лишилась незакоментованою),
що зупиняло скрипт ще до першого рядка виводу (`SyntaxError` на `except Exception:`).

### Фікс

`import_clinic.py` тепер захоплює файловий лок через `fcntl.flock()` на самому старті,
специфічний для кожної клініки (`/tmp/import_clinic_{CLINIC_ID}.lock`) — другий процес
на ту саму клініку одразу завершується з повідомленням, не чіпаючи файли:

```python
def acquire_lock(clinic_id):
    lock_path = f'/tmp/import_clinic_{clinic_id}.lock'
    lock_file = open(lock_path, 'w')
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(f'[LOCK] Імпорт {clinic_id} вже виконується іншим процесом. Виходжу.')
        sys.exit(1)
    return lock_file
```

`flock` автоматично звільняється при завершенні процесу (навіть аварійному), на відміну
від lock-файлів на базі `touch`/`rm`, які можуть залишитись "висіти" після краху.

Додатково `import_file()` перевіряє `os.path.exists(filepath)` перед обробкою — навіть
якщо лок колись обійдуть іншим шляхом, скрипт коректно пропустить зниклий файл замість падіння.

### Діагностика паралельних процесів

```bash
ps -ax | grep import_clinic
```

Якщо для однієї клініки більше одного процесу — вбий зайві, залишивши найстарший:

```bash
kill <pid1> <pid2> ...
```

Джерело дублювання варто перевірити окремо — `crontab -l`, `/etc/cron.d/`, `systemctl list-timers`.

---

## Ротація файлів по роках (`rotate_cabinets.py`)

Скрипт автоматично розподіляє документи по підкабінетах-роках і видаляє застарілі.

### Логіка роботи

```
Кабінет 0101/
  aaaa.txt        ← документ 2024 року → переміщуємо в 0101/2024/
  bbbb.txt        ← документ 2026 року → не чіпаємо (поточний рік)
  2022/           ← рік < MIN_YEAR → перейменовуємо в 2022_archive
  2023/           ← активний
  2024/           ← активний
  2022_archive/   ← через місяць видаляємо
```

**Порядок обробки:**
1. Спочатку клієнти `01000-09999` — видаляємо лінки
2. Потім клініки `0100-0999` — видаляємо файли

**Лінк** = документ клініки (`0101`) розшарений клієнту (`01001`). При видаленні спочатку прибирається лінк у клієнта, потім оригінал у клініки.

### Налаштування

```bash
# Максимальний строк зберігання (років)
export MAX_RETENTION_YEARS=5   # 2026-5=2021, видаляємо папки < 2021

# Затримка перед видаленням архіву (днів)
export ARCHIVE_DELETE_AFTER_DAYS=30
```

### `/mnt/cephfs/mayan/rotate_cabinets.py`

```python
#!/usr/bin/env python3
"""
rotate_cabinets.py — щорічна ротація файлів по кабінетах Mayan EDMS.

Використання:
  # Тест для одного кабінету
  python rotate_cabinets.py --test --cabinet 0101

  # Тест для конкретного року
  python rotate_cabinets.py --test --cabinet 0101 --year 2025

  # Повна ротація
  python rotate_cabinets.py --run

  # Видалення архівів (запускати через місяць після ротації)
  python rotate_cabinets.py --cleanup

  # Dry-run cleanup
  python rotate_cabinets.py --cleanup --dry-run
"""

import os, sys, django, argparse
from datetime import datetime, timedelta

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mayan.settings.production')
django.setup()

from django.utils import timezone
from mayan.apps.cabinets.models import Cabinet
from mayan.apps.documents.models import Document
from mayan.apps.acls.models import AccessControlList
from django.contrib.contenttypes.models import ContentType

MAX_RETENTION_YEARS    = int(os.getenv('MAX_RETENTION_YEARS', '5'))
ARCHIVE_DELETE_AFTER_DAYS = int(os.getenv('ARCHIVE_DELETE_AFTER_DAYS', '30'))

CURRENT_YEAR = datetime.now().year
MIN_YEAR     = CURRENT_YEAR - MAX_RETENTION_YEARS

doc_ct = ContentType.objects.get_for_model(Document)

counter = {'moved': 0, 'archived': 0, 'deleted_links': 0, 'deleted_docs': 0, 'errors': 0}


def log(msg, dry_run=False):
    prefix = '[DRY-RUN] ' if dry_run else ''
    print(f'{prefix}{msg}', flush=True)


def get_or_create_year_cabinet(parent_cabinet, year, dry_run=False):
    existing = Cabinet.objects.filter(label=str(year), parent=parent_cabinet).first()
    if existing:
        return existing
    if dry_run:
        log(f'  Створив би кабінет {parent_cabinet.label}/{year}', dry_run)
        return None
    cab, created = Cabinet.objects.get_or_create(label=str(year), parent=parent_cabinet)
    if created:
        log(f'  [CREATE] Кабінет {parent_cabinet.label}/{year}')
    return cab


def move_document_to_year(document, from_cabinet, to_cabinet, dry_run=False):
    if dry_run:
        log(f'  [MOVE] {document.label} → {to_cabinet.label}', dry_run)
        counter['moved'] += 1
        return
    try:
        from_cabinet.documents.remove(document)
        to_cabinet.documents.add(document)
        counter['moved'] += 1
        log(f'  [MOVE] {document.label} → {to_cabinet.label}')
    except Exception as e:
        counter['errors'] += 1
        log(f'  [ERROR] move {document.label}: {e}')


def is_link(document):
    """Документ є лінком якщо належить кабінету клініки 0100-0999."""
    return document.cabinets.filter(label__regex=r'^0[1-9][0-9]{2}$').exists()


def remove_document_from_cabinet(document, cabinet, is_link_doc=False, dry_run=False):
    if dry_run:
        action = 'видалив би лінк' if is_link_doc else 'видалив би документ'
        log(f'  [DELETE] {action}: {document.label} з {cabinet.label}', dry_run)
        if is_link_doc:
            counter['deleted_links'] += 1
        else:
            counter['deleted_docs'] += 1
        return
    try:
        from mayan.apps.permissions.models import Role
        role_label = f'role_{cabinet.label.split("/")[0]}'
        try:
            role = Role.objects.get(label=role_label)
            AccessControlList.objects.filter(
                content_type=doc_ct, object_id=document.pk, role=role
            ).delete()
        except Role.DoesNotExist:
            pass

        cabinet.documents.remove(document)

        if is_link_doc:
            counter['deleted_links'] += 1
            log(f'  [DELETE LINK] {document.label} з {cabinet.label}')
        else:
            if document.cabinets.count() == 0:
                document.delete()
                log(f'  [DELETE DOC] {document.label} видалено фізично')
            else:
                log(f'  [DELETE DOC] {document.label} видалено з {cabinet.label}')
            counter['deleted_docs'] += 1
    except Exception as e:
        counter['errors'] += 1
        log(f'  [ERROR] delete {document.label}: {e}')


def archive_old_cabinet(cabinet, dry_run=False):
    if '_archive' in cabinet.label or not cabinet.label.isdigit():
        return
    if int(cabinet.label) >= MIN_YEAR:
        return
    new_label = f'{cabinet.label}_archive'
    if Cabinet.objects.filter(label=new_label, parent=cabinet.parent).exists():
        return
    if dry_run:
        log(f'  [ARCHIVE] {cabinet.label} → {new_label}', dry_run)
        counter['archived'] += 1
        return
    try:
        old_label = cabinet.label
        cabinet.label = new_label
        cabinet.description = f'archived:{datetime.now().isoformat()}'
        cabinet.save()
        counter['archived'] += 1
        log(f'  [ARCHIVE] {old_label} → {new_label}')
    except Exception as e:
        counter['errors'] += 1
        log(f'  [ERROR] archive: {e}')


def process_cabinet(root_cabinet, dry_run=False):
    log(f'\n=== Кабінет: {root_cabinet.label} ===')

    # Переміщуємо файли з кореня в підпапки по роках
    for document in root_cabinet.documents.all():
        doc_year = document.datetime_created.year if document.datetime_created else CURRENT_YEAR
        if doc_year == CURRENT_YEAR:
            continue
        year_cabinet = get_or_create_year_cabinet(root_cabinet, doc_year, dry_run)
        if year_cabinet or dry_run:
            move_document_to_year(document, root_cabinet, year_cabinet, dry_run)

    # Архівуємо старі підкабінети
    for sub in Cabinet.objects.filter(parent=root_cabinet):
        if sub.label.isdigit():
            archive_old_cabinet(sub, dry_run)

    # Видаляємо документи зі старих підкабінетів
    for sub in Cabinet.objects.filter(parent=root_cabinet, label__regex=r'^\d{4}$'):
        if not sub.label.isdigit() or int(sub.label) >= MIN_YEAR:
            continue
        log(f'  Обробка: {sub.label} (< {MIN_YEAR})')
        for document in sub.documents.all():
            remove_document_from_cabinet(
                document, sub,
                is_link_doc=is_link(document),
                dry_run=dry_run
            )


def cleanup_archives(dry_run=False):
    log(f'\n=== Cleanup архівів (старші {ARCHIVE_DELETE_AFTER_DAYS} днів) ===')
    cutoff = datetime.now() - timedelta(days=ARCHIVE_DELETE_AFTER_DAYS)

    for cab in Cabinet.objects.filter(label__endswith='_archive'):
        archived_date = None
        if cab.description and cab.description.startswith('archived:'):
            try:
                archived_date = datetime.fromisoformat(cab.description.replace('archived:', ''))
            except Exception:
                pass

        if not archived_date:
            log(f'  [SKIP] {cab.label} — дата невідома')
            continue

        if archived_date > cutoff:
            days_left = (archived_date + timedelta(days=ARCHIVE_DELETE_AFTER_DAYS) - datetime.now()).days
            log(f'  [SKIP] {cab.label} — ще {days_left} днів')
            continue

        log(f'  [DELETE] {cab.label}')
        if not dry_run:
            try:
                for document in cab.documents.all():
                    remove_document_from_cabinet(document, cab, is_link_doc=is_link(document))
                cab.delete()
            except Exception as e:
                log(f'  [ERROR] {e}')


def get_cabinets_ordered():
    """Спочатку клієнти 01000-09999, потім клініки 0100-0999."""
    clients, clinics = [], []
    for cab in Cabinet.objects.filter(parent=None).order_by('label'):
        if not cab.label.isdigit():
            continue
        num = int(cab.label)
        if 1000 <= num <= 9999 and len(cab.label) == 5:
            clients.append(cab)
        elif 100 <= num <= 999 and len(cab.label) == 4:
            clinics.append(cab)
    return clients + clinics


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run',       action='store_true')
    parser.add_argument('--test',      action='store_true')
    parser.add_argument('--cleanup',   action='store_true')
    parser.add_argument('--dry-run',   action='store_true')
    parser.add_argument('--cabinet',   type=str)
    parser.add_argument('--year',      type=int)
    parser.add_argument('--retention', type=int)
    args = parser.parse_args()

    global MAX_RETENTION_YEARS, MIN_YEAR
    if args.retention:
        MAX_RETENTION_YEARS = args.retention
        MIN_YEAR = CURRENT_YEAR - MAX_RETENTION_YEARS

    dry_run = args.test or args.dry_run

    print(f'Поточний рік: {CURRENT_YEAR} | Мін. рік: {MIN_YEAR} | '
          f'Режим: {"DRY-RUN" if dry_run else "РЕАЛЬНИЙ"}')

    if args.cleanup:
        cleanup_archives(dry_run=dry_run)
    elif args.run or args.test:
        if args.cabinet:
            cab = Cabinet.objects.filter(label=args.cabinet, parent=None).first()
            if not cab:
                print(f'[ERROR] Кабінет {args.cabinet} не знайдено')
                sys.exit(1)
            process_cabinet(cab, dry_run=dry_run)
        else:
            cabinets = get_cabinets_ordered()
            print(f'Кабінетів: {len(cabinets)}')
            for cab in cabinets:
                process_cabinet(cab, dry_run=dry_run)
    else:
        parser.print_help()

    print(f'\nРезультати: moved={counter["moved"]} | archived={counter["archived"]} | '
          f'del_links={counter["deleted_links"]} | del_docs={counter["deleted_docs"]} | '
          f'errors={counter["errors"]}')


main()
```

### Деплой

```bash
cp /mnt/user-data/outputs/rotate_cabinets.py /mnt/cephfs/mayan/
docker cp /mnt/cephfs/mayan/rotate_cabinets.py mayan-app-1:/var/lib/mayan/
```

### Використання

```bash
# Тест на одному кабінеті
docker exec mayan-app-1 /opt/mayan-edms/bin/python \
  /var/lib/mayan/rotate_cabinets.py --test --cabinet 0102

# Тест з іншим строком зберігання
docker exec mayan-app-1 /opt/mayan-edms/bin/python \
  /var/lib/mayan/rotate_cabinets.py --test --cabinet 0102 --retention 3

# Реальна ротація
docker exec mayan-app-1 /opt/mayan-edms/bin/python \
  /var/lib/mayan/rotate_cabinets.py --run

# Перевірити що буде видалено
docker exec mayan-app-1 /opt/mayan-edms/bin/python \
  /var/lib/mayan/rotate_cabinets.py --cleanup --dry-run

# Видалити архіви
docker exec mayan-app-1 /opt/mayan-edms/bin/python \
  /var/lib/mayan/rotate_cabinets.py --cleanup
```

### Cron

```bash
crontab -e

# Ротація — 1 січня о 02:00
0 2 1 1 * docker exec mayan-app-1 /opt/mayan-edms/bin/python \
  /var/lib/mayan/rotate_cabinets.py --run >> /var/log/rotate_cabinets.log 2>&1

# Видалення архівів — 1 лютого о 02:00 (через місяць після ротації)
0 2 1 2 * docker exec mayan-app-1 /opt/mayan-edms/bin/python \
  /var/lib/mayan/rotate_cabinets.py --cleanup >> /var/log/rotate_cabinets.log 2>&1
```

### Параметри командного рядка

| Параметр | Опис |
|----------|------|
| `--run` | Повна ротація всіх кабінетів |
| `--test` | Dry-run — показує що буде зроблено |
| `--cleanup` | Видаляє `_archive` папки старші 30 днів |
| `--dry-run` | Без змін (з `--cleanup`) |
| `--cabinet 0102` | Обробити тільки один кабінет |
| `--year 2022` | Обробити тільки конкретний рік |
| `--retention 3` | Змінити строк зберігання на 3 роки |

### Змінні середовища

```bash
export MAX_RETENTION_YEARS=5        # строк зберігання (років)
export ARCHIVE_DELETE_AFTER_DAYS=30 # затримка видалення архіву
```
