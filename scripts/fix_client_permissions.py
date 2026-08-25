#!/usr/bin/env python3
"""
fix_client_permissions.py — прибирає зайві права (document_create,
sources_setup_view, sources_view, message_create/delete/edit) з усіх
існуючих ролей клієнтів (01000-09999, 5-значний код). Клініки (0100-0999,
4-значний код) не чіпає.
"""
import os, django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mayan.settings.production')
django.setup()

from mayan.apps.permissions.models import Role, StoredPermission

REMOVE_PERMS = [
    'document_create',
    'sources_setup_view',
    'sources_view',
    'message_create',
    'message_delete',
    'message_edit',
]

perms_to_remove = list(StoredPermission.objects.filter(name__in=REMOVE_PERMS))

fixed = 0
for role in Role.objects.filter(label__startswith='role_'):
    code = role.label[len('role_'):]
    if not (code.isdigit() and len(code) == 5):
        continue

    existing = set(role.permissions.values_list('name', flat=True))
    to_remove = [p for p in perms_to_remove if p.name in existing]
    if to_remove:
        role.permissions.remove(*to_remove)
        print(f'{role.label}: прибрано {[p.name for p in to_remove]}')
        fixed += 1

print(f'\nВиправлено ролей: {fixed}')
