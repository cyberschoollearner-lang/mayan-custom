#!/bin/bash
# sync_clients.sh — синхронізація клієнтів 1000-9999 (→ 01000-09999 в Mayan)
#
# Логіка (checksum-first):
#   1. Будуємо карту (checksum, шлях) файлів клієнта на remote хостах через
#      ssh + sha256sum — БЕЗ завантаження, тільки хеш обчислюється на remote.
#   2. Звіряємо карту з базою Mayan. Якщо checksum вже є — лінкуємо документ
#      у кабінет клієнта миттєво, без rsync (див. приклад: клієнт бачить файл,
#      що вже завантажений клінікою, без дублювання на диску).
#   3. rsync ТІЛЬКИ файлів, яких реально бракує.
#   4. Сортування по роках + import_clinic.py для щойно завантажених файлів.
#
# Використання:
#   ./sync_clients.sh                    # cron: MySQL + checksum-map + rsync + імпорт
#   ./sync_clients.sh --no-rsync         # MySQL + імпорт без rsync (тільки локальне)
#   ./sync_clients.sh --manual 1001      # ручний для конкретного клієнта
#   ./sync_clients.sh --manual 1001 --no-rsync
#   ./sync_clients.sh --import-only      # тільки імпорт існуючих локальних файлів

# ─── Конфіг ──────────────────────────────────────────────────────────────────
REMOTE_HOST1="yyy.yyy.yyy.5"
REMOTE_PATHS1=(
    "/var/snap/public"
    "/var/snap/xxx.xxx.xxx.55/new/public"
    "/var/snap/xxx.xxx.xxx.55/public"
)

# Хост 2 і шляхи
REMOTE_HOST2="xxx.xxx.xxx.60"
REMOTE_PATHS2=(
    "/public"
    "/backup/public"
)
REMOTE_HOST3="xxx.xxx.xxx.61"
REMOTE_PATHS3=(
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
    # >&2 — критично: не даємо log() потрапляти в stdout функцій, чиє
    # значення захоплюється через $(...) (build_client_map тощо), інакше
    # весь текст логу підмішується в змінну і bash намагається виконати
    # його як команду.
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE" >&2
}

to_mayan_id() {
    printf '%05d' "$1"
}

# Будує карту checksum для клієнта з одного хоста (всі REMOTE_PATHS для нього).
# Хеш рахується НА remote хості (sha256sum) — по мережі йдуть тільки хеші+шляхи.
build_map_from_host() {
    local HOST="$1"
    local CLIENT_ID="$2"
    shift 2
    local PATHS=("$@")

    local HASH_CMD
    HASH_CMD=$(get_remote_hash_cmd "$HOST")

    if [ -z "$HASH_CMD" ]; then
        log "  [MAP ERROR] ${HOST}: не знайдено ні sha256sum, ні sha256 — пропускаю хост"
        return
    fi

    for RPATH in "${PATHS[@]}"; do
        REMOTE_DIR="${RPATH}/${CLIENT_ID}"

        if ! ssh -o ConnectTimeout=5 -o BatchMode=yes "$HOST" \
             "sh -c '[ -d \"$REMOTE_DIR\" ]'" 2>/dev/null; then
            continue
        fi

        local real_count
        real_count=$(ssh -o ConnectTimeout=5 "$HOST" \
            "sh -c \"find '$REMOTE_DIR' -type f 2>/dev/null | wc -l\"")
        log "  [MAP] ${HOST}:${REMOTE_DIR} — файлів на хості: $real_count (хеш: $HASH_CMD)"

        if [ "$HASH_CMD" = "sha256sum" ]; then
            ssh -o ConnectTimeout=5 "$HOST" \
                "sh -c \"find '$REMOTE_DIR' -type f -exec sha256sum {} +\"" 2>/dev/null
        else
            ssh -o ConnectTimeout=5 "$HOST" \
                "sh -c \"find '$REMOTE_DIR' -type f -exec sha256 {} +\"" 2>/dev/null | \
                sed -E 's/^SHA256 \((.*)\) = ([0-9a-f]+)$/\2  \1/'
        fi | \
        while IFS= read -r out_line; do
            checksum="${out_line%%  *}"
            remote_path="${out_line#*  }"
            rel_path="${remote_path#$REMOTE_DIR/}"
            printf '%s\t%s\t%s\t%s\t%s\n' \
                "$checksum" "$HOST" "$REMOTE_DIR" "$remote_path" "$rel_path"
        done
    done
}

# Визначає доступну команду sha256 на remote хості (GNU sha256sum або BSD sha256)
# і повертає нормалізовану команду, що завжди видає GNU-подібний формат
# "хеш  шлях" через sed, незалежно від того, яка утиліта реально є на хості.
# Визначає доступну команду sha256 на remote хості. Примусово запускаємо
# через `sh -c` — на частині хостів дефолтний shell csh/tcsh, який не
# підтримує bash-синтаксис редіректів (2>&1), звідси "Ambiguous output
# redirect" при прямому виконанні через ssh без обгортки.
get_remote_hash_cmd() {
    local HOST="$1"
    if ssh -o ConnectTimeout=5 "$HOST" "sh -c 'command -v sha256sum'" >/dev/null 2>&1; then
        echo "sha256sum"
    elif ssh -o ConnectTimeout=5 "$HOST" "sh -c 'command -v sha256'" >/dev/null 2>&1; then
        echo "sha256_bsd"
    else
        echo ""
    fi
}

