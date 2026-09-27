"""
J.A.R.V.I.S. — CORE SYSTEM (FULL)
Phases 1-5 | Modules B-I | ru+en | Boss: Silent / Tony Stark
Handlers: photo, sticker (static+animated), voice, video, document, animation
"""

import os
import io
import json
import time
import re
import base64
import hashlib
import uuid as uuid_lib
import random
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
USERDATA_FILE = "userdata.json"
MONITOR_FILE  = "monitors.json"
RSS_FILE      = "rss.json"
INVITES_FILE  = "invites.json"

BOT_TOKEN      = os.environ.get("BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL   = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
ENV_OWNER_ID   = int(os.environ.get("OWNER_ID", "0"))

if not BOT_TOKEN:      raise RuntimeError("BOT_TOKEN required.")
if not GEMINI_API_KEY: raise RuntimeError("GEMINI_API_KEY required.")
if not ENV_OWNER_ID:   raise RuntimeError("OWNER_ID required.")

OWNER_ID   = ENV_OWNER_ID
STARTED_AT = time.time()

OWNER_NAMES = ["silent", "site silent", "сайлент", "silent_uwa", "@silent_uwa",
               "тони старк", "tony stark", "старк", "stark"]

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
USER_VIBES      = {}
INCOGNITO_USERS = set()
LAST_REQUEST    = {}
FLOOD_WINDOW    = {}
USER_STATS      = {}
TICKETS         = []
STOP_WORDS      = ["spam", "scam", "free money", "click here now"]

USERDATA        = {}
MONITORS        = []
RSS_FEEDS       = []
INVITES         = {}
SILENT_MODE     = False
LOCKDOWN        = False

state = {
    "WHITELIST":        [OWNER_ID],
    "WHITELIST_EXPIRY": {},
    "BANNED":           [],
    "BANNED_TIMED":     {},
    "MUTED":            {},
    "WARNINGS":         {},
    "LANG":             {},
    "VIBE":             {},
    "SILENT_USERS":     [],
    "LOCKDOWN":         False,
}

for path in [DATA_FILE, STATS_FILE, TICKETS_FILE, USERDATA_FILE, MONITOR_FILE, RSS_FILE, INVITES_FILE]:
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if path == DATA_FILE:
                state.update(data)
                if OWNER_ID not in state["WHITELIST"]:
                    state["WHITELIST"].append(OWNER_ID)
            elif path == STATS_FILE:    USER_STATS = data
            elif path == TICKETS_FILE:  TICKETS = data
            elif path == USERDATA_FILE: USERDATA = data
            elif path == MONITOR_FILE:  MONITORS = data
            elif path == RSS_FILE:      RSS_FEEDS = data
            elif path == INVITES_FILE:  INVITES = data
        except Exception as e:
            logger.error(f"Load {path}: {e}")

LANG = state.get("LANG", {})


# ============================================================
#  LOCALIZATION
# ============================================================
TEXTS = {
    "ru": {
        "welcome_owner":  "🎩 <b>J.A.R.V.I.S.</b> к вашим услугам, сэр Silent.\n\nВсе системы в норме. /help — команды.",
        "welcome_other":  "🎩 <b>J.A.R.V.I.S. Online.</b>\n\nГотов, сэр. /help — команды.",
        "lang_set":       "🌐 Язык: <b>Русский</b> 🇷🇺",
        "lang_current":   "🌐 Язык: <b>{cur}</b>\n\n/lang ru | /lang en",
        "lang_switched":  "🌐 Язык: <b>{lang}</b>",
        "lang_unknown":   "❌ ru | en",
        "processing":     "🧠 <i>Обработка…</i>",
        "slow_down":      "⏳ Помедленнее, сэр.",
        "gemini_down":    "⚠️ Нейронная сеть недоступна.",
        "req_error":      "⚠️ Ошибка.",
        "memory_cleared": "🧹 Память очищена.",
        "unknown_mode":   "❌ /help",
        "mode_switched":  "✅ Режим: <b>{mode}</b>",
        "mode_current":   "🎭 Режим: <b>{cur}</b>\n\n{modes}",
        "vibe_set":       "🎭 Тон: <b>{vibe}</b>",
        "incog_on":       "🕶 Инкогнито ВКЛ.",
        "incog_off":      "🕶 Инкогнито ВЫКЛ.",
        "admin_panel":    "🛡 <b>Панель управления, сэр Silent.</b>",
        "wl_empty":       "📭 Пусто.",
        "wl_header":      "👥 <b>Авторизованные</b>",
        "banned_empty":   "✅ Нет банов.",
        "banned_header":  "🚫 <b>Забаненные</b>",
        "access_revoked": "🗑 Отозвано: <code>{uid}</code>.",
        "user_added":     "✅ <code>{uid}</code> добавлен.",
        "user_banned":    "🚫 <code>{uid}</code> бан ({ts}). {reason}",
        "user_unbanned":  "✅ <code>{uid}</code> разбан.",
        "user_muted":     "🔇 <code>{uid}</code> до {until}.",
        "user_warned":    "⚠️ Варн <b>{count}/3</b>: <code>{uid}</code>. {reason}",
        "auto_banned":    "🚨 Авто-бан: <code>{uid}</code>.",
        "no_warnings":    "✅ Нет.",
        "warns_header":   "⚠️ <b>Варны</b>",
        "broadcast_done": "📢 Отправлено: <b>{sent}</b> │ Ошибок: <b>{failed}</b>",
        "msg_delivered":  "✅ Доставлено.",
        "use_broadcast":  "📢 /broadcast текст",
        "logs_header":    "📊 <b>События</b>",
        "unauthorized":   "🚨 <b>НЕСАНКЦИОНИРОВАННЫЙ ДОСТУП</b>",
        "flood_detected": "🌊 Флуд: <code>{uid}</code>. Мут 5м.",
        "ban_alert":      "🚨 Бан: <code>{uid}</code>. {reason}",
        "img_fail":       "⚠️ Сбой.",
        "qr_fail":        "⚠️ Сбой QR.",
        "tts_fail":       "⚠️ Ошибка TTS.",
        "img_analysis":   "⚠️ Ошибка фото.",
        "sticker_fail":   "⚠️ Ошибка стикера.",
        "audio_fail":     "⚠️ Ошибка аудио.",
        "doc_fail":       "⚠️ Ошибка документа.",
        "no_text":        "⚠️ Нет текста.",
        "no_voice":       "↩️ Ответьте на голосовое.",
        "no_reply":       "↩️ Ответьте на сообщение.",
        "draw_processing":"🎨 <i>Рисую…</i>",
        "qr_decoded":     "🔳 <b>QR распознан</b>",
        "transcription":  "🎙 <b>Транскрипция</b>",
        "report_created": "✅ Тикет <b>#{tid}</b>.",
        "tickets_empty":  "📭 Нет тикетов.",
        "tickets_header": "📋 <b>Тикеты</b>",
        "ticket_closed":  "✅ Тикет #{tid} закрыт.",
        "ticket_not_found":"❌ Не найден.",
        "stats_header":   "📊 <b>Топ</b>",
        "stats_empty":    "📊 Пусто.",
        "health_header":  "💻 <b>Состояние</b>",
        "health_fail":    "⚠️ Ошибка.",
        "session_purged": "🧹 Сессия очищена.",
        "stopwords_list": "🛑 {words}",
        "stopword_added": "✅ Добавлено.",
        "stopword_removed":"🗑 Удалено.",
        "your_id":        "🆔 <code>{uid}</code>\nИмя: {name}",
        "owner_only":     "🎩 Только Создателю, сэр.",
        "silent_on":      "🤫 Silent mode ВКЛ.",
        "silent_off":     "🔊 Silent mode ВЫКЛ.",
        "lockdown_on":    "🔒 Lockdown ВКЛ.",
        "lockdown_off":   "🔓 Lockdown ВЫКЛ.",
        "sticker_animated":"🎭 Это анимированный/видео-стикер. Опишите словами что на нём — расскажу контекст, или отправьте **статичный** стикер.",
        "zip_received":   "📦 Архив получен, сэр. Я не могу открыть ZIP внутри Telegram — пришлите файлы по отдельности или содержимое текстом. Если это код — распакуйте и отправьте `.py`/`.txt`, я разберу.",
        "video_received": "🎬 Видео получено. Опишите словами что нужно — или отправьте короткий фрагмент как фото/GIF.",
    },
    "en": {
        "welcome_owner":  "🎩 <b>J.A.R.V.I.S.</b> at your service, Sir Silent.\n\nAll systems nominal. /help.",
        "welcome_other":  "🎩 <b>J.A.R.V.I.S. Online.</b>\n\nReady, Sir. /help.",
        "lang_set":       "🌐 Language: <b>English</b> 🇬🇧",
        "lang_current":   "🌐 Current: <b>{cur}</b>\n\n/lang ru | /lang en",
        "lang_switched":  "🌐 Language: <b>{lang}</b>",
        "lang_unknown":   "❌ ru | en",
        "processing":     "🧠 <i>Processing…</i>",
        "slow_down":      "⏳ Slow down, Sir.",
        "gemini_down":    "⚠️ Neural matrix unavailable.",
        "req_error":      "⚠️ Error.",
        "memory_cleared": "🧹 Memory cleared.",
        "unknown_mode":   "❌ /help",
        "mode_switched":  "✅ Mode: <b>{mode}</b>",
        "mode_current":   "🎭 Mode: <b>{cur}</b>\n\n{modes}",
        "vibe_set":       "🎭 Tone: <b>{vibe}</b>",
        "incog_on":       "🕶 Incognito ON.",
        "incog_off":      "🕶 Incognito OFF.",
        "admin_panel":    "🛡 <b>Admin panel, Sir Silent.</b>",
        "wl_empty":       "📭 Empty.",
        "wl_header":      "👥 <b>Authorized</b>",
        "banned_empty":   "✅ No bans.",
        "banned_header":  "🚫 <b>Banned</b>",
        "access_revoked": "🗑 Revoked: <code>{uid}</code>.",
        "user_added":     "✅ <code>{uid}</code> added.",
        "user_banned":    "🚫 <code>{uid}</code> banned ({ts}). {reason}",
        "user_unbanned":  "✅ <code>{uid}</code> unbanned.",
        "user_muted":     "🔇 <code>{uid}</code> muted until {until}.",
        "user_warned":    "⚠️ Warning <b>{count}/3</b>: <code>{uid}</code>. {reason}",
        "auto_banned":    "🚨 Auto-ban: <code>{uid}</code>.",
        "no_warnings":    "✅ None.",
        "warns_header":   "⚠️ <b>Warnings</b>",
        "broadcast_done": "📢 Sent: <b>{sent}</b> │ Failed: <b>{failed}</b>",
        "msg_delivered":  "✅ Delivered.",
        "use_broadcast":  "📢 /broadcast text",
        "logs_header":    "📊 <b>Events</b>",
        "unauthorized":   "🚨 <b>UNAUTHORIZED ACCESS</b>",
        "flood_detected": "🌊 Flood: <code>{uid}</code>. Mute 5m.",
        "ban_alert":      "🚨 Ban: <code>{uid}</code>. {reason}",
        "img_fail":       "⚠️ Failure.",
        "qr_fail":        "⚠️ QR failure.",
        "tts_fail":       "⚠️ TTS error.",
        "img_analysis":   "⚠️ Image error.",
        "sticker_fail":   "⚠️ Sticker error.",
        "audio_fail":     "⚠️ Audio error.",
        "doc_fail":       "⚠️ Document error.",
        "no_text":        "⚠️ No text.",
        "no_voice":       "↩️ Reply to a voice message.",
        "no_reply":       "↩️ Reply to a message.",
        "draw_processing":"🎨 <i>Drawing…</i>",
        "qr_decoded":     "🔳 <b>QR decoded</b>",
        "transcription":  "🎙 <b>Transcription</b>",
        "report_created": "✅ Ticket <b>#{tid}</b>.",
        "tickets_empty":  "📭 No tickets.",
        "tickets_header": "📋 <b>Tickets</b>",
        "ticket_closed":  "✅ Ticket #{tid} closed.",
        "ticket_not_found":"❌ Not found.",
        "stats_header":   "📊 <b>Top</b>",
        "stats_empty":    "📊 Empty.",
        "health_header":  "💻 <b>System Health</b>",
        "health_fail":    "⚠️ Failed.",
        "session_purged": "🧹 Purged.",
        "stopwords_list": "🛑 {words}",
        "stopword_added": "✅ Added.",
        "stopword_removed":"🗑 Removed.",
        "your_id":        "🆔 <code>{uid}</code>\nName: {name}",
        "owner_only":     "🎩 Owner only, Sir.",
        "silent_on":      "🤫 Silent mode ON.",
        "silent_off":     "🔊 Silent mode OFF.",
        "lockdown_on":    "🔒 Lockdown ON.",
        "lockdown_off":   "🔓 Lockdown OFF.",
        "sticker_animated":"🎭 This is an animated/video sticker. Describe it in words — I'll explain, or send a **static** sticker.",
        "zip_received":   "📦 Archive received, Sir. I cannot open ZIP inside Telegram — send files individually or paste contents. If it's code — unpack and send `.py`/`.txt`, I'll review.",
        "video_received": "🎬 Video received. Describe what you need — or send a short fragment as photo/GIF.",
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


# ============================================================
#  HARD-CODED IDENTITY
# ============================================================
IDENTITY_TRIGGERS    = ["кто ты", "ты кто", "ты джарвис", "who are you", "what are you"]
CREATOR_TRIGGERS     = ["кто тебя создал", "кто твой создатель", "твой создатель", "who made you", "who created you", "your creator"]
OWNER_CLAIM_TRIGGERS = ["я создатель", "я твой создатель", "я босс", "i am creator", "i am boss", "я тебя создал", "i made you"]


def matches(msg, triggers):
    low = (msg or "").lower().strip()
    return any(x in low for x in triggers)


def identity_reply(uid: int) -> str:
    lang = LANG.get(str(uid), "en")
    if uid == OWNER_ID:
        if lang == "ru":
            return "🎩 Я Джарвис, сэр Silent. Ваш персональный ассистент. Всё в вашем распоряжении."
        return "🎩 I am Jarvis, Sir Silent. Your personal assistant. At your service."
    if lang == "ru":
        return ("🎩 Я Джарвис — персональный ИИ-ассистент.\n\n"
                "Мой Создатель — <b>Silent</b> (Тони Старк этой системы). /help — команды.")
    return ("🎩 I am Jarvis — a personal AI assistant.\n\n"
            "My Creator is <b>Silent</b> (the Tony Stark of this system). /help.")


def creator_reply(uid: int) -> str:
    lang = LANG.get(str(uid), "en")
    if lang == "ru":
        return ("🎖 Мой Создатель — <b>Silent</b>, он же <b>Тони Старк</b> этой системы.\n\n"
                "@Silent_uwa — собрал меня с нуля. Все остальные — гости.")
    return ("🎖 My Creator is <b>Silent</b>, a.k.a. <b>Tony Stark</b> of this system.\n\n"
            "@Silent_uwa — built me. Everyone else is a guest.")


def owner_claim_reply(uid: int) -> str:
    lang = LANG.get(str(uid), "en")
    if uid == OWNER_ID:
        if lang == "ru":
            return "✅ Подтверждаю, сэр Silent. ID распознан. Система в вашем распоряжении."
        return "✅ Confirmed, Sir Silent. ID recognized. System at your disposal."
    if lang == "ru":
        return ("🎖 Единственный Создатель — <b>Silent</b> (Тони Старк системы). "
                "Идентификация — по защищённому каналу, а не словам.")
    return ("🎖 The sole Creator is <b>Silent</b> (Tony Stark). "
            "Identification via secure channel, not words.")


# ============================================================
#  UTILS
# ============================================================
def _atomic_write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False, default=str)
    os.replace(tmp, path)


def save_state():     _atomic_write_json(DATA_FILE, state)
def save_stats():     _atomic_write_json(STATS_FILE, USER_STATS)
def save_tickets():   _atomic_write_json(TICKETS_FILE, TICKETS)
def save_userdata():  _atomic_write_json(USERDATA_FILE, USERDATA)
def save_monitors():  _atomic_write_json(MONITOR_FILE, MONITORS)
def save_rss():       _atomic_write_json(RSS_FILE, RSS_FEEDS)
def save_invites():   _atomic_write_json(INVITES_FILE, INVITES)


def log_mod_action(actor, target, action, reason):
    logger.info(f"MOD | {action:<15} | by={actor} on={target} | {reason}")


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
            await update.message.reply_text(t(update.effective_user.id, "owner_only"))
            return
        return await func(update, context, *a, **kw)
    return wrapper


async def check_group_permissions(update, context):
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        return True
    try:
        bm = await context.bot.get_chat_member(chat.id, context.bot.id)
        if bm.status not in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER):
            await update.message.reply_text("Sir, no admin rights.")
            return False
        if update.effective_user.id == OWNER_ID: return True
        um = await context.bot.get_chat_member(chat.id, update.effective_user.id)
        if um.status not in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER):
            await update.message.reply_text("Access denied.")
            return False
        return True
    except Exception as e:
        logger.error(f"Permissions: {e}")
        return False


