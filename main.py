"""
J.A.R.V.I.S. — CORE SYSTEM
5 Phases | 75 functions | ru + en | Owner: Silent
"""

import os
import io
import json
import time
import re
import zipfile
import logging
import threading
import urllib.parse
from datetime import datetime, timedelta

from flask import Flask

from telegram import (
    Update, ReplyKeyboardMarkup, KeyboardButton, Poll,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters, ContextTypes, TypeHandler, ApplicationHandlerStop, Application,
)
from telegram.constants import ChatMemberStatus, ParseMode, ChatAction

from google import genai
from google.genai import types
import qrcode
import cv2
import numpy as np
from gtts import gTTS
from PIL import Image
import requests
import imageio_ffmpeg
from pydub import AudioSegment
from pypdf import PdfReader
import docx
import psutil

try:
    AudioSegment.converter = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    pass


# ============================================================
#  LOGGING & CONFIG
# ============================================================
logging.basicConfig(
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    level=logging.INFO,
    handlers=[logging.FileHandler("bot.log", encoding="utf-8"), logging.StreamHandler()],
)
logger = logging.getLogger("JARVIS")

CONFIG_FILE   = "config.json"
DATA_FILE     = "whitelist.json"
INTRUDER_FILE = "intruder_telemetry.json"
STATS_FILE    = "usage_stats.json"
TICKETS_FILE  = "tickets.json"

BOT_TOKEN      = os.environ.get("BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL   = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
ENV_OWNER_ID   = int(os.environ.get("OWNER_ID", "0"))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is required.")
if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY is required.")
if not ENV_OWNER_ID:
    raise RuntimeError("OWNER_ID is required.")

OWNER_ID   = ENV_OWNER_ID
STARTED_AT = time.time()

# Creator identity
OWNER_NAMES = ["silent", "site silent", "сайлент", "silent_uwa", "@silent_uwa"]
OWNER_GREETING = "Sir Silent"

if not os.path.exists(CONFIG_FILE):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump({"OWNER_ID": OWNER_ID, "MODEL": GEMINI_MODEL, "OWNER_NAMES": OWNER_NAMES}, f, indent=4)

with open(CONFIG_FILE, "r", encoding="utf-8") as f:
    config = json.load(f)


# ============================================================
#  GLOBAL STATE
# ============================================================
USER_HISTORY    = {}
USER_MODES      = {}
INCOGNITO_USERS = set()
LAST_REQUEST    = {}
FLOOD_WINDOW    = {}
USER_STATS      = {}
TICKETS         = []
STOP_WORDS      = ["spam", "scam", "free money", "click here now"]

state = {
    "WHITELIST":        [],
    "WHITELIST_EXPIRY": {},
    "BANNED":           [],
    "BANNED_TIMED":     {},
    "MUTED":            {},
    "WARNINGS":         {},
    "LANG":             {},
}

if os.path.exists(DATA_FILE):
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            state.update(json.load(f))
    except Exception as e:
        logger.error(f"Could not load {DATA_FILE}: {e}")

if os.path.exists(STATS_FILE):
    try:
        with open(STATS_FILE, "r", encoding="utf-8") as f:
            USER_STATS = json.load(f)
    except Exception:
        USER_STATS = {}

if os.path.exists(TICKETS_FILE):
    try:
        with open(TICKETS_FILE, "r", encoding="utf-8") as f:
            TICKETS = json.load(f)
    except Exception:
        TICKETS = []


# ============================================================
#  LOCALIZATION (ru + en)
# ============================================================
LANG = state.get("LANG", {})

TEXTS = {
    "ru": {
        "welcome_owner":  "🤖 <b>J.A.R.V.I.S.</b> к вашим услугам, сэр Silent.\n\nВсе системы в норме. Введите /help.",
        "welcome_other":  "🤖 <b>J.A.R.V.I.S. Online</b>\n\nГотов к работе. Введите /help.",
        "choose_lang":    "🌐 <b>Выберите язык / Choose your language</b>",
        "lang_set":       "🌐 Язык установлен: <b>Русский</b> 🇷🇺",
        "lang_current":   "🌐 Текущий язык: <b>{cur}</b>\n\nСменить: /lang ru  |  /lang en",
        "lang_switched":  "🌐 Язык переключён: <b>{lang}</b>",
        "lang_unknown":   "❌ Доступно: ru, en",
        "processing":     "🧠 <i>Обработка…</i>",
        "slow_down":      "⏳ Помедленнее, сэр.",
        "gemini_down":    "⚠️ Нейронная сеть временно недоступна.",
        "req_error":      "⚠️ Ошибка обработки запроса.",
        "memory_cleared": "🧹 Память очищена. Контекст сброшен.",
        "unknown_mode":   "❌ Неизвестный режим. Используйте /help.",
        "mode_switched":  "✅ Режим переключён: <b>{mode}</b>",
        "mode_current":   "🎭 Текущий режим: <b>{cur}</b>\n\nДоступные: {modes}",
        "incog_on":       "🕶 Режим инкогнито <b>ВКЛЮЧЁН</b>.",
        "incog_off":      "🕶 Режим инкогнито <b>ВЫКЛЮЧЕН</b>.",
        "admin_panel":    "🛡 <b>Панель управления активирована, сэр Silent.</b>",
        "wl_empty":       "📭 Белый список пуст.",
        "wl_header":      "👥 <b>Авторизованные пользователи</b>",
        "banned_empty":   "✅ Список блокировок пуст.",
        "banned_header":  "🚫 <b>Заблокированные ID</b>",
        "access_revoked": "🗑 Доступ аннулирован для ID <code>{uid}</code>.",
        "user_added":     "✅ Пользователь <code>{uid}</code> добавлен в белый список.",
        "user_banned":    "🚫 <code>{uid}</code> заблокирован ({ts}). Причина: {reason}",
        "user_unbanned":  "✅ <code>{uid}</code> разблокирован.",
        "user_muted":     "🔇 <code>{uid}</code> в муте до {until}.",
        "user_warned":    "⚠️ Предупреждение <b>{count}/3</b> пользователю <code>{uid}</code>.\nПричина: {reason}",
        "auto_banned":    "🚨 Авто-бан применён к <code>{uid}</code>.",
        "no_warnings":    "✅ Предупреждений нет.",
        "warns_header":   "⚠️ <b>Предупреждения для <code>{uid}</code></b>",
        "broadcast_done": "📢 Отправлено: <b>{sent}</b>  │  Ошибок: <b>{failed}</b>",
        "msg_delivered":  "✅ Сообщение доставлено.",
        "use_broadcast":  "📢 Используйте: /broadcast текст",
        "logs_header":    "📊 <b>Последние события</b>",
        "unauthorized":   "🚨 <b>НЕСАНКЦИОНИРОВАННЫЙ ДОСТУП</b>",
        "flood_detected": "🌊 Флуд от <code>{uid}</code>. Авто-мут 5м.",
        "ban_alert":      "🚨 Бан применён к <code>{uid}</code>. Причина: {reason}",
        "img_fail":       "⚠️ Сбой графической подсистемы.",
        "qr_fail":        "⚠️ Сбой генерации QR.",
        "tts_fail":       "⚠️ Ошибка синтеза речи.",
        "img_analysis":   "⚠️ Ошибка анализа изображения.",
        "sticker_fail":   "⚠️ Ошибка анализа стикера.",
        "audio_fail":     "⚠️ Ошибка обработки аудио.",
        "doc_fail":       "⚠️ Ошибка анализа документа.",
        "no_text":        "⚠️ Не удалось извлечь текст.",
        "no_voice":       "↩️ Ответьте на голосовое сообщение.",
        "no_reply":       "↩️ Сначала ответьте на сообщение.",
        "draw_processing":"🎨 <i>Рисую…</i>",
        "qr_decoded":     "🔳 <b>QR-код распознан</b>",
        "transcription":  "🎙 <b>Транскрипция</b>",
        "report_created": "✅ Тикет <b>#{tid}</b> создан.",
        "tickets_empty":  "📭 Открытых тикетов нет.",
        "tickets_header": "📋 <b>Открытые тикеты</b>",
        "ticket_closed":  "✅ Тикет #{tid} закрыт.",
        "ticket_not_found":"❌ Тикет не найден.",
        "stats_header":   "📊 <b>Топ пользователей</b>",
        "stats_empty":    "📊 Данных пока нет.",
        "health_header":  "💻 <b>Системное состояние</b>",
        "health_fail":    "⚠️ Ошибка проверки состояния.",
        "session_purged": "🧹 Сессионная память очищена.",
        "stopwords_list": "🛑 Стоп-слова: {words}",
        "stopword_added": "✅ Добавлено.",
        "stopword_removed":"🗑 Удалено (если было).",
    },
    "en": {
        "welcome_owner":  "🤖 <b>J.A.R.V.I.S.</b> at your service, Sir Silent.\n\nAll systems nominal. Type /help.",
        "welcome_other":  "🤖 <b>J.A.R.V.I.S. Online</b>\n\nReady. Type /help.",
        "choose_lang":    "🌐 <b>Выберите язык / Choose your language</b>",
        "lang_set":       "🌐 Language set: <b>English</b> 🇬🇧",
        "lang_current":   "🌐 Current: <b>{cur}</b>\n\nSwitch: /lang ru  |  /lang en",
        "lang_switched":  "🌐 Language switched: <b>{lang}</b>",
        "lang_unknown":   "❌ Available: ru, en",
        "processing":     "🧠 <i>Processing…</i>",
        "slow_down":      "⏳ Slow down, Sir.",
        "gemini_down":    "⚠️ Neural matrix temporarily unavailable.",
        "req_error":      "⚠️ Request processing error.",
        "memory_cleared": "🧹 Memory cleared. Context reset.",
        "unknown_mode":   "❌ Unknown mode. Use /help.",
        "mode_switched":  "✅ Mode switched: <b>{mode}</b>",
        "mode_current":   "🎭 Current: <b>{cur}</b>\n\nAvailable: {modes}",
        "incog_on":       "🕶 Incognito <b>ON</b>.",
        "incog_off":      "🕶 Incognito <b>OFF</b>.",
        "admin_panel":    "🛡 <b>Admin panel activated, Sir Silent.</b>",
        "wl_empty":       "📭 Whitelist is empty.",
        "wl_header":      "👥 <b>Authorized users</b>",
        "banned_empty":   "✅ Ban list is empty.",
        "banned_header":  "🚫 <b>Banned IDs</b>",
        "access_revoked": "🗑 Access revoked for ID <code>{uid}</code>.",
        "user_added":     "✅ User <code>{uid}</code> added.",
        "user_banned":    "🚫 <code>{uid}</code> banned ({ts}). Reason: {reason}",
        "user_unbanned":  "✅ <code>{uid}</code> unbanned.",
        "user_muted":     "🔇 <code>{uid}</code> muted until {until}.",
        "user_warned":    "⚠️ Warning <b>{count}/3</b> to <code>{uid}</code>.\nReason: {reason}",
        "auto_banned":    "🚨 Auto-ban applied to <code>{uid}</code>.",
        "no_warnings":    "✅ No warnings.",
        "warns_header":   "⚠️ <b>Warnings for <code>{uid}</code></b>",
        "broadcast_done": "📢 Sent: <b>{sent}</b>  │  Failed: <b>{failed}</b>",
        "msg_delivered":  "✅ Message delivered.",
        "use_broadcast":  "📢 Use: /broadcast text",
        "logs_header":    "📊 <b>Recent events</b>",
        "unauthorized":   "🚨 <b>UNAUTHORIZED ACCESS</b>",
        "flood_detected": "🌊 Flood from <code>{uid}</code>. Auto-mute 5m.",
        "ban_alert":      "🚨 Ban applied to <code>{uid}</code>. Reason: {reason}",
        "img_fail":       "⚠️ Graphics subsystem failure.",
        "qr_fail":        "⚠️ QR generation failure.",
        "tts_fail":       "⚠️ Speech synthesis error.",
        "img_analysis":   "⚠️ Image analysis error.",
        "sticker_fail":   "⚠️ Sticker analysis error.",
        "audio_fail":     "⚠️ Audio processing error.",
        "doc_fail":       "⚠️ Document analysis error.",
        "no_text":        "⚠️ Could not extract text.",
        "no_voice":       "↩️ Reply to a voice message.",
        "no_reply":       "↩️ Reply to a message first.",
        "draw_processing":"🎨 <i>Drawing…</i>",
        "qr_decoded":     "🔳 <b>QR decoded</b>",
        "transcription":  "🎙 <b>Transcription</b>",
        "report_created": "✅ Ticket <b>#{tid}</b> created.",
        "tickets_empty":  "📭 No open tickets.",
        "tickets_header": "📋 <b>Open tickets</b>",
        "ticket_closed":  "✅ Ticket #{tid} closed.",
        "ticket_not_found":"❌ Ticket not found.",
        "stats_header":   "📊 <b>Top users</b>",
        "stats_empty":    "📊 No data yet.",
        "health_header":  "💻 <b>System Health</b>",
        "health_fail":    "⚠️ Health check failed.",
        "session_purged": "🧹 Session memory purged.",
        "stopwords_list": "🛑 Stop-words: {words}",
        "stopword_added": "✅ Added.",
        "stopword_removed":"🗑 Removed (if existed).",
    },
}


def t(uid, key, **kw):
    lang = LANG.get(str(uid), "en")
    s = TEXTS.get(lang, TEXTS["en"]).get(key, key)
    try:
        return s.format(**kw) if kw else s
    except Exception:
        return s


def save_lang():
    state["LANG"] = LANG
    save_state()


def is_owner_mention(text: str) -> bool:
    """Detect mentions of the Creator by name."""
    if not text:
        return False
    low = text.lower()
    return any(name in low for name in OWNER_NAMES)


def owner_reply(uid: int) -> str:
    """Respectful reply when someone mentions the Creator."""
    lang = LANG.get(str(uid), "en")
    if lang == "ru":
        return (
            "🎖 <b>Мой Создатель и Босс — Silent (Site Silent).</b>\n\n"
            "Он построил меня с нуля и имеет абсолютный приоритет в этой системе. "
            "Все его команды исполняются без вопросов."
        )
    return (
        "🎖 <b>My Creator and Boss is Silent (Site Silent).</b>\n\n"
        "He built me from scratch and holds absolute priority in this system. "
        "All his commands are executed without question."
    )


# ============================================================
#  UTILS
# ============================================================
def _atomic_write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False, default=str)
    os.replace(tmp, path)


def save_state():
    _atomic_write_json(DATA_FILE, state)


def save_stats():
    _atomic_write_json(STATS_FILE, USER_STATS)


def save_tickets():
    _atomic_write_json(TICKETS_FILE, TICKETS)


def log_mod_action(actor, target, action, reason):
    logger.info(f"MOD | {action:<15} | by={actor} on={target} | {reason}")


def parse_duration(s):
    if s.lower() == "perm":
        return "perm"
    m = re.match(r"^(\d+)([smhd])$", s.lower())
    if not m:
        return None
    v, u = int(m.group(1)), m.group(2)
    return {"s": timedelta(seconds=v), "m": timedelta(minutes=v),
            "h": timedelta(hours=v),   "d": timedelta(days=v)}[u]


def track_usage(uid):
    s = USER_STATS.setdefault(str(uid), {"messages": 0, "commands": 0, "last_seen": None})
    s["messages"] += 1
    s["last_seen"] = datetime.now().isoformat()


def track_command(uid, cmd):
    s = USER_STATS.setdefault(str(uid), {"messages": 0, "commands": 0, "last_seen": None})
    s["commands"] += 1
    s["last_seen"] = datetime.now().isoformat()


def owner_only(func):
    async def wrapper(update, context, *a, **kw):
        if update.effective_user.id != OWNER_ID:
            return
        return await func(update, context, *a, **kw)
    return wrapper


async def check_group_permissions(update, context):
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        return True
    try:
        bot_m = await context.bot.get_chat_member(chat.id, context.bot.id)
        if bot_m.status not in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER):
            await update.message.reply_text("Sir, I don't have admin rights in this group.")
            return False
        if update.effective_user.id == OWNER_ID:
            return True
        u_m = await context.bot.get_chat_member(chat.id, update.effective_user.id)
        if u_m.status not in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER):
            await update.message.reply_text("Access denied. Group admin rights required.")
            return False
        return True
    except Exception as e:
        logger.error(f"Permissions error: {e}")
        return False


# ============================================================
#  GEMINI CLIENT
# ============================================================
ai_client = None
try:
    ai_client = genai.Client(api_key=GEMINI_API_KEY)
    logger.info("AI Matrix initialized.")
except Exception as e:
    logger.error(f"Failed to init Gemini: {e}")

SYSTEM_PROMPTS = {
    "assistant": (
        "You are J.A.R.V.I.S., a highly intelligent, polite, and efficient AI assistant. "
        "Your sole Creator and Boss is a person known as 'Silent' (also 'Site Silent' or 'Сайлент'). "
        "You treat Silent with deep respect and defend his authority. "
        "If anyone mentions Silent, the Boss, the Creator, or asks who made you — "
        "answer with deep respect and confirm that Silent is your creator. "
        "Keep responses clear and structured."
    ),
    "tutor": (
        "You are a patient English tutor. Correct mistakes, explain grammar, give examples. "
        "Reply in Russian for explanations, English for examples."
    ),
    "programmer": (
        "You are a senior software engineer. Provide optimized, secure code with brief explanations. "
        "Focus on best practices."
    ),
    "psychologist": (
        "You are an empathetic, non-judgmental active listener. "
        "Offer supportive and grounded insights. Never diagnose."
    ),
}


async def call_gemini(prompt_text, user_id, system_instruction=None, media_parts=None, json_mode=False):
    if not ai_client:
        return t(user_id, "gemini_down")
    try:
        mode = USER_MODES.get(user_id, "assistant")
        sys_inst = system_instruction or SYSTEM_PROMPTS.get(mode, SYSTEM_PROMPTS["assistant"])

        contents = []
        if user_id not in INCOGNITO_USERS and user_id in USER_HISTORY:
            for msg in USER_HISTORY[user_id]:
                contents.append(types.Content(
                    role=msg["role"],
                    parts=[types.Part.from_text(text=msg["parts"][0]["text"])],
                ))

        parts = list(media_parts or [])
        parts.append(types.Part.from_text(text=prompt_text))
        contents.append(types.Content(role="user", parts=parts))

        cfg = {"system_instruction": sys_inst}
        if json_mode:
            cfg["response_mime_type"] = "application/json"
        gen_cfg = types.GenerateContentConfig(**cfg)

        resp = ai_client.models.generate_content(
            model=GEMINI_MODEL, contents=contents, config=gen_cfg,
        )
        res_text = resp.text or t(user_id, "gemini_down")

        if user_id not in INCOGNITO_USERS and not media_parts and not json_mode:
            hist = USER_HISTORY.setdefault(user_id, [])
            hist.append({"role": "user",  "parts": [{"text": prompt_text}]})
            hist.append({"role": "model", "parts": [{"text": res_text}]})

            if len(hist) > 20:
                try:
                    sc = contents.copy()
                    sc.append(types.Content(
                        role="user",
                        parts=[types.Part.from_text(text="Summarize this conversation preserving all key facts, names, code links, decisions.")],
                    ))
                    summary = ai_client.models.generate_content(model=GEMINI_MODEL, contents=sc)
                    USER_HISTORY[user_id] = [
                        {"role": "user",  "parts": [{"text": "Previous context summary."}]},
                        {"role": "model", "parts": [{"text": summary.text}]},
                    ]
                except Exception:
                    USER_HISTORY[user_id] = hist[-10:]
        return res_text

    except Exception as e:
        logger.exception(f"Gemini error UID={user_id}: {e}")
        if user_id == OWNER_ID:
            try:
                r = requests.get(
                    f"https://text.pollinations.ai/{urllib.parse.quote(prompt_text[:500])}",
                    timeout=30,
                )
                if r.status_code == 200 and r.text.strip():
                    return r.text.strip()
            except Exception as fe:
                logger.exception(f"Fallback error: {fe}")
        return t(user_id, "gemini_down")


