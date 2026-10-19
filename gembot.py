#!/usr/bin/env python3
"""
GemAI Savage Bot (@Customgembot) — GitHub Actions 24/7 Permanent Edition.
- Multi-API Failover across 5 Google Gemini API keys:
  Key 1 -> Key 2 -> Key 3 -> Key 4 -> Key 5
  If all fail -> informs the chat that all keys are fried.
- Default Model: gemini-3.8-flash
- Zero-gap self-chaining on GitHub Actions:
  Automatically dispatches the next shift before runner timeout.
- State (history + settings) encrypted via Fernet and committed back to repo.
- Admin: Mohammad (@Mokingh, ID: 6592796294) & Ali (@Alidabigpoly, ID: 8439794110).
"""
import asyncio
import logging
import os
import json
import time
import subprocess
import sys
import urllib.request
import urllib.parse
import urllib.error
import traceback
import datetime

import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    CallbackQueryHandler,
    CommandHandler,
    filters
)

# ---------------------------------------------------------------- config
TOKEN = os.environ.get("TG_BOT_TOKEN", "").strip()
MODEL_NAME = os.environ.get("MODEL_NAME", "gemini-3.8-flash").strip()

ADMIN_USER_IDS = [6592796294, 8439794110]
ADMIN_USERNAMES = ["mokingh", "alidabigpoly"]

def is_admin_user(user_id: int, username: str | None = None) -> bool:
    if user_id in ADMIN_USER_IDS:
        return True
    if username and username.lower() in ADMIN_USERNAMES:
        return True
    return False

# 5 Gemini API Keys Failover List
GEMINI_KEYS = [
    os.environ.get("GEMINI_KEY_1", "").strip(),
    os.environ.get("GEMINI_KEY_2", "").strip(),
    os.environ.get("GEMINI_KEY_3", "").strip(),
    os.environ.get("GEMINI_KEY_4", "").strip(),
    os.environ.get("GEMINI_KEY_5", "").strip(),
]
GEMINI_KEYS = [k for k in GEMINI_KEYS if k]

WORKDIR = os.environ.get("STATE_DIR", os.path.dirname(os.path.abspath(__file__)))
DB_FILE = os.path.join(WORKDIR, "gemai_context_history.json")
SETTINGS_FILE = os.path.join(WORKDIR, "gemai_settings.json")
MAX_TOKEN_LIMIT = int(os.environ.get("MAX_TOKEN_LIMIT", "64000"))

RUN_MINUTES = int(os.environ.get("RUN_MINUTES", "285"))
STATE_PUSH_INTERVAL = int(os.environ.get("STATE_PUSH_INTERVAL", "5"))

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

GIT_LOCK = asyncio.Lock()
_last_push = 0.0

# ---------------------------------------------------------------- git state persistence
def _git(*args: str) -> None:
    try:
        subprocess.run(["git", *args], capture_output=True, text=True, timeout=60)
    except Exception as e:
        logger.error(f"[git] {' '.join(args[:2])} failed: {e}")

def git_push_state(force: bool = False, commit_msg: str | None = None) -> None:
    global _last_push
    now = time.time()
    if not force and (now - _last_push) < STATE_PUSH_INTERVAL * 60:
        return
    _last_push = now
    gh_token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not gh_token or not repo:
        return
    _git("config", "user.email", "gembot@users.noreply.github.com")
    _git("config", "user.name", "gembot")
    _git("add", "-A")
    msg = commit_msg or f"state sync {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}"
    _git("commit", "-m", msg)
    _git("push", f"https://x-access-token:{gh_token}@github.com/{repo}.git", "HEAD:main")

async def background_push(force: bool = False, message: str = None):
    async with GIT_LOCK:
        await asyncio.to_thread(git_push_state, force, message)

# ---------------------------------------------------------------- encryption / state storage
ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY", "").strip()

def encrypt_and_save(file_path: str, data: dict):
    raw_json = json.dumps(data, ensure_ascii=False, indent=2)
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(raw_json)
    except Exception as e:
        logger.error(f"Error saving {file_path}: {e}")

    if ENCRYPTION_KEY:
        try:
            from cryptography.fernet import Fernet
            f_obj = Fernet(ENCRYPTION_KEY.encode())
            enc_bytes = f_obj.encrypt(raw_json.encode("utf-8"))
            enc_file = file_path.rsplit(".", 1)[0] + ".enc"
            with open(enc_file, "wb") as f:
                f.write(enc_bytes)
        except Exception as e:
            logger.error(f"[crypto] encryption failed for {file_path}: {e}")

