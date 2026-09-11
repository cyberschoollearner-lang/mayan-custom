#!/usr/bin/env python3
"""
fix_all_view_modes_to_list.py — одноразово переводить ВСІ існуючі записи
UserViewMode з 'items' (плитка) на 'list' (список), для всіх юзерів,
всіх view. Виправляє історичні дані, накопичені до патчу default_mode.

Використання:
    docker exec mayan-app-1 python3 /var/lib/mayan/fix_all_view_modes_to_list.py
"""
import os, django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mayan.settings.production')
django.setup()

from mayan.apps.views.models import UserViewMode

updated = UserViewMode.objects.filter(value='items').update(value='list')
print(f'Оновлено записів: {updated}')

remaining = UserViewMode.objects.filter(value='items').count()
print(f'Залишилось у режимі items: {remaining}')