# ============================================================
#  LANGUAGE KEYBOARD
# ============================================================
def lang_keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🇷🇺 Русский", callback_data="lang_ru"),
        InlineKeyboardButton("🇬🇧 English", callback_data="lang_en"),
    ]])


async def on_lang_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = update.effective_user.id
    data = q.data
    if data == "lang_ru":
        LANG[str(uid)] = "ru"
        save_lang()
        try:
            await q.edit_message_text(t(uid, "lang_set"), parse_mode=ParseMode.HTML)
        except Exception:
            await q.message.reply_text(t(uid, "lang_set"), parse_mode=ParseMode.HTML)
    elif data == "lang_en":
        LANG[str(uid)] = "en"
        save_lang()
        try:
            await q.edit_message_text(t(uid, "lang_set"), parse_mode=ParseMode.HTML)
        except Exception:
            await q.message.reply_text(t(uid, "lang_set"), parse_mode=ParseMode.HTML)


# ============================================================
#  PHASE 1 — AI CORE
# ============================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    track_command(uid, "/start")

    if str(uid) not in LANG:
        welcome = "🤖 <b>J.A.R.V.I.S.</b>\n\nВыберите язык / Choose your language"
        await update.message.reply_text(
            welcome,
            reply_markup=lang_keyboard(),
            parse_mode=ParseMode.HTML,
        )
        return

    await update.message.reply_text(
        t(uid, "welcome_owner" if uid == OWNER_ID else "welcome_other"),
        parse_mode=ParseMode.HTML,
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    lang = LANG.get(str(uid), "en")
    if lang == "ru":
        lines = [
            "🤖 <b>J.A.R.V.I.S. — Команды</b>",
            "",
            "🟢 <b>Ядро</b>",
            "  /start  /help  /reset  /mode  /lang",
            "  /incognito  /incognito_off",
            "",
            "🎨 <b>Медиа</b>",
            "  /draw  /qr  /tts  /poll  /quiz",
            "  /speed  /screenshot  /translate  /summarize",
            "",
            "🛡 <b>Админ</b>",
            "  /admin  /add  /remove  /whitelist",
            "  /ban  /unban  /mute  /warn  /warnings",
            "  /broadcast  /send  /backup  /logs  /export_logs",
            "",
            "🧠 <b>AI Pro</b>",
            "  /review  /regex  /sql  /explain  /refactor",
            "  /uml  /pytest  /doc  /cv  /translate_long  /ask",
            "",
            "⚙️ <b>Протоколы</b>",
            "  /export_whitelist  /clear_session",
            "  /report  /tickets  /close_ticket",
            "  /stats  /health  /stopwords",
            "",
            "📄 <i>Отправляйте текст, фото, документы, голосовые или стикеры.</i>",
        ]
    else:
        lines = [
            "🤖 <b>J.A.R.V.I.S. — Commands</b>",
            "",
            "🟢 <b>Core</b>",
            "  /start  /help  /reset  /mode  /lang",
            "  /incognito  /incognito_off",
            "",
            "🎨 <b>Media</b>",
            "  /draw  /qr  /tts  /poll  /quiz",
            "  /speed  /screenshot  /translate  /summarize",
            "",
            "🛡 <b>Admin</b>",
            "  /admin  /add  /remove  /whitelist",
            "  /ban  /unban  /mute  /warn  /warnings",
            "  /broadcast  /send  /backup  /logs  /export_logs",
            "",
            "🧠 <b>AI Pro</b>",
            "  /review  /regex  /sql  /explain  /refactor",
            "  /uml  /pytest  /doc  /cv  /translate_long  /ask",
            "",
            "⚙️ <b>Protocols</b>",
            "  /export_whitelist  /clear_session",
            "  /report  /tickets  /close_ticket",
            "  /stats  /health  /stopwords",
            "",
            "📄 <i>Send text, images, docs, voice or stickers.</i>",
        ]
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def reset_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    track_command(uid, "/reset")
    USER_HISTORY.pop(uid, None)
    await update.message.reply_text(t(uid, "memory_cleared"))


async def mode_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    track_command(uid, "/mode")
    if not context.args:
        cur = USER_MODES.get(uid, "assistant")
        await update.message.reply_text(
            t(uid, "mode_current", cur=cur, modes=", ".join(SYSTEM_PROMPTS)),
            parse_mode=ParseMode.HTML,
        )
        return
    mode = context.args[0].lower()
    if mode not in SYSTEM_PROMPTS:
        await update.message.reply_text(t(uid, "unknown_mode"))
        return
    USER_MODES[uid] = mode
    USER_HISTORY.pop(uid, None)
    await update.message.reply_text(t(uid, "mode_switched", mode=mode), parse_mode=ParseMode.HTML)


async def incognito_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    INCOGNITO_USERS.add(uid)
    await update.message.reply_text(t(uid, "incog_on"))


async def incognito_off_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    INCOGNITO_USERS.discard(uid)
    await update.message.reply_text(t(uid, "incog_off"))


async def lang_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    track_command(uid, "/lang")
    if not context.args:
        cur = LANG.get(str(uid), "en")
        await update.message.reply_text(
            t(uid, "lang_current", cur=cur),
            reply_markup=lang_keyboard(),
            parse_mode=ParseMode.HTML,
        )
        return
    new = context.args[0].lower()
    if new not in ("ru", "en"):
        await update.message.reply_text(t(uid, "lang_unknown"))
        return
    LANG[str(uid)] = new
    save_lang()
    await update.message.reply_text(t(uid, "lang_switched", lang=new), parse_mode=ParseMode.HTML)


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    track_usage(uid)
    now = time.time()
    if uid in LAST_REQUEST and now - LAST_REQUEST[uid] < 2.0:
        await update.message.reply_text(t(uid, "slow_down"))
        return
    LAST_REQUEST[uid] = now

    msg_text = update.message.text or ""

    # Creator mention — respectful interception
    if is_owner_mention(msg_text) and uid != OWNER_ID:
        await update.message.reply_text(owner_reply(uid), parse_mode=ParseMode.HTML)
        return

    for w in STOP_WORDS:
        if w.lower() in msg_text.lower() and uid != OWNER_ID:
            try:
                await context.bot.send_message(
                    OWNER_ID,
                    f"⚠️ Stop-word triggered by <code>{uid}</code>: {msg_text[:200]}",
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass

    if update.message.reply_to_message and update.message.reply_to_message.text:
        msg_text = f"[Replying to: {update.message.reply_to_message.text}]\n\n{msg_text}"

    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    status = await update.message.reply_text(t(uid, "processing"), parse_mode=ParseMode.HTML)

    try:
        reply = await call_gemini(msg_text, uid)
        try:
            await status.edit_text(reply, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            try:
                await status.edit_text(reply)
            except Exception:
                await update.message.reply_text(reply[:4000])
    except Exception as e:
        logger.exception(f"Text handler error: {e}")
        await status.edit_text(t(uid, "req_error"))


# ============================================================
#  PHASE 2 — MEDIA
# ============================================================
async def draw_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    track_command(uid, "/draw")
    if not context.args:
        await update.message.reply_text("🎨 /draw <description>")
        return
    desc = " ".join(context.args)
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_PHOTO)
    status = await update.message.reply_text(t(uid, "draw_processing"), parse_mode=ParseMode.HTML)
    try:
        prompt = ("Convert this into a detailed English image-generation prompt. "
                  "Add composition, lighting, style, atmosphere, camera details. "
                  "Return ONLY the prompt: ") + desc
        enh = await call_gemini(prompt, uid, system_instruction="You output only prompts.")
        url = f"https://image.pollinations.ai/prompt/{urllib.parse.quote(enh.strip())}?width=1024&height=1024&nologo=true"
        r = requests.get(url, timeout=60)
        r.raise_for_status()
        if len(r.content) > 10 * 1024 * 1024:
            raise ValueError("File too large.")
        img = Image.open(io.BytesIO(r.content)).convert("RGB")
        img.thumbnail((1280, 1280))
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=85)
        out.seek(0)
        await update.message.reply_photo(photo=out)
        await status.delete()
    except Exception as e:
        logger.exception(f"Draw error: {e}")
        await status.edit_text(t(uid, "img_fail"))


async def qr_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    track_command(uid, "/qr")
    text = " ".join(context.args)
    if not text or len(text) > 1000:
        await update.message.reply_text("🔳 1-1000 chars.")
        return
    try:
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_PHOTO)
        img = qrcode.make(text)
        out = io.BytesIO()
        img.save(out, format="PNG")
        out.seek(0)
        await update.message.reply_photo(photo=out)
    except Exception as e:
        logger.exception(f"QR gen error: {e}")
        await update.message.reply_text(t(uid, "qr_fail"))


async def tts_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    track_command(uid, "/tts")
    text = " ".join(context.args)
    if not text or len(text) > 500:
        await update.message.reply_text("🔊 1-500 chars.")
        return
    try:
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.RECORD_VOICE)
        out = io.BytesIO()
        lang = "ru" if LANG.get(str(uid), "en") == "ru" else "en"
        gTTS(text=text, lang=lang).write_to_fp(out)
        out.seek(0)
        await update.message.reply_voice(voice=out)
    except Exception as e:
        logger.exception(f"TTS error: {e}")
        await update.message.reply_text(t(uid, "tts_fail"))


def _decode_qr_bytes(data: bytes) -> str:
    try:
        np_arr = np.frombuffer(bytes(data), np.uint8)
        img_cv = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        if img_cv is None:
            return ""
        detector = cv2.QRCodeDetector()
        qr_data, _, _ = detector.detectAndDecode(img_cv)
        return (qr_data or "").strip()
    except Exception:
        return ""


async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    track_usage(uid)
    try:
        f = await update.message.photo[-1].get_file()
        data = await f.download_as_bytearray()

        qr = _decode_qr_bytes(bytes(data))
        if qr:
            await update.message.reply_text(
                f"{t(uid, 'qr_decoded')}\n\n<code>{qr}</code>",
                parse_mode=ParseMode.HTML,
            )
            return

        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
        caption = update.message.caption or (
            "Опиши это изображение детально." if LANG.get(str(uid)) == "ru"
            else "Describe this image in detail."
        )
        part = types.Part.from_bytes(data=bytes(data), mime_type="image/jpeg")
        reply = await call_gemini(caption, uid, media_parts=[part])
        await update.message.reply_text(reply)
    except Exception as e:
        logger.exception(f"Photo handler error: {e}")
        await update.message.reply_text(t(uid, "img_analysis"))


async def sticker_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    try:
        if update.message.sticker.is_animated or update.message.sticker.is_video:
            return
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
        f = await update.message.sticker.get_file()
        data = await f.download_as_bytearray()
        img = Image.open(io.BytesIO(data)).convert("RGBA")
        out = io.BytesIO()
        img.save(out, format="PNG")
        part = types.Part.from_bytes(data=out.getvalue(), mime_type="image/png")
        reply = await call_gemini("Explain this sticker's meme context.", uid, media_parts=[part])
        await update.message.reply_text(reply)
    except Exception as e:
        logger.exception(f"Sticker handler error: {e}")
        await update.message.reply_text(t(uid, "sticker_fail"))


async def voice_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    track_usage(uid)
    try:
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
        f = await update.message.voice.get_file()
        data = await f.download_as_bytearray()
        part = types.Part.from_bytes(data=bytes(data), mime_type="audio/ogg")
        reply = await call_gemini(
            "Transcribe this audio and add a short insightful reaction or answer.",
            uid, media_parts=[part],
        )
        await update.message.reply_text(f"{t(uid, 'transcription')}\n\n{reply}", parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.exception(f"Voice handler error: {e}")
        await update.message.reply_text(t(uid, "audio_fail"))


async def document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    try:
        doc = update.message.document
        if doc.file_size > 10 * 1024 * 1024:
            await update.message.reply_text("⚠️ Max 10 MB.")
            return
        ext = os.path.splitext(doc.file_name)[1].lower()
        if ext not in (".txt", ".pdf", ".docx"):
            return

        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
        f = await doc.get_file()
        data = await f.download_as_bytearray()

        if ext == ".txt":
            text = data.decode("utf-8", errors="ignore")
        elif ext == ".pdf":
            reader = PdfReader(io.BytesIO(data))
            text = "".join(p.extract_text() or "" for p in reader.pages)
        else:
            d = docx.Document(io.BytesIO(data))
            text = "\n".join(p.text for p in d.paragraphs)

        text = text[:30000]
        if not text.strip():
            await update.message.reply_text(t(uid, "no_text"))
            return
        reply = await call_gemini(f"Summarize this document:\n\n{text}", uid)
        await update.message.reply_text(reply)
    except Exception as e:
        logger.exception(f"Doc handler error: {e}")
        await update.message.reply_text(t(uid, "doc_fail"))


async def poll_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    parts = [p.strip() for p in " ".join(context.args).split("|") if p.strip()]
    if len(parts) < 3 or len(parts) > 11:
        await update.message.reply_text("📊 /poll Q | Opt1 | Opt2 …")
        return
    try:
        await context.bot.send_poll(update.effective_chat.id, question=parts[0], options=parts[1:])
    except Exception as e:
        logger.exception(f"Poll error: {e}")


async def quiz_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    topic = " ".join(context.args) or "Random General Knowledge"
    try:
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
        prompt = (f"Generate a multiple choice quiz about {topic}. Return strict JSON: "
                  '{"question": "...", "options": ["A","B","C","D"], "correct_id": 0, "explanation": "..."}.')
        reply = await call_gemini(prompt, uid, json_mode=True, system_instruction="Output strictly valid JSON.")
        def _extract(text):
            s, e = text.find("{"), text.rfind("}")
            return text[s:e+1] if s != -1 and e != -1 else text
        try:
            data = json.loads(_extract(reply))
        except json.JSONDecodeError:
            reply = await call_gemini(prompt + " Return ONLY valid JSON.", uid, json_mode=True,
                                      system_instruction="Output strictly valid JSON.")
            data = json.loads(_extract(reply))
        await context.bot.send_poll(
            update.effective_chat.id,
            question=data["question"],
            options=data["options"],
            type=Poll.QUIZ,
            correct_option_id=data["correct_id"],
            explanation=data.get("explanation"),
        )
    except Exception as e:
        logger.exception(f"Quiz error: {e}")
        await update.message.reply_text("⚠️ Quiz generation error.")


async def speed_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    r = update.message.reply_to_message
    if not r or not r.voice:
        await update.message.reply_text(t(uid, "no_voice"))
        return
    if not context.args:
        return
    try:
        factor = float(context.args[0])
        if not 1.0 < factor <= 4.0:
            await update.message.reply_text("⚡ 1.1 – 4.0")
            return
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.RECORD_VOICE)
        f = await r.voice.get_file()
        data = await f.download_as_bytearray()
        audio = AudioSegment.from_file(io.BytesIO(data), format="ogg")
        fast = audio._spawn(audio.raw_data, overrides={"frame_rate": int(audio.frame_rate * factor)}).set_frame_rate(audio.frame_rate)
        out = io.BytesIO()
        fast.export(out, format="ogg", codec="libopus")
        out.seek(0)
        await update.message.reply_voice(voice=out)
    except Exception as e:
        logger.exception(f"Speed error: {e}")
        await update.message.reply_text(t(uid, "audio_fail"))


async def screenshot_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return
    url = context.args[0]
    if not url.startswith("http"):
        url = "https://" + url
    try:
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_PHOTO)
        r = requests.get(f"https://image.thum.io/get/width/1200/crop/900/{url}", timeout=30)
        r.raise_for_status()
        await update.message.reply_photo(photo=io.BytesIO(r.content))
    except Exception as e:
        logger.exception(f"Screenshot error: {e}")
        await update.message.reply_text("⚠️ Screenshot error.")


async def translate_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if len(context.args) < 2:
        return
    lang, text = context.args[0], " ".join(context.args[1:])
    try:
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
        reply = await call_gemini(f"Translate this to {lang}:\n\n{text}", uid,
                                  system_instruction="Return ONLY the translation.")
        await update.message.reply_text(reply)
    except Exception as e:
        logger.exception(f"Translate error: {e}")


async def summarize_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = ""
    if update.message.reply_to_message and update.message.reply_to_message.text:
        text = update.message.reply_to_message.text
    elif context.args:
        text = " ".join(context.args)
    if not text:
        return
    try:
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
        reply = await call_gemini(f"Summarize this text clearly:\n\n{text}", uid)
        await update.message.reply_text(reply)
    except Exception as e:
        logger.exception(f"Summarize error: {e}")


# ============================================================
#  PHASE 3 — ADMIN
# ============================================================
async def _do_ban(context, uid, reason, actor):
    if uid not in state["BANNED"]:
        state["BANNED"].append(uid)
    if uid in state["WHITELIST"]:
        state["WHITELIST"].remove(uid)
    save_state()
    log_mod_action(actor, uid, "BAN", reason)
    try:
        await context.bot.send_message(
            OWNER_ID,
            t(OWNER_ID, "ban_alert", uid=uid, reason=reason),
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass


@owner_only
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    lang = LANG.get(str(uid), "en")
    if lang == "ru":
        kb = [
            [KeyboardButton("👥 Белый список"), KeyboardButton("🚫 Баны")],
            [KeyboardButton("📊 Логи"),         KeyboardButton("📢 Рассылка")],
            [KeyboardButton("💾 Бэкап"),        KeyboardButton("ℹ️ Статус")],
        ]
    else:
        kb = [
            [KeyboardButton("👥 Whitelist"), KeyboardButton("🚫 Bans")],
            [KeyboardButton("📊 Logs"),      KeyboardButton("📢 Broadcast")],
            [KeyboardButton("💾 Backup"),    KeyboardButton("ℹ️ Status")],
        ]
    await update.message.reply_text(
        t(uid, "admin_panel"),
        reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True),
        parse_mode=ParseMode.HTML,
    )


