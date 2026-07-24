#!/bin/bash
# sync_and_import.sh — rsync + імпорт клінік в Mayan EDMS
#
# Використання:
#   ./sync_and_import.sh 0120 0121 0122 0123
#   ./sync_and_import.sh --all          # всі клініки з remote серверів
#   ./sync_and_import.sh --no-rsync 0120 0121   # тільки імпорт без rsync
#   ./sync_and_import.sh --no-import 0120 0121  # тільки rsync без імпорту

# ─── Конфіг ──────────────────────────────────────────────────────────────────
REMOTE_HOST1="10.195.67.5"
REMOTE_PATHS1=(
    "/var/snap/public"
    "/var/snap/176.111.63.55/new/public"
    "/var/snap/176.111.63.55/public"
)

REMOTE_HOST2="176.111.63.55"
REMOTE_PATHS2=(
    "/public"
)

LOCAL_BASE="/mnt/cephfs/clinic"
MAYAN_CONTAINER="mayan-app-1"
MAYAN_PYTHON="/opt/mayan-edms/bin/python"
MAYAN_SCRIPT="/var/lib/mayan/import_clinic.py"
LOG_DIR="/mnt/cephfs/mayan/logs"
LOG_FILE="$LOG_DIR/sync_import_$(date +%Y%m%d_%H%M%S).log"

DO_RSYNC=true
DO_IMPORT=true
DO_ALL=false

mkdir -p "$LOG_DIR"

# ─── Аргументи ───────────────────────────────────────────────────────────────
CLINICS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-rsync)  DO_RSYNC=false; shift ;;
        --no-import) DO_IMPORT=false; shift ;;
        --all)       DO_ALL=true; shift ;;
        *)           CLINICS+=("$1"); shift ;;
    esac
done

# ─── Функції ─────────────────────────────────────────────────────────────────

log() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $*"
    echo "$msg" | tee -a "$LOG_FILE"
}

rsync_from_host() {
    local HOST="$1"
    local CLINIC_ID="$2"
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
        --stats
        --human-readable
    )

    local found=false
    for RPATH in "${PATHS[@]}"; do
        REMOTE_DIR="${RPATH}/${CLINIC_ID}"
        if ssh -o ConnectTimeout=5 -o BatchMode=yes "$HOST" \
           "[ -d '$REMOTE_DIR' ]" 2>/dev/null; then
            log "  rsync ${HOST}:${REMOTE_DIR}/ → ${LOCAL_DIR}/"
            rsync "${RSYNC_OPTS[@]}" \
                "${HOST}:${REMOTE_DIR}/" \
                "${LOCAL_DIR}/" 2>&1 | tee -a "$LOG_FILE"
            found=true
        fi
    done

    $found || log "  ${HOST}: папка ${CLINIC_ID} не знайдена"
}

rsync_clinic() {
    local CLINIC_ID="$1"
    local LOCAL_DIR="$LOCAL_BASE/$CLINIC_ID"
    mkdir -p "$LOCAL_DIR"
    log "--- rsync: $CLINIC_ID ---"
    rsync_from_host "$REMOTE_HOST1" "$CLINIC_ID" "$LOCAL_DIR" "${REMOTE_PATHS1[@]}"
    rsync_from_host "$REMOTE_HOST2" "$CLINIC_ID" "$LOCAL_DIR" "${REMOTE_PATHS2[@]}"
    local count
    count=$(find "$LOCAL_DIR" -type f | wc -l)
    log "  Файлів після rsync: $count"
}

import_clinic() {
    local CLINIC_ID="$1"
    log "--- import: $CLINIC_ID ---"
    docker exec "$MAYAN_CONTAINER" \
        nice -n 19 "$MAYAN_PYTHON" "$MAYAN_SCRIPT" "$CLINIC_ID" \
        2>&1 | tee -a "$LOG_FILE"
}

get_all_clinics() {
    log "Шукаємо всі клініки на remote серверах..."
    local CLINICS1
    CLINICS1=$(ssh -o ConnectTimeout=5 "$REMOTE_HOST1" "
        find /var/snap -mindepth 2 -maxdepth 3 -type d 2>/dev/null \
        | grep -oP '(?<=/public/)\d{4}' | sort -u
    " 2>/dev/null)

    local CLINICS2
    CLINICS2=$(ssh -o ConnectTimeout=5 "$REMOTE_HOST2" "
        find /public -mindepth 1 -maxdepth 1 -type d 2>/dev/null \
        | grep -oP '\d{4}$' | sort -u
    " 2>/dev/null)

    echo -e "${CLINICS1}\n${CLINICS2}" | sort -u | grep -v '^$'
}

process_clinic() {
    local CLINIC_ID="$1"
    log ""
    log "════════════════════════════════════════"
    log "  Клініка: $CLINIC_ID"
    log "════════════════════════════════════════"

    local start_time=$SECONDS

    $DO_RSYNC  && rsync_clinic  "$CLINIC_ID"
    $DO_IMPORT && import_clinic "$CLINIC_ID"

    local elapsed=$((SECONDS - start_time))
    log "  Час: ${elapsed}с"
}

# ─── Main ────────────────────────────────────────────────────────────────────

log "═══════════════════════════════════════════════"
log "  sync_and_import.sh"
log "  rsync:  $DO_RSYNC"
log "  import: $DO_IMPORT"
log "  Лог:    $LOG_FILE"
log "═══════════════════════════════════════════════"

if $DO_ALL; then
    mapfile -t CLINICS < <(get_all_clinics)
    if [ ${#CLINICS[@]} -eq 0 ]; then
        log "Клінік не знайдено"
        exit 1
    fi
    log "Знайдено клінік: ${#CLINICS[@]}"
fi

if [ ${#CLINICS[@]} -eq 0 ]; then
    echo "Використання:"
    echo "  $0 0120 0121 0122"
    echo "  $0 --all"
    echo "  $0 --no-rsync 0120 0121"
    echo "  $0 --no-import 0120 0121"
    exit 1
fi

log "Список клінік: ${CLINICS[*]}"
log "Всього: ${#CLINICS[@]}"

TOTAL_START=$SECONDS
OK=0
FAIL=0

for CLINIC_ID in "${CLINICS[@]}"; do
    if process_clinic "$CLINIC_ID"; then
        OK=$((OK + 1))
    else
        FAIL=$((FAIL + 1))
        log "  [FAIL] $CLINIC_ID"
    fi
done

TOTAL_TIME=$((SECONDS - TOTAL_START))
log ""
log "═══════════════════════════════════════════════"
log "  ЗАВЕРШЕНО"
log "  Оброблено: ${#CLINICS[@]}"
log "  Час:       ${TOTAL_TIME}с"
log "  Лог:       $LOG_FILE"
log "═══════════════════════════════════════════════"
