#!/bin/bash
# backups.sh — бекап всіх важливих файлів Mayan EDMS + коміт у git
#
# Використання:
#   ./backups.sh              # повний бекап + git commit + push
#   ./backups.sh --no-git     # тільки бекап, без git

DO_GIT=true
[[ "$1" == "--no-git" ]] && DO_GIT=false

BACKUP_DIR="/mnt/cephfs/backup/$(date +%Y%m%d_%H%M)"
PROJECT_DIR="/opt/mayan-project"
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
cp /opt/mayan/custom/__init__.py   "$BACKUP_DIR/custom/"
cp /opt/mayan/custom/apps.py       "$BACKUP_DIR/custom/"
cp /opt/mayan/custom/middleware.py "$BACKUP_DIR/custom/"
cp /opt/mayan/custom/signals.py    "$BACKUP_DIR/custom/"
cp /opt/mayan/custom/views.py      "$BACKUP_DIR/custom/" 2>/dev/null || true
cp /opt/mayan/custom/urls.py       "$BACKUP_DIR/custom/" 2>/dev/null || true
mkdir -p "$BACKUP_DIR/custom/templates/appearance/menus"
cp /opt/mayan/custom/templates/appearance/menus/topbar.html \
   "$BACKUP_DIR/custom/templates/appearance/menus/"

# 5. Settings
echo "--- Settings ---"
cp /opt/mayan/settings/local.py "$BACKUP_DIR/settings/" 2>/dev/null || true

# 6. Скрипти
echo "--- Скрипти ---"
cp /mnt/cephfs/mayan/import_clinic.py         "$BACKUP_DIR/scripts/"
cp /mnt/cephfs/mayan/sync_users_from_mysql.py "$BACKUP_DIR/scripts/" 2>/dev/null || true
cp /opt/mayan/sync_clients.sh                 "$BACKUP_DIR/scripts/" 2>/dev/null || true
cp /opt/mayan/sync_clinic.sh                  "$BACKUP_DIR/scripts/" 2>/dev/null || true
cp /mnt/cephfs/mayan/rotate_cabinets.py       "$BACKUP_DIR/scripts/" 2>/dev/null || true
cp /opt/mayan/sync_and_import.sh              "$BACKUP_DIR/scripts/" 2>/dev/null || true
cp /mnt/cephfs/backup/backups.sh              "$BACKUP_DIR/scripts/" 2>/dev/null || true

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

# 8. Синхронізація в git-проєкт і коміт
if $DO_GIT; then
    echo ""
    echo "--- Git sync ---"
    cp /opt/mayan/custom/*.py "$PROJECT_DIR/custom/" 2>/dev/null
    cp /opt/mayan/custom/templates/appearance/menus/topbar.html \
       "$PROJECT_DIR/custom/templates/appearance/menus/"
    cp /opt/mayan/settings/local.py "$PROJECT_DIR/settings/" 2>/dev/null
    cp /opt/mayan/docker-compose.yml "$PROJECT_DIR/"
    cp /mnt/cephfs/mayan/import_clinic.py "$PROJECT_DIR/scripts/"
    cp /mnt/cephfs/mayan/sync_users_from_mysql.py "$PROJECT_DIR/scripts/" 2>/dev/null
    cp /mnt/cephfs/mayan/rotate_cabinets.py "$PROJECT_DIR/scripts/" 2>/dev/null
    cp /opt/mayan/sync_clinic.sh "$PROJECT_DIR/scripts/" 2>/dev/null
    cp /opt/mayan/sync_clients.sh "$PROJECT_DIR/scripts/" 2>/dev/null
    cp /opt/mayan/sync_and_import.sh "$PROJECT_DIR/scripts/" 2>/dev/null
    cp "$0" "$PROJECT_DIR/scripts/backups.sh"

    cd "$PROJECT_DIR"
    git add -A
    if ! git diff --cached --quiet; then
        git commit -m "sync: автобекап $(date +%Y-%m-%d\ %H:%M) — оновлені скрипти й конфіги"
        git push
        echo "=== Закомічено і запушено ==="
    else
        echo "=== Змін немає, коміт не потрібен ==="
    fi
fi