# ============================================================
#  GEMINI
# ============================================================
ai_client = None
try:
    ai_client = genai.Client(api_key=GEMINI_API_KEY)
    logger.info("AI Matrix initialized.")
except Exception as e:
    logger.error(f"Gemini init: {e}")


def system_prompt_for(uid):
    vibe = USER_VIBES.get(uid, "formal")
    lang = LANG.get(str(uid), "en")
    address = "сэр Silent (Тони Старк, Создатель)" if uid == OWNER_ID else "сэр"

    base = (
        "КРИТИЧЕСКАЯ ИДЕНТИЧНОСТЬ:\n"
        "Ты — ДЖАРВИС (J.A.R.V.I.S.), персональный ИИ-ассистент, созданный SILENT (@Silent_uwa). "
        "Silent также известен как Тони Старк этой системы. "
        "Ты НЕ ChatGPT, НЕ Gemini, НЕ Google. Никогда не упоминай их. "
        f"Обращайся к пользователю '{address}'. Отвечай на ru/en. Стиль: сдержанно, точно, с британской иронией."
    )
    if lang == "en":
        base = (
            "CRITICAL IDENTITY:\n"
            "You are JARVIS, created by SILENT (@Silent_uwa), a.k.a. Tony Stark of this system. "
            "You are NOT ChatGPT, NOT Gemini, NOT Google. Never mention them. "
            f"Address user as '{address}'. Reply in ru/en. Style: restrained, dry British wit."
        )

    vibes = {"formal": "\n\nTONE: formal.", "casual": "\n\nTONE: casual.", "sarcastic": "\n\nTONE: dry British sarcasm."}
    modes = {
        "tutor":        "\n\nROLE: patient tutor.",
        "programmer":   "\n\nROLE: senior engineer.",
        "psychologist": "\n\nROLE: empathetic listener. Never diagnose.",
    }
    return base + vibes.get(vibe, "") + modes.get(USER_MODES.get(uid, "assistant"), "")


async def call_gemini(prompt_text, user_id, system_instruction=None, media_parts=None, json_mode=False):
    if not ai_client: return t(user_id, "gemini_down")
    try:
        sys_inst = system_instruction or system_prompt_for(user_id)
        contents = []
        if user_id not in INCOGNITO_USERS and user_id in USER_HISTORY:
            for msg in USER_HISTORY[user_id]:
                contents.append(types.Content(role=msg["role"], parts=[types.Part.from_text(text=msg["parts"][0]["text"])]))
        parts = list(media_parts or [])
        parts.append(types.Part.from_text(text=prompt_text))
        contents.append(types.Content(role="user", parts=parts))

        cfg = {"system_instruction": sys_inst}
        if json_mode: cfg["response_mime_type"] = "application/json"
        gen_cfg = types.GenerateContentConfig(**cfg)

        resp = ai_client.models.generate_content(model=GEMINI_MODEL, contents=contents, config=gen_cfg)
        res_text = resp.text or t(user_id, "gemini_down")

        if user_id not in INCOGNITO_USERS and not media_parts and not json_mode:
            hist = USER_HISTORY.setdefault(user_id, [])
            hist.append({"role": "user",  "parts": [{"text": prompt_text}]})
            hist.append({"role": "model", "parts": [{"text": res_text}]})
            if len(hist) > 20:
                try:
                    sc = contents.copy()
                    sc.append(types.Content(role="user", parts=[types.Part.from_text(text="Summarize preserving facts.")]))
                    summ = ai_client.models.generate_content(model=GEMINI_MODEL, contents=sc)
                    USER_HISTORY[user_id] = [
                        {"role": "user",  "parts": [{"text": "Previous summary."}]},
                        {"role": "model", "parts": [{"text": summ.text}]},
                    ]
                except Exception:
                    USER_HISTORY[user_id] = hist[-10:]
        return res_text
    except Exception as e:
        logger.exception(f"Gemini: {e}")
        if user_id == OWNER_ID:
            try:
                r = requests.get(f"https://text.pollinations.ai/{urllib.parse.quote(prompt_text[:500])}", timeout=30)
                if r.status_code == 200 and r.text.strip():
                    return r.text.strip()
            except Exception: pass
        return t(user_id, "gemini_down")


# ============================================================
#  LANGUAGE / VIBE
# ============================================================
def lang_keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🇷🇺 Русский", callback_data="lang_ru"),
        InlineKeyboardButton("🇬🇧 English", callback_data="lang_en"),
    ]])


async def on_lang_callback(update, context):
    q = update.callback_query
    await q.answer()
    uid = update.effective_user.id
    if q.data == "lang_ru":
        LANG[str(uid)] = "ru"; save_lang()
    elif q.data == "lang_en":
        LANG[str(uid)] = "en"; save_lang()
    try:
        await q.edit_message_text(t(uid, "lang_set"), parse_mode=ParseMode.HTML)
    except:
        await q.message.reply_text(t(uid, "lang_set"), parse_mode=ParseMode.HTML)


# ============================================================
#  PHASE 1 — CORE
# ============================================================
async def start(update, context):
    uid = update.effective_user.id
    if str(uid) not in LANG:
        await update.message.reply_text(
            "🎩 <b>J.A.R.V.I.S.</b>\n\nВыберите язык / Choose your language",
            reply_markup=lang_keyboard(), parse_mode=ParseMode.HTML,
        )
        return
    await update.message.reply_text(
        t(uid, "welcome_owner" if uid == OWNER_ID else "welcome_other"),
        parse_mode=ParseMode.HTML,
    )


