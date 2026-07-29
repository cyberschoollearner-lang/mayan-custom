#!/usr/bin/env python3
"""
link_or_prepare_download.py — звіряє карту (checksum, host, remote_path)
з базою Mayan. Для checksum, що вже існує в Mayan — одразу лінкує документ
у відповідний підкабінет клієнта (MAYAN_ID/рік, за rel_path), без завантаження.
Для решти — виводить список на довантаження.

Вхід (stdin), TSV: checksum<TAB>host<TAB>remote_root<TAB>remote_path<TAB>relative_path
Вивід (stdout): need_download рядки host<TAB>remote_path<TAB>relative_path
"""
import os, sys, django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mayan.settings.production')
django.setup()

from django.contrib.contenttypes.models import ContentType
from mayan.apps.documents.models import Document, DocumentFile
from mayan.apps.cabinets.models import Cabinet
from mayan.apps.acls.models import AccessControlList
from mayan.apps.permissions.models import StoredPermission, Role

MAYAN_ID = sys.argv[1]

DOCUMENT_PERMISSIONS = [
    'document_view',
    'document_file_view',
    'document_version_view',
    'document_file_download',
    'document_file_print',
]

try:
    role = Role.objects.get(label=f'role_{MAYAN_ID}')
except Role.DoesNotExist:
    print(f'[ERROR] role_{MAYAN_ID} not found', file=sys.stderr)
    sys.exit(1)

root_cabinet, _ = Cabinet.objects.get_or_create(label=MAYAN_ID)
doc_ct = ContentType.objects.get_for_model(Document)

_year_cabinet_cache = {}


def get_year_cabinet(rel_path):
    """
    Визначає підкабінет за роком з relative_path (перша частина шляху,
    якщо вона 4-значна цифра — це рік, як в import_clinic.py). Якщо
    файл лежить у корені (без підпапки року) — повертає кореневий кабінет.
    """
    parts = rel_path.split('/', 1)
    if len(parts) > 1 and parts[0].isdigit() and len(parts[0]) == 4:
        year = parts[0]
        if year not in _year_cabinet_cache:
            _year_cabinet_cache[year], _ = Cabinet.objects.get_or_create(
                label=year, parent=root_cabinet
            )
        return _year_cabinet_cache[year]
    return root_cabinet


def link_existing(document, cabinet):
    cabinet.documents.add(document)
    acl, _ = AccessControlList.objects.get_or_create(
        content_type=doc_ct, object_id=document.pk, role=role,
    )
    acl.permissions.add(
        *StoredPermission.objects.filter(name__in=DOCUMENT_PERMISSIONS)
    )


linked = 0
need_download = 0
errors = 0

for line in sys.stdin:
    line = line.rstrip('\n')
    if not line:
        continue
    try:
        checksum, host, remote_root, remote_path, rel_path = line.split('\t', 4)
    except ValueError:
        print(f'[ERROR] Некоректний рядок карти: {line!r}', file=sys.stderr)
        errors += 1
        continue

    existing = DocumentFile.objects.filter(checksum=checksum).first()

    if existing:
        document = existing.document
        cabinet = get_year_cabinet(rel_path)

        already = cabinet.documents.filter(pk=document.pk).exists()
        if not already:
            link_existing(document, cabinet)
            print(f'[LINK] {rel_path} -> pk:{document.pk} (кабінет: {cabinet.label} / {cabinet.parent.label if cabinet.parent else "корінь"})', file=sys.stderr)
            linked += 1
        else:
            print(f'[SKIP] {rel_path} вже в кабінеті {cabinet.label}', file=sys.stderr)
    else:
        print(f'{host}\t{remote_path}\t{rel_path}')
        need_download += 1

print(f'\n[SUMMARY] linked={linked} need_download={need_download} errors={errors}',
      file=sys.stderr)