@owner_only
async def admin_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text
    if   txt in ("👥 Whitelist", "👥 Белый список"): await whitelist_list(update, context)
    elif txt in ("🚫 Bans", "🚫 Баны"):               await _show_bans(update, context)
    elif txt in ("📊 Logs", "📊 Логи"):               await logs_cmd(update, context)
    elif txt in ("📢 Broadcast", "📢 Рассылка"):      await update.message.reply_text(t(update.effective_user.id, "use_broadcast"), parse_mode=ParseMode.HTML)
    elif txt in ("💾 Backup", "💾 Бэкап"):            await backup_cmd(update, context)
    elif txt in ("ℹ️ Status", "ℹ️ Статус"):          await health_cmd(update, context)


async def _show_bans(update, context):
    uid = update.effective_user.id
    if not state["BANNED"]:
        await update.message.reply_text(t(uid, "banned_empty"))
        return
    lines = [t(uid, "banned_header"), ""]
    for b in state["BANNED"]:
        lines.append(f"  • <code>{b}</code>")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


@owner_only
async def add_whitelist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("👥 /add <user_id> [duration|perm]")
        return
    try:
        uid = int(context.args[0])
    except ValueError:
        return
    if uid not in state["WHITELIST"]:
        state["WHITELIST"].append(uid)
    if len(context.args) >= 2:
        d = parse_duration(context.args[1])
        if d and d != "perm":
            state["WHITELIST_EXPIRY"][str(uid)] = (datetime.now() + d).isoformat()
    save_state()
    log_mod_action(OWNER_ID, uid, "ADD_WHITELIST", "manual")
    await update.message.reply_text(t(OWNER_ID, "user_added", uid=uid), parse_mode=ParseMode.HTML)


@owner_only
async def remove_whitelist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return
    try:
        uid = int(context.args[0])
    except ValueError:
        return
    if uid in state["WHITELIST"]:
        state["WHITELIST"].remove(uid)
    state["WHITELIST_EXPIRY"].pop(str(uid), None)
    save_state()
    await update.message.reply_text(t(OWNER_ID, "access_revoked", uid=uid), parse_mode=ParseMode.HTML)


@owner_only
async def whitelist_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not state["WHITELIST"]:
        await update.message.reply_text(t(uid, "wl_empty"))
        return
    lines = [t(uid, "wl_header"), ""]
    for w in state["WHITELIST"]:
        exp = state["WHITELIST_EXPIRY"].get(str(w), "∞")
        lines.append(f"  • <code>{w}</code>  ·  until {exp}")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private" and update.effective_user.id != OWNER_ID:
        return
    if not await check_group_permissions(update, context):
        return
    if not context.args:
        return
    try:
        uid = int(context.args[0])
    except ValueError:
        return
    rest = context.args[1:]
    duration = None
    if rest:
        d = parse_duration(rest[0])
        if d:
            duration, rest = d, rest[1:]
    reason = " ".join(rest) or "no reason"
    await _do_ban(context, uid, reason, update.effective_user.id)

    if duration and duration != "perm":
        state["BANNED_TIMED"][str(uid)] = (datetime.now() + duration).isoformat()
    else:
        state["BANNED_TIMED"].pop(str(uid), None)
    save_state()

    if update.effective_chat.type in ("group", "supergroup"):
        try:
            await context.bot.ban_chat_member(update.effective_chat.id, uid)
        except Exception as e:
            logger.error(f"Ban chat error: {e}")

    ts = "forever" if not duration or duration == "perm" else f"for {duration}"
    await update.message.reply_text(t(OWNER_ID, "user_banned", uid=uid, ts=ts, reason=reason), parse_mode=ParseMode.HTML)


async def unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private" and update.effective_user.id != OWNER_ID:
        return
    if not await check_group_permissions(update, context):
        return
    if not context.args:
        return
    try:
        uid = int(context.args[0])
    except ValueError:
        return
    if uid in state["BANNED"]:
        state["BANNED"].remove(uid)
    state["BANNED_TIMED"].pop(str(uid), None)
    save_state()
    if update.effective_chat.type in ("group", "supergroup"):
        try:
            await context.bot.unban_chat_member(update.effective_chat.id, uid)
        except Exception:
            pass
    await update.message.reply_text(t(OWNER_ID, "user_unbanned", uid=uid), parse_mode=ParseMode.HTML)


async def mute_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private" and update.effective_user.id != OWNER_ID:
        return
    if not await check_group_permissions(update, context):
        return
    if len(context.args) < 2:
        await update.message.reply_text("🔇 /mute <user_id> <duration|perm>")
        return
    try:
        uid = int(context.args[0])
    except ValueError:
        return
    d = parse_duration(context.args[1])
    if not d:
        return
    exp = datetime.now() + (timedelta(days=36500) if d == "perm" else d)
    state["MUTED"][str(uid)] = exp.isoformat()
    save_state()
    log_mod_action(update.effective_user.id, uid, "MUTE", context.args[1])
    await update.message.reply_text(
        t(OWNER_ID, "user_muted", uid=uid, until=exp.strftime("%Y-%m-%d %H:%M")),
        parse_mode=ParseMode.HTML,
    )


async def warn_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private" and update.effective_user.id != OWNER_ID:
        return
    if not await check_group_permissions(update, context):
        return
    if len(context.args) < 2:
        return
    try:
        uid = int(context.args[0])
    except ValueError:
        return
    reason = " ".join(context.args[1:])
    wl = state["WARNINGS"].setdefault(str(uid), [])
    wl.append({"reason": reason, "by": update.effective_user.id, "at": datetime.now().isoformat()})
    save_state()
    log_mod_action(update.effective_user.id, uid, "WARN", reason)
    await update.message.reply_text(
        t(OWNER_ID, "user_warned", uid=uid, count=len(wl), reason=reason),
        parse_mode=ParseMode.HTML,
    )
    if len(wl) >= 3:
        await _do_ban(context, uid, "auto-ban: 3 warnings", update.effective_user.id)
        await update.message.reply_text(t(OWNER_ID, "auto_banned", uid=uid), parse_mode=ParseMode.HTML)


async def warnings_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private" and update.effective_user.id != OWNER_ID:
        return
    if not await check_group_permissions(update, context):
        return
    if not context.args:
        return
    uid = str(context.args[0])
    warns = state["WARNINGS"].get(uid, [])
    if not warns:
        await update.message.reply_text(t(OWNER_ID, "no_warnings"))
        return
    lines = [t(OWNER_ID, "warns_header", uid=uid), ""]
    for i, w in enumerate(warns, 1):
        lines.append(f"  {i}. {w['at'][:16]} │ by {w['by']} │ {w['reason']}")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


@owner_only
async def broadcast_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args)
    if not text:
        return
    sent = failed = 0
    for u in state["WHITELIST"]:
        try:
            await context.bot.send_message(u, f"📢 <b>Broadcast</b>\n\n{text}", parse_mode=ParseMode.HTML)
            sent += 1
        except Exception:
            failed += 1
    await update.message.reply_text(
        t(OWNER_ID, "broadcast_done", sent=sent, failed=failed),
        parse_mode=ParseMode.HTML,
    )


@owner_only
async def send_direct(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        return
    try:
        uid = int(context.args[0])
    except ValueError:
        return
    text = " ".join(context.args[1:])
    try:
        await context.bot.send_message(uid, text)
        await update.message.reply_text(t(OWNER_ID, "msg_delivered"))
    except Exception as e:
        await update.message.reply_text(f"⚠️ Error: {e}")


@owner_only
async def backup_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    zip_name = "jarvis_backup.zip"
    with zipfile.ZipFile(zip_name, "w") as z:
        for f in ("main.py", "requirements.txt", "whitelist.json", "config.json", "tickets.json", "usage_stats.json"):
            if os.path.exists(f):
                z.write(f)
    await update.message.reply_document(document=open(zip_name, "rb"), filename=zip_name)
    os.remove(zip_name)


@owner_only
async def logs_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not os.path.exists("bot.log"):
        return
    with open("bot.log", "r", encoding="utf-8") as f:
        tail = f.readlines()[-35:]
    text = "".join(tail)[-4000:]
    await update.message.reply_text(
        f"{t(OWNER_ID, 'logs_header')}\n\n<pre>{text}</pre>",
        parse_mode=ParseMode.HTML,
    )


@owner_only
async def export_logs_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if os.path.exists("bot.log"):
        await update.message.reply_document(document=open("bot.log", "rb"))


# ============================================================
#  PHASE 4 — ADVANCED AI
# ============================================================
async def _ai(update, context, instruction, need_reply=False):
    uid = update.effective_user.id
    if need_reply:
        r = update.message.reply_to_message
        if not r or not (r.text or r.caption):
            await update.message.reply_text(t(uid, "no_reply"))
            return
        text = r.text or r.caption
    else:
        text = " ".join(context.args)
    if not text and not need_reply:
        await update.message.reply_text("✏️ Provide arguments.")
        return
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    status = await update.message.reply_text(t(uid, "processing"), parse_mode=ParseMode.HTML)
    try:
        reply = await call_gemini(f"{instruction}\n\nINPUT:\n{text}", uid)
        try:
            await status.edit_text(reply[:4000], parse_mode=ParseMode.MARKDOWN)
        except Exception:
            await status.edit_text(reply[:4000])
        for i in range(4000, len(reply), 4000):
            await update.message.reply_text(reply[i:i+4000])
    except Exception as e:
        logger.exception(f"AI cmd error: {e}")
        await status.edit_text(t(uid, "req_error"))


async def review_cmd(update, context):
    await _ai(update, context, "Review this code. List bugs, security issues, style problems. Suggest fixes with examples.", need_reply=True)

async def regex_cmd(update, context):
    await _ai(update, context, "Generate a regex pattern for the described task. Return ONLY the pattern and one test example.")

async def sql_cmd(update, context):
    await _ai(update, context, "Write a SQL query for the described task. Add a one-line explanation.")

async def explain_cmd(update, context):
    await _ai(update, context, "Explain this code line by line in Russian. Be concise.", need_reply=True)

async def refactor_cmd(update, context):
    await _ai(update, context, "Refactor this code for readability and performance. Return optimized version + change list.", need_reply=True)

async def uml_cmd(update, context):
    await _ai(update, context, "Return a PlantUML text diagram for the described or given code.")

async def pytest_cmd(update, context):
    await _ai(update, context, "Generate a complete pytest file with test cases for this code. Return only Python code.", need_reply=True)

async def doc_cmd(update, context):
    await _ai(update, context, "Return this code with PEP-8 docstrings and inline comments added. Preserve logic.", need_reply=True)

async def cv_cmd(update, context):
    await _ai(update, context, "Structure the following raw bio into a professional Markdown CV: Summary, Experience, Skills, Education.")

async def translate_long_cmd(update, context):
    if len(context.args) < 2:
        await update.message.reply_text("🌐 /translate_long <lang> <text>")
        return
    lang, text = context.args[0], " ".join(context.args[1:])
    await _ai(update, context, f"Translate the following into {lang}. Preserve formatting.")

async def ask_cmd(update, context):
    uid = update.effective_user.id
    r = update.message.reply_to_message
    if not r or not r.text:
        await update.message.reply_text(t(uid, "no_reply"))
        return
    q = " ".join(context.args)
    doc = r.text[:30000]
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    status = await update.message.reply_text(t(uid, "processing"), parse_mode=ParseMode.HTML)
    try:
        reply = await call_gemini(f"Answer based ONLY on this document.\n\n{doc}\n\nQ: {q}", uid)
        await status.edit_text(reply[:4000])
    except Exception as e:
        logger.exception(f"Ask error: {e}")
        await status.edit_text(t(uid, "req_error"))


# ============================================================
#  PHASE 5 — SPECIAL PROTOCOLS
# ============================================================
@owner_only
async def export_whitelist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    payload = {
        "whitelist": state["WHITELIST"],
        "expiry":    state["WHITELIST_EXPIRY"],
        "exported_at": datetime.now().isoformat(),
    }
    _atomic_write_json("whitelist_export.json", payload)
    await update.message.reply_document(document=open("whitelist_export.json", "rb"))
    os.remove("whitelist_export.json")


@owner_only
async def clear_session_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    USER_HISTORY.clear()
    USER_MODES.clear()
    INCOGNITO_USERS.clear()
    LAST_REQUEST.clear()
    await update.message.reply_text(t(OWNER_ID, "session_purged"))


async def report_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = " ".join(context.args)
    if not text:
        await update.message.reply_text("📩 /report <issue>")
        return
    ticket = {
        "id": len(TICKETS) + 1,
        "user_id": uid,
        "username": update.effective_user.username,
        "text": text,
        "status": "open",
        "at": datetime.now().isoformat(),
    }
    TICKETS.append(ticket)
    save_tickets()
    await update.message.reply_text(t(uid, "report_created", tid=ticket["id"]), parse_mode=ParseMode.HTML)
    try:
        await context.bot.send_message(
            OWNER_ID,
            f"📩 Ticket #{ticket['id']} from <code>{ticket['user_id']}</code>: {text}",
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass


@owner_only
async def tickets_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    opens = [x for x in TICKETS if x.get("status") == "open"]
    if not opens:
        await update.message.reply_text(t(OWNER_ID, "tickets_empty"))
        return
    lines = [t(OWNER_ID, "tickets_header"), ""]
    for x in opens[:20]:
        lines.append(f"  #{x['id']}  │  <code>{x['user_id']}</code>  │  {x['text'][:60]}")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


@owner_only
async def close_ticket_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return
    try:
        tid = int(context.args[0])
    except ValueError:
        return
    for x in TICKETS:
        if x["id"] == tid:
            x["status"] = "closed"
            save_tickets()
            await update.message.reply_text(t(OWNER_ID, "ticket_closed", tid=tid))
            return
    await update.message.reply_text(t(OWNER_ID, "ticket_not_found"))


@owner_only
async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    top = sorted(USER_STATS.items(), key=lambda kv: kv[1].get("messages", 0), reverse=True)[:10]
    if not top:
        await update.message.reply_text(t(OWNER_ID, "stats_empty"))
        return
    lines = [t(OWNER_ID, "stats_header"), ""]
    for uid, s in top:
        lines.append(f"  <code>{uid}</code>  ·  {s.get('messages',0)} msgs  ·  {s.get('commands',0)} cmds")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


@owner_only
async def health_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        cpu = psutil.cpu_percent(interval=0.5)
        ram = psutil.virtual_memory().percent
        dsk = psutil.disk_usage("/").percent
        up  = int(time.time() - STARTED_AT)
        h, m, s = up // 3600, (up % 3600) // 60, up % 60
        msg = (
            f"{t(OWNER_ID, 'health_header')}\n\n"
            f"  CPU    │ {cpu}%\n"
            f"  RAM    │ {ram}%\n"
            f"  Disk   │ {dsk}%\n"
            f"  Uptime │ {h}h {m}m {s}s"
        )
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.exception(f"Health error: {e}")
        await update.message.reply_text(t(OWNER_ID, "health_fail"))


@owner_only
async def stopwords_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(t(OWNER_ID, "stopwords_list", words=", ".join(STOP_WORDS)))
        return
    action = context.args[0].lower()
    if action == "add" and len(context.args) > 1:
        STOP_WORDS.append(" ".join(context.args[1:]))
        await update.message.reply_text(t(OWNER_ID, "stopword_added"))
    elif action == "remove" and len(context.args) > 1:
        w = " ".join(context.args[1:])
        if w in STOP_WORDS:
            STOP_WORDS.remove(w)
        await update.message.reply_text(t(OWNER_ID, "stopword_removed"))


# ============================================================
#  SECURITY MIDDLEWARE + BACKGROUND JOBS
# ============================================================
async def cleanup_expired_job(context):
    now = datetime.now()
    changed = False

    for u in [k for k, v in list(state["WHITELIST_EXPIRY"].items()) if now > datetime.fromisoformat(v)]:
        try:
            state["WHITELIST"].remove(int(u))
        except ValueError:
            pass
        state["WHITELIST_EXPIRY"].pop(u, None)
        changed = True

    for u in [k for k, v in list(state.get("BANNED_TIMED", {}).items()) if now > datetime.fromisoformat(v)]:
        try:
            state["BANNED"].remove(int(u))
        except ValueError:
            pass
        state["BANNED_TIMED"].pop(u, None)
        changed = True

    for u in [k for k, v in list(state["MUTED"].items()) if now > datetime.fromisoformat(v)]:
        state["MUTED"].pop(u, None)
        changed = True

    if changed:
        save_state()


async def auto_backup_job(context):
    try:
        name = f"auto_backup_{datetime.now():%Y%m%d_%H%M}.zip"
        with zipfile.ZipFile(name, "w") as z:
            for f in ("main.py", "requirements.txt", "whitelist.json", "config.json"):
                if os.path.exists(f):
                    z.write(f)
        await context.bot.send_document(OWNER_ID, document=open(name, "rb"), filename=name)
        os.remove(name)
    except Exception as e:
        logger.exception(f"Auto-backup error: {e}")


async def global_security_middleware(update: Update, context):
    if not update.effective_user or not update.message:
        return
    uid = update.effective_user.id
    suid = str(uid)
    now = datetime.now()

    if suid in state["MUTED"]:
        if now > datetime.fromisoformat(state["MUTED"][suid]):
            state["MUTED"].pop(suid, None)
            save_state()
        else:
            raise ApplicationHandlerStop

    if uid in state["BANNED"]:
        raise ApplicationHandlerStop

    now_ts = time.time()
    bucket = [x for x in FLOOD_WINDOW.get(uid, []) if now_ts - x < 60]
    bucket.append(now_ts)
    FLOOD_WINDOW[uid] = bucket
    if len(bucket) > 10 and uid != OWNER_ID:
        try:
            await context.bot.send_message(
                OWNER_ID,
                t(OWNER_ID, "flood_detected", uid=uid),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        state["MUTED"][suid] = (datetime.now() + timedelta(minutes=5)).isoformat()
        save_state()
        raise ApplicationHandlerStop

    if uid != OWNER_ID and uid not in state["WHITELIST"]:
        entry = {
            "first_name":   update.effective_user.first_name,
            "last_name":    update.effective_user.last_name,
            "user_id":      uid,
            "username":     update.effective_user.username,
            "chat_id":      update.effective_chat.id,
            "timestamp":    now.isoformat(),
            "text_preview": (update.message.text or "[Media]")[:100],
        }
        logs = []
        if os.path.exists(INTRUDER_FILE):
            try:
                with open(INTRUDER_FILE, "r", encoding="utf-8") as f:
                    logs = json.load(f)
            except json.JSONDecodeError:
                pass
        logs.append(entry)
        _atomic_write_json(INTRUDER_FILE, logs)

        alert = (
            f"{t(OWNER_ID, 'unauthorized')}\n\n"
            f"  ID    │ <code>{uid}</code>\n"
            f"  User  │ @{entry['username']} ({entry['first_name']})\n"
            f"  Chat  │ <code>{entry['chat_id']}</code>\n"
            f"  Query │ {entry['text_preview']}"
        )
        try:
            await context.bot.send_message(OWNER_ID, alert, parse_mode=ParseMode.HTML)
        except Exception:
            pass
        raise ApplicationHandlerStop


# ============================================================
#  FLASK KEEPALIVE + MAIN
# ============================================================
async def post_init(application: Application):
    await application.bot.delete_webhook(drop_pending_updates=True)
    logger.info("Webhooks cleared. J.A.R.V.I.S. Systems Online. Boss: Silent.")


def run_flask():
    flask_app = Flask(__name__)

    @flask_app.route("/")
    @flask_app.route("/health")
    def health():
        return "J.A.R.V.I.S. is alive", 200

    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(TypeHandler(Update, global_security_middleware), group=-1)
    app.job_queue.run_repeating(cleanup_expired_job, interval=60)
    app.job_queue.run_repeating(auto_backup_job, interval=7 * 24 * 3600, first=10)

    app.add_handler(CallbackQueryHandler(on_lang_callback, pattern=r"^lang_(ru|en)$"))

    for cmd, fn in [
        ("start", start), ("help", help_cmd), ("reset", reset_cmd),
        ("mode", mode_cmd), ("lang", lang_cmd),
        ("incognito", incognito_cmd), ("incognito_off", incognito_off_cmd),
    ]:
        app.add_handler(CommandHandler(cmd, fn))

    for cmd, fn in [
        ("draw", draw_cmd), ("qr", qr_cmd), ("tts", tts_cmd),
        ("poll", poll_cmd), ("quiz", quiz_cmd), ("speed", speed_cmd),
        ("screenshot", screenshot_cmd), ("translate", translate_cmd),
        ("summarize", summarize_cmd),
    ]:
        app.add_handler(CommandHandler(cmd, fn))

    app.add_handler(MessageHandler(filters.PHOTO,        photo_handler))
    app.add_handler(MessageHandler(filters.Sticker.ALL,  sticker_handler))
    app.add_handler(MessageHandler(filters.VOICE,        voice_handler))
    app.add_handler(MessageHandler(filters.Document.ALL, document_handler))

    for cmd, fn in [
        ("admin", admin_panel), ("add", add_whitelist), ("remove", remove_whitelist),
        ("whitelist", whitelist_list), ("ban", ban_user), ("unban", unban_user),
        ("mute", mute_user), ("warn", warn_user), ("warnings", warnings_list),
        ("broadcast", broadcast_msg), ("send", send_direct), ("backup", backup_cmd),
        ("logs", logs_cmd), ("export_logs", export_logs_cmd),
    ]:
        app.add_handler(CommandHandler(cmd, fn))

    app.add_handler(MessageHandler(
        filters.Regex(r"^(👥 Whitelist|🚫 Bans|📊 Logs|📢 Broadcast|💾 Backup|ℹ️ Status|👥 Белый список|🚫 Баны|📊 Логи|📢 Рассылка|💾 Бэкап|ℹ️ Статус)$"),
        admin_buttons,
    ))

    for cmd, fn in [
        ("review", review_cmd), ("regex", regex_cmd), ("sql", sql_cmd),
        ("explain", explain_cmd), ("refactor", refactor_cmd), ("uml", uml_cmd),
        ("pytest", pytest_cmd), ("doc", doc_cmd), ("cv", cv_cmd),
        ("translate_long", translate_long_cmd), ("ask", ask_cmd),
    ]:
        app.add_handler(CommandHandler(cmd, fn))

    for cmd, fn in [
        ("export_whitelist", export_whitelist_cmd), ("clear_session", clear_session_cmd),
        ("report", report_cmd), ("tickets", tickets_cmd), ("close_ticket", close_ticket_cmd),
        ("stats", stats_cmd), ("health", health_cmd), ("stopwords", stopwords_cmd),
    ]:
        app.add_handler(CommandHandler(cmd, fn))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    logger.info("Starting polling...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    logger.info("Flask keepalive started.")
    main() "wl_header":      "👥 <b>Authorized users</b>",
        "banned_empty":   "✅ Ban list is empty.",
        "banned_header":  "🚫 <b>Banned IDs</b>",
        "access_revoked": "🗑 Access revoked for ID <code>{uid}</code>.",
        "user_added":     "✅ User <code>{uid}</code> added to whitelist.",
        "user_banned":    "🚫 <code>{uid}</code> banned ({ts}). Reason: {reason}",
        "user_unbanned":  "✅ <code>{uid}</code> unbanned.",
        "user_muted":     "🔇 <code>{uid}</code> muted until {until}.",
        "user_warned":    "⚠️ Warning <b>{count}/3</b> to <code>{uid}</code>.\nReason: {reason}",
        "auto_banned":    "🚨 Auto-ban applied to <code>{uid}</code>.",
        "no_warnings":    "✅ No warnings.",
        "warns_header":   "⚠️ <b>Warnings for <code>{uid}</code></b>",
        "broadcast_done": "📢 Sent: <b>{sent}</b>  │  Failed: <b>{failed}</b>",
        "msg_delivered":  "✅ Message delivered.",
        "use_broadcast":  "📢 Use: /broadcast &lt;text&gt;",
        "backup_ready":   "💾 Backup ready.",
        "logs_header":    "📊 <b>Recent events</b>",
        "unauthorized":   "🚨 <b>UNAUTHORIZED ACCESS</b>",
        "flood_detected": "🌊 Flood from <code>{uid}</code>. Auto-mute 5m.",
        "ban_alert":      "🚨 Ban applied to <code>{uid}</code>. Reason: {reason}",

        "img_fail":       "⚠️ Graphics subsystem failure.",
        "qr_fail":        "⚠️ QR generation failure.",
        "tts_fail":       "⚠️ Speech synthesis error.",
        "img_analysis":   "⚠️ Image analysis error.",
        "sticker_fail":   "⚠️ Sticker analysis error.",
        "audio_fail":     "⚠️ Audio processing error.",
        "doc_fail":       "⚠️ Document analysis error.",
        "no_text":        "⚠️ Could not extract text.",
        "no_voice":       "↩️ Reply to a voice message.",
        "no_reply":       "↩️ Reply to a message first.",
        "draw_processing":"🎨 <i>Drawing…</i>",
        "qr_decoded":     "🔳 <b>QR decoded</b>",
        "transcription":  "🎙 <b>Transcription</b>",

        "report_created": "✅ Ticket <b>#{tid}</b> created.",
        "tickets_empty":  "📭 No open tickets.",
        "tickets_header": "📋 <b>Open tickets</b>",
        "ticket_closed":  "✅ Ticket #{tid} closed.",
        "ticket_not_found":"❌ Ticket not found.",
        "stats_header":   "📊 <b>Top users</b>",
        "stats_empty":    "📊 No data yet.",
        "health_header":  "💻 <b>System Health</b>",
        "health_fail":    "⚠️ Health check failed.",
        "session_purged": "🧹 Session memory purged.",
        "export_ready":   "📤 File ready.",
        "stopwords_list": "🛑 Stop-words: {words}",
        "stopword_added": "✅ Added.",
        "stopword_removed":"🗑 Removed (if existed).",
    },
}

def t(uid, key, **kw):
    """Get localized string for a user, default 'en'."""
    lang = LANG.get(str(uid), "en")
    s = TEXTS.get(lang, TEXTS["en"]).get(key, key)
    try:
        return s.format(**kw) if kw else s
    except Exception:
        return s

def save_lang():
    state["LANG"] = LANG
    save_state()


# ══════════════════════════════════════════════════════════════════════
#  UTILS
# ══════════════════════════════════════════════════════════════════════
def _atomic_write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False, default=str)
    os.replace(tmp, path)

def save_state():   _atomic_write_json(DATA_FILE, state)
def save_stats():   _atomic_write_json(STATS_FILE, USER_STATS)
def save_tickets(): _atomic_write_json(TICKETS_FILE, TICKETS)

def log_mod_action(actor, target, action, reason):
    logger.info(f"MOD │ {action:<15} │ by={actor} on={target} │ {reason}")

def parse_duration(s):
    if s.lower() == "perm": return "perm"
    m = re.match(r"^(\d+)([smhd])$", s.lower())
    if not m: return None
    v, u = int(m.group(1)), m.group(2)
    return {"s": timedelta(seconds=v), "m": timedelta(minutes=v),
            "h": timedelta(hours=v),   "d": timedelta(days=v)}[u]

def track_usage(uid):
    s = USER_STATS.setdefault(str(uid), {"messages": 0, "commands": 0, "last_seen": None})
    s["messages"] += 1
    s["last_seen"] = datetime.now().isoformat()

def track_command(uid, cmd):
    s = USER_STATS.setdefault(str(uid), {"messages": 0, "commands": 0, "last_seen": None})
    s["commands"] += 1
    s["last_seen"] = datetime.now().isoformat()

def owner_only(func):
    async def wrapper(update, context, *a, **kw):
        if update.effective_user.id != OWNER_ID:
            return
        return await func(update, context, *a, **kw)
    return wrapper

async def check_group_permissions(update, context):
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        return True
    try:
        bot_m = await context.bot.get_chat_member(chat.id, context.bot.id)
        if bot_m.status not in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER):
            await update.message.reply_text("Sir, I don't have admin rights in this group.")
            return False
        if update.effective_user.id == OWNER_ID:
            return True
        u_m = await context.bot.get_chat_member(chat.id, update.effective_user.id)
        if u_m.status not in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER):
            await update.message.reply_text("Access denied. Group admin rights required.")
            return False
        return True
    except Exception as e:
        logger.error(f"Permissions error: {e}")
        return False