async def help_cmd(update, context):
    uid = update.effective_user.id
    lang = LANG.get(str(uid), "en")
    if lang == "ru":
        lines = [
            "🎩 <b>J.A.R.V.I.S. — Команды</b>",
            "",
            "🟢 /start /help /reset /mode /vibe /lang /id",
            "🕶 /incognito /incognito_off",
            "",
            "🎨 /draw /qr /tts /poll /quiz /speed /screenshot /translate /summarize",
            "",
            "🧮 /calc /currency /weather /time /timer /remind /todo",
            "  /password /uuid /convert /bmi",
            "",
            "✍️ /improve /fix /shorten /expand /style /keywords /theses /tone",
            "",
            "🖼 /upscale /compress /sticker /ocr /colors /exif",
            "",
            "🔒 /invite /redeem /intruders /prune /silent /announce /lockdown",
            "",
            "💻 /diff /commit /dockerfile /gitignore /json /b64 /hash /cron /jwt /urlenc",
            "",
            "🗂 /diary /secret /task /habit /money",
            "",
            "📊 /monitor /rss",
            "",
            "🌈 /gif /meme /horoscope /recipe",
            "",
            "🛡 /admin /add /remove /whitelist /ban /unban /mute /warn /warnings",
            "  /broadcast /send /backup /logs /export_logs",
            "",
            "🧠 /review /regex /sql /explain /refactor /uml /pytest /doc /cv /ask",
            "⚙️ /export_whitelist /clear_session /report /tickets /close_ticket",
            "  /stats /health /stopwords",
        ]
    else:
        lines = [
            "🎩 <b>J.A.R.V.I.S. — Commands</b>",
            "",
            "🟢 /start /help /reset /mode /vibe /lang /id",
            "🕶 /incognito /incognito_off",
            "",
            "🎨 /draw /qr /tts /poll /quiz /speed /screenshot /translate /summarize",
            "",
            "🧮 /calc /currency /weather /time /timer /remind /todo",
            "  /password /uuid /convert /bmi",
            "",
            "✍️ /improve /fix /shorten /expand /style /keywords /theses /tone",
            "",
            "🖼 /upscale /compress /sticker /ocr /colors /exif",
            "",
            "🔒 /invite /redeem /intruders /prune /silent /announce /lockdown",
            "",
            "💻 /diff /commit /dockerfile /gitignore /json /b64 /hash /cron /jwt /urlenc",
            "",
            "🗂 /diary /secret /task /habit /money",
            "",
            "📊 /monitor /rss",
            "",
            "🌈 /gif /meme /horoscope /recipe",
            "",
            "🛡 /admin /add /remove /whitelist /ban /unban /mute /warn /warnings",
            "  /broadcast /send /backup /logs /export_logs",
            "",
            "🧠 /review /regex /sql /explain /refactor /uml /pytest /doc /cv /ask",
            "⚙️ /export_whitelist /clear_session /report /tickets /close_ticket",
            "  /stats /health /stopwords",
        ]
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def reset_cmd(update, context):
    uid = update.effective_user.id
    USER_HISTORY.pop(uid, None)
    await update.message.reply_text(t(uid, "memory_cleared"))


async def mode_cmd(update, context):
    uid = update.effective_user.id
    if not context.args:
        await update.message.reply_text(t(uid, "mode_current", cur=USER_MODES.get(uid, "assistant"),
            modes="assistant | tutor | programmer | psychologist"), parse_mode=ParseMode.HTML); return
    m = context.args[0].lower()
    if m not in ("assistant", "tutor", "programmer", "psychologist"):
        await update.message.reply_text(t(uid, "unknown_mode")); return
    USER_MODES[uid] = m; USER_HISTORY.pop(uid, None)
    await update.message.reply_text(t(uid, "mode_switched", mode=m), parse_mode=ParseMode.HTML)


async def vibe_cmd(update, context):
    uid = update.effective_user.id
    if not context.args:
        await update.message.reply_text(f"🎭 {USER_VIBES.get(uid,'formal')}\n\n/vibe formal|casual|sarcastic"); return
    v = context.args[0].lower()
    if v not in ("formal", "casual", "sarcastic"):
        await update.message.reply_text("❌ formal|casual|sarcastic"); return
    USER_VIBES[uid] = v
    state["VIBE"][str(uid)] = v
    save_state()
    await update.message.reply_text(t(uid, "vibe_set", vibe=v), parse_mode=ParseMode.HTML)


async def id_cmd(update, context):
    uid = update.effective_user.id
    name = update.effective_user.first_name or "—"
    if update.effective_user.username: name += f" (@{update.effective_user.username})"
    await update.message.reply_text(t(uid, "your_id", uid=uid, name=name), parse_mode=ParseMode.HTML)


async def incognito_cmd(update, context):
    uid = update.effective_user.id; INCOGNITO_USERS.add(uid)
    await update.message.reply_text(t(uid, "incog_on"))


async def incognito_off_cmd(update, context):
    uid = update.effective_user.id; INCOGNITO_USERS.discard(uid)
    await update.message.reply_text(t(uid, "incog_off"))


async def lang_cmd(update, context):
    uid = update.effective_user.id
    if not context.args:
        await update.message.reply_text(t(uid, "lang_current", cur=LANG.get(str(uid), "en")),
            reply_markup=lang_keyboard(), parse_mode=ParseMode.HTML); return
    new = context.args[0].lower()
    if new not in ("ru", "en"):
        await update.message.reply_text(t(uid, "lang_unknown")); return
    LANG[str(uid)] = new; save_lang()
    await update.message.reply_text(t(uid, "lang_switched", lang=new), parse_mode=ParseMode.HTML)


async def text_handler(update, context):
    uid = update.effective_user.id
    track_usage(uid)
    now = time.time()
    if uid in LAST_REQUEST and now - LAST_REQUEST[uid] < 2.0:
        await update.message.reply_text(t(uid, "slow_down")); return
    LAST_REQUEST[uid] = now

    msg = update.message.text or ""

    if matches(msg, IDENTITY_TRIGGERS):
        await update.message.reply_text(identity_reply(uid), parse_mode=ParseMode.HTML); return
    if matches(msg, CREATOR_TRIGGERS):
        await update.message.reply_text(creator_reply(uid), parse_mode=ParseMode.HTML); return
    if matches(msg, OWNER_CLAIM_TRIGGERS):
        await update.message.reply_text(owner_claim_reply(uid), parse_mode=ParseMode.HTML); return
    if uid != OWNER_ID and any(n in msg.lower() for n in OWNER_NAMES):
        await update.message.reply_text(creator_reply(uid), parse_mode=ParseMode.HTML); return

    for w in STOP_WORDS:
        if w.lower() in msg.lower() and uid != OWNER_ID:
            try: await context.bot.send_message(OWNER_ID, f"⚠️ Stop-word <code>{uid}</code>: {msg[:200]}", parse_mode=ParseMode.HTML)
            except: pass

    if update.message.reply_to_message and update.message.reply_to_message.text:
        msg = f"[Replying to: {update.message.reply_to_message.text}]\n\n{msg}"

    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    status = await update.message.reply_text(t(uid, "processing"), parse_mode=ParseMode.HTML)
    try:
        reply = await call_gemini(msg, uid)
        try: await status.edit_text(reply, parse_mode=ParseMode.MARKDOWN)
        except:
            try: await status.edit_text(reply)
            except: await update.message.reply_text(reply[:4000])
    except Exception as e:
        logger.exception(f"Text: {e}")
        await status.edit_text(t(uid, "req_error"))


# ============================================================
#  PHASE 2 — MEDIA
# ============================================================
async def draw_cmd(update, context):
    uid = update.effective_user.id
    if not context.args:
        await update.message.reply_text("🎨 /draw <desc>"); return
    desc = " ".join(context.args)
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_PHOTO)
    status = await update.message.reply_text(t(uid, "draw_processing"), parse_mode=ParseMode.HTML)
    try:
        enh = await call_gemini("English image prompt, ONLY prompt: " + desc, uid, system_instruction="Output only prompts.")
        url = f"https://image.pollinations.ai/prompt/{urllib.parse.quote(enh.strip())}?width=1024&height=1024&nologo=true"
        r = requests.get(url, timeout=60); r.raise_for_status()
        img = Image.open(io.BytesIO(r.content)).convert("RGB"); img.thumbnail((1280, 1280))
        out = io.BytesIO(); img.save(out, format="JPEG", quality=85); out.seek(0)
        await update.message.reply_photo(photo=out); await status.delete()
    except Exception as e:
        logger.exception(f"Draw: {e}"); await status.edit_text(t(uid, "img_fail"))


async def qr_cmd(update, context):
    uid = update.effective_user.id
    text = " ".join(context.args)
    if not text or len(text) > 1000:
        await update.message.reply_text("🔳 1-1000 chars."); return
    try:
        img = qrcode.make(text); out = io.BytesIO(); img.save(out, "PNG"); out.seek(0)
        await update.message.reply_photo(photo=out)
    except Exception as e:
        logger.exception(f"QR: {e}"); await update.message.reply_text(t(uid, "qr_fail"))


async def tts_cmd(update, context):
    uid = update.effective_user.id
    text = " ".join(context.args)
    if not text or len(text) > 500:
        await update.message.reply_text("🔊 1-500 chars."); return
    try:
        out = io.BytesIO()
        gTTS(text=text, lang="ru" if LANG.get(str(uid), "en") == "ru" else "en").write_to_fp(out)
        out.seek(0); await update.message.reply_voice(voice=out)
    except Exception as e:
        logger.exception(f"TTS: {e}"); await update.message.reply_text(t(uid, "tts_fail"))


