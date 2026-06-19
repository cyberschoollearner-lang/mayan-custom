#!/bin/bash
# sync_clients.sh — синхронізація клієнтів 1000-9999 (→ 01000-09999 в Mayan)
#
# Використання:
#   ./sync_clients.sh                    # cron: MySQL + rsync + сортування + імпорт
#   ./sync_clients.sh --no-rsync         # MySQL + імпорт без rsync
#   ./sync_clients.sh --manual 1001      # ручний для конкретного клієнта
#   ./sync_clients.sh --manual 1001 --no-rsync
#   ./sync_clients.sh --import-only      # тільки імпорт існуючих файлів

# ─── Конфіг ──────────────────────────────────────────────────────────────────
# Хост 1 і шляхи де шукати папки клієнтів
REMOTE_HOST1="xxx.xxx.xxx.5"
REMOTE_PATHS1=(
    "/var/snap/public"
    "/var/snap/yyy.yyy.yyy.yyy/new/public"
    "/var/snap/yyy.yyy.yyy.yyy/public"
)

# Хост 2 і шляхи
REMOTE_HOST2="zzz.zzz.zzz.55"
REMOTE_PATHS2=(
    "/public"
    "/backup/public"
)

LOCAL_BASE="/mnt/cephfs/clinic"
MAYAN_PYTHON="/opt/mayan-edms/bin/python"
MAYAN_SCRIPT="/var/lib/mayan/import_clinic.py"
MAYAN_SYNC="/var/lib/mayan/sync_users_from_mysql.py"
MAYAN_CONTAINER="mayan-app-1"
LOG_FILE="/var/log/sync_clients.log"
CURRENT_YEAR=$(date +%Y)

DO_RSYNC=true
MANUAL_CLIENT=""
IMPORT_ONLY=false

# ─── Аргументи ───────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-rsync)    DO_RSYNC=false; shift ;;
        --import-only) IMPORT_ONLY=true; DO_RSYNC=false; shift ;;
        --manual)      MANUAL_CLIENT="$2"; shift 2 ;;
        *) shift ;;
    esac
done

# ─── Функції ─────────────────────────────────────────────────────────────────

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

# Конвертуємо MySQL login (1001) в Mayan ID (01001)
to_mayan_id() {
    printf '%05d' "$1"
}

# rsync з одного хоста — перебираємо всі шляхи
rsync_from_host() {
    local HOST="$1"
    local CLIENT_ID="$2"    # MySQL login: 1001
    local LOCAL_DIR="$3"
    shift 3
    local PATHS=("$@")

    local RSYNC_OPTS=(
        --archive
        --times
        --recursive
        --ignore-existing
        --no-perms
        --omit-dir-times
        --quiet
    )

    for RPATH in "${PATHS[@]}"; do
        REMOTE_DIR="${RPATH}/${CLIENT_ID}"
        if ssh -o ConnectTimeout=5 "$HOST" "[ -d '$REMOTE_DIR' ]" 2>/dev/null; then
            log "  rsync ${HOST}:${REMOTE_DIR}/ → ${LOCAL_DIR}/"
            rsync "${RSYNC_OPTS[@]}" \
                "${HOST}:${REMOTE_DIR}/" \
                "${LOCAL_DIR}/"
        fi
    done
}

# rsync файлів клієнта з обох серверів
rsync_client() {
    local CLIENT_ID="$1"    # MySQL login: 1001
    local MAYAN_ID="$2"     # Mayan ID: 01001
    local LOCAL_DIR="$LOCAL_BASE/$MAYAN_ID"
    mkdir -p "$LOCAL_DIR"

    rsync_from_host "$REMOTE_HOST1" "$CLIENT_ID" "$LOCAL_DIR" "${REMOTE_PATHS1[@]}"
    rsync_from_host "$REMOTE_HOST2" "$CLIENT_ID" "$LOCAL_DIR" "${REMOTE_PATHS2[@]}"
}

# Сортування файлів по роках (тільки файли в корені папки)
sort_by_year() {
    local LOCAL_DIR="$1"
    [ -d "$LOCAL_DIR" ] || return

    local moved=0
    for fpath in "$LOCAL_DIR"/*; do
        [ -f "$fpath" ] || continue
        fname=$(basename "$fpath")

        # Рік модифікації файлу
        year=$(date -r "$fpath" +%Y 2>/dev/null)
        [ -z "$year" ] && continue

        # Поточний рік — не чіпаємо
        [ "$year" = "$CURRENT_YEAR" ] && continue

        year_dir="$LOCAL_DIR/$year"
        mkdir -p "$year_dir"
        mv "$fpath" "$year_dir/$fname"
        log "  [SORT] $fname → $year/"
        moved=$((moved + 1))
    done

    [ $moved -gt 0 ] && log "  [SORT] Переміщено файлів: $moved"
}

# Імпорт в Mayan через docker exec
import_to_mayan() {
    local MAYAN_ID="$1"
    log "  [IMPORT] $MAYAN_ID → Mayan"
    docker exec "$MAYAN_CONTAINER" \
        "$MAYAN_PYTHON" "$MAYAN_SCRIPT" "$MAYAN_ID" 2>&1 | tee -a "$LOG_FILE"
}

# Повна обробка одного клієнта
process_client() {
    local CLIENT_ID="$1"    # MySQL login: 1001
    local MAYAN_ID
    MAYAN_ID=$(to_mayan_id "$CLIENT_ID")

    log "=== Клієнт: $CLIENT_ID → $MAYAN_ID ==="

    if $DO_RSYNC; then
        rsync_client "$CLIENT_ID" "$MAYAN_ID"
    fi

    sort_by_year "$LOCAL_BASE/$MAYAN_ID"
    import_to_mayan "$MAYAN_ID"
}

# Синхронізація юзерів з MySQL
sync_from_mysql() {
    log "Перевірка MySQL..."
    NEW_CLIENTS=$(docker exec "$MAYAN_CONTAINER" \
        "$MAYAN_PYTHON" "$MAYAN_SYNC" --once 2>&1 | tee -a "$LOG_FILE" | grep "^NEW_CLIENT:")
    echo "$NEW_CLIENTS"
}

# ─── Main ────────────────────────────────────────────────────────────────────

if [ -n "$MANUAL_CLIENT" ]; then
    log "=== РУЧНИЙ ЗАПУСК: $MANUAL_CLIENT ==="
    process_client "$MANUAL_CLIENT"
    log "=== ГОТОВО ==="
    exit 0
fi

if $IMPORT_ONLY; then
    log "=== IMPORT ONLY ==="
    for dir in "$LOCAL_BASE"/0[1-9][0-9][0-9][0-9]; do
        [ -d "$dir" ] || continue
        MAYAN_ID=$(basename "$dir")
        num=${MAYAN_ID#0}
        if [ "$num" -ge 1000 ] 2>/dev/null && [ "$num" -le 9999 ] 2>/dev/null; then
            sort_by_year "$dir"
            import_to_mayan "$MAYAN_ID"
        fi
    done
    log "=== ГОТОВО ==="
    exit 0
fi

# Cron режим
NEW_CLIENTS=$(sync_from_mysql)

if [ -z "$NEW_CLIENTS" ]; then
    exit 0
fi

# Обробляємо нових клієнтів
while IFS=: read -r _ CLIENT_ID MAYAN_ID; do
    [ -n "$CLIENT_ID" ] || continue
    process_client "$CLIENT_ID"
done <<< "$NEW_CLIENTS"

log "=== СИНХРОНІЗАЦІЯ ЗАВЕРШЕНА ==="
