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
