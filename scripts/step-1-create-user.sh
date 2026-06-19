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
# СПИСОК КОРИСТУВАЧІВ
# =========================
USERS    = ["1003", "1004"]  # <-- додавайте сюди
PASSWORD = "UploadPassword123"

GLOBAL_PERMS = [
    "document_create",
    "document_type_view",
    "sources_setup_view",
    "sources_view",
    "document_view",
    "document_file_view",
    "document_version_view",
    "document_file_download",
    "document_file_print",
    "message_create",
    "message_delete",
    "message_edit",
    "message_view",
]

CABINET_PERMS = [
    "cabinet_view",
    "document_view",
    "document_file_view",
    "document_file_download",
    "document_version_view",
]

SUBSCRIBE_EVENTS = [
    'download_files.downloaded',
    'download_files.created',
]

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
                user=user,
                stored_event_type=event.stored_event_type,
            )
        except Exception as e:
            print(f"  [WARN] {event_id}: {e}")

    cabinet, _ = Cabinet.objects.get_or_create(label=USERNAME)
    cabinet_ct = ContentType.objects.get_for_model(cabinet)
    acl, _ = AccessControlList.objects.get_or_create(
        content_type=cabinet_ct, object_id=cabinet.pk, role=role
    )
    acl.permissions.add(*StoredPermission.objects.filter(name__in=CABINET_PERMS))

    print(f"[OK] {USERNAME} / пароль: {PASSWORD}")

print("\n=== ГОТОВО ===")
PYEOF
