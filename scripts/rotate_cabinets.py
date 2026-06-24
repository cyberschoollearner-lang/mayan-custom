#!/usr/bin/env python3
"""
rotate_cabinets.py — щорічна ротація файлів по кабінетах Mayan EDMS.

Логіка:
  1. Створює підкабінет {year} в кожному кабінеті
  2. Переміщує документи з кореня кабінету в підкабінет відповідно до року створення
  3. Старі папки перейменовує в {year}_archive
  4. Через місяць (--cleanup) видаляє _archive папки

Порядок обробки:
  - Спочатку 01000-09999 (клієнти) — видаляємо лінки
  - Потім 0100-0999 (клініки) — видаляємо файли

Використання:
  # Тест для одного кабінету
  python rotate_cabinets.py --test --cabinet 0101

  # Тест для конкретного року
  python rotate_cabinets.py --test --cabinet 0101 --year 2025

  # Повна ротація (запускати раз на рік)
  python rotate_cabinets.py --run

  # Видалення архівів старших за місяць (запускати раз на місяць)
  python rotate_cabinets.py --cleanup

  # Перевірити що буде видалено (без реального видалення)
  python rotate_cabinets.py --cleanup --dry-run
"""

import os, sys, django, argparse
from datetime import datetime, timedelta

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mayan.settings.production')
django.setup()

from django.utils import timezone
from mayan.apps.cabinets.models import Cabinet
from mayan.apps.documents.models import Document
from mayan.apps.acls.models import AccessControlList
from django.contrib.contenttypes.models import ContentType

# ─── Налаштування ────────────────────────────────────────────────────────────

# Максимальний строк зберігання в роках
MAX_RETENTION_YEARS = int(os.getenv('MAX_RETENTION_YEARS', '5'))

# Затримка перед видаленням архіву (днів)
ARCHIVE_DELETE_AFTER_DAYS = int(os.getenv('ARCHIVE_DELETE_AFTER_DAYS', '30'))

CURRENT_YEAR = datetime.now().year
MIN_YEAR     = CURRENT_YEAR - MAX_RETENTION_YEARS  # наприклад 2026-5=2021

doc_ct = ContentType.objects.get_for_model(Document)

# ─── Лічильники ──────────────────────────────────────────────────────────────
counter = {
    'moved': 0,
    'archived': 0,
    'deleted_links': 0,
    'deleted_docs': 0,
    'errors': 0,
}


def log(msg, dry_run=False):
    prefix = '[DRY-RUN] ' if dry_run else ''
    print(f'{prefix}{msg}', flush=True)


def get_or_create_year_cabinet(parent_cabinet, year, dry_run=False):
    """Створює або повертає підкабінет року."""
    label = str(year)
    existing = Cabinet.objects.filter(label=label, parent=parent_cabinet).first()
    if existing:
        return existing
    if dry_run:
        log(f'  Створив би кабінет {parent_cabinet.label}/{year}', dry_run)
        return None
    cab, created = Cabinet.objects.get_or_create(
        label=label, parent=parent_cabinet
    )
    if created:
        log(f'  [CREATE] Кабінет {parent_cabinet.label}/{year}')
    return cab


def move_document_to_year(document, from_cabinet, to_cabinet, dry_run=False):
    """Переміщує документ з одного кабінету в інший."""
    if dry_run:
        log(f'  [MOVE] {document.label} → {to_cabinet.label}', dry_run)
        counter['moved'] += 1
        return

    try:
        from_cabinet.documents.remove(document)
        to_cabinet.documents.add(document)
        counter['moved'] += 1
        log(f'  [MOVE] {document.label} → {to_cabinet.label}')
    except Exception as e:
        counter['errors'] += 1
        log(f'  [ERROR] move {document.label}: {e}')


def is_link(document, cabinet_label):
    """
    Перевіряє чи документ є лінком (розшарений з клініки).
    Лінк = документ є також в кабінеті клініки (0100-0999).
    """
    clinic_cabinets = document.cabinets.filter(
        label__regex=r'^0[1-9][0-9]{2}$'  # 0100-0999
    )
    return clinic_cabinets.exists()


