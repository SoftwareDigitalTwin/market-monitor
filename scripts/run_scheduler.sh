#!/usr/bin/env bash
set -euo pipefail

RUN_AT="${DTC_DAILY_RUN_AT:-03:15}"
RUN_ON_STARTUP="${DTC_RUN_ON_STARTUP:-false}"
LAST_RUN_DATE=""

if [ "$RUN_ON_STARTUP" = "true" ]; then
  python main.py pipeline
  LAST_RUN_DATE="$(date +%F)"
fi

while true; do
  NOW_TIME="$(date +%H:%M)"
  TODAY="$(date +%F)"

  if [ "$NOW_TIME" = "$RUN_AT" ] && [ "$LAST_RUN_DATE" != "$TODAY" ]; then
    python main.py pipeline
    LAST_RUN_DATE="$TODAY"
  fi

  sleep 60
done
