#!/usr/bin/env bash
set -euo pipefail

python -m dtc.db.wait_for_db

if [ "${DTC_INIT_DB:-true}" = "true" ]; then
  python main.py init
fi

exec "$@"
