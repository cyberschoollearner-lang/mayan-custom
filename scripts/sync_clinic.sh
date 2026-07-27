#!/bin/bash
# sync_clinic.sh — копіює файли клінік з двох remote серверів в /mnt/cephfs/clinic/
#
# Використання:
#   ./sync_clinic.sh          — всі клініки з обох хостів
#   ./sync_clinic.sh 0101     — одна клініка з обох хостів
#   ./sync_clinic.sh 0101 0102 0103  — кілька клінік

LOCAL_BASE="/mnt/cephfs/clinic"

# ─── Хост 1: yyy.yyy.yyy.5 ───────────────────────────────────────────────────
REMOTE_HOST1="yyy.yyy.yyy.5"
REMOTE_PATHS1=(
    "/var/snap/public"
    "/var/snap/xxx.xxx.xxx.55/new/public"
    "/var/snap/xxx.xxx.xxx.55/public"
)

# ─── Хост 2: xxx.xxx.xxx.55 ──────────────────────────────────────────────────
REMOTE_HOST2="xxx.xxx.xxx.55"
REMOTE_PATHS2=(
    "/public"
)

RSYNC_OPTS=(
    --archive
    --times
    --recursive
    --ignore-existing  # не перезаписувати дублі
    --no-perms
    --omit-dir-times
    --progress
    --human-readable
    --stats
)

sync_from_host() {
    local HOST="$1"
    local CLINIC_ID="$2"
    local LOCAL_DIR="$LOCAL_BASE/$CLINIC_ID"
    shift 2
    local PATHS=("$@")

    for REMOTE_DIR in "${PATHS[@]}"; do
        FULL_REMOTE="${REMOTE_DIR}/${CLINIC_ID}"

        if ssh "$HOST" "[ -d '$FULL_REMOTE' ]"; then
            echo "--- ${HOST}:${FULL_REMOTE} → ${LOCAL_DIR} ---"
            rsync "${RSYNC_OPTS[@]}" \
                "${HOST}:${FULL_REMOTE}/" \
                "${LOCAL_DIR}/"
        else
            echo "--- Пропускаємо ${HOST}:${FULL_REMOTE} (не існує) ---"
        fi
    done
}

sync_clinic() {
    local CLINIC_ID="$1"
    local LOCAL_DIR="$LOCAL_BASE/$CLINIC_ID"
    mkdir -p "$LOCAL_DIR"

    echo ""
    echo "════════════════════════════════════"
    echo "  Клініка: $CLINIC_ID"
    echo "════════════════════════════════════"

    sync_from_host "$REMOTE_HOST1" "$CLINIC_ID" "${REMOTE_PATHS1[@]}"
    sync_from_host "$REMOTE_HOST2" "$CLINIC_ID" "${REMOTE_PATHS2[@]}"

    echo "✔ $CLINIC_ID готово | файлів: $(find "$LOCAL_DIR" -type f | wc -l)"
}

get_all_clinics() {
    echo "Шукаємо всі клініки на обох хостах..."

    CLINICS1=$(ssh "$REMOTE_HOST1" "
        find /var/snap -mindepth 2 -maxdepth 3 -type d \
        | grep -oP '(?<=/public/)\d{4}' | sort -u
    ")

    CLINICS2=$(ssh "$REMOTE_HOST2" "
        find /public -mindepth 1 -maxdepth 1 -type d \
        | grep -oP '\d{4}$' | sort -u
    ")

    echo -e "${CLINICS1}\n${CLINICS2}" | sort -u | grep -v '^$'
}

# ─── Main ────────────────────────────────────────────────────────────────────

if [ $# -gt 0 ]; then
    for CLINIC in "$@"; do
        sync_clinic "$CLINIC"
    done
else
    CLINICS=$(get_all_clinics)

    if [ -z "$CLINICS" ]; then
        echo "Клінік не знайдено"
        exit 1
    fi

    echo "Знайдено: $(echo "$CLINICS" | wc -l) клінік"
    echo "$CLINICS"
    echo ""

    for CLINIC in $CLINICS; do
        sync_clinic "$CLINIC"
    done
fi

echo ""
echo "=== СИНХРОНІЗАЦІЯ ЗАВЕРШЕНА ==="

bash ./archive_file.sh 
