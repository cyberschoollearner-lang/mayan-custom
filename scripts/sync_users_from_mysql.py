#!/usr/bin/env python3
"""
sync_users_from_mysql.py — синхронізація клієнтів 1000-9999 з MySQL в Mayan EDMS.
Login в MySQL: 1001 → Login в Mayan: 01001 (5 знаків з нулем спереду)

Режими:
    --import-all   одноразовий імпорт всіх існуючих юзерів
    --daemon       демон: перевіряє кожні N секунд
    --once         одна перевірка (для cron/shell скрипту)
"""

import os, sys, django, time, argparse
import pymysql
import pymysql.cursors

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

# ─── MySQL конфіг ────────────────────────────────────────────────────────────
DB_CONFIG = {
    'host':      '127.0.0.1',
    'port':      3306,
    'user':      'threedcenter',
    'password':  'IzNGBOmfouIg5kZ',
    'database':  'threedcenter',
    'charset':   'utf8mb4',
    'cursorclass': pymysql.cursors.DictCursor,
}
DB_TABLE = 'main_db'

# ─── Mayan дозволи ───────────────────────────────────────────────────────────
GLOBAL_PERMS = [
    'document_view',
    'document_file_view',
    'document_version_view',
    'document_file_download',
    'document_file_print',
    'message_create',
    'message_delete',
    'message_edit',
    'message_view',
]

CABINET_PERMS = [
    'cabinet_view',
    'document_view',
    'document_file_view',
    'document_file_download',
    'document_version_view',
]

SUBSCRIBE_EVENTS = [
    'download_files.downloaded',
    'download_files.created',
]

LIST_VIEW_NAMES = [
    'documents:document_list',
    'cabinets:cabinet_view',
    'cabinets:cabinet_list',
]

User = get_user_model()


def to_mayan_login(mysql_login):
    """Конвертує MySQL login (1001) в Mayan login (01001)."""
    return f'{int(mysql_login):05d}'


# ─── MySQL ───────────────────────────────────────────────────────────────────

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
    """Юзери з add_user_stats=1 (нові або змінені)."""
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


# ─── Mayan ───────────────────────────────────────────────────────────────────

def setup_list_mode(user):
    for view_name in LIST_VIEW_NAMES:
        namespace = view_name.split(':')[0]
        UserViewMode.objects.get_or_create(
            defaults={'namespace': namespace, 'value': 'list'},
            name=view_name,
            user=user,
        )


def subscribe_user(user):
    for event_id in SUBSCRIBE_EVENTS:
        try:
            event = EventType.get(id=event_id)
            EventSubscription.objects.get_or_create(
                user=user,
                stored_event_type=event.stored_event_type,
            )
        except Exception as e:
            print(f'  [WARN] Підписка {event_id}: {e}')


def create_or_update_user(row):
    mysql_login = str(row['login']).strip()
    username    = to_mayan_login(mysql_login)  # 1001 → 01001
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
            print(f'  [PWD] {username} пароль змінено')
        if user.is_active == del_user:
            user.is_active = not del_user
            changed = True
            status = 'деактивовано' if del_user else 'активовано'
            print(f'  [STATE] {username} {status}')
        if changed:
            user.save()
        else:
            print(f'  [SKIP] {username} без змін')
        return

    # Тільки для нових юзерів
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
        content_type=cabinet_ct,
        object_id=cabinet.pk,
        role=role,
    )
    acl.permissions.add(*StoredPermission.objects.filter(name__in=CABINET_PERMS))

    return username  # повертаємо Mayan login для подальшої обробки


# ─── Режими ──────────────────────────────────────────────────────────────────

def import_all():
    print('=== Імпорт всіх клієнтів 1000-9999 ===')
    conn = db_connect()
    rows = get_all_users(conn)
    conn.close()
    print(f'Знайдено в MySQL: {len(rows)}')
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
            if result:  # новий юзер
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


# ─── Main ────────────────────────────────────────────────────────────────────

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
        # Виводимо нових клієнтів для shell скрипту
        for c in new:
            print(f'NEW_CLIENT:{c["mysql_login"]}:{c["mayan_id"]}')
    else:
        parser.print_help()

