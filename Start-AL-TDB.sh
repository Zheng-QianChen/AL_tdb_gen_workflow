#!/bin/sh
set -eu
root=$(CDPATH= cd -P "$(dirname "$0")" && pwd)
if [ -n "${AL_TDB_PYTHON:-}" ]; then
    exec "$AL_TDB_PYTHON" "$root/altdb/launcher.py" "$@"
fi
for python in python3.12 python3.11 python3; do
    if command -v "$python" >/dev/null 2>&1 && "$python" -c 'import sys; sys.exit(sys.version_info[:2] not in ((3,11),(3,12)))'; then
        exec "$python" "$root/altdb/launcher.py" "$@"
    fi
done
echo 'Install Python 3.11 or 3.12 with venv, or set AL_TDB_PYTHON to its full path.' >&2
exit 2