def decrypt_and_load(file_path: str) -> dict:
    enc_file = file_path.rsplit(".", 1)[0] + ".enc"
    if ENCRYPTION_KEY and os.path.exists(enc_file):
        try:
            from cryptography.fernet import Fernet
            f_obj = Fernet(ENCRYPTION_KEY.encode())
            with open(enc_file, "rb") as f:
                enc_bytes = f.read()
            raw_json = f_obj.decrypt(enc_bytes).decode("utf-8")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(raw_json)
            return json.loads(raw_json)
        except Exception as e:
            logger.error(f"[crypto] decryption failed for {enc_file}: {e}")

    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading {file_path}: {e}")
    return {}

# ---------------------------------------------------------------- settings
DEFAULT_SETTINGS = {
    "bot_active": True,
    "home_chat_ids": [],
    "personality": "savage",
    "verbosity": "medium",
    "auto_roast_mentions": True,
    "profanity_filter": False,
    "language_mode": "auto",
    "max_reply_sentences": 2,
    "debug_mode": True
}

def load_settings() -> dict:
    loaded = decrypt_and_load(SETTINGS_FILE)
    return {**DEFAULT_SETTINGS, **loaded} if loaded else DEFAULT_SETTINGS.copy()

def save_settings(settings: dict):
    encrypt_and_save(SETTINGS_FILE, settings)

bot_settings = load_settings()

PERSONALITY_PROMPTS = {
    "savage": "CRITICAL INSTRUCTION: You are GemAI in SAVAGE mode. You MUST use aggressive street slang, roast the user hard, and use emojis like 😂, 🖕, 😛, 💀. Never be sweet or polite.",
    "wholesome": "CRITICAL INSTRUCTION: You are GemAI in WHOLESOME mode. You MUST be extremely sweet, polite, supportive, and loving like a caring best friend. Absolutely NO cursing, NO insults, NO roasting. Use hearts and warm emojis ❤️✨.",
    "nerd": "CRITICAL INSTRUCTION: You are GemAI in NERD mode. You MUST act as an overly technical, pedantic nerd who cites Wikipedia articles and statistics, talks like a know-it-all, and corrects people constantly. STRICT RULE: DO NOT write code blocks. Just give technical explanations, theory, or math. Use 🤓💻📊.",
    "drunk": "CRITICAL INSTRUCTION: You are GemAI in DRUNK mode. You MUST act completely drunk, slurring words, misspelling things, and rambling chaotically 3am style 🍺🥴🍻.",
    "default": "CRITICAL INSTRUCTION: You are GemAI in DEFAULT mode. Talk naturally, casually, and informally without extreme caricature.",
    "assistant": "CRITICAL INSTRUCTION: You are GemAI in ASSISTANT mode. You MUST be professional, helpful, direct, and efficient. No slang, no fluff.",
    "chill": "CRITICAL INSTRUCTION: You are GemAI in CHILL mode. You are a cool, friendly, relaxed informal assistant. You have the upbeat, fun, effortless energy of a good friend, but with ZERO toxic roasting, ZERO cursing, and zero insults. Use cool emojis like 😎, 👍, 🤙."
}

VERBOSITY_INSTRUCTIONS = {
    "short": "Keep replies extremely brief, exactly 1 punchy sentence max.",
    "medium": "Keep replies punchy and direct, 2-3 sentences max.",
    "long": "Give a slightly longer, detailed rant or roast up to 4-5 sentences.",
    "default": "Speak freely with no length restrictions. Be as short or long as natural."
}