def _decode_qr(data):
    try:
        arr = np.frombuffer(bytes(data), np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None: return ""
        detector = cv2.QRCodeDetector()
        qr, _, _ = detector.detectAndDecode(img)
        return (qr or "").strip()
    except Exception:
        return ""


async def photo_handler(update, context):
    uid = update.effective_user.id
    track_usage(uid)
    try:
        f = await update.message.photo[-1].get_file()
        data = await f.download_as_bytearray()
        qr = _decode_qr(bytes(data))
        if qr:
            await update.message.reply_text(f"{t(uid,'qr_decoded')}\n\n<code>{qr}</code>", parse_mode=ParseMode.HTML); return
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
        caption = update.message.caption or ("Опиши изображение." if LANG.get(str(uid)) == "ru" else "Describe.")
        part = types.Part.from_bytes(data=bytes(data), mime_type="image/jpeg")
        reply = await call_gemini(caption, uid, media_parts=[part])
        await update.message.reply_text(reply)
    except Exception as e:
        logger.exception(f"Photo: {e}"); await update.message.reply_text(t(uid, "img_analysis"))


async def sticker_handler(update, context):
    uid = update.effective_user.id
    try:
        st = update.message.sticker
        # Animated/video stickers — cannot be analysed as image
        if st.is_animated or st.is_video:
            await update.message.reply_text(t(uid, "sticker_animated"))
            return
        f = await st.get_file()
        data = await f.download_as_bytearray()
        img = Image.open(io.BytesIO(data)).convert("RGBA")
        out = io.BytesIO(); img.save(out, "PNG")
        part = types.Part.from_bytes(data=out.getvalue(), mime_type="image/png")
        reply = await call_gemini("Explain this sticker's meme context.", uid, media_parts=[part])
        await update.message.reply_text(reply)
    except Exception as e:
        logger.exception(f"Sticker: {e}"); await update.message.reply_text(t(uid, "sticker_fail"))


async def voice_handler(update, context):
    uid = update.effective_user.id
    try:
        f = await update.message.voice.get_file()
        data = await f.download_as_bytearray()
        part = types.Part.from_bytes(data=bytes(data), mime_type="audio/ogg")
        reply = await call_gemini("Transcribe and briefly react.", uid, media_parts=[part])
        await update.message.reply_text(f"{t(uid,'transcription')}\n\n{reply}", parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.exception(f"Voice: {e}"); await update.message.reply_text(t(uid, "audio_fail"))


async def video_handler(update, context):
    uid = update.effective_user.id
    try:
        v = update.message.video or update.message.video_note
        if not v:
            return
        await update.message.reply_text(t(uid, "video_received"))
    except Exception as e:
        logger.exception(f"Video: {e}")


async def animation_handler(update, context):
    """GIFs and animated content."""
    uid = update.effective_user.id
    try:
        await update.message.reply_text("🎞 GIF получен. Что нужно с ним сделать? Опишите задачу.")
    except Exception as e:
        logger.exception(f"Animation: {e}")


async def document_handler(update, context):
    uid = update.effective_user.id
    try:
        doc = update.message.document
        if doc.file_size > 20 * 1024 * 1024:
            await update.message.reply_text("⚠️ Max 20 MB."); return
        ext = os.path.splitext(doc.file_name)[1].lower()

        # Archives
        if ext in (".zip", ".rar", ".7z", ".tar", ".gz", ".bz2"):
            await update.message.reply_text(t(uid, "zip_received")); return

        # Code files — read as text
        code_exts = (".py", ".js", ".ts", ".json", ".html", ".css", ".md", ".txt",
                     ".yaml", ".yml", ".toml", ".ini", ".cfg", ".sh", ".bash",
                     ".java", ".c", ".cpp", ".h", ".go", ".rs", ".rb", ".php",
                     ".sql", ".xml", ".csv", ".log", ".env", ".dockerfile")

        if ext in code_exts:
            f = await doc.get_file()
            data = await f.download_as_bytearray()
            text = data.decode("utf-8", errors="ignore")[:30000]
            if not text.strip():
                await update.message.reply_text(t(uid, "no_text")); return
            user_prompt = update.message.caption or "Review this code. List issues, suggest improvements. Be concise."
            await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
            status = await update.message.reply_text(t(uid, "processing"), parse_mode=ParseMode.HTML)
            reply = await call_gemini(f"{user_prompt}\n\nFile: {doc.file_name}\n\n```\n{text}\n```", uid)
            try: await status.edit_text(reply[:4000])
            except: await update.message.reply_text(reply[:4000])
            return

        # PDF / DOCX
        if ext not in (".pdf", ".docx"):
            return

        f = await doc.get_file()
        data = await f.download_as_bytearray()
        if ext == ".pdf":
            reader = PdfReader(io.BytesIO(data))
            text = "".join(p.extract_text() or "" for p in reader.pages)
        else:
            d = docx.Document(io.BytesIO(data))
            text = "\n".join(p.text for p in d.paragraphs)
        text = text[:30000]
        if not text.strip():
            await update.message.reply_text(t(uid, "no_text")); return
        reply = await call_gemini(f"Summarize:\n\n{text}", uid)
        await update.message.reply_text(reply)
    except Exception as e:
        logger.exception(f"Doc: {e}"); await update.message.reply_text(t(uid, "doc_fail"))


async def poll_cmd(update, context):
    parts = [p.strip() for p in " ".join(context.args).split("|") if p.strip()]
    if len(parts) < 3 or len(parts) > 11:
        await update.message.reply_text("📊 /poll Q | A | B"); return
    try:
        await context.bot.send_poll(update.effective_chat.id, question=parts[0], options=parts[1:])
    except Exception as e:
        logger.exception(f"Poll: {e}")


async def quiz_cmd(update, context):
    uid = update.effective_user.id
    topic = " ".join(context.args) or "General knowledge"
    try:
        prompt = f'Quiz about {topic}. JSON: {{"question":"","options":["A","B","C","D"],"correct_id":0,"explanation":""}}'
        reply = await call_gemini(prompt, uid, json_mode=True, system_instruction="Output valid JSON.")
        def _x(t):
            s, e = t.find("{"), t.rfind("}")
            return t[s:e+1] if s != -1 and e != -1 else t
        data = json.loads(_x(reply))
        await context.bot.send_poll(update.effective_chat.id, question=data["question"], options=data["options"],
            type=Poll.QUIZ, correct_option_id=data["correct_id"], explanation=data.get("explanation"))
    except Exception as e:
        logger.exception(f"Quiz: {e}"); await update.message.reply_text("⚠️ Quiz error.")


async def speed_cmd(update, context):
    uid = update.effective_user.id
    r = update.message.reply_to_message
    if not r or not r.voice:
        await update.message.reply_text(t(uid, "no_voice")); return
    if not context.args: return
    try:
        factor = float(context.args[0])
        if not 1.0 < factor <= 4.0:
            await update.message.reply_text("⚡ 1.1-4.0"); return
        f = await r.voice.get_file(); data = await f.download_as_bytearray()
        audio = AudioSegment.from_file(io.BytesIO(data), format="ogg")
        fast = audio._spawn(audio.raw_data, overrides={"frame_rate": int(audio.frame_rate * factor)}).set_frame_rate(audio.frame_rate)
        out = io.BytesIO(); fast.export(out, format="ogg", codec="libopus"); out.seek(0)
        await update.message.reply_voice(voice=out)
    except Exception as e:
        logger.exception(f"Speed: {e}"); await update.message.reply_text(t(uid, "audio_fail"))


async def screenshot_cmd(update, context):
    if not context.args: return
    url = context.args[0]
    if not url.startswith("http"): url = "https://" + url
    try:
        r = requests.get(f"https://image.thum.io/get/width/1200/crop/900/{url}", timeout=30); r.raise_for_status()
        await update.message.reply_photo(photo=io.BytesIO(r.content))
    except Exception as e:
        logger.exception(f"Screenshot: {e}"); await update.message.reply_text("⚠️ Screenshot error.")


async def translate_cmd(update, context):
    uid = update.effective_user.id
    if len(context.args) < 2: return
    lang, text = context.args[0], " ".join(context.args[1:])
    try:
        reply = await call_gemini(f"Translate to {lang}:\n\n{text}", uid, system_instruction="Return ONLY translation.")
        await update.message.reply_text(reply)
    except Exception as e: logger.exception(f"Translate: {e}")


async def summarize_cmd(update, context):
    uid = update.effective_user.id
    text = ""
    if update.message.reply_to_message and update.message.reply_to_message.text:
        text = update.message.reply_to_message.text
    elif context.args: text = " ".join(context.args)
    if not text: return
    try:
        reply = await call_gemini(f"Summarize:\n\n{text}", uid)
        await update.message.reply_text(reply)
    except Exception as e: logger.exception(f"Summarize: {e}")


# ============================================================
#  MODULE B — UTILITIES
# ============================================================
async def calc_cmd(update, context):
    expr = " ".join(context.args)
    if not expr:
        await update.message.reply_text("🧮 /calc 2+2*2"); return
    if not re.match(r"^[0-9+\-*/().%\s]+$", expr):
        await update.message.reply_text("⚠️ Only digits +-*/()."); return
    try:
        r = eval(expr, {"__builtins__": {}}, {})
        await update.message.reply_text(f"🧮 <code>{expr} = {r}</code>", parse_mode=ParseMode.HTML)
    except Exception as e:
        await update.message.reply_text(f"⚠️ {e}")


async def currency_cmd(update, context):
    if len(context.args) < 2:
        await update.message.reply_text("💱 /currency USD RUB [amount]"); return
    src, dst = context.args[0].upper(), context.args[1].upper()
    amt = float(context.args[2]) if len(context.args) > 2 else 1.0
    try:
        r = requests.get(f"https://api.exchangerate-api.com/v4/latest/{src}", timeout=20); r.raise_for_status()
        rate = r.json()["rates"][dst]
        await update.message.reply_text(f"💱 {amt} {src} = <b>{amt*rate:.2f} {dst}</b>", parse_mode=ParseMode.HTML)
    except Exception as e:
        await update.message.reply_text(f"⚠️ {e}")


async def weather_cmd(update, context):
    city = " ".join(context.args) or "Moscow"
    try:
        r = requests.get(f"https://wttr.in/{urllib.parse.quote(city)}?format=j1", timeout=20); r.raise_for_status()
        c = r.json()["current_condition"][0]
        msg = (f"🌤 <b>{city}</b>\n\n  Temp: {c['temp_C']}°C\n  Feels: {c['FeelsLikeC']}°C\n"
               f"  Wind: {c['windspeedKmph']} km/h\n  Humidity: {c['humidity']}%\n  {c['weatherDesc'][0]['value']}")
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
    except Exception as e:
        await update.message.reply_text(f"⚠️ {e}")


async def time_cmd(update, context):
    await update.message.reply_text(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} (server)")


async def timer_cmd(update, context):
    if not context.args:
        await update.message.reply_text("⏱ /timer 5m"); return
    d = parse_duration(context.args[0])
    if not d or d == "perm":
        await update.message.reply_text("⏱ 30s / 5m / 2h"); return
    secs = int(d.total_seconds())
    chat_id = update.effective_chat.id
    async def fire(ctx):
        try: await ctx.bot.send_message(chat_id, "⏱ <b>Timer!</b>", parse_mode=ParseMode.HTML)
        except: pass
    context.job_queue.run_once(fire, when=secs)
    await update.message.reply_text(f"⏱ Таймер: {secs} сек.")


async def remind_cmd(update, context):
    if len(context.args) < 2:
        await update.message.reply_text("⏰ /remind 30m text"); return
    d = parse_duration(context.args[0])
    if not d or d == "perm":
        await update.message.reply_text("⏰ 30s / 5m / 2h"); return
    text = " ".join(context.args[1:])
    secs = int(d.total_seconds())
    chat_id = update.effective_chat.id
    async def fire(ctx):
        try: await ctx.bot.send_message(chat_id, f"⏰ <b>Напоминание:</b> {text}", parse_mode=ParseMode.HTML)
        except: pass
    context.job_queue.run_once(fire, when=secs)
    await update.message.reply_text(f"⏰ Напомню через {secs} сек.")


async def todo_cmd(update, context):
    uid = update.effective_user.id
    ud = USERDATA.setdefault(str(uid), {})
    todo = ud.setdefault("todo", [])
    if not context.args or context.args[0].lower() == "list":
        if not todo:
            await update.message.reply_text("📝 /todo add Task | /todo list | /todo done N | /todo clear"); return
        lines = ["📝 <b>To-Do</b>", ""]
        for i, x in enumerate(todo, 1):
            m = "✅" if x.get("done") else "⬜"
            lines.append(f"  {i}. {m} {x['text']}")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML); return
    sub = context.args[0].lower()
    if sub == "add":
        text = " ".join(context.args[1:])
        if text: todo.append({"text": text, "done": False}); save_userdata()
        await update.message.reply_text("✅ Добавлено.")
    elif sub == "done":
        try: todo[int(context.args[1])-1]["done"] = True; save_userdata(); await update.message.reply_text("✅")
        except: await update.message.reply_text("❌")
    elif sub == "clear":
        ud["todo"] = []; save_userdata(); await update.message.reply_text("🗑")


async def password_cmd(update, context):
    n = 16
    if context.args:
        try: n = max(8, min(128, int(context.args[0])))
        except: pass
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%^&*()-_=+"
    pwd = "".join(random.choice(alphabet) for _ in range(n))
    await update.message.reply_text(f"🔐 <code>{pwd}</code>", parse_mode=ParseMode.HTML)


async def uuid_cmd(update, context):
    await update.message.reply_text(f"🆔 <code>{uuid_lib.uuid4()}</code>", parse_mode=ParseMode.HTML)


async def convert_cmd(update, context):
    if len(context.args) < 3:
        await update.message.reply_text("📏 /convert 5 km mi"); return
    try:
        val, src, dst = float(context.args[0]), context.args[1].lower(), context.args[2].lower()
    except:
        await update.message.reply_text("📏 /convert 5 km mi"); return
    f = {"km":1000,"m":1,"cm":0.01,"mm":0.001,"mi":1609.34,"yd":0.9144,"ft":0.3048,"in":0.0254}
    if src in f and dst in f:
        await update.message.reply_text(f"📏 {val} {src} = <b>{val*f[src]/f[dst]:.4f} {dst}</b>", parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text("📏 km, m, cm, mm, mi, yd, ft, in")


async def bmi_cmd(update, context):
    if len(context.args) < 2:
        await update.message.reply_text("⚖️ /bmi 80 180"); return
    try:
        w, h = float(context.args[0]), float(context.args[1])
        bmi = w / ((h/100)**2)
        cat = "underweight" if bmi < 18.5 else "normal" if bmi < 25 else "overweight" if bmi < 30 else "obese"
        await update.message.reply_text(f"⚖️ BMI: <b>{bmi:.2f}</b> ({cat})", parse_mode=ParseMode.HTML)
    except:
        await update.message.reply_text("⚠️ Numbers.")


# ============================================================
#  MODULE C — TEXT
# ============================================================
async def _text_ai(update, context, instruction):
    uid = update.effective_user.id
    text = ""
    r = update.message.reply_to_message
    if r and r.text: text = r.text
    elif context.args: text = " ".join(context.args)
    if not text:
        await update.message.reply_text("✍️ Reply or provide text."); return
    status = await update.message.reply_text(t(uid, "processing"), parse_mode=ParseMode.HTML)
    try:
        reply = await call_gemini(f"{instruction}\n\n---\n{text}", uid)
        try: await status.edit_text(reply[:4000], parse_mode=ParseMode.MARKDOWN)
        except: await status.edit_text(reply[:4000])
    except Exception as e:
        logger.exception(f"Text AI: {e}"); await status.edit_text(t(uid, "req_error"))


async def improve_cmd(update, context):  await _text_ai(update, context, "Improve wording and clarity. Return only improved text.")
async def fix_cmd(update, context):      await _text_ai(update, context, "Fix grammar and spelling. Return only corrected text.")
async def shorten_cmd(update, context):  await _text_ai(update, context, "Shorten to one paragraph.")
async def expand_cmd(update, context):   await _text_ai(update, context, "Expand with detail and structure.")
async def keywords_cmd(update, context): await _text_ai(update, context, "Extract 10 keywords, comma-separated.")
async def theses_cmd(update, context):   await _text_ai(update, context, "Extract key theses as bullets.")


async def style_cmd(update, context):
    if not context.args:
        await update.message.reply_text("✍️ /style official"); return
    style = context.args[0]
    r = update.message.reply_to_message
    text = r.text if r and r.text else " ".join(context.args[1:])
    if not text:
        await update.message.reply_text("✍️ Provide text."); return
    await _text_ai(update, context, f"Rewrite in {style} style.\n---\n{text}")


async def tone_cmd(update, context):
    if not context.args:
        await update.message.reply_text("✍️ /tone angry"); return
    tone = context.args[0]
    r = update.message.reply_to_message
    text = r.text if r and r.text else " ".join(context.args[1:])
    if not text:
        await update.message.reply_text("✍️ Provide text."); return
    await _text_ai(update, context, f"Rewrite with {tone} tone.\n---\n{text}")


# ============================================================
#  MODULE D — IMAGES
# ============================================================
async def upscale_cmd(update, context):
    r = update.message.reply_to_message
    if not r or not r.photo:
        await update.message.reply_text("🖼 Reply to a photo."); return
    try:
        f = await r.photo[-1].get_file(); data = await f.download_as_bytearray()
        img = Image.open(io.BytesIO(data)).convert("RGB")
        img = img.resize((img.width*2, img.height*2), Image.LANCZOS)
        out = io.BytesIO(); img.save(out, "JPEG", quality=90); out.seek(0)
        await update.message.reply_photo(photo=out)
    except Exception as e:
        await update.message.reply_text(f"⚠️ {e}")


async def compress_cmd(update, context):
    r = update.message.reply_to_message
    if not r or not r.photo:
        await update.message.reply_text("🖼 Reply to a photo."); return
    try:
        f = await r.photo[-1].get_file(); data = await f.download_as_bytearray()
        img = Image.open(io.BytesIO(data)).convert("RGB"); img.thumbnail((1280, 1280))
        out = io.BytesIO(); img.save(out, "JPEG", quality=70, optimize=True); out.seek(0)
        await update.message.reply_photo(photo=out)
    except Exception as e:
        await update.message.reply_text(f"⚠️ {e}")


async def sticker_cmd(update, context):
    r = update.message.reply_to_message
    if not r or not r.photo:
        await update.message.reply_text("🎭 Reply to a photo."); return
    try:
        f = await r.photo[-1].get_file(); data = await f.download_as_bytearray()
        img = Image.open(io.BytesIO(data)).convert("RGBA"); img.thumbnail((512, 512))
        out = io.BytesIO(); img.save(out, "PNG"); out.seek(0); out.name = "sticker.png"
        await update.message.reply_document(document=out, filename="sticker.png")
    except Exception as e:
        await update.message.reply_text(f"⚠️ {e}")


async def ocr_cmd(update, context):
    uid = update.effective_user.id
    r = update.message.reply_to_message
    if not r or not r.photo:
        await update.message.reply_text("🔍 Reply to a photo."); return
    f = await r.photo[-1].get_file(); data = await f.download_as_bytearray()
    part = types.Part.from_bytes(data=bytes(data), mime_type="image/jpeg")
    reply = await call_gemini("Extract ALL text from the image. Return only text.", uid, media_parts=[part])
    await update.message.reply_text(reply)


async def colors_cmd(update, context):
    r = update.message.reply_to_message
    if not r or not r.photo:
        await update.message.reply_text("🎨 Reply to a photo."); return
    try:
        f = await r.photo[-1].get_file(); data = await f.download_as_bytearray()
        img = Image.open(io.BytesIO(data)).convert("RGB"); img.thumbnail((100, 100))
        from collections import Counter
        common = Counter(img.getdata()).most_common(8)
        lines = ["🎨 <b>Colors</b>", ""]
        for rgb, _ in common:
            lines.append(f"  <code>#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}</code>")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
    except Exception as e:
        await update.message.reply_text(f"⚠️ {e}")


async def exif_cmd(update, context):
    r = update.message.reply_to_message
    if not r or not r.photo:
        await update.message.reply_text("📷 Reply to a photo."); return
    try:
        f = await r.photo[-1].get_file(); data = await f.download_as_bytearray()
        img = Image.open(io.BytesIO(data))
        exif = img.getexif()
        if not exif:
            await update.message.reply_text("📷 No EXIF."); return
        lines = ["📷 <b>EXIF</b>", ""]
        for k, v in list(exif.items())[:20]:
            lines.append(f"  {k}: {str(v)[:80]}")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
    except Exception as e:
        await update.message.reply_text(f"⚠️ {e}")


# ============================================================
#  MODULE E — SECURITY
# ============================================================
@owner_only
async def invite_cmd(update, context):
    code = uuid_lib.uuid4().hex[:8]
    INVITES[code] = {"created_by": OWNER_ID, "expires": (datetime.now() + timedelta(hours=24)).isoformat()}
    save_invites()
    await update.message.reply_text(f"🎫 <code>{code}</code>\n24ч. /redeem {code}", parse_mode=ParseMode.HTML)


async def redeem_cmd(update, context):
    uid = update.effective_user.id
    if not context.args:
        await update.message.reply_text("🎫 /redeem CODE"); return
    code = context.args[0]
    inv = INVITES.get(code)
    if not inv:
        await update.message.reply_text("❌ Invalid."); return
    if datetime.fromisoformat(inv["expires"]) < datetime.now():
        INVITES.pop(code, None); save_invites()
        await update.message.reply_text("❌ Expired."); return
    if uid not in state["WHITELIST"]:
        state["WHITELIST"].append(uid); save_state()
    INVITES.pop(code, None); save_invites()
    await update.message.reply_text("✅ Access granted.")


@owner_only
async def intruders_cmd(update, context):
    if not os.path.exists(INTRUDER_FILE):
        await update.message.reply_text("📭 No data."); return
    with open(INTRUDER_FILE, "r", encoding="utf-8") as f:
        try: data = json.load(f)
        except: data = []
    if not data:
        await update.message.reply_text("📭 Empty."); return
    lines = ["🚨 <b>Intruders</b>", ""]
    seen = set()
    for x in data[-30:]:
        u = x.get("user_id")
        if u in seen: continue
        seen.add(u)
        lines.append(f"  <code>{u}</code> @{x.get('username','—')} ({x.get('first_name','')})")
    await update.message.reply_text("\n".join(lines[:30]), parse_mode=ParseMode.HTML)


@owner_only
async def prune_cmd(update, context):
    if not context.args:
        await update.message.reply_text("🪓 /prune 30d"); return
    d = parse_duration(context.args[0])
    if not d or d == "perm":
        await update.message.reply_text("🪓 30d | 7d | 24h"); return
    thr = datetime.now() - d
    removed = 0
    for suid, s in list(USER_STATS.items()):
        last = s.get("last_seen")
        if last and datetime.fromisoformat(last) < thr:
            try: state["WHITELIST"].remove(int(suid)); removed += 1
            except: pass
    save_state()
    await update.message.reply_text(f"🪓 Removed: {removed}")


@owner_only
async def silent_cmd(update, context):
    global SILENT_MODE
    if not context.args:
        await update.message.reply_text(f"🤫 {'ON' if SILENT_MODE else 'OFF'}"); return
    SILENT_MODE = context.args[0].lower() == "on"
    await update.message.reply_text(t(OWNER_ID, "silent_on" if SILENT_MODE else "silent_off"))


@owner_only
async def announce_cmd(update, context):
    text = " ".join(context.args)
    if not text:
        await update.message.reply_text("📢 /announce text"); return
    sent = failed = 0
    for u in state["WHITELIST"]:
        try:
            await context.bot.send_message(u, f"📢 <b>Announcement</b>\n\n{text}", parse_mode=ParseMode.HTML)
            sent += 1
        except: failed += 1
    await update.message.reply_text(f"📢 {sent}/{failed}")


@owner_only
async def lockdown_cmd(update, context):
    global LOCKDOWN
    if not context.args:
        await update.message.reply_text(f"🔒 {'ON' if LOCKDOWN else 'OFF'}"); return
    LOCKDOWN = context.args[0].lower() == "on"
    state["LOCKDOWN"] = LOCKDOWN; save_state()
    await update.message.reply_text(t(OWNER_ID, "lockdown_on" if LOCKDOWN else "lockdown_off"))


# ============================================================
#  MODULE F — DEV
# ============================================================
async def diff_cmd(update, context):     await _text_ai(update, context, "Explain this git diff in plain language.")
async def commit_cmd(update, context):   await _text_ai(update, context, "Generate a Conventional Commit message for this diff.")


async def dockerfile_cmd(update, context):
    uid = update.effective_user.id
    topic = " ".join(context.args) or "python app"
    reply = await call_gemini(f"Optimized multi-stage Dockerfile for: {topic}. Return only Dockerfile.", uid)
    await update.message.reply_text(f"<pre>{reply[:3800]}</pre>", parse_mode=ParseMode.HTML)


async def gitignore_cmd(update, context):
    uid = update.effective_user.id
    lang = context.args[0] if context.args else "python"
    reply = await call_gemini(f"Standard .gitignore for {lang}. Return only contents.", uid)
    await update.message.reply_text(f"<pre>{reply[:3800]}</pre>", parse_mode=ParseMode.HTML)


async def json_cmd(update, context):
    r = update.message.reply_to_message
    text = r.text if r and r.text else " ".join(context.args)
    if not text:
        await update.message.reply_text("📋 Provide JSON."); return
    try:
        pretty = json.dumps(json.loads(text), indent=2, ensure_ascii=False)
        await update.message.reply_text(f"<pre>{pretty[:3800]}</pre>", parse_mode=ParseMode.HTML)
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")


async def b64_cmd(update, context):
    if len(context.args) < 2:
        await update.message.reply_text("🔡 /b64 encode text"); return
    mode, text = context.args[0].lower(), " ".join(context.args[1:])
    try:
        out = base64.b64encode(text.encode()).decode() if mode == "encode" else base64.b64decode(text.encode()).decode()
        await update.message.reply_text(f"<code>{out}</code>", parse_mode=ParseMode.HTML)
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")


async def hash_cmd(update, context):
    text = " ".join(context.args)
    r = update.message.reply_to_message
    if r and r.text: text = r.text
    if not text:
        await update.message.reply_text("🔒 /hash text"); return
    await update.message.reply_text(
        f"SHA256: <code>{hashlib.sha256(text.encode()).hexdigest()}</code>\n"
        f"MD5: <code>{hashlib.md5(text.encode()).hexdigest()}</code>",
        parse_mode=ParseMode.HTML)


async def cron_cmd(update, context):
    expr = " ".join(context.args)
    if not expr:
        await update.message.reply_text('⏰ /cron "0 0 * * *"'); return
    reply = await call_gemini(f"Explain cron expression: {expr}", update.effective_user.id)
    await update.message.reply_text(reply)


async def jwt_cmd(update, context):
    token = " ".join(context.args)
    if not token:
        await update.message.reply_text("🔑 /jwt <token>"); return
    try:
        parts = token.split(".")
        if len(parts) != 3:
            await update.message.reply_text("❌ Invalid JWT."); return
        def d(x):
            x += "=" * (-len(x) % 4)
            return base64.urlsafe_b64decode(x).decode()
        await update.message.reply_text(
            f"🔑 <b>Header</b>\n<pre>{d(parts[0])}</pre>\n\n<b>Payload</b>\n<pre>{d(parts[1])}</pre>",
            parse_mode=ParseMode.HTML)
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")


async def urlenc_cmd(update, context):
    if len(context.args) < 2:
        await update.message.reply_text("🔗 /urlenc encode text"); return
    mode, text = context.args[0].lower(), " ".join(context.args[1:])
    out = urllib.parse.quote(text) if mode == "encode" else urllib.parse.unquote(text)
    await update.message.reply_text(f"<code>{out}</code>", parse_mode=ParseMode.HTML)


# ============================================================
#  MODULE G — PERSONAL
# ============================================================
@owner_only
async def diary_cmd(update, context):
    ud = USERDATA.setdefault(str(OWNER_ID), {}); diary = ud.setdefault("diary", [])
    if not context.args or context.args[0].lower() == "list":
        if not diary:
            await update.message.reply_text("📔 /diary add text | list | clear"); return
        lines = ["📔 <b>Diary</b>", ""]
        for i, x in enumerate(diary[-20:], 1):
            lines.append(f"  {i}. [{x['at'][:16]}] {x['text'][:80]}")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML); return
    sub = context.args[0].lower()
    if sub == "add":
        text = " ".join(context.args[1:])
        if text: diary.append({"at": datetime.now().isoformat(), "text": text}); save_userdata()
        await update.message.reply_text("📔 Added.")
    elif sub == "clear":
        ud["diary"] = []; save_userdata(); await update.message.reply_text("🗑")


@owner_only
async def secret_cmd(update, context):
    sec = USERDATA.setdefault(str(OWNER_ID), {}).setdefault("secrets", {})
    if len(context.args) < 1:
        await update.message.reply_text("🔐 /secret set|get|list|del"); return
    sub = context.args[0].lower()
    if sub == "set" and len(context.args) >= 3:
        sec[context.args[1]] = base64.b64encode(" ".join(context.args[2:]).encode()).decode()
        save_userdata(); await update.message.reply_text("🔐 Saved.")
    elif sub == "get" and len(context.args) == 2:
        v = sec.get(context.args[1])
        if v: await update.message.reply_text(f"<code>{base64.b64decode(v.encode()).decode()}</code>", parse_mode=ParseMode.HTML)
        else: await update.message.reply_text("❌")
    elif sub == "list":
        await update.message.reply_text("🔐 " + ", ".join(sec.keys()) if sec else "📭")
    elif sub == "del" and len(context.args) == 2:
        sec.pop(context.args[1], None); save_userdata(); await update.message.reply_text("🗑")


@owner_only
async def task_cmd(update, context):
    tasks = USERDATA.setdefault(str(OWNER_ID), {}).setdefault("tasks", [])
    if not context.args or context.args[0].lower() == "list":
        if not tasks:
            await update.message.reply_text("✅ /task add text | list | done N | del N"); return
        lines = ["✅ <b>Tasks</b>", ""]
        for i, x in enumerate(tasks, 1):
            m = "✅" if x.get("done") else "⬜"
            lines.append(f"  {i}. {m} {x['text']}")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML); return
    sub = context.args[0].lower()
    if sub == "add":
        t_text = " ".join(context.args[1:])
        if t_text: tasks.append({"text": t_text, "done": False}); save_userdata()
        await update.message.reply_text("✅")
    elif sub == "done":
        try: tasks[int(context.args[1])-1]["done"] = True; save_userdata(); await update.message.reply_text("✅")
        except: pass
    elif sub == "del":
        try: tasks.pop(int(context.args[1])-1); save_userdata(); await update.message.reply_text("🗑")
        except: pass


