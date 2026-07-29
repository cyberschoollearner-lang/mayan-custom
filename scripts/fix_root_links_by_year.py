#!/usr/bin/env python3
"""
fix_root_links_by_year.py — переносить документи, які вже прив'язані
до кореневого кабінету клієнта (без розбивки по роках), у відповідні
підкабінети MAYAN_ID/рік, за датою створення документа (datetime_created).

Використання:
    docker exec mayan-app-1 python3 /var/lib/mayan/fix_root_links_by_year.py 01003
"""
import os, sys, django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mayan.settings.production')
django.setup()

from mayan.apps.cabinets.models import Cabinet

MAYAN_ID = sys.argv[1]

root_cabinet = Cabinet.objects.get(label=MAYAN_ID)

# Документи, що прив'язані САМЕ до кореневого кабінету (не до підкабінетів)
docs = root_cabinet.documents.all()

moved = 0
for doc in docs:
    year = str(doc.datetime_created.year)
    year_cabinet, _ = Cabinet.objects.get_or_create(label=year, parent=root_cabinet)

    if not year_cabinet.documents.filter(pk=doc.pk).exists():
        year_cabinet.documents.add(doc)
    root_cabinet.documents.remove(doc)
    print(f'[MOVE] {doc.label} -> {MAYAN_ID}/{year}')
    moved += 1

print(f'\n[DONE] Перенесено: {moved}')