def remove_document_from_cabinet(document, cabinet, is_link_doc=False, dry_run=False):
    """
    Видаляє документ з кабінету.
    Якщо лінк — тільки прибираємо з кабінету і видаляємо ACL.
    Якщо оригінал і більше ніде немає — видаляємо фізично.
    """
    if dry_run:
        action = 'видалив би лінк' if is_link_doc else 'видалив би документ'
        log(f'  [DELETE] {action}: {document.label} з {cabinet.label}', dry_run)
        if is_link_doc:
            counter['deleted_links'] += 1
        else:
            counter['deleted_docs'] += 1
        return

    try:
        # Видаляємо ACL для ролі цього кабінету
        from mayan.apps.permissions.models import Role
        role_label = f'role_{cabinet.label.split("/")[0]}'
        try:
            role = Role.objects.get(label=role_label)
            AccessControlList.objects.filter(
                content_type=doc_ct,
                object_id=document.pk,
                role=role
            ).delete()
        except Role.DoesNotExist:
            pass

        # Прибираємо документ з кабінету
        cabinet.documents.remove(document)

        if is_link_doc:
            counter['deleted_links'] += 1
            log(f'  [DELETE LINK] {document.label} з {cabinet.label}')
        else:
            # Перевіряємо чи документ ще десь є
            remaining_cabinets = document.cabinets.count()
            if remaining_cabinets == 0:
                document.delete()
                counter['deleted_docs'] += 1
                log(f'  [DELETE DOC] {document.label} видалено фізично')
            else:
                counter['deleted_docs'] += 1
                log(f'  [DELETE DOC] {document.label} видалено з {cabinet.label} (є в {remaining_cabinets} інших)')

    except Exception as e:
        counter['errors'] += 1
        log(f'  [ERROR] delete {document.label}: {e}')


def archive_old_cabinet(cabinet, dry_run=False):
    """Перейменовує кабінет в {label}_archive."""
    if '_archive' in cabinet.label:
        return  # вже архів

    year = int(cabinet.label) if cabinet.label.isdigit() else None
    if not year:
        return
    if year >= MIN_YEAR:
        return  # рік в межах допустимого

    new_label = f'{cabinet.label}_archive'
    existing = Cabinet.objects.filter(
        label=new_label, parent=cabinet.parent
    ).first()

    if existing:
        return  # архів вже існує

    if dry_run:
        log(f'  [ARCHIVE] {cabinet.label} → {new_label}', dry_run)
        counter['archived'] += 1
        return

    try:
        cabinet.label = new_label
        cabinet.save()
        # Зберігаємо дату архівування
        cabinet.description = f'archived:{datetime.now().isoformat()}'
        cabinet.save()
        counter['archived'] += 1
        log(f'  [ARCHIVE] {cabinet.label}')
    except Exception as e:
        counter['errors'] += 1
        log(f'  [ERROR] archive {cabinet.label}: {e}')


def process_cabinet(root_cabinet, dry_run=False):
    """Обробляє один кореневий кабінет."""
    cabinet_label = root_cabinet.label
    log(f'\n=== Кабінет: {cabinet_label} ===')

    # 1. Переміщуємо файли з кореня кабінету в підпапки по роках
    root_docs = root_cabinet.documents.all()
    for document in root_docs:
        # Визначаємо рік документа
        doc_year = document.datetime_created.year if document.datetime_created else CURRENT_YEAR

        # Поточний рік — не чіпаємо
        if doc_year == CURRENT_YEAR:
            continue

        # Створюємо підкабінет року
        year_cabinet = get_or_create_year_cabinet(root_cabinet, doc_year, dry_run)
        if year_cabinet or dry_run:
            move_document_to_year(document, root_cabinet, year_cabinet, dry_run)

    # 2. Архівуємо старі підкабінети
    sub_cabinets = Cabinet.objects.filter(parent=root_cabinet)
    for sub in sub_cabinets:
        if not sub.label.isdigit():
            continue
        year = int(sub.label)
        if year < MIN_YEAR:
            archive_old_cabinet(sub, dry_run)

    # 3. Видаляємо документи зі старих підкабінетів
    old_subs = Cabinet.objects.filter(
        parent=root_cabinet,
        label__regex=r'^\d{4}$'
    )
    for sub in old_subs:
        if not sub.label.isdigit():
            continue
        year = int(sub.label)
        if year >= MIN_YEAR:
            continue

        log(f'  Обробка старого підкабінету: {sub.label} (< {MIN_YEAR})')
        is_client = bool(
            root_cabinet.label.startswith('0') and
            len(root_cabinet.label) == 5 and
            root_cabinet.label[1:].isdigit()
        )

        for document in sub.documents.all():
            link = is_link(document, cabinet_label)
            remove_document_from_cabinet(document, sub, is_link_doc=link, dry_run=dry_run)


