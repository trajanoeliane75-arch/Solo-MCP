#!/bin/sh
# May be opened from a file manager or run once after cloning.
set -eu
SOLO_SOURCE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec /usr/bin/python3 "$SOLO_SOURCE_DIR/launch.py" "$@"
