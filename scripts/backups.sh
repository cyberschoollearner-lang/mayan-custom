#!/bin/bash
# backup.sh — бекап всіх важливих файлів Mayan EDMS
# Використання: ./backup.sh

BACKUP_DIR="/mnt/cephfs/backup/$(date +%Y%m%d_%H%M)"
mkdir -p "$BACKUP_DIR"/{custom,settings,scripts,config}

echo "=== Бекап в $BACKUP_DIR ==="

# 1. БД PostgreSQL
echo "--- БД ---"
docker exec mayan-postgresql-1 pg_dump -U mayan mayan | gzip \
  > "$BACKUP_DIR/mayan_db.sql.gz"
ls -lh "$BACKUP_DIR/mayan_db.sql.gz"

# 2. Docker конфіг
echo "--- Docker ---"
cp /opt/mayan/docker-compose.yml "$BACKUP_DIR/config/"
cp /opt/mayan/.env               "$BACKUP_DIR/config/"
cp /opt/mayan/.env-local         "$BACKUP_DIR/config/" 2>/dev/null || true

# 3. Mayan config.yml
echo "--- config.yml ---"
cp /mnt/cephfs/mayan/config.yml "$BACKUP_DIR/config/"

# 4. Custom додаток
echo "--- Custom app ---"
cp /opt/mayan/custom/__init__.py  "$BACKUP_DIR/custom/"
cp /opt/mayan/custom/apps.py      "$BACKUP_DIR/custom/"
cp /opt/mayan/custom/middleware.py "$BACKUP_DIR/custom/"
cp /opt/mayan/custom/signals.py   "$BACKUP_DIR/custom/"
cp /opt/mayan/custom/views.py     "$BACKUP_DIR/custom/" 2>/dev/null || true
cp /opt/mayan/custom/urls.py      "$BACKUP_DIR/custom/" 2>/dev/null || true
mkdir -p "$BACKUP_DIR/custom/templates/appearance/menus"
cp /opt/mayan/custom/templates/appearance/menus/topbar.html \
   "$BACKUP_DIR/custom/templates/appearance/menus/"

# 5. Settings
echo "--- Settings ---"
cp /opt/mayan/settings/local.py "$BACKUP_DIR/settings/" 2>/dev/null || true

# 6. Скрипти
echo "--- Скрипти ---"
cp /mnt/cephfs/mayan/import_clinic.py       "$BACKUP_DIR/scripts/"
cp /mnt/cephfs/mayan/sync_users_from_mysql.py "$BACKUP_DIR/scripts/" 2>/dev/null || true
cp /opt/mayan/sync_clients.sh               "$BACKUP_DIR/scripts/" 2>/dev/null || true
cp /opt/mayan/sync_clinic.sh                "$BACKUP_DIR/scripts/" 2>/dev/null || true
cp /opt/mayan/rotate_cabinets.py	    "$BACKUP_DIR/scripts/" 2>/dev/null || true

# 7. Медіа
echo "--- Медіа ---"
cp /mnt/cephfs/mayan/login_bg.jpg "$BACKUP_DIR/" 2>/dev/null || true

echo ""
echo "=== ГОТОВО ==="
echo "Розмір бекапу:"
du -sh "$BACKUP_DIR"
ls -lh "$BACKUP_DIR/"
ls -lh "$BACKUP_DIR/custom/"
ls -lh "$BACKUP_DIR/scripts/"
ls -lh "$BACKUP_DIR/config/"