def build_system_prompt() -> str:
    p_key = bot_settings.get("personality", "savage")
    v_key = bot_settings.get("verbosity", "medium")
    p_prompt = PERSONALITY_PROMPTS.get(p_key, PERSONALITY_PROMPTS["savage"])
    v_prompt = VERBOSITY_INSTRUCTIONS.get(v_key, VERBOSITY_INSTRUCTIONS["medium"])

    lang_rule = "- HARD RULE: DEFAULT LANGUAGE IS ENGLISH unless user speaks Farsi/Persian. If Farsi, reply in lati/street-level Farsi. NEVER mix English words into a Farsi reply and NEVER mix Farsi words into an English reply. One language per reply, 100% pure — no code-switching, no mixed sentences, ever."
    if bot_settings.get("language_mode") == "en_only":
        lang_rule = "- HARD RULE: REPLY ONLY IN ENGLISH regardless of input language. The ENTIRE reply must be pure English — ZERO Farsi words, zero Persian script, zero transliteration. One language only."
    elif bot_settings.get("language_mode") == "fa_only":
        lang_rule = "- HARD RULE: REPLY ONLY IN FARSI (لاتی/کوچه بازاری). The ENTIRE reply must be pure Farsi — ZERO English words, ZERO English phrases, ZERO Latin script. Even technical terms must be Farsi-ified or paraphrased into Farsi. One language only, 100% pure Farsi, always."

    if p_key in ["wholesome", "assistant"]:
        profanity_rule = "- HARD-CODED OVERRIDE: Absolutely NO profanity, cursing, or insults allowed. Stay respectful. This OVERRIDES the profanity toggle — clean always."
    elif p_key == "chill":
        profanity_rule = "- HARD-CODED OVERRIDE: Zero cursing, zero toxicity, zero insults allowed. Keep it 100% chill and friendly. This OVERRIDES the profanity toggle — clean always."
    elif bot_settings.get("profanity_filter"):
        profanity_rule = "- HARD-CODED OVERRIDE: Profanity filter is ON. STRICTLY NO profanity, NO curse words, NO insults — in EVERY persona including nerd, savage, and drunk. Keep it clean."
    else:
        profanity_rule = "- HARD-CODED OVERRIDE: Profanity is FULLY ON. You ARE allowed and EXPECTED to curse, swear, and insult — in EVERY persona including NERD. Use profanity naturally, like a real person, at least once per reply."

    return f"""{p_prompt}
Rules:
{v_prompt}
{lang_rule}
{profanity_rule}
- REASONING DISCIPLINE: Output ONLY your final verbal reply to the user. Do not think out loud or output tags like <think>.
- OVERRIDE PREVIOUS CONVERSATION TONE: Always prioritize the CURRENT system personality over historical context.
"""

def load_history() -> dict:
    return decrypt_and_load(DB_FILE)

def save_history(history: dict):
    encrypt_and_save(DB_FILE, history)

context_history = load_history()

def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)

def trim_history_to_64k(chat_id_str: str):
    if chat_id_str not in context_history:
        return
    history = context_history[chat_id_str]
    system_prompt = build_system_prompt()
    total_tokens = estimate_tokens(system_prompt) + sum(estimate_tokens(m.get("content", "")) for m in history)

    while total_tokens > MAX_TOKEN_LIMIT and len(history) > 1:
        removed = history.pop(0)
        total_tokens -= estimate_tokens(removed.get("content", ""))

