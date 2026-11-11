#!/bin/sh
# Запуск приложения из любого текущего каталога.
app_directory=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd) || exit 1
exec /bin/sh "$app_directory/start.sh" "$@"
