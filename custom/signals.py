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
    'document_print',
    'document_download',
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


# Перезаписуємо функцію з перевіркою адміна
@receiver(pre_delete, sender=DocumentFile)
def delete_hardlink_original(sender, instance, **kwargs):
    try:
        from custom.middleware import get_current_user
        current_user = get_current_user()

        # Якщо не HTTP запит (shell, скрипт) — пропускаємо
        if current_user is None:
            return

        # Якщо HTTP але не адмін — пропускаємо
        if not getattr(current_user, 'is_superuser', False):
            print(f'[DELETE SKIP] не адмін')
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
