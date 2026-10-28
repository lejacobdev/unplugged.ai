#!/bin/bash
# Restarts run_all.sh if it dies before finishing (base training resumes from its last checkpoint).
cd "$(dirname "$0")"
tries=0
while [ ! -f ALL_DONE ] && [ $tries -lt 4 ]; do
  sleep 300
  if [ ! -f ALL_DONE ] && ! pgrep -f "run_all.sh" > /dev/null; then
    tries=$((tries + 1))
    echo "[$(date '+%H:%M:%S')] watchdog: run_all.sh not running, restart #$tries" >> logs/run_all.log
    BASE_MIN=${BASE_MIN:-240} LORA_MIN=${LORA_MIN:-45} nohup caffeinate -dimsu ./run_all.sh >> logs/nohup.log 2>&1 &
  fi
done
