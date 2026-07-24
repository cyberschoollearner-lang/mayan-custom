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
DELETE        = '--delete' in sys.argv
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

    # Хардлінк успадковує власника оригінального файлу (часто root,
    # бо rsync виконується з хоста). Mayan-процес працює під uid 1000 (mayan),
    # тому без явного chown Celery не зможе видалити/оновити цей файл пізніше.
    try:
        os.chown(dest_path, 1000, 1000)
    except PermissionError:
        # Скрипт запускається не з root — chown неможливий, залишаємо
        # як є і попереджаємо в лог, щоб не приховувати проблему.
        print(f'[WARNING] Не вдалось змінити власника {dest_path} — '
              f'запусти import_clinic.py з правами root')

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
            print(f'[LINK] {filename} → існуючий документ pk:{document.pk}', flush=True)

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
        err_str = str(e).encode('utf-8', errors='replace').decode('utf-8')
        print(f'[ERROR] {filepath}: {err_str}', flush=True)

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
    """Рекурсивно видаляє порожні папки знизу вверх."""
    for root, dirs, files in os.walk(path, topdown=False):
        for d in dirs:
            dirpath = os.path.join(root, d)
            if not os.listdir(dirpath):
                os.rmdir(dirpath)
                print(f'[RMDIR] {dirpath}')
    # Видаляємо основну папку якщо порожня
    if os.path.isdir(path) and not os.listdir(path):
        os.rmdir(path)
        print(f'[RMDIR] {path}')
    elif os.path.isdir(path):
        remaining = sum(len(f) for _, _, f in os.walk(path))
        print(f'[INFO] Залишилось файлів в {path}: {remaining} (не видалено)')


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

    # Завжди видаляємо порожні папки після імпорту
    print(f'\n[CLEANUP] Видаляємо порожні папки...', flush=True)
    cleanup_empty_dirs(CLINIC_DIR)


main()

