#!/usr/bin/env python3
"""
revoke_expired_edit_permissions.py — щогодини перевіряє, чи вийшло вікно
редагування (8:00 + CUSTOM_EDIT_WINDOW_HOURS), і якщо так — знімає
document_edit/document_file_new/document_file_delete/document_delete
з ACL документів, завантажених СЬОГОДНІ клініками (0101-0999).

acl_edit (розшарювання) і базові view/download/print НЕ чіпаються —
лишаються назавжди. Клієнтів (01000-09999) не чіпає — у них цих прав
і так нема.

Ідемпотентний — маркер-файл на день не дає повторити зайве.

Запуск через cron (щогодини):
    0 * * * * docker exec mayan-app-1 /opt/mayan-edms/bin/python \
        /var/lib/mayan/revoke_expired_edit_permissions.py

Використання:
    revoke_expired_edit_permissions.py            # звичайний cron-режим
    revoke_expired_edit_permissions.py --force     # ігнорувати маркер/час, виконати зараз
    revoke_expired_edit_permissions.py --dry-run   # показати що буде відкликано, нічого не міняти
"""
import os, sys, django
from datetime import datetime, time as dtime

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mayan.settings.production')
django.setup()

from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from mayan.apps.documents.models import Document
from mayan.apps.acls.models import AccessControlList
from mayan.apps.permissions.models import StoredPermission
from custom.settings import setting_edit_window_hours

DRY_RUN = '--dry-run' in sys.argv
FORCE = '--force' in sys.argv

MARKER_DIR = '/tmp/revoke_edit_markers'
os.makedirs(MARKER_DIR, exist_ok=True)

TIME_LIMITED_PERMS = [
    'document_edit',
    'document_file_new',
    'document_file_delete',
    'document_delete',
]


def is_clinic_role(role_label):
    """role_0101 -> True (4-значний код клініки). role_01001 -> False (5-значний клієнт)."""
    if not role_label.startswith('role_'):
        return False
    code = role_label[len('role_'):]
    return code.isdigit() and len(code) == 4


def main():
    today = timezone.localdate()
    marker_path = os.path.join(MARKER_DIR, f'{today.isoformat()}.done')

    if not FORCE and os.path.exists(marker_path):
        print(f'[SKIP] Вже виконано сьогодні ({marker_path} існує)')
        return

    edit_window_hours = setting_edit_window_hours.value
    start_of_window = timezone.make_aware(datetime.combine(today, dtime(8, 0)))
    cutoff = start_of_window + timezone.timedelta(hours=edit_window_hours)

    now = timezone.localtime()
    if now < cutoff and not FORCE:
        print(f'[SKIP] Вікно ще діє до {cutoff.strftime("%H:%M")}, зараз {now.strftime("%H:%M")}')
        return

    print(f'[INFO] Вікно завершено о {cutoff.strftime("%H:%M")} '
          f'(8:00 + {edit_window_hours}г), зараз {now.strftime("%H:%M")}. Відкликаю права...')

    day_start = timezone.make_aware(datetime.combine(today, dtime(0, 0)))
    docs_today = Document.objects.filter(datetime_created__gte=day_start)

    doc_ct = ContentType.objects.get_for_model(Document)
    time_limited_perm_objs = list(
        StoredPermission.objects.filter(name__in=TIME_LIMITED_PERMS)
    )

    revoked_count = 0
    for document in docs_today:
        acls = AccessControlList.objects.filter(
            content_type=doc_ct, object_id=document.pk
        )
        for acl in acls:
            if not is_clinic_role(acl.role.label):
                continue

            existing = set(acl.permissions.values_list('name', flat=True))
            to_revoke = [p for p in time_limited_perm_objs if p.name in existing]
            if not to_revoke:
                continue

            if DRY_RUN:
                print(f'[DRY-RUN] {document.label} (роль {acl.role.label}): '
                      f'відкликав би {[p.name for p in to_revoke]}')
            else:
                acl.permissions.remove(*to_revoke)
                print(f'[REVOKE] {document.label} (роль {acl.role.label}): '
                      f'{[p.name for p in to_revoke]}')
            revoked_count += 1

    print(f'\n[DONE] Оброблено ACL-записів: {revoked_count}')

    if not DRY_RUN:
        with open(marker_path, 'w') as f:
            f.write(now.isoformat())
        print(f'[MARKER] Створено {marker_path}')


main()