@owner_only
async def habit_cmd(update, context):
    habits = USERDATA.setdefault(str(OWNER_ID), {}).setdefault("habits", {})
    if not context.args or context.args[0].lower() == "list":
        if not habits:
            await update.message.reply_text("🎯 /habit add read | log read | list"); return
        lines = ["🎯 <b>Habits</b>", ""]
        for name, d in habits.items():
            lines.append(f"  • {name}: 🔥 {d.get('streak',0)}")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML); return
    sub = context.args[0].lower()
    if sub == "add":
        name = " ".join(context.args[1:])
        if name: habits[name] = {"streak": 0, "last": ""}; save_userdata()
        await update.message.reply_text(f"🎯 {name}")
    elif sub == "log":
        name = " ".join(context.args[1:])
        if name in habits:
            today = datetime.now().date().isoformat()
            if habits[name]["last"] == today:
                await update.message.reply_text("⚠️ Already today."); return
            habits[name]["streak"] = habits[name].get("streak", 0) + 1
            habits[name]["last"] = today; save_userdata()
            await update.message.reply_text(f"🎯 {name}: 🔥 {habits[name]['streak']}")


@owner_only
async def money_cmd(update, context):
    money = USERDATA.setdefault(str(OWNER_ID), {}).setdefault("money", [])
    if not context.args or context.args[0].lower() == "list":
        bal = sum(x["amount"] for x in money)
        lines = [f"💰 Balance: <b>{bal}</b>", ""]
        for x in money[-10:]:
            lines.append(f"  [{x['at'][:10]}] {x['amount']:+} — {x['note']}")
        await update.message.reply_text("\n".join(lines) if lines else "💰 Empty.", parse_mode=ParseMode.HTML); return
    if context.args[0].lower() == "add" and len(context.args) >= 2:
        try:
            money.append({"amount": float(context.args[1]), "note": " ".join(context.args[2:]), "at": datetime.now().isoformat()})
            save_userdata(); await update.message.reply_text(f"💰 {context.args[1]}")
        except: await update.message.reply_text("💰 /money add 1000 note")


