mport os, sys, django
from datetime import datetime
import uuid
import hashlib
import fcntl
import multiprocessing as mp

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


def acquire_lock(clinic_id):
    """
    Захист від паралельного запуску import_clinic.py на ту саму клініку
    (наприклад, через збіг cron + ручного запуску). flock автоматично
    звільняється навіть якщо процес впаде некоректно.
    """
    lock_path = f'/tmp/import_clinic_{clinic_id}.lock'
    lock_file = open(lock_path, 'w')
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(f'[LOCK] Імпорт {clinic_id} вже виконується іншим процесом. Виходжу.')
        sys.exit(1)
    return lock_file


_lock_handle = acquire_lock(CLINIC_ID)

try:
    role = Role.objects.get(label=f'role_{CLINIC_ID}')
except Role.DoesNotExist:
    print(f'[ERROR] role_{CLINIC_ID} not found')
    sys.exit(1)

doc_type, _ = DocumentType.objects.get_or_create(label='Clinic Documents')
doc_ct       = ContentType.objects.get_for_model(Document)

# Глобальний лічильник актуальний тільки в послідовному режимі (workers=1).
# В паралельному режимі кожен воркер — окремий процес із власною копією
# пам'яті, тому підсумок рахується в батьківському процесі з результатів,
# які повертає кожен pool.map-виклик (див. worker_import_file / main()).
counter = {'ok': 0, 'skip': 0, 'linked': 0, 'error': 0}


def get_default_workers():
    """
    Половина ядер хоста, мінімум 1, максимум 4 — обмеження навмисне:
    кожен воркер тримає власне з'єднання з PostgreSQL і пише на CephFS,
    занадто велика кількість паралельних процесів для ОДНІЄЇ клініки
    може перевантажити БД/диск без відчутного приросту швидкості.
    """
    cpu = mp.cpu_count()
    return max(1, min(4, cpu // 2))


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
    """
    Імпортує один файл у вказаний кабінет. Повертає статус:
    'ok' | 'skip' | 'linked' | 'error' | None (порожнє ім'я, нічого не робимо).

    Глобальний counter оновлюється тут для сумісності з послідовним режимом
    (workers=1) — у паралельному режимі значення в дочірньому процесі
    ігнорується, підсумок рахується в батьківському процесі окремо.
    """
    raw_filename = os.path.basename(filepath)
    filename = clean_filename(raw_filename).strip()

    if not filename:
        return None

    if not os.path.exists(filepath):
        # Файл міг зникнути між os.listdir() і обробкою (наприклад,
        # видалений паралельним процесом чи повторним запуском).
        print(f'[SKIP] {filename} — файл вже не існує (оброблено раніше?)', flush=True)
        counter['skip'] += 1
        return 'skip'

    checksum = sha256_file(filepath)
    existing_file = DocumentFile.objects.filter(checksum=checksum).first()

    if existing_file:
        document = existing_file.document
        already_in_cabinet = cabinet.documents.filter(pk=document.pk).exists()

        if already_in_cabinet:
            counter['skip'] += 1
            print(f'[SKIP] {filename} вже в кабінеті', flush=True)
            status = 'skip'
        else:
            add_to_cabinet_with_acl(document, cabinet)
            counter['linked'] += 1
            print(f'[LINK] {filename} → існуючий документ pk:{document.pk}', flush=True)
            status = 'linked'

        if os.path.exists(filepath):
            os.remove(filepath)
        return status

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
        print(f'[OK] {filename} ({file_date.strftime("%Y-%m-%d")})', flush=True)

        os.remove(filepath)
        return 'ok'

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
        return 'error'


def worker_import_file(args):
    """
    Обгортка для multiprocessing.Pool. Кожен воркер — форкнутий процес,
    тому обов'язково закриваємо успадковані з'єднання БД одразу на старті:
    Django відкриє нове з'єднання автоматично при першому запиті.
    """
    filepath, cabinet_id = args
    from django import db
    db.connections.close_all()

    cabinet = Cabinet.objects.get(pk=cabinet_id)
    status = import_file(filepath, cabinet)
    return status


def import_files_batch(filepaths, cabinet, workers):
    """
    Імпортує список файлів у кабінет. Якщо workers > 1 і файлів більше
    одного — паралельно через Pool, інакше послідовно (без накладних
    витрат на форк процесів заради 1-2 файлів).
    """
    if workers > 1 and len(filepaths) > 1:
        args = [(fp, cabinet.pk) for fp in filepaths]
        with mp.Pool(workers) as pool:
            results = pool.map(worker_import_file, args)
        for status in results:
            if status:
                counter[status] += 1
    else:
        for fpath in filepaths:
            import_file(fpath, cabinet)


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

    workers = int(os.environ.get('IMPORT_WORKERS', get_default_workers()))
    print(f'[INFO] Потоків: {workers}', flush=True)

    root_cabinet, _ = Cabinet.objects.get_or_create(label=CLINIC_ID)

    # Файли в корені
    root_files = [
        os.path.join(CLINIC_DIR, f) for f in sorted(os.listdir(CLINIC_DIR))
        if os.path.isfile(os.path.join(CLINIC_DIR, f))
    ]
    import_files_batch(root_files, root_cabinet, workers)

    # Підпапки (роки) — обробляються послідовно одна за одною, але файли
    # всередині кожного року — паралельно
    for year_dir in sorted(os.listdir(CLINIC_DIR)):
        year_path = os.path.join(CLINIC_DIR, year_dir)
        if not os.path.isdir(year_path):
            continue
        print(f'[DIR] {year_dir}', flush=True)
        year_cabinet = get_or_create_sub(root_cabinet, year_dir)

        year_files = [
            os.path.join(year_path, f) for f in sorted(os.listdir(year_path))
            if os.path.isfile(os.path.join(year_path, f))
        ]
        import_files_batch(year_files, year_cabinet, workers)

    print(f'\n=== {CLINIC_ID} ЗАВЕРШЕНО ===', flush=True)
    print(f'OK: {counter["ok"]} | LINK: {counter["linked"]} | SKIP: {counter["skip"]} | ERROR: {counter["error"]}')

    print(f'\n[CLEANUP] Видаляємо порожні папки...', flush=True)
    cleanup_empty_dirs(CLINIC_DIR)


main()