# Повна карта клієнта з обох хостів. echo лише шлях до файлу — уся
# інша інформація (log) іде через stderr, тому $(...) захоплює чистий шлях.
build_client_map() {
    local CLIENT_ID="$1"
    local MAYAN_ID="$2"
    local MAP_FILE="$MAP_DIR/${MAYAN_ID}.map"

    log "  [MAP] Будуємо карту checksum для $CLIENT_ID..."
    {
        build_map_from_host "$REMOTE_HOST1" "$CLIENT_ID" "${REMOTE_PATHS1[@]}"
        build_map_from_host "$REMOTE_HOST2" "$CLIENT_ID" "${REMOTE_PATHS2[@]}"
        build_map_from_host "$REMOTE_HOST3" "$CLIENT_ID" "${REMOTE_PATHS3[@]}"
    } > "$MAP_FILE"

    local total
    total=$(wc -l < "$MAP_FILE")
    log "  [MAP] Файлів у карті: $total"
    echo "$MAP_FILE"
}

# Звіряємо карту з Mayan, лінкуємо існуючі, отримуємо список на завантаження.
# echo — тільки шлях до DOWNLOAD_LIST. Виставляє глобальні _LINK_SUMMARY_*.
link_and_get_download_list() {
    local MAYAN_ID="$1"
    local MAP_FILE="$2"
    local DOWNLOAD_LIST="$MAP_DIR/${MAYAN_ID}.need_download"
    local LINK_LOG="$MAP_DIR/${MAYAN_ID}.link.log"

    log "  [LINK] Звіряємо checksum з Mayan..."
    docker exec -i "$MAYAN_CONTAINER" "$MAYAN_PYTHON" "$MAYAN_LINK" "$MAYAN_ID" \
        < "$MAP_FILE" > "$DOWNLOAD_LIST" 2> "$LINK_LOG"

    while IFS= read -r line; do log "  $line"; done < "$LINK_LOG"

    local summary_line
    summary_line=$(grep '^\[SUMMARY\]' "$LINK_LOG" | tail -1)
    _LINK_SUMMARY_LINKED=$(echo "$summary_line" | grep -oP 'linked=\K[0-9]+' || echo 0)
    _LINK_SUMMARY_NEED=$(echo "$summary_line" | grep -oP 'need_download=\K[0-9]+' || echo 0)
    _LINK_SUMMARY_ERRORS=$(echo "$summary_line" | grep -oP 'errors=\K[0-9]+' || echo 0)
    # ВАЖЛИВО: жодного echo шляху в кінці — функцію викликаємо напряму,
    # не через $(...), інакше всі присвоєння вище знову загубляться.
}