def cleanup_archives(dry_run=False):
    """Видаляє _archive кабінети старші за ARCHIVE_DELETE_AFTER_DAYS."""
    log(f'\n=== Cleanup архівів (старші {ARCHIVE_DELETE_AFTER_DAYS} днів) ===')
    cutoff = datetime.now() - timedelta(days=ARCHIVE_DELETE_AFTER_DAYS)

    archive_cabs = Cabinet.objects.filter(label__endswith='_archive')
    for cab in archive_cabs:
        # Перевіряємо дату архівування
        archived_date = None
        if cab.description and cab.description.startswith('archived:'):
            try:
                archived_date = datetime.fromisoformat(
                    cab.description.replace('archived:', '')
                )
            except Exception:
                pass

        if not archived_date:
            log(f'  [SKIP] {cab.label} — дата архівування невідома')
            continue

        if archived_date > cutoff:
            days_left = (archived_date + timedelta(days=ARCHIVE_DELETE_AFTER_DAYS) - datetime.now()).days
            log(f'  [SKIP] {cab.label} — ще {days_left} днів до видалення')
            continue

        log(f'  [DELETE ARCHIVE] {cab.label} (архівовано {archived_date.strftime("%Y-%m-%d")})')

        if not dry_run:
            try:
                # Видаляємо всі документи з архівного кабінету
                for document in cab.documents.all():
                    link = is_link(document, cab.label)
                    remove_document_from_cabinet(document, cab, is_link_doc=link)
                # Видаляємо сам кабінет
                cab.delete()
                log(f'  [DELETED] {cab.label}')
            except Exception as e:
                log(f'  [ERROR] {e}')


def get_cabinets_ordered():
    """
    Повертає кабінети в правильному порядку:
    1. Спочатку клієнти 01000-09999
    2. Потім клініки 0100-0999
    """
    clients = []
    clinics  = []

    for cab in Cabinet.objects.filter(parent=None).order_by('label'):
        label = cab.label
        if not label.isdigit():
            continue
        num = int(label)
        if 1000 <= num <= 9999 and len(label) == 5:
            clients.append(cab)
        elif 100 <= num <= 999 and len(label) == 4:
            clinics.append(cab)

    return clients + clinics


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Ротація файлів по роках в кабінетах Mayan EDMS'
    )
    parser.add_argument('--run',      action='store_true', help='Запустити повну ротацію')
    parser.add_argument('--test',     action='store_true', help='Тестовий запуск (dry-run)')
    parser.add_argument('--cleanup',  action='store_true', help='Видалити архіви старші за місяць')
    parser.add_argument('--dry-run',  action='store_true', help='Показати що буде зроблено без змін')
    parser.add_argument('--cabinet',  type=str,            help='Обробити тільки один кабінет')
    parser.add_argument('--year',     type=int,            help='Обробити тільки конкретний рік')
    parser.add_argument('--retention',type=int,            help=f'Максимальний строк зберігання в роках (default: {MAX_RETENTION_YEARS})')
    args = parser.parse_args()

    global MAX_RETENTION_YEARS, MIN_YEAR
    if args.retention:
        MAX_RETENTION_YEARS = args.retention
        MIN_YEAR = CURRENT_YEAR - MAX_RETENTION_YEARS

    dry_run = args.test or args.dry_run

    print(f'═══════════════════════════════════════════')
    print(f'  Ротація кабінетів Mayan EDMS')
    print(f'  Поточний рік:     {CURRENT_YEAR}')
    print(f'  Макс. зберігання: {MAX_RETENTION_YEARS} років')
    print(f'  Мін. рік:         {MIN_YEAR}')
    print(f'  Режим:            {"DRY-RUN" if dry_run else "РЕАЛЬНИЙ"}')
    print(f'═══════════════════════════════════════════\n')

    if args.cleanup:
        cleanup_archives(dry_run=dry_run)

    elif args.run or args.test:
        if args.cabinet:
            # Один кабінет
            cab = Cabinet.objects.filter(label=args.cabinet, parent=None).first()
            if not cab:
                print(f'[ERROR] Кабінет {args.cabinet} не знайдено')
                sys.exit(1)
            process_cabinet(cab, dry_run=dry_run)
        else:
            # Всі кабінети в правильному порядку
            cabinets = get_cabinets_ordered()
            print(f'Кабінетів для обробки: {len(cabinets)}')
            for cab in cabinets:
                process_cabinet(cab, dry_run=dry_run)

    else:
        parser.print_help()
        sys.exit(0)

    print(f'\n═══════════════════════════════════════════')
    print(f'  РЕЗУЛЬТАТИ:')
    print(f'  Переміщено документів:    {counter["moved"]}')
    print(f'  Архівовано кабінетів:     {counter["archived"]}')
    print(f'  Видалено лінків:          {counter["deleted_links"]}')
    print(f'  Видалено документів:      {counter["deleted_docs"]}')
    print(f'  Помилок:                  {counter["errors"]}')
    print(f'═══════════════════════════════════════════')


main()