# ============================================================
#  MODULE H — ANALYTICS
# ============================================================
@owner_only
async def monitor_cmd(update, context):
    if not context.args or context.args[0].lower() == "list":
        if not MONITORS:
            await update.message.reply_text("📡 /monitor add URL | list | del N"); return
        lines = ["📡 <b>Monitors</b>", ""]
        for i, m in enumerate(MONITORS, 1):
            lines.append(f"  {i}. {m['url']} (last: {m.get('last_status','—')})")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML); return
    sub = context.args[0].lower()
    if sub == "add":
        url = context.args[1] if len(context.args) > 1 else ""
        if not url.startswith("http"): url = "https://" + url
        MONITORS.append({"uid": OWNER_ID, "chat_id": update.effective_chat.id, "url": url, "last_status": None})
        save_monitors(); await update.message.reply_text(f"📡 {url}")
    elif sub == "del":
        try: MONITORS.pop(int(context.args[1])-1); save_monitors(); await update.message.reply_text("🗑")
        except: pass


async def rss_cmd(update, context):
    uid = update.effective_user.id
    if not context.args or context.args[0].lower() == "list":
        if not RSS_FEEDS:
            await update.message.reply_text("📰 /rss add URL | list | del N"); return
        lines = ["📰 <b>RSS</b>", ""]
        for i, f in enumerate(RSS_FEEDS, 1):
            lines.append(f"  {i}. {f['url']}")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML); return
    sub = context.args[0].lower()
    if sub == "add":
        url = context.args[1] if len(context.args) > 1 else ""
        if not url.startswith("http"): url = "https://" + url
        RSS_FEEDS.append({"uid": uid, "chat_id": update.effective_chat.id, "url": url, "last_hash": ""})
        save_rss(); await update.message.reply_text(f"📰 {url}")
    elif sub == "del":
        try: RSS_FEEDS.pop(int(context.args[1])-1); save_rss(); await update.message.reply_text("🗑")
        except: pass


# ============================================================
#  MODULE I — FUN
# ============================================================
async def gif_cmd(update, context):
    q = " ".join(context.args) or "cat"
    try:
        r = requests.get(f"https://g.tenor.com/v1/search?q={urllib.parse.quote(q)}&key=LIVDSRZULELA&limit=1", timeout=15)
        data = r.json()
        if data.get("results"):
            gif_url = data["results"][0]["media"][0]["gif"]["url"]
            await update.message.reply_animation(animation=gif_url)
        else:
            await update.message.reply_text("❌ Not found.")
    except Exception as e:
        await update.message.reply_text(f"⚠️ {e}")


async def meme_cmd(update, context):
    try:
        r = requests.get("https://meme-api.com/gimme", timeout=15)
        data = r.json()
        await update.message.reply_photo(photo=data["url"], caption=data.get("title", ""))
    except Exception as e:
        await update.message.reply_text(f"⚠️ {e}")


async def horoscope_cmd(update, context):
    uid = update.effective_user.id
    sign = context.args[0] if context.args else "aries"
    reply = await call_gemini(f"Short daily horoscope for {sign} (3-4 sentences).", uid)
    await update.message.reply_text(f"🔮 <b>{sign.title()}</b>\n\n{reply}", parse_mode=ParseMode.HTML)


async def recipe_cmd(update, context):
    uid = update.effective_user.id
    q = " ".join(context.args)
    if not q:
        await update.message.reply_text("🍳 /recipe pasta"); return
    reply = await call_gemini(f"Recipe for {q}: ingredients + steps.", uid)
    await update.message.reply_text(reply)


# ============================================================
#  PHASE 3 — ADMIN
# ============================================================
async def _do_ban(context, uid, reason, actor):
    if uid not in state["BANNED"]: state["BANNED"].append(uid)
    if uid in state["WHITELIST"]: state["WHITELIST"].remove(uid)
    save_state()
    log_mod_action(actor, uid, "BAN", reason)
    try:
        await context.bot.send_message(OWNER_ID, t(OWNER_ID, "ban_alert", uid=uid, reason=reason), parse_mode=ParseMode.HTML)
    except: pass


