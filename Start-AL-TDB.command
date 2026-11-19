#!/bin/sh
set -eu
root=$(CDPATH= cd -P "$(dirname "$0")" && pwd)
exec /bin/sh "$root/Start-AL-TDB.sh" "$@"
