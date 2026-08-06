#!/usr/bin/env bash
# GemBot local 24/7 launcher — survives container restarts via cron @reboot / watchdog
# Log: /tmp/gembot_local.log
set -u

BOT_DIR="/data/workspace/tg_bot_host"
LOG="/tmp/gembot_local.log"

# Kill any stale gembot instance
for pid in $(ls /proc | grep -E '^[0-9]+$'); do
  if [ -r "/proc/$pid/cmdline" ]; then
    if grep -q 'gembot.py' "/proc/$pid/cmdline" 2>/dev/null; then
      kill -9 "$pid" 2>/dev/null
    fi
  fi
done

sleep 2

# Load env
if [ -f /tmp/gembot_env.sh ]; then
  source /tmp/gembot_env.sh
fi

export HOME="/data"
cd "$BOT_DIR"
exec python3 gembot.py >> "$LOG" 2>&1
