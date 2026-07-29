#!/bin/bash
# sync_clients.sh — синхронізація клієнтів 1000-9999 (→ 01000-09999 в Mayan)
#
# Нова логіка (checksum-first):
#   1. Будуємо карту (checksum, шлях) файлів клієнта на remote хостах через
#      ssh + sha256sum — БЕЗ завантаження, тільки хеш обчислюється на remote.
#   2. Звіряємо карту з базою Mayan. Якщо checksum вже є — лінкуємо документ
#      у кабінет клієнта миттєво, без rsync.
#   3. rsync --files-from ТІЛЬКИ файлів, яких реально бракує.
#   4. Сортування по роках + import_clinic.py для щойно завантажених файлів.
#
# Використання:
#   ./sync_clients.sh                    # cron: MySQL + checksum-map + rsync + імпорт
#   ./sync_clients.sh --no-rsync         # MySQL + імпорт без rsync (тільки локальне)
#   ./sync_clients.sh --manual 1001      # ручний для конкретного клієнта
#   ./sync_clients.sh --manual 1001 --no-rsync
#   ./sync_clients.sh --import-only      # тільки імпорт існуючих локальних файлів

# ─── Конфіг ──────────────────────────────────────────────────────────────────
REMOTE_HOST1="xxx.xxx.xxx.5"
REMOTE_PATHS1=(
    "/var/snap/public"
    "/var/snap/yyy.yyy.yyy.yyy/new/public"
    "/var/snap/yyy.yyy.yyy.yyy/public"
)

REMOTE_HOST2="zzz.zzz.zzz.55"
REMOTE_PATHS2=(
    "/public"
    "/backup/public"
)

LOCAL_BASE="/mnt/cephfs/clinic"
MAP_DIR="/mnt/cephfs/mayan/logs/checksum_maps"
MAYAN_PYTHON="/opt/mayan-edms/bin/python"
MAYAN_SCRIPT="/var/lib/mayan/import_clinic.py"
MAYAN_SYNC="/var/lib/mayan/sync_users_from_mysql.py"
MAYAN_LINK="/var/lib/mayan/link_or_prepare_download.py"
MAYAN_CONTAINER="mayan-app-1"
LOG_FILE="/var/log/sync_clients.log"
CURRENT_YEAR=$(date +%Y)

DO_RSYNC=true
MANUAL_CLIENT=""
IMPORT_ONLY=false

mkdir -p "$MAP_DIR"

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

to_mayan_id() {
    printf '%05d' "$1"
}

# Будує карту checksum для клієнта з одного хоста (всі REMOTE_PATHS для нього).
# Хеш рахується НА remote хості (sha256sum), по мережі йде тільки текст —
# файли не завантажуються на цьому кроці.
build_map_from_host() {
    local HOST="$1"
    local CLIENT_ID="$2"
    shift 2
    local PATHS=("$@")

    for RPATH in "${PATHS[@]}"; do
        REMOTE_DIR="${RPATH}/${CLIENT_ID}"
        if ! ssh -o ConnectTimeout=5 -o BatchMode=yes "$HOST" "[ -d '$REMOTE_DIR' ]" 2>/dev/null; then
            continue
        fi
        log "  [MAP] ${HOST}:${REMOTE_DIR} (sha256 на remote)"
        # find + sha256sum виконуються НА remote хості — тільки хеші йдуть по мережі
        ssh -o ConnectTimeout=5 "$HOST" \
            "find '$REMOTE_DIR' -type f -exec sha256sum {} +" 2>/dev/null | \
        while IFS= read -r out_line; do
            checksum="${out_line%%  *}"
            remote_path="${out_line#*  }"
            # Відносний шлях (для збереження структури рік/файл при rsync)
            rel_path="${remote_path#$REMOTE_DIR/}"
            printf '%s\t%s\t%s\t%s\t%s\n' \
                "$checksum" "$HOST" "$REMOTE_DIR" "$remote_path" "$rel_path"
        done
    done
}

# Повна карта клієнта з обох хостів
build_client_map() {
    local CLIENT_ID="$1"
    local MAYAN_ID="$2"
    local MAP_FILE="$MAP_DIR/${MAYAN_ID}.map"

    log "  [MAP] Будуємо карту checksum для $CLIENT_ID..."
    {
        build_map_from_host "$REMOTE_HOST1" "$CLIENT_ID" "${REMOTE_PATHS1[@]}"
        build_map_from_host "$REMOTE_HOST2" "$CLIENT_ID" "${REMOTE_PATHS2[@]}"
    } > "$MAP_FILE"

    local total
    total=$(wc -l < "$MAP_FILE")
    log "  [MAP] Файлів у карті: $total"
    echo "$MAP_FILE"
}

# Звіряємо карту з Mayan, лінкуємо існуючі, отримуємо список на завантаження
link_and_get_download_list() {
    local MAYAN_ID="$1"
    local MAP_FILE="$2"
    local DOWNLOAD_LIST="$MAP_DIR/${MAYAN_ID}.need_download"

    log "  [LINK] Звіряємо checksum з Mayan..."
    docker exec -i "$MAYAN_CONTAINER" "$MAYAN_PYTHON" "$MAYAN_LINK" "$MAYAN_ID" \
        < "$MAP_FILE" > "$DOWNLOAD_LIST" 2> >(tee -a "$LOG_FILE" >&2)

    local need
    need=$(wc -l < "$DOWNLOAD_LIST")
    log "  [LINK] Потрібно завантажити: $need файлів"
    echo "$DOWNLOAD_LIST"
}

