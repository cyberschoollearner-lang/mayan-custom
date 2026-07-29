#!/usr/bin/env python3
"""
link_or_prepare_download.py — звіряє карту (checksum, host, remote_path)
з базою Mayan. Для checksum, що вже існує в Mayan — одразу лінкує документ
у кабінет клієнта (без завантаження файлу). Для решти — виводить список
"host<TAB>remote_path<TAB>local_relative_path" для подальшого rsync.

Вхід (stdin), формат TSV, одна строка на файл:
    checksum<TAB>host<TAB>remote_root<TAB>remote_path<TAB>relative_path

Використання:
    cat map.tsv | docker exec -i mayan-app-1 python3 \
        /var/lib/mayan/link_or_prepare_download.py 01001

Вивід (stdout): рядки need_download у форматі
    host<TAB>remote_path<TAB>relative_path
"""
import os, sys, django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mayan.settings.production')
django.setup()

from django.contrib.contenttypes.models import ContentType
from mayan.apps.documents.models import DocumentFile
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

cabinet, _ = Cabinet.objects.get_or_create(label=MAYAN_ID)
doc_ct = ContentType.objects.get_for_model(cabinet.__class__)  # placeholder, замінено нижче

from mayan.apps.documents.models import Document
doc_ct = ContentType.objects.get_for_model(Document)


def link_existing(document):
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
        already = cabinet.documents.filter(pk=document.pk).exists()
        if not already:
            link_existing(document)
            print(f'[LINK] {rel_path} -> pk:{document.pk}', file=sys.stderr)
            linked += 1
        else:
            print(f'[SKIP] {rel_path} вже в кабінеті', file=sys.stderr)
    else:
        # Потрібне завантаження — виводимо в stdout для rsync
        print(f'{host}\t{remote_path}\t{rel_path}')
        need_download += 1

print(f'\n[SUMMARY] linked={linked} need_download={need_download} errors={errors}',
      file=sys.stderr)