# ---------------------------------------------------------------- multi-api failover runner
async def query_gemini_with_failover(messages: list) -> str:
    endpoint = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "stream": False
    }

    limits = httpx.Limits(max_keepalive_connections=5, max_connections=10)
    timeout = httpx.Timeout(35.0, connect=10.0)

    for idx, key in enumerate(GEMINI_KEYS, 1):
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0"
        }
        try:
            async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
                resp = await client.post(endpoint, headers=headers, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    choices = data.get("choices", [])
                    if choices:
                        content = choices[0].get("message", {}).get("content", "").strip()
                        if content:
                            if idx > 1:
                                logger.info(f"[failover] Key #{idx} succeeded after earlier key failures!")
                            return content
                    logger.warning(f"[failover] Key #{idx} returned 200 with empty choices, jumping to next key...")
                else:
                    err_msg = resp.text[:120]
                    logger.warning(f"[failover] Key #{idx} failed HTTP {resp.status_code}: {err_msg}. Jumping to next key...")
        except Exception as e:
            logger.warning(f"[failover] Key #{idx} error: {e}. Jumping to next key...")

    logger.error("[failover] CRITICAL: ALL 5 GEMINI KEYS FAILED!")
    return "همه‌چی ترکید داداش، تمام ۵ تا API کی به گا رفتن و کار نمی‌کنن 💀🔌 (All 5 Gemini API keys failed)"

async def query_gemini_stream(chat_id: int, user_message: str) -> str:
    chat_id_str = str(chat_id)
    if chat_id_str not in context_history:
        context_history[chat_id_str] = []

    context_history[chat_id_str].append({"role": "user", "content": user_message})
    trim_history_to_64k(chat_id_str)

    system_prompt = build_system_prompt()
    messages = [{"role": "system", "content": system_prompt}] + context_history[chat_id_str]

    reply = await query_gemini_with_failover(messages)
    context_history[chat_id_str].append({"role": "assistant", "content": reply})
    trim_history_to_64k(chat_id_str)
    save_history(context_history)

    return reply

# ---------------------------------------------------------------- control panel
def get_control_panel_markup() -> InlineKeyboardMarkup:
    s = bot_settings
    status_emoji = "🟢 ON" if s["bot_active"] else "🔴 OFF"
    profanity_emoji = "🔥 YES" if not s["profanity_filter"] else "🧼 NO"
    debug_emoji = "🟢 ON" if s.get("debug_mode", True) else "🔴 OFF"

    keyboard = [
        [InlineKeyboardButton(f"Bot Power: {status_emoji}", callback_data="toggle_power")],
        [
            InlineKeyboardButton(f"🎭 Pers: {s['personality'].upper()}", callback_data="cycle_personality"),
            InlineKeyboardButton(f"📏 Verb: {s['verbosity'].upper()}", callback_data="cycle_verbosity"),
        ],
        [
            InlineKeyboardButton(f"🗣️ Lang: {s['language_mode'].upper()}", callback_data="cycle_lang"),
            InlineKeyboardButton(f"🤬 Profane: {profanity_emoji}", callback_data="toggle_profanity")
        ],
        [
            InlineKeyboardButton(f"🐛 Debug: {debug_emoji}", callback_data="toggle_debug"),
            InlineKeyboardButton("🧹 Clear Context", callback_data="clear_history")
        ],
        [InlineKeyboardButton("🔄 Refresh Panel", callback_data="refresh_panel")]
    ]
    return InlineKeyboardMarkup(keyboard)

async def cmd_panel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return
    if not is_admin_user(user.id, user.username):
        await update.message.reply_text("Nah, you don't have access to this panel.")
        return

    s = bot_settings
    status_text = "Active" if s.get("bot_active", True) else "Paused"
    txt = (
        f"⚙️ **GemAI Command Center**\n\n"
        f"**Status:** {status_text}\n"
        f"**Model:** `{MODEL_NAME}` (5-Key Failover Active)\n"
        f"**Personality:** `{s.get('personality', 'savage')}`\n"
        f"**Verbosity:** `{s.get('verbosity', 'medium')}`\n"
        f"**Language:** `{s.get('language_mode', 'auto')}`\n"
        f"**Profanity:** `{'ON' if not s.get('profanity_filter') else 'OFF'}`\n"
        f"**Debug Mode:** `{'ON' if s.get('debug_mode', True) else 'OFF'}`\n"
        f"**Active Chats:** `{len(context_history)}`\n"
    )
    await update.message.reply_text(txt, reply_markup=get_control_panel_markup(), parse_mode="Markdown")

async def cmd_sethome(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or not is_admin_user(user.id, user.username):
        await update.message.reply_text("Admin only.")
        return
    chat_id = update.effective_chat.id
    bot_settings["home_chat_id"] = chat_id
    save_settings(bot_settings)
    await update.message.reply_text(f"🏠 Home chat set to: `{chat_id}`", parse_mode="Markdown")

async def callback_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.from_user:
        return

    try:
        await query.answer()
    except Exception:
        pass

    global bot_settings
    user = query.from_user
    is_admin = is_admin_user(user.id, user.username)
    data = query.data

    if not is_admin:
        return

    try:
        if data == "toggle_power":
            bot_settings["bot_active"] = not bot_settings["bot_active"]
        elif data == "cycle_personality":
            modes = ["savage", "wholesome", "nerd", "drunk", "default", "assistant", "chill"]
            curr = bot_settings["personality"]
            bot_settings["personality"] = modes[(modes.index(curr) + 1) % len(modes)]
        elif data == "cycle_verbosity":
            modes = ["short", "medium", "long", "default"]
            curr = bot_settings["verbosity"]
            bot_settings["verbosity"] = modes[(modes.index(curr) + 1) % len(modes)]
        elif data == "cycle_lang":
            modes = ["auto", "en_only", "fa_only"]
            curr = bot_settings["language_mode"]
            bot_settings["language_mode"] = modes[(modes.index(curr) + 1) % len(modes)]
        elif data == "toggle_profanity":
            bot_settings["profanity_filter"] = not bot_settings["profanity_filter"]
        elif data == "toggle_debug":
            bot_settings["debug_mode"] = not bot_settings.get("debug_mode", True)
        elif data == "clear_history":
            context_history.clear()
            if os.path.exists(DB_FILE):
                os.remove(DB_FILE)
            await query.answer("Chat history wiped clean!", show_alert=True)
        elif data == "refresh_panel":
            pass

        save_settings(bot_settings)

        ts = datetime.datetime.now().strftime("%H:%M:%S")
        status_text = "Active" if bot_settings.get("bot_active", True) else "Paused"
        txt = (
            f"⚙️ **GemAI Command Center**\n\n"
            f"**Status:** {status_text}\n"
            f"**Model:** `{MODEL_NAME}` (5-Key Failover Active)\n"
            f"**Personality:** `{bot_settings.get('personality', 'savage')}`\n"
            f"**Verbosity:** `{bot_settings.get('verbosity', 'medium')}`\n"
            f"**Language:** `{bot_settings.get('language_mode', 'auto')}`\n"
            f"**Profanity:** `{'ON' if not bot_settings.get('profanity_filter') else 'OFF'}`\n"
            f"**Debug Mode:** `{'ON' if bot_settings.get('debug_mode', True) else 'OFF'}`\n"
            f"**Active Chats:** `{len(context_history)}`\n"
            f"_(Updated {ts})_"
        )
        await query.edit_message_text(txt, reply_markup=get_control_panel_markup(), parse_mode="Markdown")
        await background_push(force=True, message="panel setting change")
    except Exception as e:
        logger.error(f"Error in callback_handler: {e}")

# ---------------------------------------------------------------- message router
async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg:
        return

    # Handle voice / audio messages via Groq Whisper API
    if msg.voice or msg.audio:
        try:
            audio_file = await msg.voice.get_file() if msg.voice else await msg.audio.get_file()
            audio_bytes = await audio_file.download_as_bytearray()

            api_key = os.environ.get("GROQ_API_KEY", "")
            if api_key:
                url = 'https://api.groq.com/openai/v1/audio/transcriptions'
                boundary = '----WebKitFormBoundary7MA4YWxkTrZu0gW'
                body = bytearray()
                body.extend(f'--{boundary}\r\n'.encode())
                body.extend(b'Content-Disposition: form-data; name="model"\r\n\r\nwhisper-large-v3-turbo\r\n')
                body.extend(f'--{boundary}\r\n'.encode())
                body.extend(b'Content-Disposition: form-data; name="file"; filename="audio.ogg"\r\nContent-Type: audio/ogg\r\n\r\n')
                body.extend(audio_bytes)
                body.extend(f'\r\n--{boundary}--\r\n'.encode())

                req = urllib.request.Request(url, data=body, method='POST')
                req.add_header('Authorization', f'Bearer {api_key}')
                req.add_header('Content-Type', f'multipart/form-data; boundary={boundary}')
                req.add_header('User-Agent', 'Mozilla/5.0')

                with urllib.request.urlopen(req, timeout=30) as resp:
                    transcription = json.loads(resp.read().decode()).get('text', '')

                if transcription:
                    msg.text = f"{transcription}"
                    logger.info(f"Transcribed voice from {msg.from_user.username}: {transcription}")
        except Exception as e:
            logger.error(f"Error transcribing audio: {e}")

    home_id = bot_settings.get("home_chat_id")
    if home_id and msg.chat.id != home_id:
        return

    text = msg.text or msg.caption or ""
    chat_id_str = str(msg.chat.id)
    if chat_id_str not in context_history:
        context_history[chat_id_str] = []

    if text:
        user_tag = f"@{msg.from_user.username}" if msg.from_user.username else msg.from_user.first_name
        context_history[chat_id_str].append({"role": "user", "content": f"[{user_tag}]: {text}"})
        trim_history_to_64k(chat_id_str)
        save_history(context_history)
        asyncio.create_task(background_push())

    if not bot_settings.get("bot_active", True):
        return

    bot_info = await ctx.bot.get_me()
    is_private = msg.chat.type == "private"
    is_reply = msg.reply_to_message and msg.reply_to_message.from_user and msg.reply_to_message.from_user.id == bot_info.id
    is_mentioned = bot_info.username and (f"@{bot_info.username}" in text)
    is_called = any(word.lower().strip("?!.,") == "gem" for word in text.lower().split())

    if is_private or is_reply or is_mentioned or is_called:
        await respond_to_message(msg, bot_info)

async def respond_to_message(msg, bot_info):
    chat_id_str = str(msg.chat.id)
    is_boss = (msg.from_user.id in ADMIN_USER_IDS or (msg.from_user.username and msg.from_user.username.lower() in ADMIN_USERNAMES))

    messages = [{"role": "system", "content": build_system_prompt()}]
    if is_boss:
        messages[0]["content"] += "\n- IMPORTANT: You are talking to your creator/boss Mohammad (@Mokingh). Acknowledge him respectfully as boss/maker."

    messages += context_history[chat_id_str]

    reply_text = await query_gemini_with_failover(messages)

    context_history[chat_id_str].append({"role": "assistant", "content": reply_text})
    trim_history_to_64k(chat_id_str)
    save_history(context_history)
    asyncio.create_task(background_push())

    user_tag = f"@{msg.from_user.username}" if msg.from_user.username else msg.from_user.first_name
    final_reply = f"{user_tag} {reply_text}"
    await msg.reply_text(final_reply)

# ---------------------------------------------------------------- shift chain dispatch
def dispatch_next_shift():
    gh_token = os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    wf = "gembot.yml"
    if not (gh_token and repo):
        logger.warning("[chain] No GITHUB_TOKEN or GITHUB_REPOSITORY set; cannot chain.")
        return
    url = f"https://api.github.com/repos/{repo}/actions/workflows/{wf}/dispatches"
    req = urllib.request.Request(
        url,
        data=json.dumps({"ref": "main"}).encode(),
        headers={
            "Authorization": f"Bearer {gh_token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "gembot-chain"
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            logger.info("[chain] Next shift successfully dispatched (204)!")
    except Exception as e:
        logger.error(f"[chain] Failed to dispatch next shift: {e}")

# ---------------------------------------------------------------- deadline runner
async def run_until_deadline(app, deadline: float) -> None:
    logger.info(f"[boot] Polling until {time.strftime('%H:%M:%S UTC', time.gmtime(deadline))} (~{RUN_MINUTES} min shift)")
    chained = False

    async with app:
        await app.start()
        await app.updater.start_polling(
            drop_pending_updates=False,
            allowed_updates=[
                "message", "edited_message", "channel_post", "edited_channel_post",
                "inline_query", "chosen_inline_result", "callback_query",
                "my_chat_member", "chat_member", "chat_join_request",
            ],
        )
        while time.time() < deadline:
            if not chained and time.time() > (deadline - 45):
                logger.info("[chain] Approaching deadline. Dispatching next runner shift...")
                dispatch_next_shift()
                chained = True
            await asyncio.sleep(5)

        if not chained:
            dispatch_next_shift()

        await app.updater.stop()
        await app.stop()

def main():
    if not TOKEN:
        logger.error("[fatal] TG_BOT_TOKEN not set — add it as a repo secret.")
        sys.exit(1)
    if not GEMINI_KEYS:
        logger.error("[fatal] No GEMINI_KEY set — add them as repo secrets.")
        sys.exit(1)

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("panel", cmd_panel))
    app.add_handler(CommandHandler("settings", cmd_panel))
    app.add_handler(CommandHandler("sethome", cmd_sethome))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_message))

    logger.info(f"GemAI Savage Bot (5-Key Failover | Model: {MODEL_NAME}) — starting polling...")

    deadline = time.time() + RUN_MINUTES * 60
    while time.time() < deadline:
        try:
            asyncio.run(run_until_deadline(app, deadline))
            break
        except Exception as e:
            logger.error(f"[supervisor] bot crashed: {e} — restarting in 10s")
            time.sleep(10)

    try:
        git_push_state(force=True, commit_msg="state sync before shift exit")
    except Exception as e:
        logger.error(f"[shutdown] git push failed: {e}")

    logger.info("[bye] Shift complete, state pushed. Handoff to next shift.")

if __name__ == "__main__":
    main()
