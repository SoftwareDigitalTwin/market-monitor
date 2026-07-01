#!/usr/bin/env bash
set -euo pipefail

RUN_AT="${DTC_DAILY_RUN_AT:-03:15}"
RUN_ON_STARTUP="${DTC_RUN_ON_STARTUP:-false}"
LAST_RUN_DATE=""

echo "Scheduler iniciado. TZ=${TZ:-system} RUN_AT=${RUN_AT} NOW=$(date '+%F %T %Z')"

if [ "$RUN_ON_STARTUP" = "true" ]; then
  echo "DTC_RUN_ON_STARTUP=true. Ejecutando pipeline inicial en $(date '+%F %T %Z')"
  python main.py pipeline
  LAST_RUN_DATE="$(date +%F)"
  echo "Pipeline inicial finalizado en $(date '+%F %T %Z')"
fi

while true; do
  NOW_TIME="$(date +%H:%M)"
  TODAY="$(date +%F)"

  if [ "$NOW_TIME" = "$RUN_AT" ] && [ "$LAST_RUN_DATE" != "$TODAY" ]; then
    echo "Ejecutando pipeline programado para ${TODAY} ${NOW_TIME} en $(date '+%F %T %Z')"
    python main.py pipeline
    LAST_RUN_DATE="$TODAY"
    echo "Pipeline programado finalizado para ${TODAY} en $(date '+%F %T %Z')"
  fi

  sleep 60
done