# ══════════════════════════════════════════════════════════════════════
#  GEMINI CLIENT
# ══════════════════════════════════════════════════════════════════════
ai_client = None
try:
    ai_client = genai.Client(api_key=GEMINI_API_KEY)
    logger.info("AI Matrix initialized.")
except Exception as e:
    logger.error(f"Failed to init Gemini: {e}")

SYSTEM_PROMPTS = {
    "assistant":    "You are J.A.R.V.I.S., a highly intelligent, polite, and efficient AI assistant. Keep responses clear and structured.",
    "tutor":        "You are a patient English tutor. Correct mistakes, explain grammar, give examples. Reply in Russian for explanations, English for examples.",
    "programmer":   "You are a senior software engineer. Provide optimized, secure code with brief explanations. Focus on best practices.",
    "psychologist": "You are an empathetic, non-judgmental active listener. Offer supportive and grounded insights. Never diagnose.",
}


async def call_gemini(prompt_text, user_id, system_instruction=None, media_parts=None, json_mode=False):
    if not ai_client:
        return t(user_id, "gemini_down")
    try:
        mode = USER_MODES.get(user_id, "assistant")
        sys_inst = system_instruction or SYSTEM_PROMPTS.get(mode, SYSTEM_PROMPTS["assistant"])

        contents = []
        if user_id not in INCOGNITO_USERS and user_id in USER_HISTORY:
            for msg in USER_HISTORY[user_id]:
                contents.append(types.Content(
                    role=msg["role"],
                    parts=[types.Part.from_text(text=msg["parts"][0]["text"])],
                ))

        parts = list(media_parts or [])
        parts.append(types.Part.from_text(text=prompt_text))
        contents.append(types.Content(role="user", parts=parts))

        cfg = {"system_instruction": sys_inst}
        if json_mode:
            cfg["response_mime_type"] = "application/json"
        gen_cfg = types.GenerateContentConfig(**cfg)

        resp = ai_client.models.generate_content(
            model=GEMINI_MODEL, contents=contents, config=gen_cfg,
        )
        res_text = resp.text or t(user_id, "gemini_down")

        if user_id not in INCOGNITO_USERS and not media_parts and not json_mode:
            hist = USER_HISTORY.setdefault(user_id, [])
            hist.append({"role": "user",  "parts": [{"text": prompt_text}]})
            hist.append({"role": "model", "parts": [{"text": res_text}]})

            if len(hist) > 20:
                try:
                    sc = contents.copy()
                    sc.append(types.Content(
                        role="user",
                        parts=[types.Part.from_text(text="Summarize this conversation preserving all key facts, names, code links, decisions.")],
                    ))
                    summary = ai_client.models.generate_content(model=GEMINI_MODEL, contents=sc)
                    USER_HISTORY[user_id] = [
                        {"role": "user",  "parts": [{"text": "Previous context summary."}]},
                        {"role": "model", "parts": [{"text": summary.text}]},
                    ]
                except Exception:
                    USER_HISTORY[user_id] = hist[-10:]
        return res_text

    except Exception as e:
        logger.exception(f"Gemini error UID={user_id}: {e}")
        if user_id == OWNER_ID:
            try:
                r = requests.get(
                    f"https://text.pollinations.ai/{urllib.parse.quote(prompt_text[:500])}",
                    timeout=30,
                )
                if r.status_code == 200 and r.text.strip():
                    return r.text.strip()
            except Exception as fe:
                logger.exception(f"Fallback error: {fe}")
        return t(user_id, "gemini_down")


# ══════════════════════════════════════════════════════════════════════
#  HELPERS: language keyboard
# ══════════════════════════════════════════════════════════════════════
def lang_keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🇷🇺 Русский", callback_data="lang_ru"),
        InlineKeyboardButton("🇬🇧 English", callback_data="lang_en"),
    ]])


async def on_lang_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = update.effective_user.id
    data = q.data
    if data == "lang_ru":
        LANG[str(uid)] = "ru"
        save_lang()
        try:
            await q.edit_message_text(t(uid, "lang_set"), parse_mode=ParseMode.HTML)
        except Exception:
            await q.message.reply_text(t(uid, "lang_set"), parse_mode=ParseMode.HTML)
    elif data == "lang_en":
        LANG[str(uid)] = "en"
        save_lang()
        try:
            await q.edit_message_text(t(uid, "lang_set"), parse_mode=ParseMode.HTML)
        except Exception:
            await q.message.reply_text(t(uid, "lang_set"), parse_mode=ParseMode.HTML)


# ══════════════════════════════════════════════════════════════════════
#  PHASE 1 — AI CORE
# ══════════════════════════════════════════════════════════════════════
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    track_command(uid, "/start")

    # If user has no language yet — show welcome + language chooser
    if str(uid) not in LANG:
        welcome = "🤖 <b>J.A.R.V.I.S.</b>\n\nВыберите язык / Choose your language"
        await update.message.reply_text(
            welcome,
            reply_markup=lang_keyboard(),
            parse_mode=ParseMode.HTML,
        )
        return

    await update.message.reply_text(
        t(uid, "welcome_owner" if uid == OWNER_ID else "welcome_other"),
        parse_mode=ParseMode.HTML,
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if LANG.get(str(uid), "en") == "ru":
        lines = [
            "🤖 <b>J.A.R.V.I.S. — Команды</b>",
            "",
            "🟢 <b>Ядро</b>",
            "  /start  /help  /reset  /mode  /lang",
            "  /incognito  /incognito_off",
            "",
            "🎨 <b>Медиа</b>",
            "  /draw  /qr  /tts  /poll  /quiz",
            "  /speed  /screenshot  /translate  /summarize",
            "",
            "🛡 <b>Админ</b>",
            "  /admin  /add  /remove  /whitelist",
            "  /ban  /unban  /mute  /warn  /warnings",
            "  /broadcast  /send  /backup  /logs  /export_logs",
            "",
            "🧠 <b>AI Pro</b>",
            "  /review  /regex  /sql  /explain  /refactor",
            "  /uml  /pytest  /doc  /cv  /translate_long  /ask",
            "",
            "⚙️ <b>Протоколы</b>",
            "  /export_whitelist  /clear_session",
            "  /report  /tickets  /close_ticket",
            "  /stats  /health  /stopwords",
            "",
            "📄 <i>Отправляйте текст, фото, документы, голосовые или стикеры.</i>",
        ]
    else:
        lines = [
            "🤖 <b>J.A.R.V.I.S. — Commands</b>",
            "",
            "🟢 <b>Core</b>",
            "  /start  /help  /reset  /mode  /lang",
            "  /incognito  /incognito_off",
            "",
            "🎨 <b>Media</b>",
            "  /draw  /qr  /tts  /poll  /quiz",
            "  /speed  /screenshot  /translate  /summarize",
            "",
            "🛡 <b>Admin</b>",
            "  /admin  /add  /remove  /whitelist",
            "  /ban  /unban  /mute  /warn  /warnings",
            "  /broadcast  /send  /backup  /logs  /export_logs",
            "",
            "🧠 <b>AI Pro</b>",
            "  /review  /regex  /sql  /explain  /refactor",
            "  /uml  /pytest  /doc  /cv  /translate_long  /ask",
            "",
            "⚙️ <b>Protocols</b>",
            "  /export_whitelist  /clear_session",
            "  /report  /tickets  /close_ticket",
            "  /stats  /health  /stopwords",
            "",
            "📄 <i>Send text, images, docs, voice or stickers.</i>",
        ]
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def reset_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    track_command(uid, "/reset")
    USER_HISTORY.pop(uid, None)
    await update.message.reply_text(t(uid, "memory_cleared"))


async def mode_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    track_command(uid, "/mode")
    if not context.args:
        cur = USER_MODES.get(uid, "assistant")
        await update.message.reply_text(
            t(uid, "mode_current", cur=cur, modes=", ".join(SYSTEM_PROMPTS)),
            parse_mode=ParseMode.HTML,
        )
        return
    mode = context.args[0].lower()
    if mode not in SYSTEM_PROMPTS:
        await update.message.reply_text(t(uid, "unknown_mode"))
        return
    USER_MODES[uid] = mode
    USER_HISTORY.pop(uid, None)
    await update.message.reply_text(t(uid, "mode_switched", mode=mode), parse_mode=ParseMode.HTML)


async def incognito_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    INCOGNITO_USERS.add(uid)
    await update.message.reply_text(t(uid, "incog_on"))


async def incognito_off_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    INCOGNITO_USERS.discard(uid)
    await update.message.reply_text(t(uid, "incog_off"))


async def lang_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    track_command(uid, "/lang")
    if not context.args:
        cur = LANG.get(str(uid), "en")
        # show inline keyboard too
        await update.message.reply_text(
            t(uid, "lang_current", cur=cur),
            reply_markup=lang_keyboard(),
            parse_mode=ParseMode.HTML,
        )
        return
    new = context.args[0].lower()
    if new not in ("ru", "en"):
        await update.message.reply_text(t(uid, "lang_unknown"))
        return
    LANG[str(uid)] = new
    save_lang()
    await update.message.reply_text(t(uid, "lang_switched", lang=new), parse_mode=ParseMode.HTML)


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    track_usage(uid)
    now = time.time()
    if uid in LAST_REQUEST and now - LAST_REQUEST[uid] < 2.0:
        await update.message.reply_text(t(uid, "slow_down"))
        return
    LAST_REQUEST[uid] = now

    msg_text = update.message.text or ""
    for w in STOP_WORDS:
        if w.lower() in msg_text.lower() and uid != OWNER_ID:
            try:
                await context.bot.send_message(
                    OWNER_ID,
                    f"⚠️ Stop-word triggered by <code>{uid}</code>: {msg_text[:200]}",
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass

    if update.message.reply_to_message and update.message.reply_to_message.text:
        msg_text = f"[Replying to: {update.message.reply_to_message.text}]\n\n{msg_text}"

    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    status = await update.message.reply_text(t(uid, "processing"), parse_mode=ParseMode.HTML)

    try:
        reply = await call_gemini(msg_text, uid)
        try:
            await status.edit_text(reply, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            try:
                await status.edit_text(reply)
            except Exception:
                await update.message.reply_text(reply[:4000])
    except Exception as e:
        logger.exception(f"Text handler error: {e}")
        await status.edit_text(t(uid, "req_error"))


# ══════════════════════════════════════════════════════════════════════
#  PHASE 2 — MEDIA
# ══════════════════════════════════════════════════════════════════════
async def draw_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    track_command(uid, "/draw")
    if not context.args:
        await update.message.reply_text("🎨 /draw &lt;description&gt;", parse_mode=ParseMode.HTML)
        return
    desc = " ".join(context.args)
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_PHOTO)
    status = await update.message.reply_text(t(uid, "draw_processing"), parse_mode=ParseMode.HTML)
    try:
        prompt = ("Convert this into a detailed English image-generation prompt. "
                  "Add composition, lighting, style, atmosphere, camera details. "
                  "Return ONLY the prompt: ") + desc
        enh = await call_gemini(prompt, uid, system_instruction="You output only prompts.")
        url = f"https://image.pollinations.ai/prompt/{urllib.parse.quote(enh.strip())}?width=1024&height=1024&nologo=true"
        r = requests.get(url, timeout=60)
        r.raise_for_status()
        if len(r.content) > 10 * 1024 * 1024:
            raise ValueError("File too large.")
        img = Image.open(io.BytesIO(r.content)).convert("RGB")
        img.thumbnail((1280, 1280))
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=85)
        out.seek(0)
        await update.message.reply_photo(photo=out)
        await status.delete()
    except Exception as e:
        logger.exception(f"Draw error: {e}")
        await status.edit_text(t(uid, "img_fail"))


async def qr_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    track_command(uid, "/qr")
    text = " ".join(context.args)
    if not text or len(text) > 1000:
        await update.message.reply_text("🔳 1-1000 chars.")
        return
    try:
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_PHOTO)
        img = qrcode.make(text)
        out = io.BytesIO(); img.save(out, format="PNG"); out.seek(0)
        await update.message.reply_photo(photo=out)
    except Exception as e:
        logger.exception(f"QR gen error: {e}")
        await update.message.reply_text(t(uid, "qr_fail"))


