#!/usr/bin/env python3
"""GemBot watchdog: ensure gembot.py is running locally; restart if dead.
Quiet when healthy (empty stdout = silent cron)."""
import os
import sys
import subprocess
import time

BOT_DIR = "/data/workspace/tg_bot_host"
LOG = "/tmp/gembot_local.log"

def gembot_pids():
    pids = []
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                cmd = f.read().decode("utf-8", "ignore").replace("\x00", " ")
            if "gembot.py" in cmd:
                pids.append(int(pid))
        except (IOError, OSError):
            continue
    return pids

pids = gembot_pids()
if pids:
    sys.exit(0)  # healthy — silent

# Dead: restart
print(f"[watchdog {time.strftime('%H:%M:%S')}] gembot.py NOT running — restarting...")
try:
    env = dict(os.environ)
    env_file = "/tmp/gembot_env.sh"
    if os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line.startswith("export "):
                    kv = line[len("export "):]
                    key, _, val = kv.partition("=")
                    val = val.strip('"').strip("'")
                    if key and val:
                        env[key] = val
    env["HOME"] = "/data"
    proc = subprocess.Popen(
        ["python3", "gembot.py"],
        cwd=BOT_DIR,
        env=env,
        stdout=open(LOG, "a"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    print(f"[watchdog] restarted with PID {proc.pid}")
except Exception as e:
    print(f"[watchdog] restart FAILED: {e}")
