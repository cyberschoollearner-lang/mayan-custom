#!/bin/bash
# step-1-create-user.sh — ручне створення клієнтів (1000-9999 → 01000-09999)
#
# Клієнти можуть завантажувати свої документи (document_create) і бачити
# тільки свій кабінет через ACL — так само, як клініки, але окремий діапазон
# username (01000-09999 замість 0101-0999).
#
# Використання:
#   ./step-1-create-user.sh                      # список з USERS_RAW / пароль з PASSWORD
#   ./step-1-create-user.sh 1003                 # один юзер, пароль з PASSWORD
#   ./step-1-create-user.sh 1003 MyPass123        # один юзер з власним паролем
#   ./step-1-create-user.sh 1003 1004 1005        # кілька юзерів, пароль з PASSWORD
#   ./step-1-create-user.sh 1003 1004 -- MyPass123  # кілька юзерів, спільний пароль

# ─── Значення за замовчуванням (якщо аргументи не передані) ─────────────────
#DEFAULT_USERS_RAW=("1003" "1004")
DEFAULT_USERS_RAW=("1003")
DEFAULT_PASSWORD="ChangeMe123!"

# ─── Розбір аргументів ───────────────────────────────────────────────────────
ARGS=("$@")
USERS_RAW=()
PASSWORD=""

if [ ${#ARGS[@]} -eq 0 ]; then
    # Аргументів немає — беремо дефолти
    USERS_RAW=("${DEFAULT_USERS_RAW[@]}")
    PASSWORD="$DEFAULT_PASSWORD"

elif [ ${#ARGS[@]} -eq 1 ]; then
    # Один аргумент — це юзер, пароль дефолтний
    USERS_RAW=("${ARGS[0]}")
    PASSWORD="$DEFAULT_PASSWORD"

else
    # Перевіряємо чи є "--" роздільник (кілька юзерів + спільний пароль в кінці)
    SEP_FOUND=false
    for arg in "${ARGS[@]}"; do
        if [ "$arg" = "--" ]; then
            SEP_FOUND=true
            break
        fi
    done

    if $SEP_FOUND; then
        # login1 login2 ... -- password
        BEFORE_SEP=true
        for arg in "${ARGS[@]}"; do
            if [ "$arg" = "--" ]; then
                BEFORE_SEP=false
                continue
            fi
            if $BEFORE_SEP; then
                USERS_RAW+=("$arg")
            else
                PASSWORD="$arg"
            fi
        done
    elif [ ${#ARGS[@]} -eq 2 ]; then
        # login password
        USERS_RAW=("${ARGS[0]}")
        PASSWORD="${ARGS[1]}"
    else
        # 3+ аргументи без "--" — трактуємо всі як login-и, пароль дефолтний
        USERS_RAW=("${ARGS[@]}")
        PASSWORD="$DEFAULT_PASSWORD"
    fi
fi

echo "Користувачі: ${USERS_RAW[*]}"
echo "Пароль:      $PASSWORD"
echo ""

# Формуємо Python-список для передачі в heredoc
PY_USERS=$(printf '"%s", ' "${USERS_RAW[@]}")
PY_USERS="[${PY_USERS%, }]"

docker exec -i mayan-app-1 /opt/mayan-edms/bin/mayan-edms.py shell << PYEOF
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType
from mayan.apps.permissions.models import Role, StoredPermission
from mayan.apps.cabinets.models import Cabinet
from mayan.apps.acls.models import AccessControlList
from mayan.apps.events.models import EventSubscription
from mayan.apps.events.classes import EventType

USERS_RAW = ${PY_USERS}
PASSWORD  = "${PASSWORD}"

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

SUBSCRIBE_EVENTS = ['download_files.downloaded', 'download_files.created']

User = get_user_model()

for RAW in USERS_RAW:
    USERNAME = f'{int(RAW):05d}'

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

    print(f"[OK] {RAW} -> {USERNAME} / пароль: {PASSWORD}")

print("\n=== ГОТОВО ===")
PYEOF