async def tts_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    track_command(uid, "/tts")
    text = " ".join(context.args)
    if not text or len(text) > 500:
        await update.message.reply_text("🔊 1-500 chars.")
        return
    try:
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.RECORD_VOICE)
        out = io.BytesIO()
        lang = "ru" if LANG.get(str(uid), "en") == "ru" else "en"
        gTTS(text=text, lang=lang).write_to_fp(out)
        out.seek(0)
        await update.message.reply_voice(voice=out)
    except Exception as e:
        logger.exception(f"TTS error: {e}")
        await update.message.reply_text(t(uid, "tts_fail"))


def _decode_qr_bytes(data: bytes) -> str:
    try:
        np_arr = np.frombuffer(bytes(data), np.uint8)
        img_cv = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        if img_cv is None:
            return ""
        detector = cv2.QRCodeDetector()
        qr_data, _, _ = detector.detectAndDecode(img_cv)
        return (qr_data or "").strip()
    except Exception:
        return ""


async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    track_usage(uid)
    try:
        f = await update.message.photo[-1].get_file()
        data = await f.download_as_bytearray()

        qr = _decode_qr_bytes(bytes(data))
        if qr:
            await update.message.reply_text(
                f"{t(uid, 'qr_decoded')}\n\n<code>{qr}</code>",
                parse_mode=ParseMode.HTML,
            )
            return

        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
        caption = update.message.caption or ("Опиши это изображение детально." if LANG.get(str(uid)) == "ru" else "Describe this image in detail.")
        part = types.Part.from_bytes(data=bytes(data), mime_type="image/jpeg")
        reply = await call_gemini(caption, uid, media_parts=[part])
        await update.message.reply_text(reply)
    except Exception as e:
        logger.exception(f"Photo handler error: {e}")
        await update.message.reply_text(t(uid, "img_analysis"))


async def sticker_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    try:
        if update.message.sticker.is_animated or update.message.sticker.is_video:
            return
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
        f = await update.message.sticker.get_file()
        data = await f.download_as_bytearray()
        img = Image.open(io.BytesIO(data)).convert("RGBA")
        out = io.BytesIO(); img.save(out, format="PNG")
        part = types.Part.from_bytes(data=out.getvalue(), mime_type="image/png")
        reply = await call_gemini("Explain this sticker's meme context.", uid, media_parts=[part])
        await update.message.reply_text(reply)
    except Exception as e:
        logger.exception(f"Sticker handler error: {e}")
        await update.message.reply_text(t(uid, "sticker_fail"))


async def voice_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    track_usage(uid)
    try:
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
        f = await update.message.voice.get_file()
        data = await f.download_as_bytearray()
        part = types.Part.from_bytes(data=bytes(data), mime_type="audio/ogg")
        reply = await call_gemini(
            "Transcribe this audio and add a short insightful reaction or answer.",
            uid, media_parts=[part],
        )
        await update.message.reply_text(f"{t(uid, 'transcription')}\n\n{reply}", parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.exception(f"Voice handler error: {e}")
        await update.message.reply_text(t(uid, "audio_fail"))


async def document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    try:
        doc = update.message.document
        if doc.file_size > 10 * 1024 * 1024:
            await update.message.reply_text("⚠️ Max 10 MB.")
            return
        ext = os.path.splitext(doc.file_name)[1].lower()
        if ext not in (".txt", ".pdf", ".docx"):
            return

        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
        f = await doc.get_file()
        data = await f.download_as_bytearray()

        if ext == ".txt":
            text = data.decode("utf-8", errors="ignore")
        elif ext == ".pdf":
            reader = PdfReader(io.BytesIO(data))
            text = "".join(p.extract_text() or "" for p in reader.pages)
        else:
            d = docx.Document(io.BytesIO(data))
            text = "\n".join(p.text for p in d.paragraphs)

        text = text[:30000]
        if not text.strip():
            await update.message.reply_text(t(uid, "no_text"))
            return
        reply = await call_gemini(f"Summarize this document:\n\n{text}", uid)
        await update.message.reply_text(reply)
    except Exception as e:
        logger.exception(f"Doc handler error: {e}")
        await update.message.reply_text(t(uid, "doc_fail"))


async def poll_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    parts = [p.strip() for p in " ".join(context.args).split("|") if p.strip()]
    if len(parts) < 3 or len(parts) > 11:
        await update.message.reply_text("📊 /poll Q | Opt1 | Opt2 …")
        return
    try:
        await context.bot.send_poll(update.effective_chat.id, question=parts[0], options=parts[1:])
    except Exception as e:
        logger.exception(f"Poll error: {e}")


async def quiz_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    topic = " ".join(context.args) or "Random General Knowledge"
    try:
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
        prompt = (f"Generate a multiple choice quiz about {topic}. Return strict JSON: "
                  '{"question": "...", "options": ["A","B","C","D"], "correct_id": 0, "explanation": "..."}.')
        reply = await call_gemini(prompt, uid, json_mode=True, system_instruction="Output strictly valid JSON.")
        def _extract(text):
            s, e = text.find("{"), text.rfind("}")
            return text[s:e+1] if s != -1 and e != -1 else text
        try:
            data = json.loads(_extract(reply))
        except json.JSONDecodeError:
            reply = await call_gemini(prompt + " Return ONLY valid JSON.", uid, json_mode=True,
                                      system_instruction="Output strictly valid JSON.")
            data = json.loads(_extract(reply))
        await context.bot.send_poll(
            update.effective_chat.id,
            question=data["question"],
            options=data["options"],
            type=Poll.QUIZ,
            correct_option_id=data["correct_id"],
            explanation=data.get("explanation"),
        )
    except Exception as e:
        logger.exception(f"Quiz error: {e}")
        await update.message.reply_text("⚠️ Quiz generation error.")


async def speed_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    r = update.message.reply_to_message
    if not r or not r.voice:
        await update.message.reply_text(t(uid, "no_voice"))
        return
    if not context.args:
        return
    try:
        factor = float(context.args[0])
        if not 1.0 < factor <= 4.0:
            await update.message.reply_text("⚡ 1.1 – 4.0")
            return
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.RECORD_VOICE)
        f = await r.voice.get_file()
        data = await f.download_as_bytearray()
        audio = AudioSegment.from_file(io.BytesIO(data), format="ogg")
        fast = audio._spawn(audio.raw_data, overrides={"frame_rate": int(audio.frame_rate * factor)}).set_frame_rate(audio.frame_rate)
        out = io.BytesIO(); fast.export(out, format="ogg", codec="libopus"); out.seek(0)
        await update.message.reply_voice(voice=out)
    except Exception as e:
        logger.exception(f"Speed error: {e}")
        await update.message.reply_text(t(uid, "audio_fail"))


async def screenshot_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return
    url = context.args[0]
    if not url.startswith("http"):
        url = "https://" + url
    try:
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_PHOTO)
        r = requests.get(f"https://image.thum.io/get/width/1200/crop/900/{url}", timeout=30)
        r.raise_for_status()
        await update.message.reply_photo(photo=io.BytesIO(r.content))
    except Exception as e:
        logger.exception(f"Screenshot error: {e}")
        await update.message.reply_text("⚠️ Screenshot error.")


async def translate_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if len(context.args) < 2:
        return
    lang, text = context.args[0], " ".join(context.args[1:])
    try:
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
        reply = await call_gemini(f"Translate this to {lang}:\n\n{text}", uid,
                                  system_instruction="Return ONLY the translation.")
        await update.message.reply_text(reply)
    except Exception as e:
        logger.exception(f"Translate error: {e}")


async def summarize_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = ""
    if update.message.reply_to_message and update.message.reply_to_message.text:
        text = update.message.reply_to_message.text
    elif context.args:
        text = " ".join(context.args)
    if not text:
        return
    try:
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
        reply = await call_gemini(f"Summarize this text clearly:\n\n{text}", uid)
        await update.message.reply_text(reply)
    except Exception as e:
        logger.exception(f"Summarize error: {e}")


# ══════════════════════════════════════════════════════════════════════
#  PHASE 3 — ADMIN
# ══════════════════════════════════════════════════════════════════════
async def _do_ban(context, uid, reason, actor):
    if uid not in state["BANNED"]:
        state["BANNED"].append(uid)
    if uid in state["WHITELIST"]:
        state["WHITELIST"].remove(uid)
    save_state()
    log_mod_action(actor, uid, "BAN", reason)
    try:
        await context.bot.send_message(
            OWNER_ID,
            t(OWNER_ID, "ban_alert", uid=uid, reason=reason),
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass


@owner_only
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    lang = LANG.get(str(uid), "en")
    if lang == "ru":
        kb = [
            [KeyboardButton("👥 Белый список"), KeyboardButton("🚫 Баны")],
            [KeyboardButton("📊 Логи"),         KeyboardButton("📢 Рассылка")],
            [KeyboardButton("💾 Бэкап"),        KeyboardButton("ℹ️ Статус")],
        ]
    else:
        kb = [
            [KeyboardButton("👥 Whitelist"), KeyboardButton("🚫 Bans")],
            [KeyboardButton("📊 Logs"),      KeyboardButton("📢 Broadcast")],
            [KeyboardButton("💾 Backup"),    KeyboardButton("ℹ️ Status")],
        ]
    await update.message.reply_text(
        t(uid, "admin_panel"),
        reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True),
        parse_mode=ParseMode.HTML,
    )


@owner_only
async def admin_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text
    if   txt in ("👥 Whitelist", "👥 Белый список"): await whitelist_list(update, context)
    elif txt in ("🚫 Bans", "🚫 Баны"):               await _show_bans(update, context)
    elif txt in ("📊 Logs", "📊 Логи"):               await logs_cmd(update, context)
    elif txt in ("📢 Broadcast", "📢 Рассылка"):      await update.message.reply_text(t(update.effective_user.id, "use_broadcast"), parse_mode=ParseMode.HTML)
    elif txt in ("💾 Backup", "💾 Бэкап"):            await backup_cmd(update, context)
    elif txt in ("ℹ️ Status", "ℹ️ Статус"):          await health_cmd(update, context)


async def _show_bans(update, context):
    uid = update.effective_user.id
    if not state["BANNED"]:
        await update.message.reply_text(t(uid, "banned_empty"))
        return
    lines = [t(uid, "banned_header"), ""]
    for b in state["BANNED"]:
        lines.append(f"  • <code>{b}</code>")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


@owner_only
async def add_whitelist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("👥 /add &lt;user_id&gt; [duration|perm]", parse_mode=ParseMode.HTML)
        return
    try:
        uid = int(context.args[0])
    except ValueError:
        return
    if uid not in state["WHITELIST"]:
        state["WHITELIST"].append(uid)
    if len(context.args) >= 2:
        d = parse_duration(context.args[1])
        if d and d != "perm":
            state["WHITELIST_EXPIRY"][str(uid)] = (datetime.now() + d).isoformat()
    save_state()
    log_mod_action(OWNER_ID, uid, "ADD_WHITELIST", "manual")
    await update.message.reply_text(t(OWNER_ID, "user_added", uid=uid), parse_mode=ParseMode.HTML)


@owner_only
async def remove_whitelist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return
    try:
        uid = int(context.args[0])
    except ValueError:
        return
    if uid in state["WHITELIST"]:
        state["WHITELIST"].remove(uid)
    state["WHITELIST_EXPIRY"].pop(str(uid), None)
    save_state()
    await update.message.reply_text(t(OWNER_ID, "access_revoked", uid=uid), parse_mode=ParseMode.HTML)


@owner_only
async def whitelist_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not state["WHITELIST"]:
        await update.message.reply_text(t(uid, "wl_empty"))
        return
    lines = [t(uid, "wl_header"), ""]
    for w in state["WHITELIST"]:
        exp = state["WHITELIST_EXPIRY"].get(str(w), "∞")
        lines.append(f"  • <code>{w}</code>  ·  until {exp}")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private" and update.effective_user.id != OWNER_ID:
        return
    if not await check_group_permissions(update, context):
        return
    if not context.args:
        return
    try:
        uid = int(context.args[0])
    except ValueError:
        return
    rest = context.args[1:]
    duration = None
    if rest:
        d = parse_duration(rest[0])
        if d:
            duration, rest = d, rest[1:]
    reason = " ".join(rest) or "no reason"
    await _do_ban(context, uid, reason, update.effective_user.id)

    if duration and duration != "perm":
        state["BANNED_TIMED"][str(uid)] = (datetime.now() + duration).isoformat()
    else:
        state["BANNED_TIMED"].pop(str(uid), None)
    save_state()

    if update.effective_chat.type in ("group", "supergroup"):
        try:
            await context.bot.ban_chat_member(update.effective_chat.id, uid)
        except Exception as e:
            logger.error(f"Ban chat error: {e}")

    ts = "forever" if not duration or duration == "perm" else f"for {duration}"
    await update.message.reply_text(t(OWNER_ID, "user_banned", uid=uid, ts=ts, reason=reason), parse_mode=ParseMode.HTML)


async def unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private" and update.effective_user.id != OWNER_ID:
        return
    if not await check_group_permissions(update, context):
        return
    if not context.args:
        return
    try:
        uid = int(context.args[0])
    except ValueError:
        return
    if uid in state["BANNED"]:
        state["BANNED"].remove(uid)
    state["BANNED_TIMED"].pop(str(uid), None)
    save_state()
    if update.effective_chat.type in ("group", "supergroup"):
        try:
            await context.bot.unban_chat_member(update.effective_chat.id, uid)
        except Exception:
            pass
    await update.message.reply_text(t(OWNER_ID, "user_unbanned", uid=uid), parse_mode=ParseMode.HTML)


async def mute_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private" and update.effective_user.id != OWNER_ID:
        return
    if not await check_group_permissions(update, context):
        return
    if len(context.args) < 2:
        await update.message.reply_text("🔇 /mute &lt;user_id&gt; &lt;duration|perm&gt;", parse_mode=ParseMode.HTML)
        return
    try:
        uid = int(context.args[0])
    except ValueError:
        return
    d = parse_duration(context.args[1])
    if not d:
        return
    exp = datetime.now() + (timedelta(days=36500) if d == "perm" else d)
    state["MUTED"][str(uid)] = exp.isoformat()
    save_state()
    log_mod_action(update.effective_user.id, uid, "MUTE", context.args[1])
    await update.message.reply_text(
        t(OWNER_ID, "user_muted", uid=uid, until=exp.strftime("%Y-%m-%d %H:%M")),
        parse_mode=ParseMode.HTML,
    )


async def warn_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private" and update.effective_user.id != OWNER_ID:
        return
    if not await check_group_permissions(update, context):
        return
    if len(context.args) < 2:
        return
    try:
        uid = int(context.args[0])
    except ValueError:
        return
    reason = " ".join(context.args[1:])
    wl = state["WARNINGS"].setdefault(str(uid), [])
    wl.append({"reason": reason, "by": update.effective_user.id, "at": datetime.now().isoformat()})
    save_state()
    log_mod_action(update.effective_user.id, uid, "WARN", reason)
    await update.message.reply_text(
        t(OWNER_ID, "user_warned", uid=uid, count=len(wl), reason=reason),
        parse_mode=ParseMode.HTML,
    )
    if len(wl) >= 3:
        await _do_ban(context, uid, "auto-ban: 3 warnings", update.effective_user.id)
        await update.message.reply_text(t(OWNER_ID, "auto_banned", uid=uid), parse_mode=ParseMode.HTML)


async def warnings_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private" and update.effective_user.id != OWNER_ID:
        return
    if not await check_group_permissions(update, context):
        return
    if not context.args:
        return
    uid = str(context.args[0])
    warns = state["WARNINGS"].get(uid, [])
    if not warns:
        await update.message.reply_text(t(OWNER_ID, "no_warnings"))
        return
    lines = [t(OWNER_ID, "warns_header", uid=uid), ""]
    for i, w in enumerate(warns, 1):
        lines.append(f"  {i}. {w['at'][:16]} │ by {w['by']} │ {w['reason']}")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


@owner_only
async def broadcast_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args)
    if not text:
        return
    sent = failed = 0
    for u in state["WHITELIST"]:
        try:
            await context.bot.send_message(u, f"📢 <b>Broadcast</b>\n\n{text}", parse_mode=ParseMode.HTML)
            sent += 1
        except Exception:
            failed += 1
    await update.message.reply_text(
        t(OWNER_ID, "broadcast_done", sent=sent, failed=failed),
        parse_mode=ParseMode.HTML,
    )


