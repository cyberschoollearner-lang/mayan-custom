#!/bin/sh

WORKDIR="/mnt/cephfs/clinic"
CURRENT_YEAR=$(date +%Y)

cd "$WORKDIR" || exit 1

find . -mindepth 2 -maxdepth 2 -type f | while read -r FILE; do
    FILE_YEAR=$(date -r "$FILE" +%Y)

    # Файли поточного року не чіпаємо
    [ "$FILE_YEAR" = "$CURRENT_YEAR" ] && continue

    DIRNAME=$(dirname "$FILE")
    TARGET_DIR="${DIRNAME}/${FILE_YEAR}"

    mkdir -p "$TARGET_DIR"

    echo "mv '$FILE' -> '$TARGET_DIR/'"
    mv "$FILE" "$TARGET_DIR/"
done
