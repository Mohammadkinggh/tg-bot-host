#!/usr/bin/env python3
"""Create PRIVATE gist from the original bot's memory files. Prints gist ID only."""
import json
import re
import sqlite3
import urllib.request

# GH token from state.db
token = None
conn = sqlite3.connect('/data/.hermes/state.db')
for r in conn.execute("SELECT content FROM messages WHERE content LIKE '%ghp_%' LIMIT 20"):
    m = re.findall(r'ghp_[A-Za-z0-9]{20,}', r[0])
    if m:
        token = m[0]
        break
if not token:
    raise SystemExit("no token")

hist = open('/data/bots/gemai_context_history.json', encoding='utf-8').read()
sett = open('/data/bots/gemai_settings.json', encoding='utf-8').read()

payload = {
    "description": "GemBot memory (private state: history + settings)",
    "public": False,
    "files": {
        "gemai_context_history.json": {"content": hist},
        "gemai_settings.json": {"content": sett},
    },
}
req = urllib.request.Request(
    "https://api.github.com/gists",
    data=json.dumps(payload).encode(),
    headers={
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "User-Agent": "gembot-migrate",
    },
    method="POST",
)
with urllib.request.urlopen(req, timeout=60) as resp:
    d = json.loads(resp.read().decode())
    print("GIST_ID:", d["id"])
    print("PUBLIC:", d["public"])
    print("URL:", d["html_url"])
    for f in d["files"]:
        print("  file:", f, d["files"][f]["size"], "bytes")