@owner_only
async def send_direct(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        return
    try:
        uid = int(context.args[0])
    except ValueError:
        return
    text = " ".join(context.args[1:])
    try:
        await context.bot.send_message(uid, text)
        await update.message.reply_text(t(OWNER_ID, "msg_delivered"))
    except Exception as e:
        await update.message.reply_text(f"⚠️ Error: {e}")


@owner_only
async def backup_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    zip_name = "jarvis_backup.zip"
    with zipfile.ZipFile(zip_name, "w") as z:
        for f in ("main.py", "requirements.txt", "whitelist.json", "config.json", "tickets.json", "usage_stats.json"):
            if os.path.exists(f):
                z.write(f)
    await update.message.reply_document(document=open(zip_name, "rb"), filename=zip_name)
    os.remove(zip_name)


@owner_only
async def logs_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not os.path.exists("bot.log"):
        return
    with open("bot.log", "r", encoding="utf-8") as f:
        tail = f.readlines()[-35:]
    text = "".join(tail)[-4000:]
    await update.message.reply_text(
        f"{t(OWNER_ID, 'logs_header')}\n\n<pre>{text}</pre>",
        parse_mode=ParseMode.HTML,
    )


@owner_only
async def export_logs_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if os.path.exists("bot.log"):
        await update.message.reply_document(document=open("bot.log", "rb"))


# ══════════════════════════════════════════════════════════════════════
#  PHASE 4 — ADVANCED AI
# ══════════════════════════════════════════════════════════════════════
async def _ai(update, context, instruction, need_reply=False):
    uid = update.effective_user.id
    if need_reply:
        r = update.message.reply_to_message
        if not r or not (r.text or r.caption):
            await update.message.reply_text(t(uid, "no_reply"))
            return
        text = r.text or r.caption
    else:
        text = " ".join(context.args)
    if not text and not need_reply:
        await update.message.reply_text("✏️ Provide arguments.")
        return
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    status = await update.message.reply_text(t(uid, "processing"), parse_mode=ParseMode.HTML)
    try:
        reply = await call_gemini(f"{instruction}\n\nINPUT:\n{text}", uid)
        try:
            await status.edit_text(reply[:4000], parse_mode=ParseMode.MARKDOWN)
        except Exception:
            await status.edit_text(reply[:4000])
        for i in range(4000, len(reply), 4000):
            await update.message.reply_text(reply[i:i+4000])
    except Exception as e:
        logger.exception(f"AI cmd error: {e}")
        await status.edit_text(t(uid, "req_error"))


async def review_cmd(update, context):
    await _ai(update, context, "Review this code. List bugs, security issues, style problems. Suggest fixes with examples.", need_reply=True)

async def regex_cmd(update, context):
    await _ai(update, context, "Generate a regex pattern for the described task. Return ONLY the pattern and one test example.")

async def sql_cmd(update, context):
    await _ai(update, context, "Write a SQL query for the described task. Add a one-line explanation.")

async def explain_cmd(update, context):
    await _ai(update, context, "Explain this code line by line in Russian. Be concise.", need_reply=True)

async def refactor_cmd(update, context):
    await _ai(update, context, "Refactor this code for readability and performance. Return optimized version + change list.", need_reply=True)

async def uml_cmd(update, context):
    await _ai(update, context, "Return a PlantUML text diagram for the described or given code.")

async def pytest_cmd(update, context):
    await _ai(update, context, "Generate a complete pytest file with test cases for this code. Return only Python code.", need_reply=True)

async def doc_cmd(update, context):
    await _ai(update, context, "Return this code with PEP-8 docstrings and inline comments added. Preserve logic.", need_reply=True)

async def cv_cmd(update, context):
    await _ai(update, context, "Structure the following raw bio into a professional Markdown CV: Summary, Experience, Skills, Education.")

async def translate_long_cmd(update, context):
    if len(context.args) < 2:
        await update.message.reply_text("🌐 /translate_long &lt;lang&gt; &lt;text&gt;", parse_mode=ParseMode.HTML)
        return
    lang, text = context.args[0], " ".join(context.args[1:])
    await _ai(update, context, f"Translate the following into {lang}. Preserve formatting.")

async def ask_cmd(update, context):
    uid = update.effective_user.id
    r = update.message.reply_to_message
    if not r or not r.text:
        await update.message.reply_text(t(uid, "no_reply"))
        return
    q = " ".join(context.args)
    doc = r.text[:30000]
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    status = await update.message.reply_text(t(uid, "processing"), parse_mode=ParseMode.HTML)
    try:
        reply = await call_gemini(f"Answer based ONLY on this document.\n\n{doc}\n\nQ: {q}", uid)
        await status.edit_text(reply[:4000])
    except Exception as e:
        logger.exception(f"Ask error: {e}")
        await status.edit_text(t(uid, "req_error"))


# ══════════════════════════════════════════════════════════════════════
#  PHASE 5 — SPECIAL PROTOCOLS
# ══════════════════════════════════════════════════════════════════════
@owner_only
async def export_whitelist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    payload = {
        "whitelist": state["WHITELIST"],
        "expiry":    state["WHITELIST_EXPIRY"],
        "exported_at": datetime.now().isoformat(),
    }
    _atomic_write_json("whitelist_export.json", payload)
    await update.message.reply_document(document=open("whitelist_export.json", "rb"))
    os.remove("whitelist_export.json")


@owner_only
async def clear_session_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    USER_HISTORY.clear()
    USER_MODES.clear()
    INCOGNITO_USERS.clear()
    LAST_REQUEST.clear()
    await update.message.reply_text(t(OWNER_ID, "session_purged"))


async def report_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = " ".join(context.args)
    if not text:
        await update.message.reply_text("📩 /report &lt;issue&gt;", parse_mode=ParseMode.HTML)
        return
    ticket = {
        "id": len(TICKETS) + 1,
        "user_id": uid,
        "username": update.effective_user.username,
        "text": text,
        "status": "open",
        "at": datetime.now().isoformat(),
    }
    TICKETS.append(ticket)
    save_tickets()
    await update.message.reply_text(t(uid, "report_created", tid=ticket["id"]), parse_mode=ParseMode.HTML)
    try:
        await context.bot.send_message(
            OWNER_ID,
            f"📩 Ticket #{ticket['id']} from <code>{ticket['user_id']}</code>: {text}",
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass


@owner_only
async def tickets_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    opens = [x for x in TICKETS if x.get("status") == "open"]
    if not opens:
        await update.message.reply_text(t(OWNER_ID, "tickets_empty"))
        return
    lines = [t(OWNER_ID, "tickets_header"), ""]
    for x in opens[:20]:
        lines.append(f"  #{x['id']}  │  <code>{x['user_id']}</code>  │  {x['text'][:60]}")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


@owner_only
async def close_ticket_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return
    try:
        tid = int(context.args[0])
    except ValueError:
        return
    for x in TICKETS:
        if x["id"] == tid:
            x["status"] = "closed"
            save_tickets()
            await update.message.reply_text(t(OWNER_ID, "ticket_closed", tid=tid))
            return
    await update.message.reply_text(t(OWNER_ID, "ticket_not_found"))


@owner_only
async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    top = sorted(USER_STATS.items(), key=lambda kv: kv[1].get("messages", 0), reverse=True)[:10]
    if not top:
        await update.message.reply_text(t(OWNER_ID, "stats_empty"))
        return
    lines = [t(OWNER_ID, "stats_header"), ""]
    for uid, s in top:
        lines.append(f"  <code>{uid}</code>  ·  {s.get('messages',0)} msgs  ·  {s.get('commands',0)} cmds")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


@owner_only
async def health_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        cpu = psutil.cpu_percent(interval=0.5)
        ram = psutil.virtual_memory().percent
        dsk = psutil.disk_usage("/").percent
        up  = int(time.time() - STARTED_AT)
        h, m, s = up // 3600, (up % 3600) // 60, up % 60
        msg = (
            f"{t(OWNER_ID, 'health_header')}\n\n"
            f"  CPU    │ {cpu}%\n"
            f"  RAM    │ {ram}%\n"
            f"  Disk   │ {dsk}%\n"
            f"  Uptime │ {h}h {m}m {s}s"
        )
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.exception(f"Health error: {e}")
        await update.message.reply_text(t(OWNER_ID, "health_fail"))


@owner_only
async def stopwords_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(t(OWNER_ID, "stopwords_list", words=", ".join(STOP_WORDS)))
        return
    action = context.args[0].lower()
    if action == "add" and len(context.args) > 1:
        STOP_WORDS.append(" ".join(context.args[1:]))
        await update.message.reply_text(t(OWNER_ID, "stopword_added"))
    elif action == "remove" and len(context.args) > 1:
        w = " ".join(context.args[1:])
        if w in STOP_WORDS:
            STOP_WORDS.remove(w)
        await update.message.reply_text(t(OWNER_ID, "stopword_removed"))


# ══════════════════════════════════════════════════════════════════════
#  SECURITY MIDDLEWARE + BACKGROUND JOBS
# ══════════════════════════════════════════════════════════════════════
async def cleanup_expired_job(context):
    now = datetime.now()
    changed = False

    for u in [k for k, v in list(state["WHITELIST_EXPIRY"].items()) if now > datetime.fromisoformat(v)]:
        try:
            state["WHITELIST"].remove(int(u))
        except ValueError:
            pass
        state["WHITELIST_EXPIRY"].pop(u, None)
        changed = True

    for u in [k for k, v in list(state.get("BANNED_TIMED", {}).items()) if now > datetime.fromisoformat(v)]:
        try:
            state["BANNED"].remove(int(u))
        except ValueError:
            pass
        state["BANNED_TIMED"].pop(u, None)
        changed = True

    for u in [k for k, v in list(state["MUTED"].items()) if now > datetime.fromisoformat(v)]:
        state["MUTED"].pop(u, None)
        changed = True

    if changed:
        save_state()


async def auto_backup_job(context):
    try:
        name = f"auto_backup_{datetime.now():%Y%m%d_%H%M}.zip"
        with zipfile.ZipFile(name, "w") as z:
            for f in ("main.py", "requirements.txt", "whitelist.json", "config.json"):
                if os.path.exists(f):
                    z.write(f)
        await context.bot.send_document(OWNER_ID, document=open(name, "rb"), filename=name)
        os.remove(name)
    except Exception as e:
        logger.exception(f"Auto-backup error: {e}")


async def global_security_middleware(update: Update, context):
    if not update.effective_user or not update.message:
        return
    uid = update.effective_user.id
    suid = str(uid)
    now = datetime.now()

    if suid in state["MUTED"]:
        if now > datetime.fromisoformat(state["MUTED"][suid]):
            state["MUTED"].pop(suid, None)
            save_state()
        else:
            raise ApplicationHandlerStop

    if uid in state["BANNED"]:
        raise ApplicationHandlerStop

    now_ts = time.time()
    bucket = [x for x in FLOOD_WINDOW.get(uid, []) if now_ts - x < 60]
    bucket.append(now_ts)
    FLOOD_WINDOW[uid] = bucket
    if len(bucket) > 10 and uid != OWNER_ID:
        try:
            await context.bot.send_message(
                OWNER_ID,
                t(OWNER_ID, "flood_detected", uid=uid),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        state["MUTED"][suid] = (datetime.now() + timedelta(minutes=5)).isoformat()
        save_state()
        raise ApplicationHandlerStop

    if uid != OWNER_ID and uid not in state["WHITELIST"]:
        entry = {
            "first_name":   update.effective_user.first_name,
            "last_name":    update.effective_user.last_name,
            "user_id":      uid,
            "username":     update.effective_user.username,
            "chat_id":      update.effective_chat.id,
            "timestamp":    now.isoformat(),
            "text_preview": (update.message.text or "[Media]")[:100],
        }
        logs = []
        if os.path.exists(INTRUDER_FILE):
            try:
                with open(INTRUDER_FILE, "r", encoding="utf-8") as f:
                    logs = json.load(f)
            except json.JSONDecodeError:
                pass
        logs.append(entry)
        _atomic_write_json(INTRUDER_FILE, logs)

        alert = (
            f"{t(OWNER_ID, 'unauthorized')}\n\n"
            f"  ID    │ <code>{uid}</code>\n"
            f"  User  │ @{entry['username']} ({entry['first_name']})\n"
            f"  Chat  │ <code>{entry['chat_id']}</code>\n"
            f"  Query │ {entry['text_preview']}"
        )
        try:
            await context.bot.send_message(OWNER_ID, alert, parse_mode=ParseMode.HTML)
        except Exception:
            pass
        raise ApplicationHandlerStop


# ══════════════════════════════════════════════════════════════════════
#  FLASK KEEPALIVE + MAIN
# ══════════════════════════════════════════════════════════════════════
async def post_init(application: Application):
    await application.bot.delete_webhook(drop_pending_updates=True)
    logger.info("Webhooks cleared. J.A.R.V.I.S. Systems Online.")


def run_flask():
    flask_app = Flask(__name__)

    @flask_app.route("/")
    @flask_app.route("/health")
    def health():
        return "J.A.R.V.I.S. is alive", 200

    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(TypeHandler(Update, global_security_middleware), group=-1)
    app.job_queue.run_repeating(cleanup_expired_job, interval=60)
    app.job_queue.run_repeating(auto_backup_job, interval=7 * 24 * 3600, first=10)

    # Language chooser callback
    app.add_handler(CallbackQueryHandler(on_lang_callback, pattern=r"^lang_(ru|en)$"))

    # Phase 1
    for cmd, fn in [
        ("start", start), ("help", help_cmd), ("reset", reset_cmd),
        ("mode", mode_cmd), ("lang", lang_cmd),
        ("incognito", incognito_cmd), ("incognito_off", incognito_off_cmd),
    ]:
        app.add_handler(CommandHandler(cmd, fn))

    # Phase 2
    for cmd, fn in [
        ("draw", draw_cmd), ("qr", qr_cmd), ("tts", tts_cmd),
        ("poll", poll_cmd), ("quiz", quiz_cmd), ("speed", speed_cmd),
        ("screenshot", screenshot_cmd), ("translate", translate_cmd),
        ("summarize", summarize_cmd),
    ]:
        app.add_handler(CommandHandler(cmd, fn))

    app.add_handler(MessageHandler(filters.PHOTO,        photo_handler))
    app.add_handler(MessageHandler(filters.Sticker.ALL,  sticker_handler))
    app.add_handler(MessageHandler(filters.VOICE,        voice_handler))
    app.add_handler(MessageHandler(filters.Document.ALL, document_handler))

    # Phase 3
    for cmd, fn in [
        ("admin", admin_panel), ("add", add_whitelist), ("remove", remove_whitelist),
        ("whitelist", whitelist_list), ("ban", ban_user), ("unban", unban_user),
        ("mute", mute_user), ("warn", warn_user), ("warnings", warnings_list),
        ("broadcast", broadcast_msg), ("send", send_direct), ("backup", backup_cmd),
        ("logs", logs_cmd), ("export_logs", export_logs_cmd),
    ]:
        app.add_handler(CommandHandler(cmd, fn))

    # Admin panel buttons: ru + en labels
    app.add_handler(MessageHandler(
        filters.Regex(r"^(👥 Whitelist|🚫 Bans|📊 Logs|📢 Broadcast|💾 Backup|ℹ️ Status|👥 Белый список|🚫 Баны|📊 Логи|📢 Рассылка|💾 Бэкап|ℹ️ Статус)$"),
        admin_buttons,
    ))

    # Phase 4
    for cmd, fn in [
        ("review", review_cmd), ("regex", regex_cmd), ("sql", sql_cmd),
        ("explain", explain_cmd), ("refactor", refactor_cmd), ("uml", uml_cmd),
        ("pytest", pytest_cmd), ("doc", doc_cmd), ("cv", cv_cmd),
        ("translate_long", translate_long_cmd), ("ask", ask_cmd),
    ]:
        app.add_handler(CommandHandler(cmd, fn))

    # Phase 5
    for cmd, fn in [
        ("export_whitelist", export_whitelist_cmd), ("clear_session", clear_session_cmd),
        ("report", report_cmd), ("tickets", tickets_cmd), ("close_ticket", close_ticket_cmd),
        ("stats", stats_cmd), ("health", health_cmd), ("stopwords", stopwords_cmd),
    ]:
        app.add_handler(CommandHandler(cmd, fn))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    logger.info("Starting polling...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    logger.info("Flask keepalive started.")
    main() await update.message.reply_text("Sir, I don't have admin rights in this group.")
            return False
        if update.effective_user.id == OWNER_ID:
            return True
        u_m = await context.bot.get_chat_member(chat.id, update.effective_user.id)
        if u_m.status not in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER):
            await update.message.reply_text("Access denied. Group admin rights required.")
            return False
        return True
    except Exception as e:
        logger.error(f"Permissions error: {e}")
        return False


# ══════════════════════════════════════════════════════════════════════
#  GEMINI CLIENT
# ══════════════════════════════════════════════════════════════════════
ai_client = None
try:
    ai_client = genai.Client(api_key=GEMINI_API_KEY)
    logger.info("AI Matrix initialized.")
except Exception as e:
    logger.error(f"Failed to init Gemini: {e}")

SYSTEM_PROMPTS = {
    "assistant":    "You are J.A.R.V.I.S., a highly intelligent, polite, and efficient AI assistant. Keep responses clear and structured.",
    "tutor":        "You are a patient English tutor. Correct mistakes, explain grammar, give examples. Reply in Russian for explanations, English for examples.",
    "programmer":   "You are a senior software engineer. Provide optimized, secure code with brief explanations. Focus on best practices.",
    "psychologist": "You are an empathetic, non-judgmental active listener. Offer supportive and grounded insights. Never diagnose.",
}


async def call_gemini(prompt_text, user_id, system_instruction=None, media_parts=None, json_mode=False):
    if not ai_client:
        return t(user_id, "gemini_down")
    try:
        mode = USER_MODES.get(user_id, "assistant")
        sys_inst = system_instruction or SYSTEM_PROMPTS.get(mode, SYSTEM_PROMPTS["assistant"])

        contents = []
        if user_id not in INCOGNITO_USERS and user_id in USER_HISTORY:
            for msg in USER_HISTORY[user_id]:
                contents.append(types.Content(
                    role=msg["role"],
                    parts=[types.Part.from_text(text=msg["parts"][0]["text"])],
                ))

        parts = list(media_parts or [])
        parts.append(types.Part.from_text(text=prompt_text))
        contents.append(types.Content(role="user", parts=parts))

        cfg = {"system_instruction": sys_inst}
        if json_mode:
            cfg["response_mime_type"] = "application/json"
        gen_cfg = types.GenerateContentConfig(**cfg)

        resp = ai_client.models.generate_content(
            model=GEMINI_MODEL, contents=contents, config=gen_cfg,
        )
        res_text = resp.text or t(user_id, "gemini_down")

        if user_id not in INCOGNITO_USERS and not media_parts and not json_mode:
            hist = USER_HISTORY.setdefault(user_id, [])
            hist.append({"role": "user",  "parts": [{"text": prompt_text}]})
            hist.append({"role": "model", "parts": [{"text": res_text}]})

            if len(hist) > 20:
                try:
                    sc = contents.copy()
                    sc.append(types.Content(
                        role="user",
                        parts=[types.Part.from_text(text="Summarize this conversation, preserving all key facts, names, code links and decisions.")],
                    ))
                    summary = ai_client.models.generate_content(model=GEMINI_MODEL, contents=sc)
                    USER_HISTORY[user_id] = [
                        {"role": "user",  "parts": [{"text": "Previous context summary."}]},
                        {"role": "model", "parts": [{"text": summary.text}]},
                    ]
                except Exception:
                    USER_HISTORY[user_id] = hist[-10:]
        return res_text

    except Exception as e:
        logger.exception(f"Gemini error UID={user_id}: {e}")
        if user_id == OWNER_ID:
            try:
                r = requests.get(
                    f"https://text.pollinations.ai/{urllib.parse.quote(prompt_text[:500])}",
                    timeout=30,
                )
                if r.status_code == 200 and r.text.strip():
                    return r.text.strip()
            except Exception as fe:
                logger.exception(f"Fallback error: {fe}")
        return t(user_id, "gemini_down")


# ══════════════════════════════════════════════════════════════════════
#  PHASE 1 — AI CORE
# ══════════════════════════════════════════════════════════════════════
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    track_command(uid, "/start")
    await update.message.reply_text(
        t(uid, "welcome_owner" if uid == OWNER_ID else "welcome_other"),
        parse_mode=ParseMode.HTML,
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = [
        "🤖 <b>J.A.R.V.I.S. — Commands</b>",
        "",
        "🟢 <b>Core</b>",
        "  /start  /help  /reset  /mode  /lang",
        "  /incognito  /incognito_off",
        "",
        "🎨 <b>Media</b>",
        "  /draw  /qr  /tts  /poll  /quiz",
        "  /speed  /screenshot  /translate  /summarize",
        "",
        "🛡 <b>Admin</b>",
        "  /admin  /add  /remove  /whitelist",
        "  /ban  /unban  /mute  /warn  /warnings",
        "  /broadcast  /send  /backup  /logs  /export_logs",
        "",
        "🧠 <b>AI Pro</b>",
        "  /review  /regex  /sql  /explain  /refactor",
        "  /uml  /pytest  /doc  /cv  /translate_long  /ask",
        "",
        "⚙️ <b>Protocols</b>",
        "  /export_whitelist  /clear_session",
        "  /report  /tickets  /close_ticket",
        "  /stats  /health  /stopwords",
        "",
        "📄 <i>Send text, images, docs, voice or stickers.</i>",
    ]
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def reset_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    track_command(uid, "/reset")
    USER_HISTORY.pop(uid, None)
    await update.message.reply_text(t(uid, "memory_cleared"))


async def mode_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    track_command(uid, "/mode")
    if not context.args:
        cur = USER_MODES.get(uid, "assistant")
        await update.message.reply_text(
            t(uid, "mode_current", cur=cur, modes=", ".join(SYSTEM_PROMPTS)),
            parse_mode=ParseMode.HTML,
        )
        return
    mode = context.args[0].lower()
    if mode not in SYSTEM_PROMPTS:
        await update.message.reply_text(t(uid, "unknown_mode"))
        return
    USER_MODES[uid] = mode
    USER_HISTORY.pop(uid, None)
    await update.message.reply_text(t(uid, "mode_switched", mode=mode), parse_mode=ParseMode.HTML)


async def incognito_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    INCOGNITO_USERS.add(uid)
    await update.message.reply_text(t(uid, "incog_on"))


async def incognito_off_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    INCOGNITO_USERS.discard(uid)
    await update.message.reply_text(t(uid, "incog_off"))


async def lang_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    track_command(uid, "/lang")
    if not context.args:
        cur = LANG.get(str(uid), "en")
        await update.message.reply_text(t(uid, "lang_current", cur=cur), parse_mode=ParseMode.HTML)
        return
    new = context.args[0].lower()
    if new not in ("ru", "en"):
        await update.message.reply_text(t(uid, "lang_unknown"))
        return
    LANG[str(uid)] = new
    save_lang()
    await update.message.reply_text(t(uid, "lang_switched", lang=new), parse_mode=ParseMode.HTML)


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    track_usage(uid)
    now = time.time()
    if uid in LAST_REQUEST and now - LAST_REQUEST[uid] < 2.0:
        await update.message.reply_text(t(uid, "slow_down"))
        return
    LAST_REQUEST[uid] = now

    msg_text = update.message.text or ""
    for w in STOP_WORDS:
        if w.lower() in msg_text.lower() and uid != OWNER_ID:
            try:
                await context.bot.send_message(
                    OWNER_ID,
                    f"⚠️ Stop-word triggered by <code>{uid}</code>: {msg_text[:200]}",
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass

    if update.message.reply_to_message and update.message.reply_to_message.text:
        msg_text = f"[Replying to: {update.message.reply_to_message.text}]\n\n{msg_text}"

    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    status = await update.message.reply_text(t(uid, "processing"), parse_mode=ParseMode.HTML)

    try:
        reply = await call_gemini(msg_text, uid)
        try:
            await status.edit_text(reply, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            try:
                await status.edit_text(reply)
            except Exception:
                await update.message.reply_text(reply[:4000])
    except Exception as e:
        logger.exception(f"Text handler error: {e}")
        await status.edit_text(t(uid, "req_error"))


# ══════════════════════════════════════════════════════════════════════
#  PHASE 2 — MEDIA
# ══════════════════════════════════════════════════════════════════════
async def draw_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    track_command(uid, "/draw")
    if not context.args:
        await update.message.reply_text("🎨 /draw &lt;description&gt;", parse_mode=ParseMode.HTML)
        return
    desc = " ".join(context.args)
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_PHOTO)
    status = await update.message.reply_text("🎨 <i>Drawing…</i>", parse_mode=ParseMode.HTML)
    try:
        prompt = ("Convert this into a detailed English image-generation prompt. "
                  "Add composition, lighting, style, atmosphere, camera details. "
                  "Return ONLY the prompt: ") + desc
        enh = await call_gemini(prompt, uid, system_instruction="You output only prompts.")
        url = f"https://image.pollinations.ai/prompt/{urllib.parse.quote(enh.strip())}?width=1024&height=1024&nologo=true"
        r = requests.get(url, timeout=60)
        r.raise_for_status()
        if len(r.content) > 10 * 1024 * 1024:
            raise ValueError("File too large.")
        img = Image.open(io.BytesIO(r.content)).convert("RGB")
        img.thumbnail((1280, 1280))
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=85)
        out.seek(0)
        await update.message.reply_photo(photo=out)
        await status.delete()
    except Exception as e:
        logger.exception(f"Draw error: {e}")
        await status.edit_text(t(uid, "img_fail"))


async def qr_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    track_command(uid, "/qr")
    text = " ".join(context.args)
    if not text or len(text) > 1000:
        await update.message.reply_text("🔳 1-1000 chars.")
        return
    try:
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_PHOTO)
        img = qrcode.make(text)
        out = io.BytesIO(); img.save(out, format="PNG"); out.seek(0)
        await update.message.reply_photo(photo=out)
    except Exception as e:
        logger.exception(f"QR gen error: {e}")
        await update.message.reply_text(t(uid, "qr_fail"))


async def tts_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    track_command(uid, "/tts")
    text = " ".join(context.args)
    if not text or len(text) > 500:
        await update.message.reply_text("🔊 1-500 chars.")
        return
    try:
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.RECORD_VOICE)
        out = io.BytesIO()
        gTTS(text=text, lang="ru").write_to_fp(out)
        out.seek(0)
        await update.message.reply_voice(voice=out)
    except Exception as e:
        logger.exception(f"TTS error: {e}")
        await update.message.reply_text(t(uid, "tts_fail"))


def _decode_qr_bytes(data: bytes) -> str:
    """Decode QR from raw image bytes using OpenCV. Returns empty string if none."""
    try:
        np_arr = np.frombuffer(bytes(data), np.uint8)
        img_cv = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        if img_cv is None:
            return ""
        detector = cv2.QRCodeDetector()
        qr_data, _, _ = detector.detectAndDecode(img_cv)
        return (qr_data or "").strip()
    except Exception:
        return ""


async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    track_usage(uid)
    try:
        f = await update.message.photo[-1].get_file()
        data = await f.download_as_bytearray()

        qr = _decode_qr_bytes(bytes(data))
        if qr:
            await update.message.reply_text(
                f"🔳 <b>QR decoded</b>\n\n<code>{qr}</code>",
                parse_mode=ParseMode.HTML,
            )
            return

        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
        caption = update.message.caption or "Describe this image in detail."
        part = types.Part.from_bytes(data=bytes(data), mime_type="image/jpeg")
        reply = await call_gemini(caption, uid, media_parts=[part])
        await update.message.reply_text(reply)
    except Exception as e:
        logger.exception(f"Photo handler error: {e}")
        await update.message.reply_text(t(uid, "img_analysis"))


async def sticker_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    try:
        if update.message.sticker.is_animated or update.message.sticker.is_video:
            return
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
        f = await update.message.sticker.get_file()
        data = await f.download_as_bytearray()
        img = Image.open(io.BytesIO(data)).convert("RGBA")
        out = io.BytesIO(); img.save(out, format="PNG")
        part = types.Part.from_bytes(data=out.getvalue(), mime_type="image/png")
        reply = await call_gemini("Explain this sticker's meme context.", uid, media_parts=[part])
        await update.message.reply_text(reply)
    except Exception as e:
        logger.exception(f"Sticker handler error: {e}")
        await update.message.reply_text(t(uid, "sticker_fail"))


async def voice_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    track_usage(uid)
    try:
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
        f = await update.message.voice.get_file()
        data = await f.download_as_bytearray()
        part = types.Part.from_bytes(data=bytes(data), mime_type="audio/ogg")
        reply = await call_gemini(
            "Transcribe this audio and add a short insightful reaction or answer.",
            uid, media_parts=[part],
        )
        await update.message.reply_text(f"🎙 <b>Transcription</b>\n\n{reply}", parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.exception(f"Voice handler error: {e}")
        await update.message.reply_text(t(uid, "audio_fail"))


async def document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    try:
        doc = update.message.document
        if doc.file_size > 10 * 1024 * 1024:
            await update.message.reply_text("⚠️ Max 10 MB.")
            return
        ext = os.path.splitext(doc.file_name)[1].lower()
        if ext not in (".txt", ".pdf", ".docx"):
            return

        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
        f = await doc.get_file()
        data = await f.download_as_bytearray()

        if ext == ".txt":
            text = data.decode("utf-8", errors="ignore")
        elif ext == ".pdf":
            reader = PdfReader(io.BytesIO(data))
            text = "".join(p.extract_text() or "" for p in reader.pages)
        else:
            d = docx.Document(io.BytesIO(data))
            text = "\n".join(p.text for p in d.paragraphs)

        text = text[:30000]
        if not text.strip():
            await update.message.reply_text(t(uid, "no_text"))
            return
        reply = await call_gemini(f"Summarize this document:\n\n{text}", uid)
        await update.message.reply_text(reply)
    except Exception as e:
        logger.exception(f"Doc handler error: {e}")
        await update.message.reply_text(t(uid, "doc_fail"))


async def poll_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    parts = [p.strip() for p in " ".join(context.args).split("|") if p.strip()]
    if len(parts) < 3 or len(parts) > 11:
        await update.message.reply_text("📊 /poll Q | Opt1 | Opt2 …")
        return
    try:
        await context.bot.send_poll(update.effective_chat.id, question=parts[0], options=parts[1:])
    except Exception as e:
        logger.exception(f"Poll error: {e}")


async def quiz_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    topic = " ".join(context.args) or "Random General Knowledge"
    try:
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
        prompt = (f"Generate a multiple choice quiz about {topic}. Return strict JSON: "
                  '{"question": "...", "options": ["A","B","C","D"], "correct_id": 0, "explanation": "..."}.')
        reply = await call_gemini(prompt, uid, json_mode=True, system_instruction="Output strictly valid JSON.")
        def _extract(text):
            s, e = text.find("{"), text.rfind("}")
            return text[s:e+1] if s != -1 and e != -1 else text
        try:
            data = json.loads(_extract(reply))
        except json.JSONDecodeError:
            reply = await call_gemini(prompt + " Return ONLY valid JSON.", uid, json_mode=True,
                                      system_instruction="Output strictly valid JSON.")
            data = json.loads(_extract(reply))
        await context.bot.send_poll(
            update.effective_chat.id,
            question=data["question"],
            options=data["options"],
            type=Poll.QUIZ,
            correct_option_id=data["correct_id"],
            explanation=data.get("explanation"),
        )
    except Exception as e:
        logger.exception(f"Quiz error: {e}")
        await update.message.reply_text("⚠️ Quiz generation error.")


async def speed_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    r = update.message.reply_to_message
    if not r or not r.voice:
        await update.message.reply_text(t(uid, "no_voice"))
        return
    if not context.args:
        return
    try:
        factor = float(context.args[0])
        if not 1.0 < factor <= 4.0:
            await update.message.reply_text("⚡ 1.1 – 4.0")
            return
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.RECORD_VOICE)
        f = await r.voice.get_file()
        data = await f.download_as_bytearray()
        audio = AudioSegment.from_file(io.BytesIO(data), format="ogg")
        fast = audio._spawn(audio.raw_data, overrides={"frame_rate": int(audio.frame_rate * factor)}).set_frame_rate(audio.frame_rate)
        out = io.BytesIO(); fast.export(out, format="ogg", codec="libopus"); out.seek(0)
        await update.message.reply_voice(voice=out)
    except Exception as e:
        logger.exception(f"Speed error: {e}")
        await update.message.reply_text(t(uid, "audio_fail"))


async def screenshot_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return
    url = context.args[0]
    if not url.startswith("http"):
        url = "https://" + url
    try:
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_PHOTO)
        r = requests.get(f"https://image.thum.io/get/width/1200/crop/900/{url}", timeout=30)
        r.raise_for_status()
        await update.message.reply_photo(photo=io.BytesIO(r.content))
    except Exception as e:
        logger.exception(f"Screenshot error: {e}")
        await update.message.reply_text("⚠️ Screenshot error.")


async def translate_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if len(context.args) < 2:
        return
    lang, text = context.args[0], " ".join(context.args[1:])
    try:
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
        reply = await call_gemini(f"Translate this to {lang}:\n\n{text}", uid,
                                  system_instruction="Return ONLY the translation.")
        await update.message.reply_text(reply)
    except Exception as e:
        logger.exception(f"Translate error: {e}")


async def summarize_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = ""
    if update.message.reply_to_message and update.message.reply_to_message.text:
        text = update.message.reply_to_message.text
    elif context.args:
        text = " ".join(context.args)
    if not text:
        return
    try:
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
        reply = await call_gemini(f"Summarize this text clearly:\n\n{text}", uid)
        await update.message.reply_text(reply)
    except Exception as e:
        logger.exception(f"Summarize error: {e}")


# ══════════════════════════════════════════════════════════════════════
#  PHASE 3 — ADMIN
# ══════════════════════════════════════════════════════════════════════
async def _do_ban(context, uid, reason, actor):
    if uid not in state["BANNED"]:
        state["BANNED"].append(uid)
    if uid in state["WHITELIST"]:
        state["WHITELIST"].remove(uid)
    save_state()
    log_mod_action(actor, uid, "BAN", reason)
    try:
        await context.bot.send_message(OWNER_ID, f"🚨 Ban: <code>{uid}</code>. Reason: {reason}",
                                       parse_mode=ParseMode.HTML)
    except Exception:
        pass


@owner_only
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    kb = [
        [KeyboardButton("👥 Whitelist"), KeyboardButton("🚫 Bans")],
        [KeyboardButton("📊 Logs"),      KeyboardButton("📢 Broadcast")],
        [KeyboardButton("💾 Backup"),    KeyboardButton("ℹ️ Status")],
    ]
    await update.message.reply_text(
        t(uid, "admin_panel"),
        reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True),
    )