# rsync тільки файлів зі списку need_download. Виставляє _DOWNLOAD_OK/_DOWNLOAD_FAIL.
download_needed_files() {
    local MAYAN_ID="$1"
    local DOWNLOAD_LIST="$2"
    local LOCAL_DIR="$LOCAL_BASE/$MAYAN_ID"
    mkdir -p "$LOCAL_DIR"

    _DOWNLOAD_OK=0
    _DOWNLOAD_FAIL=0

    if [ ! -s "$DOWNLOAD_LIST" ]; then
        log "  [RSYNC] Нема файлів для завантаження"
        return
    fi

    while IFS=$'\t' read -r HOST RPATH RELPATH; do
        DEST="$LOCAL_DIR/$RELPATH"
        mkdir -p "$(dirname "$DEST")"
        if rsync -a --no-perms --omit-dir-times -e "ssh -o ConnectTimeout=5" \
            "${HOST}:${RPATH}" "$DEST" 2>&1 | tee -a "$LOG_FILE"; then
            _DOWNLOAD_OK=$((_DOWNLOAD_OK + 1))
        else
            _DOWNLOAD_FAIL=$((_DOWNLOAD_FAIL + 1))
            log "  [RSYNC ERROR] $HOST:$RPATH"
        fi
    done < "$DOWNLOAD_LIST"

    log "  [RSYNC] Завантажено: $_DOWNLOAD_OK | Помилок: $_DOWNLOAD_FAIL"
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

# Імпорт в Mayan. Виставляє глобальні _IMPORT_OK/_IMPORT_LINK/_IMPORT_SKIP/_IMPORT_ERROR
import_to_mayan() {
    local MAYAN_ID="$1"
    log "  [IMPORT] $MAYAN_ID → Mayan"

    local IMPORT_LOG
    IMPORT_LOG=$(docker exec "$MAYAN_CONTAINER" \
        "$MAYAN_PYTHON" "$MAYAN_SCRIPT" "$MAYAN_ID" 2>&1 | tee -a "$LOG_FILE")

    local stats_line
    stats_line=$(echo "$IMPORT_LOG" | grep -oP 'OK: \d+ \| LINK: \d+ \| SKIP: \d+ \| ERROR: \d+' | tail -1)

    #_IMPORT_OK=$(echo "$stats_line"    | grep -oP 'OK: \K[0-9]+'    || echo 0)
    _IMPORT_OK=$(echo "$stats_line"    | sed -n 's/.*OK: \([0-9]*\).*/\1/p')
    #_IMPORT_LINK=$(echo "$stats_line"  | grep -oP 'LINK: \K[0-9]+'  || echo 0)
    _IMPORT_LINK=$(echo "$stats_line"  | sed -n 's/.*LINK: \([0-9]*\).*/\1/p')
    #_IMPORT_SKIP=$(echo "$stats_line"  | grep -oP 'SKIP: \K[0-9]+'  || echo 0)
    _IMPORT_SKIP=$(echo "$stats_line"  | sed -n 's/.*SKIP: \([0-9]*\).*/\1/p')
    #_IMPORT_ERROR=$(echo "$stats_line" | grep -oP 'ERROR: \K[0-9]+' || echo 0)
    _IMPORT_ERROR=$(echo "$stats_line" | sed -n 's/.*ERROR: \([0-9]*\).*/\1/p')
}

# Повна обробка одного клієнта. MAP_TOTAL і _* — НЕ local, щоб зовнішній
# цикл (cron-режим) міг підсумувати їх у загальну статистику.
process_client() {
    local CLIENT_ID="$1"
    local MAYAN_ID
    MAYAN_ID=$(to_mayan_id "$CLIENT_ID")

    log "=== Клієнт: $CLIENT_ID → $MAYAN_ID ==="

    MAP_TOTAL=0
    _LINK_SUMMARY_LINKED=0; _LINK_SUMMARY_NEED=0; _LINK_SUMMARY_ERRORS=0
    _DOWNLOAD_OK=0; _DOWNLOAD_FAIL=0
    _IMPORT_OK=0; _IMPORT_LINK=0; _IMPORT_SKIP=0; _IMPORT_ERROR=0

    if $DO_RSYNC; then
        local MAP_FILE
        MAP_FILE=$(build_client_map "$CLIENT_ID" "$MAYAN_ID")
        MAP_TOTAL=$(wc -l < "$MAP_FILE")

        local DOWNLOAD_LIST="$MAP_DIR/${MAYAN_ID}.need_download"
        link_and_get_download_list "$MAYAN_ID" "$MAP_FILE"
        download_needed_files "$MAYAN_ID" "$DOWNLOAD_LIST"
    fi

    sort_by_year "$LOCAL_BASE/$MAYAN_ID"
    import_to_mayan "$MAYAN_ID"

    log "  ────────────────────────────────────────"
    log "  ПІДСУМОК $CLIENT_ID → $MAYAN_ID:"
    log "    Карта:        $MAP_TOTAL файлів (усі хости разом)"
    log "    Лінк (dup):   $_LINK_SUMMARY_LINKED | помилок лінку: $_LINK_SUMMARY_ERRORS"
    log "    Завантажено:  $_DOWNLOAD_OK | помилок rsync: $_DOWNLOAD_FAIL"
    log "    Імпорт:       OK=$_IMPORT_OK LINK=$_IMPORT_LINK SKIP=$_IMPORT_SKIP ERROR=$_IMPORT_ERROR"
    log "  ────────────────────────────────────────"
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

TOTAL_MAP=0
TOTAL_LINKED=0
TOTAL_DOWNLOADED=0
TOTAL_IMPORT_OK=0
TOTAL_IMPORT_ERROR=0
TOTAL_CLIENTS=0

while IFS=: read -r _ CLIENT_ID MAYAN_ID; do
    [ -n "$CLIENT_ID" ] || continue
    process_client "$CLIENT_ID"

    TOTAL_CLIENTS=$((TOTAL_CLIENTS + 1))
    TOTAL_MAP=$((TOTAL_MAP + MAP_TOTAL))
    TOTAL_LINKED=$((TOTAL_LINKED + _LINK_SUMMARY_LINKED))
    TOTAL_DOWNLOADED=$((TOTAL_DOWNLOADED + _DOWNLOAD_OK))
    TOTAL_IMPORT_OK=$((TOTAL_IMPORT_OK + _IMPORT_OK))
    TOTAL_IMPORT_ERROR=$((TOTAL_IMPORT_ERROR + _IMPORT_ERROR))
done <<< "$NEW_CLIENTS"

log ""
log "═══════════════════════════════════════════════"
log "  ЗАГАЛЬНИЙ ПІДСУМОК"
log "  Клієнтів оброблено: $TOTAL_CLIENTS"
log "  Файлів у картах:    $TOTAL_MAP"
log "  Лінковано (dup):    $TOTAL_LINKED"
log "  Завантажено:        $TOTAL_DOWNLOADED"
log "  Імпорт OK:          $TOTAL_IMPORT_OK"
log "  Імпорт ERROR:       $TOTAL_IMPORT_ERROR"
log "═══════════════════════════════════════════════"
log "=== СИНХРОНІЗАЦІЯ ЗАВЕРШЕНА ==="