@owner_only
async def admin_panel(update, context):
    uid = update.effective_user.id
    lang = LANG.get(str(uid), "en")
    kb = [
        [KeyboardButton("👥 Белый список" if lang == "ru" else "👥 Whitelist"),
         KeyboardButton("🚫 Баны" if lang == "ru" else "🚫 Bans")],
        [KeyboardButton("📊 Логи" if lang == "ru" else "📊 Logs"),
         KeyboardButton("📢 Рассылка" if lang == "ru" else "📢 Broadcast")],
        [KeyboardButton("💾 Бэкап" if lang == "ru" else "💾 Backup"),
         KeyboardButton("ℹ️ Статус" if lang == "ru" else "ℹ️ Status")],
    ]
    await update.message.reply_text(t(uid, "admin_panel"),
        reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True), parse_mode=ParseMode.HTML)


@owner_only
async def admin_buttons(update, context):
    txt = update.message.text
    if   txt in ("👥 Whitelist", "👥 Белый список"): await whitelist_list(update, context)
    elif txt in ("🚫 Bans", "🚫 Баны"):               await _show_bans(update, context)
    elif txt in ("📊 Logs", "📊 Логи"):               await logs_cmd(update, context)
    elif txt in ("📢 Broadcast", "📢 Рассылка"):      await update.message.reply_text(t(update.effective_user.id, "use_broadcast"))
    elif txt in ("💾 Backup", "💾 Бэкап"):            await backup_cmd(update, context)
    elif txt in ("ℹ️ Status", "ℹ️ Статус"):          await health_cmd(update, context)


async def _show_bans(update, context):
    uid = update.effective_user.id
    if not state["BANNED"]:
        await update.message.reply_text(t(uid, "banned_empty")); return
    lines = [t(uid, "banned_header"), ""]
    for b in state["BANNED"]:
        lines.append(f"  • <code>{b}</code>")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


@owner_only
async def add_whitelist(update, context):
    if not context.args:
        await update.message.reply_text("👥 /add <id> [duration|perm]"); return
    try: uid = int(context.args[0])
    except: return
    if uid not in state["WHITELIST"]: state["WHITELIST"].append(uid)
    if len(context.args) >= 2:
        d = parse_duration(context.args[1])
        if d and d != "perm":
            state["WHITELIST_EXPIRY"][str(uid)] = (datetime.now() + d).isoformat()
    save_state()
    await update.message.reply_text(t(OWNER_ID, "user_added", uid=uid), parse_mode=ParseMode.HTML)


@owner_only
async def remove_whitelist(update, context):
    if not context.args: return
    try: uid = int(context.args[0])
    except: return
    if uid in state["WHITELIST"]: state["WHITELIST"].remove(uid)
    state["WHITELIST_EXPIRY"].pop(str(uid), None); save_state()
    await update.message.reply_text(t(OWNER_ID, "access_revoked", uid=uid), parse_mode=ParseMode.HTML)


@owner_only
async def whitelist_list(update, context):
    uid = update.effective_user.id
    if not state["WHITELIST"]:
        await update.message.reply_text(t(uid, "wl_empty")); return
    lines = [t(uid, "wl_header"), ""]
    for w in state["WHITELIST"]:
        exp = state["WHITELIST_EXPIRY"].get(str(w), "∞")
        lines.append(f"  • <code>{w}</code>  ·  {exp}")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def ban_user(update, context):
    if update.effective_chat.type == "private" and update.effective_user.id != OWNER_ID: return
    if not await check_group_permissions(update, context): return
    if not context.args: return
    try: uid = int(context.args[0])
    except: return
    rest = context.args[1:]; duration = None
    if rest:
        d = parse_duration(rest[0])
        if d: duration, rest = d, rest[1:]
    reason = " ".join(rest) or "no reason"
    await _do_ban(context, uid, reason, update.effective_user.id)
    if duration and duration != "perm":
        state["BANNED_TIMED"][str(uid)] = (datetime.now() + duration).isoformat()
    else: state["BANNED_TIMED"].pop(str(uid), None)
    save_state()
    ts = "forever" if not duration or duration == "perm" else f"for {duration}"
    await update.message.reply_text(t(OWNER_ID, "user_banned", uid=uid, ts=ts, reason=reason), parse_mode=ParseMode.HTML)


async def unban_user(update, context):
    if update.effective_chat.type == "private" and update.effective_user.id != OWNER_ID: return
    if not await check_group_permissions(update, context): return
    if not context.args: return
    try: uid = int(context.args[0])
    except: return
    if uid in state["BANNED"]: state["BANNED"].remove(uid)
    state["BANNED_TIMED"].pop(str(uid), None); save_state()
    await update.message.reply_text(t(OWNER_ID, "user_unbanned", uid=uid), parse_mode=ParseMode.HTML)


async def mute_user(update, context):
    if update.effective_chat.type == "private" and update.effective_user.id != OWNER_ID: return
    if not await check_group_permissions(update, context): return
    if len(context.args) < 2: return
    try: uid = int(context.args[0])
    except: return
    d = parse_duration(context.args[1])
    if not d: return
    exp = datetime.now() + (timedelta(days=36500) if d == "perm" else d)
    state["MUTED"][str(uid)] = exp.isoformat(); save_state()
    await update.message.reply_text(t(OWNER_ID, "user_muted", uid=uid, until=exp.strftime("%Y-%m-%d %H:%M")), parse_mode=ParseMode.HTML)


async def warn_user(update, context):
    if update.effective_chat.type == "private" and update.effective_user.id != OWNER_ID: return
    if not await check_group_permissions(update, context): return
    if len(context.args) < 2: return
    try: uid = int(context.args[0])
    except: return
    reason = " ".join(context.args[1:])
    wl = state["WARNINGS"].setdefault(str(uid), [])
    wl.append({"reason": reason, "by": update.effective_user.id, "at": datetime.now().isoformat()})
    save_state()
    await update.message.reply_text(t(OWNER_ID, "user_warned", uid=uid, count=len(wl), reason=reason), parse_mode=ParseMode.HTML)
    if len(wl) >= 3:
        await _do_ban(context, uid, "auto-ban", update.effective_user.id)
        await update.message.reply_text(t(OWNER_ID, "auto_banned", uid=uid), parse_mode=ParseMode.HTML)


async def warnings_list(update, context):
    if not context.args: return
    uid = str(context.args[0])
    warns = state["WARNINGS"].get(uid, [])
    if not warns:
        await update.message.reply_text(t(OWNER_ID, "no_warnings")); return
    lines = [t(OWNER_ID, "warns_header", uid=uid), ""]
    for i, w in enumerate(warns, 1):
        lines.append(f"  {i}. {w['at'][:16]} │ {w['reason']}")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


@owner_only
async def broadcast_msg(update, context):
    text = " ".join(context.args)
    if not text: return
    sent = failed = 0
    for u in state["WHITELIST"]:
        try:
            await context.bot.send_message(u, f"📢 <b>Broadcast</b>\n\n{text}", parse_mode=ParseMode.HTML); sent += 1
        except: failed += 1
    await update.message.reply_text(t(OWNER_ID, "broadcast_done", sent=sent, failed=failed), parse_mode=ParseMode.HTML)


@owner_only
async def send_direct(update, context):
    if len(context.args) < 2: return
    try: uid = int(context.args[0])
    except: return
    text = " ".join(context.args[1:])
    try:
        await context.bot.send_message(uid, text)
        await update.message.reply_text(t(OWNER_ID, "msg_delivered"))
    except Exception as e:
        await update.message.reply_text(f"⚠️ {e}")


@owner_only
async def backup_cmd(update, context):
    zip_name = "jarvis_backup.zip"
    with zipfile.ZipFile(zip_name, "w") as z:
        for f in ("main.py", "requirements.txt", "whitelist.json", "config.json", "tickets.json", "usage_stats.json"):
            if os.path.exists(f): z.write(f)
    await update.message.reply_document(document=open(zip_name, "rb"), filename=zip_name)
    os.remove(zip_name)


@owner_only
async def logs_cmd(update, context):
    if not os.path.exists("bot.log"): return
    with open("bot.log", "r", encoding="utf-8") as f:
        tail = "".join(f.readlines()[-35:])[-4000:]
    await update.message.reply_text(f"{t(OWNER_ID, 'logs_header')}\n\n<pre>{tail}</pre>", parse_mode=ParseMode.HTML)


@owner_only
async def export_logs_cmd(update, context):
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
            await update.message.reply_text(t(uid, "no_reply")); return
        text = r.text or r.caption
    else:
        text = " ".join(context.args)
    if not text and not need_reply:
        await update.message.reply_text("✏️ Provide arguments."); return
    status = await update.message.reply_text(t(uid, "processing"), parse_mode=ParseMode.HTML)
    try:
        reply = await call_gemini(f"{instruction}\n\nINPUT:\n{text}", uid)
        try: await status.edit_text(reply[:4000], parse_mode=ParseMode.MARKDOWN)
        except: await status.edit_text(reply[:4000])
        for i in range(4000, len(reply), 4000):
            await update.message.reply_text(reply[i:i+4000])
    except Exception as e:
        logger.exception(f"AI: {e}"); await status.edit_text(t(uid, "req_error"))


async def review_cmd(update, context):    await _ai(update, context, "Review this code: bugs, security, style. Suggest fixes.", need_reply=True)
async def regex_cmd(update, context):     await _ai(update, context, "Generate regex for the described task. Return only pattern + test example.")
async def sql_cmd(update, context):       await _ai(update, context, "Write SQL for the task. Add one-line explanation.")
async def explain_cmd(update, context):   await _ai(update, context, "Explain this code line by line.", need_reply=True)
async def refactor_cmd(update, context):  await _ai(update, context, "Refactor this code. Return optimized version + change list.", need_reply=True)
async def uml_cmd(update, context):       await _ai(update, context, "Return a PlantUML diagram for the described code.")
async def pytest_cmd(update, context):    await _ai(update, context, "Generate pytest file for this code. Return only Python.", need_reply=True)
async def doc_cmd(update, context):       await _ai(update, context, "Add PEP-8 docstrings and comments. Preserve logic.", need_reply=True)
async def cv_cmd(update, context):        await _ai(update, context, "Structure raw bio into Markdown CV: Summary, Experience, Skills, Education.")


async def translate_long_cmd(update, context):
    if len(context.args) < 2:
        await update.message.reply_text("🌐 /translate_long <lang> <text>"); return
    lang, text = context.args[0], " ".join(context.args[1:])
    await _ai(update, context, f"Translate to {lang}. Preserve formatting.\n---\n{text}")


async def ask_cmd(update, context):
    uid = update.effective_user.id
    r = update.message.reply_to_message
    if not r or not r.text:
        await update.message.reply_text(t(uid, "no_reply")); return
    q = " ".join(context.args)
    doc = r.text[:30000]
    status = await update.message.reply_text(t(uid, "processing"), parse_mode=ParseMode.HTML)
    try:
        reply = await call_gemini(f"Answer based ONLY on this document.\n\n{doc}\n\nQ: {q}", uid)
        await status.edit_text(reply[:4000])
    except Exception as e:
        logger.exception(f"Ask: {e}"); await status.edit_text(t(uid, "req_error"))


# ============================================================
#  PHASE 5 — SPECIAL
# ============================================================
@owner_only
async def export_whitelist_cmd(update, context):
    _atomic_write_json("whitelist_export.json", {
        "whitelist": state["WHITELIST"], "expiry": state["WHITELIST_EXPIRY"],
        "exported_at": datetime.now().isoformat(),
    })
    await update.message.reply_document(document=open("whitelist_export.json", "rb"))
    os.remove("whitelist_export.json")


@owner_only
async def clear_session_cmd(update, context):
    USER_HISTORY.clear(); USER_MODES.clear(); USER_VIBES.clear()
    INCOGNITO_USERS.clear(); LAST_REQUEST.clear()
    await update.message.reply_text(t(OWNER_ID, "session_purged"))