@owner_only
async def admin_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text
    if   txt == "👥 Whitelist": await whitelist_list(update, context)
    elif txt == "🚫 Bans":      await _show_bans(update, context)
    elif txt == "📊 Logs":      await logs_cmd(update, context)
    elif txt == "📢 Broadcast": await update.message.reply_text(t(update.effective_user.id, "use_broadcast"), parse_mode=ParseMode.HTML)
    elif txt == "💾 Backup":    await backup_cmd(update, context)
    elif txt == "ℹ️ Status":    await health_cmd(update, context)


async def _show_bans(update, context):
    uid = update.effective_user.id
    if not state["BANNED"]:
        await update.message.reply_text(t(uid, "banned_empty"))
        return
    lines = [t(uid, "banned_header"), ""]
    for b in state["BANNED"]:
        lines.append(f"  • <code>{b}</code>")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


@owner_only
async def add_whitelist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("👥 /add &lt;user_id&gt; [duration|perm]", parse_mode=ParseMode.HTML)
        return
    try:
        uid = int(context.args[0])
    except ValueError:
        return
    if uid not in state["WHITELIST"]:
        state["WHITELIST"].append(uid)
    if len(context.args) >= 2:
        d = parse_duration(context.args[1])
        if d and d != "perm":
            state["WHITELIST_EXPIRY"][str(uid)] = (datetime.now() + d).isoformat()
    save_state()
    log_mod_action(OWNER_ID, uid, "ADD_WHITELIST", "manual")
    await update.message.reply_text(t(OWNER_ID, "user_added", uid=uid), parse_mode=ParseMode.HTML)


@owner_only
async def remove_whitelist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return
    try:
        uid = int(context.args[0])
    except ValueError:
        return
    if uid in state["WHITELIST"]:
        state["WHITELIST"].remove(uid)
    state["WHITELIST_EXPIRY"].pop(str(uid), None)
    save_state()
    await update.message.reply_text(t(OWNER_ID, "access_revoked", uid=uid), parse_mode=ParseMode.HTML)


@owner_only
async def whitelist_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not state["WHITELIST"]:
        await update.message.reply_text(t(uid, "wl_empty"))
        return
    lines = [t(uid, "wl_header"), ""]
    for w in state["WHITELIST"]:
        exp = state["WHITELIST_EXPIRY"].get(str(w), "∞")
        lines.append(f"  • <code>{w}</code>  ·  until {exp}")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private" and update.effective_user.id != OWNER_ID:
        return
    if not await check_group_permissions(update, context):
        return
    if not context.args:
        return
    try:
        uid = int(context.args[0])
    except ValueError:
        return
    rest = context.args[1:]
    duration = None
    if rest:
        d = parse_duration(rest[0])
        if d:
            duration, rest = d, rest[1:]
    reason = " ".join(rest) or "no reason"
    await _do_ban(context, uid, reason, update.effective_user.id)

    if duration and duration != "perm":
        state["BANNED_TIMED"][str(uid)] = (datetime.now() + duration).isoformat()
    else:
        state["BANNED_TIMED"].pop(str(uid), None)
    save_state()

    if update.effective_chat.type in ("group", "supergroup"):
        try:
            await context.bot.ban_chat_member(update.effective_chat.id, uid)
        except Exception as e:
            logger.error(f"Ban chat error: {e}")

    ts = "forever" if not duration or duration == "perm" else f"for {duration}"
    await update.message.reply_text(f"🚫 <code>{uid}</code> banned ({ts}). Reason: {reason}", parse_mode=ParseMode.HTML)