# rsync тільки файлів зі списку need_download, згрупованих по host+remote_root
download_needed_files() {
    local MAYAN_ID="$1"
    local DOWNLOAD_LIST="$2"
    local LOCAL_DIR="$LOCAL_BASE/$MAYAN_ID"
    mkdir -p "$LOCAL_DIR"

    [ -s "$DOWNLOAD_LIST" ] || { log "  [RSYNC] Нема файлів для завантаження"; return; }

    # Групуємо по host (remote_root вже частина relative_path через find,
    # тому rsync --files-from працює відносно host:/ і потребує relative
    # шляхів БЕЗ спільного кореня між різними REMOTE_PATHS — обробляємо
    # по одному host+root за раз)
    local TMP_FILES
    TMP_FILES=$(mktemp -d)

    # Витягуємо унікальні пари host+remote_path з download-листа і будуємо
    # files-from списки згруповані по host (remote_path вже абсолютний,
    # rsync --files-from підтримує абсолютні шляхи з host: напряму)
    awk -F'\t' '{print $1}' "$DOWNLOAD_LIST" | sort -u | while read -r HOST; do
        awk -F'\t' -v h="$HOST" '$1==h {print $2}' "$DOWNLOAD_LIST" \
            > "$TMP_FILES/${HOST//[^a-zA-Z0-9]/_}.list"
    done

    for FLIST in "$TMP_FILES"/*.list; do
        [ -s "$FLIST" ] || continue
        HOST=$(awk -F'\t' -v f="$FLIST" 'BEGIN{split(f,a,"/"); n=split(a[length(a)],b,"."); print b[1]}')
        # Простіше й надійніше — rsync кожен файл окремо з абсолютним шляхом
        while IFS= read -r RPATH; do
            local_target="$LOCAL_DIR/$(basename "$RPATH")"
            log "  [RSYNC] $RPATH"
        done < "$FLIST"
    done

    # Практичний і надійний варіант: rsync по одному файлу через список
    # host<TAB>remote_path<TAB>relative_path, зберігаючи структуру папок
    while IFS=$'\t' read -r HOST RPATH RELPATH; do
        DEST="$LOCAL_DIR/$RELPATH"
        mkdir -p "$(dirname "$DEST")"
        rsync -a --no-perms --omit-dir-times -e "ssh -o ConnectTimeout=5" \
            "${HOST}:${RPATH}" "$DEST" 2>&1 | tee -a "$LOG_FILE"
    done < "$DOWNLOAD_LIST"

    rm -rf "$TMP_FILES"
}

sort_by_year() {
    local LOCAL_DIR="$1"
    [ -d "$LOCAL_DIR" ] || return

    local moved=0
    for fpath in "$LOCAL_DIR"/*; do
        [ -f "$fpath" ] || continue
        fname=$(basename "$fpath")

        year=$(date -r "$fpath" +%Y 2>/dev/null)
        [ -z "$year" ] && continue
        [ "$year" = "$CURRENT_YEAR" ] && continue

        year_dir="$LOCAL_DIR/$year"
        mkdir -p "$year_dir"
        mv "$fpath" "$year_dir/$fname"
        log "  [SORT] $fname → $year/"
        moved=$((moved + 1))
    done

    [ $moved -gt 0 ] && log "  [SORT] Переміщено файлів: $moved"
}

import_to_mayan() {
    local MAYAN_ID="$1"
    log "  [IMPORT] $MAYAN_ID → Mayan"
    docker exec "$MAYAN_CONTAINER" \
        "$MAYAN_PYTHON" "$MAYAN_SCRIPT" "$MAYAN_ID" 2>&1 | tee -a "$LOG_FILE"
}

process_client() {
    local CLIENT_ID="$1"
    local MAYAN_ID
    MAYAN_ID=$(to_mayan_id "$CLIENT_ID")

    log "=== Клієнт: $CLIENT_ID → $MAYAN_ID ==="

    if $DO_RSYNC; then
        local MAP_FILE DOWNLOAD_LIST
        MAP_FILE=$(build_client_map "$CLIENT_ID" "$MAYAN_ID")
        DOWNLOAD_LIST=$(link_and_get_download_list "$MAYAN_ID" "$MAP_FILE")
        download_needed_files "$MAYAN_ID" "$DOWNLOAD_LIST"
    fi

    sort_by_year "$LOCAL_BASE/$MAYAN_ID"
    import_to_mayan "$MAYAN_ID"
}

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

while IFS=: read -r _ CLIENT_ID MAYAN_ID; do
    [ -n "$CLIENT_ID" ] || continue
    process_client "$CLIENT_ID"
done <<< "$NEW_CLIENTS"

log "=== СИНХРОНІЗАЦІЯ ЗАВЕРШЕНА ==="