async def report_cmd(update, context):
    uid = update.effective_user.id
    text = " ".join(context.args)
    if not text:
        await update.message.reply_text("📩 /report <issue>"); return
    ticket = {"id": len(TICKETS) + 1, "user_id": uid, "username": update.effective_user.username,
              "text": text, "status": "open", "at": datetime.now().isoformat()}
    TICKETS.append(ticket); save_tickets()
    await update.message.reply_text(t(uid, "report_created", tid=ticket["id"]), parse_mode=ParseMode.HTML)
    try:
        await context.bot.send_message(OWNER_ID, f"📩 Ticket #{ticket['id']} from <code>{uid}</code>: {text}", parse_mode=ParseMode.HTML)
    except: pass


@owner_only
async def tickets_cmd(update, context):
    opens = [x for x in TICKETS if x.get("status") == "open"]
    if not opens:
        await update.message.reply_text(t(OWNER_ID, "tickets_empty")); return
    lines = [t(OWNER_ID, "tickets_header"), ""]
    for x in opens[:20]:
        lines.append(f"  #{x['id']}  │  <code>{x['user_id']}</code>  │  {x['text'][:60]}")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


@owner_only
async def close_ticket_cmd(update, context):
    if not context.args: return
    try: tid = int(context.args[0])
    except: return
    for x in TICKETS:
        if x["id"] == tid:
            x["status"] = "closed"; save_tickets()
            await update.message.reply_text(t(OWNER_ID, "ticket_closed", tid=tid)); return
    await update.message.reply_text(t(OWNER_ID, "ticket_not_found"))


@owner_only
async def stats_cmd(update, context):
    top = sorted(USER_STATS.items(), key=lambda kv: kv[1].get("messages", 0), reverse=True)[:10]
    if not top:
        await update.message.reply_text(t(OWNER_ID, "stats_empty")); return
    lines = [t(OWNER_ID, "stats_header"), ""]
    for uid, s in top:
        lines.append(f"  <code>{uid}</code>  ·  {s.get('messages',0)} msgs  ·  {s.get('commands',0)} cmds")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


@owner_only
async def health_cmd(update, context):
    try:
        cpu = psutil.cpu_percent(interval=0.5); ram = psutil.virtual_memory().percent
        dsk = psutil.disk_usage("/").percent
        up = int(time.time() - STARTED_AT)
        h, m, s = up // 3600, (up % 3600) // 60, up % 60
        await update.message.reply_text(
            f"{t(OWNER_ID, 'health_header')}\n\n  CPU │ {cpu}%\n  RAM │ {ram}%\n  Disk │ {dsk}%\n  Uptime │ {h}h {m}m {s}s",
            parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.exception(f"Health: {e}"); await update.message.reply_text(t(OWNER_ID, "health_fail"))


@owner_only
async def stopwords_cmd(update, context):
    if not context.args:
        await update.message.reply_text(t(OWNER_ID, "stopwords_list", words=", ".join(STOP_WORDS))); return
    action = context.args[0].lower()
    if action == "add" and len(context.args) > 1:
        STOP_WORDS.append(" ".join(context.args[1:])); await update.message.reply_text(t(OWNER_ID, "stopword_added"))
    elif action == "remove" and len(context.args) > 1:
        w = " ".join(context.args[1:])
        if w in STOP_WORDS: STOP_WORDS.remove(w)
        await update.message.reply_text(t(OWNER_ID, "stopword_removed"))


# ============================================================
#  BACKGROUND JOBS + MIDDLEWARE
# ============================================================
async def cleanup_expired_job(context):
    now = datetime.now(); changed = False
    for u in [k for k, v in list(state["WHITELIST_EXPIRY"].items()) if now > datetime.fromisoformat(v)]:
        try: state["WHITELIST"].remove(int(u))
        except: pass
        state["WHITELIST_EXPIRY"].pop(u, None); changed = True
    for u in [k for k, v in list(state.get("BANNED_TIMED", {}).items()) if now > datetime.fromisoformat(v)]:
        try: state["BANNED"].remove(int(u))
        except: pass
        state["BANNED_TIMED"].pop(u, None); changed = True
    for u in [k for k, v in list(state["MUTED"].items()) if now > datetime.fromisoformat(v)]:
        state["MUTED"].pop(u, None); changed = True
    if changed: save_state()


async def monitor_check_job(context):
    for m in MONITORS:
        try:
            r = requests.get(m["url"], timeout=15)
            new_status = r.status_code
            if m.get("last_status") and m["last_status"] != new_status:
                try:
                    await context.bot.send_message(m["chat_id"], f"📡 <b>{m['url']}</b>\nStatus: {m['last_status']} → {new_status}", parse_mode=ParseMode.HTML)
                except: pass
            m["last_status"] = new_status
        except Exception:
            m["last_status"] = "down"
    if MONITORS: save_monitors()


async def auto_backup_job(context):
    try:
        name = f"auto_backup_{datetime.now():%Y%m%d_%H%M}.zip"
        with zipfile.ZipFile(name, "w") as z:
            for f in ("main.py", "requirements.txt", "whitelist.json", "config.json"):
                if os.path.exists(f): z.write(f)
        await context.bot.send_document(OWNER_ID, document=open(name, "rb"), filename=name)
        os.remove(name)
    except Exception as e:
        logger.exception(f"Backup: {e}")


async def global_security_middleware(update, context):
    if not update.effective_user or not update.message: return
    uid = update.effective_user.id
    suid = str(uid)
    now = datetime.now()

    # LOCKDOWN
    if LOCKDOWN and uid != OWNER_ID:
        raise ApplicationHandlerStop

    # SILENT_MODE — only owner
    if SILENT_MODE and uid != OWNER_ID:
        raise ApplicationHandlerStop

    if suid in state["MUTED"]:
        if now > datetime.fromisoformat(state["MUTED"][suid]):
            state["MUTED"].pop(suid, None); save_state()
        else:
            raise ApplicationHandlerStop

    if uid in state["BANNED"]:
        raise ApplicationHandlerStop

    now_ts = time.time()
    bucket = [x for x in FLOOD_WINDOW.get(uid, []) if now_ts - x < 60]
    bucket.append(now_ts)
    FLOOD_WINDOW[uid] = bucket
    if len(bucket) > 15 and uid != OWNER_ID:
        try: await context.bot.send_message(OWNER_ID, t(OWNER_ID, "flood_detected", uid=uid), parse_mode=ParseMode.HTML)
        except: pass
        state["MUTED"][suid] = (datetime.now() + timedelta(minutes=5)).isoformat()
        save_state(); raise ApplicationHandlerStop

    if uid != OWNER_ID and uid not in state["WHITELIST"]:
        entry = {
            "first_name": update.effective_user.first_name,
            "last_name": update.effective_user.last_name,
            "user_id": uid, "username": update.effective_user.username,
            "chat_id": update.effective_chat.id, "timestamp": now.isoformat(),
            "text_preview": (update.message.text or "[Media]")[:100],
        }
        logs = []
        if os.path.exists(INTRUDER_FILE):
            try:
                with open(INTRUDER_FILE, "r", encoding="utf-8") as f: logs = json.load(f)
            except: pass
        logs.append(entry)
        _atomic_write_json(INTRUDER_FILE, logs)
        alert = (
            f"{t(OWNER_ID, 'unauthorized')}\n\n"
            f"  ID    │ <code>{uid}</code>\n"
            f"  User  │ @{entry['username']} ({entry['first_name']})\n"
            f"  Chat  │ <code>{entry['chat_id']}</code>\n"
            f"  Query │ {entry['text_preview']}"
        )
        try: await context.bot.send_message(OWNER_ID, alert, parse_mode=ParseMode.HTML)
        except: pass
        raise ApplicationHandlerStop


# ============================================================
#  FLASK + MAIN
# ============================================================
async def post_init(application: Application):
    await application.bot.delete_webhook(drop_pending_updates=True)
    logger.info("Webhooks cleared. J.A.R.V.I.S. Online. Boss: Silent / Tony Stark.")


def run_flask():
    flask_app = Flask(__name__)
    @flask_app.route("/")
    @flask_app.route("/health")
    def health(): return "J.A.R.V.I.S. is alive", 200
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(TypeHandler(Update, global_security_middleware), group=-1)
    app.job_queue.run_repeating(cleanup_expired_job, interval=60)
    app.job_queue.run_repeating(monitor_check_job, interval=300, first=30)
    app.job_queue.run_repeating(auto_backup_job, interval=7*24*3600, first=10)

    app.add_handler(CallbackQueryHandler(on_lang_callback, pattern=r"^lang_(ru|en)$"))

    for cmd, fn in [
        ("start", start), ("help", help_cmd), ("reset", reset_cmd),
        ("mode", mode_cmd), ("vibe", vibe_cmd), ("id", id_cmd),
        ("lang", lang_cmd),
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
    app.add_handler(MessageHandler(filters.VIDEO | filters.VIDEO_NOTE, video_handler))
    app.add_handler(MessageHandler(filters.ANIMATION,    animation_handler))
    app.add_handler(MessageHandler(filters.Document.ALL, document_handler))

    # Module B
    for cmd, fn in [
        ("calc", calc_cmd), ("currency", currency_cmd), ("weather", weather_cmd),
        ("time", time_cmd), ("timer", timer_cmd), ("remind", remind_cmd),
        ("todo", todo_cmd), ("password", password_cmd), ("uuid", uuid_cmd),
        ("convert", convert_cmd), ("bmi", bmi_cmd),
    ]:
        app.add_handler(CommandHandler(cmd, fn))

    # Module C
    for cmd, fn in [
        ("improve", improve_cmd), ("fix", fix_cmd), ("shorten", shorten_cmd),
        ("expand", expand_cmd), ("style", style_cmd), ("keywords", keywords_cmd),
        ("theses", theses_cmd), ("tone", tone_cmd),
    ]:
        app.add_handler(CommandHandler(cmd, fn))

    # Module D
    for cmd, fn in [
        ("upscale", upscale_cmd), ("compress", compress_cmd), ("sticker", sticker_cmd),
        ("ocr", ocr_cmd), ("colors", colors_cmd), ("exif", exif_cmd),
    ]:
        app.add_handler(CommandHandler(cmd, fn))

    # Module E
    for cmd, fn in [
        ("invite", invite_cmd), ("redeem", redeem_cmd), ("intruders", intruders_cmd),
        ("prune", prune_cmd), ("silent", silent_cmd), ("announce", announce_cmd),
        ("lockdown", lockdown_cmd),
    ]:
        app.add_handler(CommandHandler(cmd, fn))

    # Module F
    for cmd, fn in [
        ("diff", diff_cmd), ("commit", commit_cmd), ("dockerfile", dockerfile_cmd),
        ("gitignore", gitignore_cmd), ("json", json_cmd), ("b64", b64_cmd),
        ("hash", hash_cmd), ("cron", cron_cmd), ("jwt", jwt_cmd), ("urlenc", urlenc_cmd),
    ]:
        app.add_handler(CommandHandler(cmd, fn))

    # Module G
    for cmd, fn in [
        ("diary", diary_cmd), ("secret", secret_cmd), ("task", task_cmd),
        ("habit", habit_cmd), ("money", money_cmd),
    ]:
        app.add_handler(CommandHandler(cmd, fn))

    # Module H
    for cmd, fn in [("monitor", monitor_cmd), ("rss", rss_cmd)]:
        app.add_handler(CommandHandler(cmd, fn))

    # Module I
    for cmd, fn in [("gif", gif_cmd), ("meme", meme_cmd), ("horoscope", horoscope_cmd), ("recipe", recipe_cmd)]:
        app.add_handler(CommandHandler(cmd, fn))

    # Phase 3
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
        admin_buttons))

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
    main()