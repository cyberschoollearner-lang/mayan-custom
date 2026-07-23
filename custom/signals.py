import os
import logging
from logging.handlers import RotatingFileHandler

from actstream.models import Action
from django.db.models.signals import post_save, pre_delete
from django.contrib.auth.signals import (
    user_logged_in, user_logged_out, user_login_failed
)
from django.dispatch import receiver
from django.contrib.contenttypes.models import ContentType

from mayan.apps.documents.models import DocumentFile, Document
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


# ---------------------------------------------------------------------------
# Логування спроб входу
# ---------------------------------------------------------------------------

AUTH_LOG_PATH = '/var/lib/mayan/logs/auth.log'
auth_logger = logging.getLogger('custom.auth')
if not auth_logger.handlers:
    try:
        os.makedirs(os.path.dirname(AUTH_LOG_PATH), exist_ok=True)
        _handler = RotatingFileHandler(
            AUTH_LOG_PATH, maxBytes=10 * 1024 * 1024, backupCount=10
        )
        _handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
        auth_logger.addHandler(_handler)
        auth_logger.setLevel(logging.INFO)
        auth_logger.propagate = False
    except Exception as e:
        print(f'[CUSTOM] auth_logger init error: {e}')


def _client_ip(request):
    if not request:
        return '-'
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '-')


@receiver(user_logged_in)
def on_login_success(sender, request, user, **kwargs):
    auth_logger.info(f'[AUTH OK] user={user.username} ip={_client_ip(request)}')


@receiver(user_logged_out)
def on_logout(sender, request, user, **kwargs):
    username = getattr(user, 'username', 'unknown')
    auth_logger.info(f'[AUTH LOGOUT] user={username} ip={_client_ip(request)}')


@receiver(user_login_failed)
def on_login_failed(sender, credentials, request=None, **kwargs):
    username = credentials.get('username', 'unknown')
    auth_logger.warning(f'[AUTH FAIL] user={username} ip={_client_ip(request)}')


# ---------------------------------------------------------------------------
# Автоматична прив'язка документа до кабінету користувача при завантаженні
# ---------------------------------------------------------------------------

def _grant_cabinet_acl(document, cabinet, role):
    cabinet.documents.add(document)
    doc_ct = ContentType.objects.get_for_model(document)
    acl, _ = AccessControlList.objects.get_or_create(
        content_type=doc_ct, object_id=document.pk, role=role
    )
    acl.permissions.add(
        *StoredPermission.objects.filter(name__in=DOCUMENT_PERMISSIONS)
    )


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

    try:
        role = Role.objects.get(label=f'role_{username}')
    except Role.DoesNotExist:
        print(f'[CABINET] WARNING: role_{username} not found')
        return

    _grant_cabinet_acl(document, cabinet, role)
    print(f'[CABINET] {username} -> {document.label} OK')


# ---------------------------------------------------------------------------
# Перевірка дублікатів по checksum при веб-завантаженні
# ---------------------------------------------------------------------------

@receiver(post_save, sender=DocumentFile)
def on_document_file_check_duplicate(sender, instance, **kwargs):
    if getattr(instance, '_dedup_checked', False):
        return
    if not instance.checksum:
        return

    document = instance.document
    if not document.pk:
        return

    actor = getattr(instance, '_event_actor', None)
    username = getattr(actor, 'username', None)
    if not username or username in SKIP_USERS:
        return
    if getattr(actor, 'is_superuser', False):
        return

    instance._dedup_checked = True

    existing = DocumentFile.objects.filter(
        checksum=instance.checksum
    ).exclude(document_id=document.pk).exclude(
        document__in_trash=True
    ).first()

    if not existing:
        return

    original_document = existing.document
    cabinet, _ = Cabinet.objects.get_or_create(label=username)

    try:
        role = Role.objects.get(label=f'role_{username}')
    except Role.DoesNotExist:
        print(f'[DEDUP] WARNING: role_{username} not found')
        return

    _grant_cabinet_acl(original_document, cabinet, role)
    print(f'[DEDUP] {username}: дублікат по checksum, залишено оригінал pk:{original_document.pk}')

    try:
        document.delete()
    except Exception as e:
        print(f'[DEDUP ERROR] не вдалось видалити дублікат {document.pk}: {e}')


# ---------------------------------------------------------------------------
# Видалення оригіналу файлу при видаленні документа адміном
# ---------------------------------------------------------------------------

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
