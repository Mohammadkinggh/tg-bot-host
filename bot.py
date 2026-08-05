#!/usr/bin/env python3
"""
tg-bot-host — Free 24/7 Telegram bot via GitHub Actions cron.

Architecture:
  - GitHub Actions runs this script on a schedule (every 5h).
  - Each run long-polls Telegram for ~4.75h, then exits cleanly.
  - The next scheduled run picks up where the last one left off.
  - The update offset is persisted to a GitHub Gist so no message is
    ever re-processed or lost between runs.

Swap in your bot logic in `handle_update()`. The template echoes back.
"""
import json
import os
import sys
import time
import urllib.request
import urllib.error

TOKEN = os.environ.get("TG_BOT_TOKEN", "")
GIST_ID = os.environ.get("GIST_ID", "")
GH_TOKEN = os.environ.get("GH_TOKEN", "")
RUN_MINUTES = int(os.environ.get("RUN_MINUTES", "285"))
API = f"https://api.telegram.org/bot{TOKEN}"
GIST_URL = f"https://api.github.com/gists/{GIST_ID}"

OFFSET = 0


# ---------------------------------------------------------------- state
def load_offset():
    """Read the last processed update_id from the gist."""
    global OFFSET
    if not GIST_ID or not GH_TOKEN:
        return
    try:
        req = urllib.request.Request(GIST_URL, headers={"Authorization": f"token {GH_TOKEN}"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        raw = data["files"]["state.json"]["content"]
        OFFSET = json.loads(raw).get("offset", 0)
        print(f"[state] loaded offset={OFFSET}", flush=True)
    except Exception as e:
        print(f"[state] load failed ({e}) — continuing with offset={OFFSET}", flush=True)


def save_offset():
    """Persist the current offset back to the gist."""
    global OFFSET
    if not GIST_ID or not GH_TOKEN:
        return
    try:
        body = json.dumps({
            "description": "tg-bot-host state",
            "files": {"state.json": {"content": json.dumps({"offset": OFFSET})}},
        }).encode()
        req = urllib.request.Request(
            GIST_URL, data=body, method="PATCH",
            headers={"Authorization": f"token {GH_TOKEN}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            r.read()
        print(f"[state] saved offset={OFFSET}", flush=True)
    except Exception as e:
        print(f"[state] save failed ({e})", flush=True)


# ---------------------------------------------------------------- telegram
def api_call(method, payload=None, timeout=30):
    req = urllib.request.Request(
        f"{API}/{method}",
        data=json.dumps(payload or {}).encode() if payload is not None else None,
        headers={"Content-Type": "application/json"} if payload is not None else {},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def get_updates(offset):
    return api_call("getUpdates", {"offset": offset, "timeout": 25, "allowed_updates": ["message"]})


def send_message(chat_id, text, reply_to=None):
    payload = {"chat_id": chat_id, "text": text}
    if reply_to:
        payload["reply_to_message_id"] = reply_to
    try:
        api_call("sendMessage", payload)
    except Exception as e:
        print(f"[send] failed to {chat_id}: {e}", flush=True)


# ---------------------------------------------------------------- bot logic
def handle_update(upd):
    """★ YOUR BOT LOGIC GOES HERE ★  (template: echo bot)"""
    msg = upd.get("message", {})
    chat_id = msg.get("chat", {}).get("id")
    text = msg.get("text", "").strip()
    if not chat_id or not text:
        return
    print(f"[msg] from {msg.get('from', {}).get('first_name', '?')} ({chat_id}): {text[:60]}", flush=True)
    # --- replace below with your real bot behavior ---
    if text.lower() in ("/start", "hi", "hello", "سلام", "salam"):
        send_message(chat_id, "Bot is alive on free GitHub Actions hosting! 🟢", reply_to=msg.get("message_id"))
    elif text.lower() == "/status":
        send_message(chat_id, f"Running via GitHub Actions cron.\nLast check-in: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}", reply_to=msg.get("message_id"))
    else:
        send_message(chat_id, f"Echo: {text}", reply_to=msg.get("message_id"))


# ---------------------------------------------------------------- main loop
def main():
    global OFFSET
    if not TOKEN:
        print("[fatal] TG_BOT_TOKEN not set — add it as a repo secret.", flush=True)
        sys.exit(1)

    load_offset()
    deadline = time.time() + RUN_MINUTES * 60
    print(f"[boot] polling until {time.strftime('%H:%M:%S UTC', time.gmtime(deadline))} "
          f"(~{RUN_MINUTES} min run)", flush=True)

    while time.time() < deadline:
        try:
            data = get_updates(OFFSET)
            for upd in data.get("result", []):
                OFFSET = max(OFFSET, upd["update_id"] + 1)
                handle_update(upd)
            if data.get("result"):
                save_offset()
        except urllib.error.HTTPError as e:
            print(f"[poll] HTTP {e.code}: {e.read().decode()[:120]}", flush=True)
            time.sleep(10)
        except Exception as e:
            print(f"[poll] error: {e}", flush=True)
            time.sleep(5)

    save_offset()
    print("[bye] run complete, handoff to next scheduled run.", flush=True)


if __name__ == "__main__":
    main()