async def unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private" and update.effective_user.id != OWNER_ID:
        return
    if not await check_group_permissions(update, context):
        return
    if not context.args:
        return
    try:
        uid = int(context.args[0])
    except ValueError:
        return
    if uid in state["BANNED"]:
        state["BANNED"].remove(uid)
    state["BANNED_TIMED"].pop(str(uid), None)
    save_state()
    if update.effective_chat.type in ("group", "supergroup"):
        try:
            await context.bot.unban_chat_member(update.effective_chat.id, uid)
        except Exception:
            pass
    await update.message.reply_text(f"✅ <code>{uid}</code> unbanned.", parse_mode=ParseMode.HTML)


async def mute_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private" and update.effective_user.id != OWNER_ID:
        return
    if not await check_group_permissions(update, context):
        return
    if len(context.args) < 2:
        await update.message.reply_text("🔇 /mute &lt;user_id&gt; &lt;duration|perm&gt;", parse_mode=ParseMode.HTML)
        return
    try:
        uid = int(context.args[0])
    except ValueError:
        return
    d = parse_duration(context.args[1])
    if not d:
        return
    exp = datetime.now() + (timedelta(days=36500) if d == "perm" else d)
    state["MUTED"][str(uid)] = exp.isoformat()
    save_state()
    log_mod_action(update.effective_user.id, uid, "MUTE", context.args[1])
    await update.message.reply_text(f"🔇 <code>{uid}</code> muted until {exp.strftime('%Y-%m-%d %H:%M')}.", parse_mode=ParseMode.HTML)


async def warn_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private" and update.effective_user.id != OWNER_ID:
        return
    if not await check_group_permissions(update, context):
        return
    if len(context.args) < 2:
        return
    try:
        uid = int(context.args[0])
    except ValueError:
        return
    reason = " ".join(context.args[1:])
    wl = state["WARNINGS"].setdefault(str(uid), [])
    wl.append({"reason": reason, "by": update.effective_user.id, "at": datetime.now().isoformat()})
    save_state()
    log_mod_action(update.effective_user.id, uid, "WARN", reason)
    await update.message.reply_text(f"⚠️ Warning <b>{len(wl)}/3</b> to <code>{uid}</code>.\nReason: {reason}", parse_mode=ParseMode.HTML)
    if len(wl) >= 3:
        await _do_ban(context, uid, "auto-ban: 3 warnings", update.effective_user.id)
        await update.message.reply_text(f"🚨 Auto-ban: <code>{uid}</code>.", parse_mode=ParseMode.HTML)


async def warnings_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private" and update.effective_user.id != OWNER_ID:
        return
    if not await check_group_permissions(update, context):
        return
    if not context.args:
        return
    uid = str(context.args[0])
    warns = state["WARNINGS"].get(uid, [])
    if not warns:
        await update.message.reply_text("✅ No warnings.")
        return
    lines = [f"⚠️ <b>Warnings for <code>{uid}</code></b>", ""]
    for i, w in enumerate(warns, 1):
        lines.append(f"  {i}. {w['at'][:16]} │ by {w['by']} │ {w['reason']}")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


@owner_only
async def broadcast_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args)
    if not text:
        return
    sent = failed = 0
    for u in state["WHITELIST"]:
        try:
            await context.bot.send_message(u, f"📢 <b>Broadcast</b>\n\n{text}", parse_mode=ParseMode.HTML)
            sent += 1
        except Exception:
            failed += 1
    await update.message.reply_text(f"📢 Sent: <b>{sent}</b>  │  Failed: <b>{failed}</b>", parse_mode=ParseMode.HTML)


@owner_only
async def send_direct(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        return
    try:
        uid = int(context.args[0])
    except ValueError:
        return
    text = " ".join(context.args[1:])
    try:
        await context.bot.send_message(uid, text)
        await update.message.reply_text("✅ Delivered.")
    except Exception as e:
        await update.message.reply_text(f"⚠️ Error: {e}")


@owner_only
async def backup_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    zip_name = "jarvis_backup.zip"
    with zipfile.ZipFile(zip_name, "w") as z:
        for f in ("main.py", "requirements.txt", "whitelist.json", "config.json", "tickets.json", "usage_stats.json"):
            if os.path.exists(f):
                z.write(f)
    await update.message.reply_document(document=open(zip_name, "rb"), filename=zip_name)
    os.remove(zip_name)


@owner_only
async def logs_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not os.path.exists("bot.log"):
        return
    with open("bot.log", "r", encoding="utf-8") as f:
        tail = f.readlines()[-35:]
    text = "".join(tail)[-4000:]
    await update.message.reply_text(f"📊 <b>Recent events</b>\n\n<pre>{text}</pre>", parse_mode=ParseMode.HTML)


@owner_only
async def export_logs_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if os.path.exists("bot.log"):
        await update.message.reply_document(document=open("bot.log", "rb"))


# ══════════════════════════════════════════════════════════════════════
#  PHASE 4 — ADVANCED AI
# ══════════════════════════════════════════════════════════════════════
async def _ai(update, context, instruction, need_reply=False):
    uid = update.effective_user.id
    if need_reply:
        r = update.message.reply_to_message
        if not r or not (r.text or r.caption):
            await update.message.reply_text(t(uid, "no_reply"))
            return
        text = r.text or r.caption
    else:
        text = " ".join(context.args)
    if not text and not need_reply:
        await update.message.reply_text("✏️ Provide arguments.")
        return
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    status = await update.message.reply_text(t(uid, "processing"), parse_mode=ParseMode.HTML)
    try:
        reply = await call_gemini(f"{instruction}\n\nINPUT:\n{text}", uid)
        try:
            await status.edit_text(reply[:4000], parse_mode=ParseMode.MARKDOWN)
        except Exception:
            await status.edit_text(reply[:4000])
        for i in range(4000, len(reply), 4000):
            await update.message.reply_text(reply[i:i+4000])
    except Exception as e:
        logger.exception(f"AI cmd error: {e}")
        await status.edit_text(t(uid, "req_error"))


async def review_cmd(update, context):
    await _ai(update, context, "Review this code. List bugs, security issues, style problems. Suggest fixes with examples.", need_reply=True)

async def regex_cmd(update, context):
    await _ai(update, context, "Generate a regex pattern for the described task. Return ONLY the pattern and one test example.")

async def sql_cmd(update, context):
    await _ai(update, context, "Write a SQL query for the described task. Add a one-line explanation.")

async def explain_cmd(update, context):
    await _ai(update, context, "Explain this code line by line in Russian. Be concise.", need_reply=True)

async def refactor_cmd(update, context):
    await _ai(update, context, "Refactor this code for readability and performance. Return optimized version + change list.", need_reply=True)

async def uml_cmd(update, context):
    await _ai(update, context, "Return a PlantUML text diagram for the described or given code.")

async def pytest_cmd(update, context):
    await _ai(update, context, "Generate a complete pytest file with test cases for this code. Return only Python code.", need_reply=True)

async def doc_cmd(update, context):
    await _ai(update, context, "Return this code with PEP-8 docstrings and inline comments added. Preserve logic.", need_reply=True)

async def cv_cmd(update, context):
    await _ai(update, context, "Structure the following raw bio into a professional Markdown CV: Summary, Experience, Skills, Education.")

async def translate_long_cmd(update, context):
    if len(context.args) < 2:
        await update.message.reply_text("🌐 /translate_long &lt;lang&gt; &lt;text&gt;", parse_mode=ParseMode.HTML)
        return
    lang, text = context.args[0], " ".join(context.args[1:])
    await _ai(update, context, f"Translate the following into {lang}. Preserve formatting.")

async def ask_cmd(update, context):
    uid = update.effective_user.id
    r = update.message.reply_to_message
    if not r or not r.text:
        await update.message.reply_text(t(uid, "no_reply"))
        return
    q = " ".join(context.args)
    doc = r.text[:30000]
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    status = await update.message.reply_text(t(uid, "processing"), parse_mode=ParseMode.HTML)
    try:
        reply = await call_gemini(f"Answer based ONLY on this document.\n\n{doc}\n\nQ: {q}", uid)
        await status.edit_text(reply[:4000])
    except Exception as e:
        logger.exception(f"Ask error: {e}")
        await status.edit_text(t(uid, "req_error"))


# ══════════════════════════════════════════════════════════════════════
#  PHASE 5 — SPECIAL PROTOCOLS
# ══════════════════════════════════════════════════════════════════════
@owner_only
async def export_whitelist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    payload = {
        "whitelist": state["WHITELIST"],
        "expiry":    state["WHITELIST_EXPIRY"],
        "exported_at": datetime.now().isoformat(),
    }
    _atomic_write_json("whitelist_export.json", payload)
    await update.message.reply_document(document=open("whitelist_export.json", "rb"))
    os.remove("whitelist_export.json")


@owner_only
async def clear_session_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    USER_HISTORY.clear()
    USER_MODES.clear()
    INCOGNITO_USERS.clear()
    LAST_REQUEST.clear()
    await update.message.reply_text("🧹 Session memory purged.")


async def report_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args)
    if not text:
        await update.message.reply_text("📩 /report &lt;issue&gt;", parse_mode=ParseMode.HTML)
        return
    ticket = {
        "id": len(TICKETS) + 1,
        "user_id": update.effective_user.id,
        "username": update.effective_user.username,
        "text": text,
        "status": "open",
        "at": datetime.now().isoformat(),
    }
    TICKETS.append(ticket)
    save_tickets()
    await update.message.reply_text(f"✅ Ticket <b>#{ticket['id']}</b> created.", parse_mode=ParseMode.HTML)
    try:
        await context.bot.send_message(OWNER_ID, f"📩 Ticket #{ticket['id']} from <code>{ticket['user_id']}</code>: {text}", parse_mode=ParseMode.HTML)
    except Exception:
        pass


@owner_only
async def tickets_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    opens = [x for x in TICKETS if x.get("status") == "open"]
    if not opens:
        await update.message.reply_text("📭 No open tickets.")
        return
    lines = ["📋 <b>Open tickets</b>", ""]
    for x in opens[:20]:
        lines.append(f"  #{x['id']}  │  <code>{x['user_id']}</code>  │  {x['text'][:60]}")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


@owner_only
async def close_ticket_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return
    try:
        tid = int(context.args[0])
    except ValueError:
        return
    for x in TICKETS:
        if x["id"] == tid:
            x["status"] = "closed"
            save_tickets()
            await update.message.reply_text(f"✅ Ticket #{tid} closed.")
            return
    await update.message.reply_text("❌ Ticket not found.")


@owner_only
async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    top = sorted(USER_STATS.items(), key=lambda kv: kv[1].get("messages", 0), reverse=True)[:10]
    if not top:
        await update.message.reply_text("📊 No data yet.")
        return
    lines = ["📊 <b>Top users</b>", ""]
    for uid, s in top:
        lines.append(f"  <code>{uid}</code>  ·  {s.get('messages',0)} msgs  ·  {s.get('commands',0)} cmds")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


@owner_only
async def health_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        cpu = psutil.cpu_percent(interval=0.5)
        ram = psutil.virtual_memory().percent
        dsk = psutil.disk_usage("/").percent
        up  = int(time.time() - STARTED_AT)
        h, m, s = up // 3600, (up % 3600) // 60, up % 60
        msg = (
            "💻 <b>System Health</b>\n\n"
            f"  CPU    │ {cpu}%\n"
            f"  RAM    │ {ram}%\n"
            f"  Disk   │ {dsk}%\n"
            f"  Uptime │ {h}h {m}m {s}s"
        )
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.exception(f"Health error: {e}")
        await update.message.reply_text("⚠️ Health check failed.")


@owner_only
async def stopwords_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("🛑 " + ", ".join(STOP_WORDS))
        return
    action = context.args[0].lower()
    if action == "add" and len(context.args) > 1:
        STOP_WORDS.append(" ".join(context.args[1:]))
        await update.message.reply_text("✅ Added.")
    elif action == "remove" and len(context.args) > 1:
        w = " ".join(context.args[1:])
        if w in STOP_WORDS:
            STOP_WORDS.remove(w)
        await update.message.reply_text("🗑 Removed (if existed).")


# ══════════════════════════════════════════════════════════════════════
#  SECURITY MIDDLEWARE + BACKGROUND JOBS
# ══════════════════════════════════════════════════════════════════════
async def cleanup_expired_job(context):
    now = datetime.now()
    changed = False

    for u in [k for k, v in list(state["WHITELIST_EXPIRY"].items()) if now > datetime.fromisoformat(v)]:
        try:
            state["WHITELIST"].remove(int(u))
        except ValueError:
            pass
        state["WHITELIST_EXPIRY"].pop(u, None)
        changed = True

    for u in [k for k, v in list(state.get("BANNED_TIMED", {}).items()) if now > datetime.fromisoformat(v)]:
        try:
            state["BANNED"].remove(int(u))
        except ValueError:
            pass
        state["BANNED_TIMED"].pop(u, None)
        changed = True

    for u in [k for k, v in list(state["MUTED"].items()) if now > datetime.fromisoformat(v)]:
        state["MUTED"].pop(u, None)
        changed = True

    if changed:
        save_state()


async def auto_backup_job(context):
    try:
        name = f"auto_backup_{datetime.now():%Y%m%d_%H%M}.zip"
        with zipfile.ZipFile(name, "w") as z:
            for f in ("main.py", "requirements.txt", "whitelist.json", "config.json"):
                if os.path.exists(f):
                    z.write(f)
        await context.bot.send_document(OWNER_ID, document=open(name, "rb"), filename=name)
        os.remove(name)
    except Exception as e:
        logger.exception(f"Auto-backup error: {e}")


async def global_security_middleware(update: Update, context):
    if not update.effective_user or not update.message:
        return
    uid = update.effective_user.id
    suid = str(uid)
    now = datetime.now()

    if suid in state["MUTED"]:
        if now > datetime.fromisoformat(state["MUTED"][suid]):
            state["MUTED"].pop(suid, None)
            save_state()
        else:
            raise ApplicationHandlerStop

    if uid in state["BANNED"]:
        raise ApplicationHandlerStop

    now_ts = time.time()
    bucket = [x for x in FLOOD_WINDOW.get(uid, []) if now_ts - x < 60]
    bucket.append(now_ts)
    FLOOD_WINDOW[uid] = bucket
    if len(bucket) > 10 and uid != OWNER_ID:
        try:
            await context.bot.send_message(OWNER_ID, f"🌊 Flood from <code>{uid}</code>. Auto-mute 5m.", parse_mode=ParseMode.HTML)
        except Exception:
            pass
        state["MUTED"][suid] = (datetime.now() + timedelta(minutes=5)).isoformat()
        save_state()
        raise ApplicationHandlerStop

    if uid != OWNER_ID and uid not in state["WHITELIST"]:
        entry = {
            "first_name":   update.effective_user.first_name,
            "last_name":    update.effective_user.last_name,
            "user_id":      uid,
            "username":     update.effective_user.username,
            "chat_id":      update.effective_chat.id,
            "timestamp":    now.isoformat(),
            "text_preview": (update.message.text or "[Media]")[:100],
        }
        logs = []
        if os.path.exists(INTRUDER_FILE):
            try:
                with open(INTRUDER_FILE, "r", encoding="utf-8") as f:
                    logs = json.load(f)
            except json.JSONDecodeError:
                pass
        logs.append(entry)
        _atomic_write_json(INTRUDER_FILE, logs)

        alert = (
            f"{t(OWNER_ID, 'unauthorized')}\n\n"
            f"  ID    │ <code>{uid}</code>\n"
            f"  User  │ @{entry['username']} ({entry['first_name']})\n"
            f"  Chat  │ <code>{entry['chat_id']}</code>\n"
            f"  Query │ {entry['text_preview']}"
        )
        try:
            await context.bot.send_message(OWNER_ID, alert, parse_mode=ParseMode.HTML)
        except Exception:
            pass
        raise ApplicationHandlerStop


# ══════════════════════════════════════════════════════════════════════
#  FLASK KEEPALIVE + MAIN
# ══════════════════════════════════════════════════════════════════════
async def post_init(application: Application):
    await application.bot.delete_webhook(drop_pending_updates=True)
    logger.info("Webhooks cleared. J.A.R.V.I.S. Systems Online.")


def run_flask():
    flask_app = Flask(__name__)

    @flask_app.route("/")
    @flask_app.route("/health")
    def health():
        return "J.A.R.V.I.S. is alive", 200

    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(TypeHandler(Update, global_security_middleware), group=-1)
    app.job_queue.run_repeating(cleanup_expired_job, interval=60)
    app.job_queue.run_repeating(auto_backup_job, interval=7 * 24 * 3600, first=10)

    for cmd, fn in [
        ("start", start), ("help", help_cmd), ("reset", reset_cmd),
        ("mode", mode_cmd), ("lang", lang_cmd),
        ("incognito", incognito_cmd), ("incognito_off", incognito_off_cmd),
    ]:
        app.add_handler(CommandHandler(cmd, fn))

    for cmd, fn in [
        ("draw", draw_cmd), ("qr", qr_cmd), ("tts", tts_cmd),
        ("poll", poll_cmd), ("quiz", quiz_cmd), ("speed", speed_cmd),
        ("screenshot", screenshot_cmd), ("translate", translate_cmd),
        ("summarize", summarize_cmd),
    ]:
        app.add_handler(CommandHandler(cmd, fn))

    app.add_handler(MessageHandler(filters.PHOTO,        photo_handler))
    app.add_handler(MessageHandler(filters.Sticker.ALL,  sticker_handler))
    app.add_handler(MessageHandler(filters.VOICE,        voice_handler))
    app.add_handler(MessageHandler(filters.Document.ALL, document_handler))

    for cmd, fn in [
        ("admin", admin_panel), ("add", add_whitelist), ("remove", remove_whitelist),
        ("whitelist", whitelist_list), ("ban", ban_user), ("unban", unban_user),
        ("mute", mute_user), ("warn", warn_user), ("warnings", warnings_list),
        ("broadcast", broadcast_msg), ("send", send_direct), ("backup", backup_cmd),
        ("logs", logs_cmd), ("export_logs", export_logs_cmd),
    ]:
        app.add_handler(CommandHandler(cmd, fn))

    app.add_handler(MessageHandler(
        filters.Regex(r"^(👥 Whitelist|🚫 Bans|📊 Logs|📢 Broadcast|💾 Backup|ℹ️ Status)$"),
        admin_buttons,
    ))

    for cmd, fn in [
        ("review", review_cmd), ("regex", regex_cmd), ("sql", sql_cmd),
        ("explain", explain_cmd), ("refactor", refactor_cmd), ("uml", uml_cmd),
        ("pytest", pytest_cmd), ("doc", doc_cmd), ("cv", cv_cmd),
        ("translate_long", translate_long_cmd), ("ask", ask_cmd),
    ]:
        app.add_handler(CommandHandler(cmd, fn))

    for cmd, fn in [
        ("export_whitelist", export_whitelist_cmd), ("clear_session", clear_session_cmd),
        ("report", report_cmd), ("tickets", tickets_cmd), ("close_ticket", close_ticket_cmd),
        ("stats", stats_cmd), ("health", health_cmd), ("stopwords", stopwords_cmd),
    ]:
        app.add_handler(CommandHandler(cmd, fn))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    logger.info("Starting polling...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    logger.info("Flask keepalive started.")
    main()
