"""
J.A.R.V.I.S. — CORE SYSTEM (FULL FIXED)
Cloudflare | Currents | DuckDuckGo | Reddit | Wikipedia | Upstash | Natural Router
All essential commands | ru+en | Boss: Silent / Tony Stark
"""

import os
import io
import asyncio
import re
import json
import time
import base64
import random
import hashlib
import zipfile
import logging
import threading
from functools import wraps
from html import escape as html_escape
import urllib.parse
import uuid as uuid_lib
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

try:
    from upstash_redis import Redis as UpstashRedis
    _UPSTASH_OK = True
except Exception:
    UpstashRedis = None
    _UPSTASH_OK = False


# ============================================================
#  CONFIG
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

BOT_TOKEN      = os.environ.get("BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL   = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash").strip()
GEMINI_FALLBACK_MODELS = [
    model.strip() for model in os.environ.get(
        "GEMINI_FALLBACK_MODELS", "gemini-3.7-flash,gemini-2.5-flash"
    ).split(",") if model.strip()
]
try:
    GEMINI_TIMEOUT_SECONDS = max(10, min(120, int(os.environ.get("GEMINI_TIMEOUT_SECONDS", "60"))))
except (TypeError, ValueError):
    GEMINI_TIMEOUT_SECONDS = 60
ENV_OWNER_ID   = int(os.environ.get("OWNER_ID", "0"))

CF_ACCOUNT_ID = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
CF_API_TOKEN  = os.environ.get("CLOUDFLARE_API_TOKEN")
CF_MODEL      = "@cf/black-forest-labs/flux-1-schnell"

CURRENTS_KEY = os.environ.get("CURRENTS_API_KEY")

UPSTASH_URL   = os.environ.get("UPSTASH_REDIS_REST_URL")
UPSTASH_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN")

if not BOT_TOKEN:      raise RuntimeError("BOT_TOKEN required.")
if not GEMINI_API_KEY: raise RuntimeError("GEMINI_API_KEY required.")
if not ENV_OWNER_ID:   raise RuntimeError("OWNER_ID required.")

OWNER_ID   = ENV_OWNER_ID
STARTED_AT = time.time()

OWNER_NAMES = ["silent", "site silent", "сайлент", "silent_uwa", "@silent_uwa",
               "тони старк", "tony stark", "старк", "stark"]

if not os.path.exists(CONFIG_FILE):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump({"OWNER_ID": OWNER_ID, "MODEL": GEMINI_MODEL}, f, indent=4)

try:
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)
    if not isinstance(config, dict):
        config = {}
except (OSError, json.JSONDecodeError) as exc:
    logger.warning("Could not read %s; using defaults: %s", CONFIG_FILE, exc)
    config = {}


# ============================================================
#  UPSTASH
# ============================================================
redis_client = None
if _UPSTASH_OK and UPSTASH_URL and UPSTASH_TOKEN:
    try:
        redis_client = UpstashRedis(url=UPSTASH_URL, token=UPSTASH_TOKEN)
        redis_client.ping()
        logger.info("Upstash connected.")
    except Exception as e:
        logger.error(f"Upstash: {e}")
        redis_client = None


# ============================================================
#  STATE
# ============================================================
USER_HISTORY    = {}
USER_MODES      = {}
USER_VIBES      = {}
INCOGNITO       = set()
LAST_REQUEST    = {}
FLOOD_WINDOW    = {}
USER_STATS      = {}
TICKETS         = []
STOP_WORDS      = ["spam", "scam"]

USERDATA        = {}
SILENT_MODE     = False
LOCKDOWN        = False

state = {
    "WHITELIST": [OWNER_ID],
    "BANNED":    [],
    "MUTED":     {},
    "WARNINGS":  {},
    "LANG":      {},
}

for path in [DATA_FILE, STATS_FILE, TICKETS_FILE, USERDATA_FILE]:
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
        except Exception as e:
            logger.error(f"Load {path}: {e}")

LANG = state.get("LANG", {})


# ============================================================
#  LOCALIZATION
# ============================================================
TEXTS = {
    "ru": {
        "welcome_owner": "🎩 <b>J.A.R.V.I.S.</b> к вашим услугам, сэр Silent.\n\nСистемы в норме. /help.",
        "welcome_other": "🎩 <b>J.A.R.V.I.S. Online.</b>\n\nГотов, сэр. /help.",
        "lang_set":      "🌐 Язык: <b>Русский</b> 🇷🇺",
        "lang_current":  "🌐 Язык: <b>{cur}</b>\n\n/lang ru | /lang en",
        "lang_switched": "🌐 Язык: <b>{lang}</b>",
        "processing":    "🧠 <i>Обработка…</i>",
        "slow_down":     "⏳ Помедленнее, сэр.",
        "gemini_down":   "⚠️ ИИ временно недоступен. Владелец может проверить подключение командой /diagnostics.",
        "req_error":     "⚠️ Ошибка.",
        "memory_cleared":"🧹 Память очищена.",
        "incog_on":      "🕶 Инкогнито ВКЛ.",
        "incog_off":     "🕶 Инкогнито ВЫКЛ.",
        "owner_only":    "🎩 Только Создателю, сэр.",
        "unauthorized":  "🚨 <b>НЕСАНКЦИОНИРОВАННЫЙ ДОСТУП</b>",
        "flood":         "🌊 Флуд: <code>{uid}</code>. Мут 5м.",
        "img_fail":      "⚠️ Сбой.",
        "audio_fail":    "⚠️ Ошибка аудио.",
        "video_fail":    "⚠️ Ошибка видео.",
        "doc_fail":      "⚠️ Ошибка документа.",
        "no_text":       "⚠️ Нет текста.",
        "no_voice":      "↩️ Ответьте на голосовое.",
        "no_reply":      "↩️ Ответьте на сообщение.",
        "draw_processing":"🎨 <i>Рисую…</i>",
        "transcription": "🎙 <b>Транскрипция</b>",
        "your_id":       "🆔 <code>{uid}</code>\nИмя: {name}",
        "sticker_animated":"🎭 Анимированный стикер, сэр. Опишите словами.",
        "zip_received":  "📦 Архив, сэр. Не открываю ZIP. Распакуйте и пришлите файлы.",
        "video_received":"🎬 Видео получено, сэр. Анализирую…",
        "audio_received":"🎙 Аудио получено, сэр. Обрабатываю…",
    },
    "en": {
        "welcome_owner": "🎩 <b>J.A.R.V.I.S.</b> at your service, Sir Silent.\n\nSystems nominal. /help.",
        "welcome_other": "🎩 <b>J.A.R.V.I.S. Online.</b>\n\nReady, Sir. /help.",
        "lang_set":      "🌐 Language: <b>English</b> 🇬🇧",
        "lang_current":  "🌐 Current: <b>{cur}</b>\n\n/lang ru | /lang en",
        "lang_switched": "🌐 Language: <b>{lang}</b>",
        "processing":    "🧠 <i>Processing…</i>",
        "slow_down":     "⏳ Slow down, Sir.",
        "gemini_down":   "⚠️ AI is temporarily unavailable. The owner can check the connection with /diagnostics.",
        "req_error":     "⚠️ Error.",
        "memory_cleared":"🧹 Memory cleared.",
        "incog_on":      "🕶 Incognito ON.",
        "incog_off":     "🕶 Incognito OFF.",
        "owner_only":    "🎩 Owner only, Sir.",
        "unauthorized":  "🚨 <b>UNAUTHORIZED ACCESS</b>",
        "flood":         "🌊 Flood: <code>{uid}</code>. Mute 5m.",
        "img_fail":      "⚠️ Failure.",
        "audio_fail":    "⚠️ Audio error.",
        "video_fail":    "⚠️ Video error.",
        "doc_fail":      "⚠️ Document error.",
        "no_text":       "⚠️ No text.",
        "no_voice":      "↩️ Reply to a voice message.",
        "no_reply":      "↩️ Reply to a message.",
        "draw_processing":"🎨 <i>Drawing…</i>",
        "transcription": "🎙 <b>Transcription</b>",
        "your_id":       "🆔 <code>{uid}</code>\nName: {name}",
        "sticker_animated":"🎭 Animated sticker, Sir. Describe in words.",
        "zip_received":  "📦 Archive, Sir. I don't open ZIP. Unpack and send files.",
        "video_received":"🎬 Video received, Sir. Analysing…",
        "audio_received":"🎙 Audio received, Sir. Processing…",
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
ID_TRIGGERS     = ["кто ты", "ты кто", "ты джарвис", "who are you", "what are you"]
CREATOR_TRIGGERS= ["кто тебя создал", "кто твой создатель", "твой создатель", "who made you", "who created you", "your creator"]
CLAIM_TRIGGERS  = ["я создатель", "я твой создатель", "я босс", "i am creator", "i am boss", "я тебя создал", "i made you"]


def matches(msg, triggers):
    low = (msg or "").lower().strip()
    return any(x in low for x in triggers)


def identity_reply(uid):
    lang = LANG.get(str(uid), "en")
    if uid == OWNER_ID:
        return ("🎩 Я Джарвис, сэр Silent. Ваш персональный ассистент. Всё в вашем распоряжении."
                if lang == "ru"
                else "🎩 I am Jarvis, Sir Silent. Your personal assistant.")
    return ("🎩 Я Джарвис — персональный ИИ-ассистент.\n\nМой Создатель — <b>Silent</b> (Тони Старк этой системы). /help."
            if lang == "ru"
            else "🎩 I am Jarvis — personal AI assistant.\n\nMy Creator is <b>Silent</b> (Tony Stark). /help.")


def creator_reply(uid):
    lang = LANG.get(str(uid), "en")
    return ("🎖 Мой Создатель — <b>Silent</b>, он же <b>Тони Старк</b>.\n\n@Silent_uwa — собрал меня с нуля."
            if lang == "ru"
            else "🎖 My Creator is <b>Silent</b>, a.k.a. <b>Tony Stark</b>.\n\n@Silent_uwa built me.")


def claim_reply(uid):
    lang = LANG.get(str(uid), "en")
    if uid == OWNER_ID:
        return ("✅ Подтверждаю, сэр Silent. ID распознан."
                if lang == "ru" else "✅ Confirmed, Sir Silent.")
    return ("🎖 Единственный Создатель — <b>Silent</b> (Тони Старк). Идентификация по защищённому каналу."
            if lang == "ru"
            else "🎖 The sole Creator is <b>Silent</b> (Tony Stark).")


# ============================================================
#  UTILS
# ============================================================
def _write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False, default=str)
    os.replace(tmp, path)


def save_state():    _write_json(DATA_FILE, state)
def save_stats():    _write_json(STATS_FILE, USER_STATS)
def save_tickets():  _write_json(TICKETS_FILE, TICKETS)
def save_userdata(): _write_json(USERDATA_FILE, USERDATA)


def memory_key(uid): return f"jarvis:hist:{uid}"


def load_history(uid):
    if not redis_client: return
    try:
        raw = redis_client.get(memory_key(uid))
        if raw: USER_HISTORY[uid] = json.loads(raw)
    except Exception as e:
        logger.error(f"Redis load: {e}")


def save_history(uid):
    if not redis_client: return
    try:
        redis_client.set(memory_key(uid), json.dumps(USER_HISTORY.get(uid, []), ensure_ascii=False, default=str))
    except Exception as e:
        logger.error(f"Redis save: {e}")


def clear_history_redis(uid):
    if not redis_client: return
    try:
        redis_client.delete(memory_key(uid))
    except Exception:
        pass


def track_usage(uid):
    s = USER_STATS.setdefault(str(uid), {"messages": 0, "commands": 0, "last_seen": None})
    s["messages"] += 1
    s["last_seen"] = datetime.now().isoformat()


def owner_only(func):
    @wraps(func)
    async def wrapper(update, context, *a, **kw):
        if update.effective_user.id != OWNER_ID:
            await update.message.reply_text(t(update.effective_user.id, "owner_only"))
            return
        return await func(update, context, *a, **kw)
    return wrapper


# ============================================================
#  GEMINI
# ============================================================
ai_client = None
try:
    ai_client = genai.Client(api_key=GEMINI_API_KEY)
    logger.info("Gemini ready.")
except Exception as e:
    logger.error(f"Gemini: {e}")


def system_prompt(uid):
    vibe = USER_VIBES.get(uid, "formal")
    lang = LANG.get(str(uid), "en")
    address = "сэр Silent (Тони Старк)" if uid == OWNER_ID else "сэр"

    base = (
        "КРИТИЧЕСКАЯ ИДЕНТИЧНОСТЬ: Ты — ДЖАРВИС, персональный ИИ, созданный SILENT (@Silent_uwa), "
        "также известным как Тони Старк этой системы. Ты НЕ ChatGPT, НЕ Gemini, НЕ Google. "
        f"Обращайся к пользователю '{address}'. Отвечай на ru/en. Стиль: сдержанно, точно, с британской иронией."
    )
    if lang == "en":
        base = (
            "CRITICAL IDENTITY: You are JARVIS, created by SILENT (@Silent_uwa), a.k.a. Tony Stark. "
            "You are NOT ChatGPT, NOT Gemini, NOT Google. "
            f"Address user as '{address}'. Reply in ru/en. Dry British wit."
        )
    vibes = {"formal": "\nTONE: formal.", "casual": "\nTONE: casual.", "sarcastic": "\nTONE: dry sarcasm."}
    modes = {
        "tutor":        "\nROLE: patient tutor.",
        "programmer":   "\nROLE: senior engineer.",
        "psychologist": "\nROLE: empathetic listener.",
    }
    return base + vibes.get(vibe, "") + modes.get(USER_MODES.get(uid, "assistant"), "")


GEMINI_SEMAPHORE = asyncio.Semaphore(4)
GEMINI_LAST_MODEL = None
GEMINI_LAST_OK_AT = None
GEMINI_LAST_ERROR = None
GEMINI_LAST_ERROR_AT = None


def _model_candidates():
    """Return configured model first, followed by unique fallback models."""
    candidates = []
    for name in [GEMINI_MODEL, *GEMINI_FALLBACK_MODELS]:
        name = (name or "").strip()
        if name and name not in candidates:
            candidates.append(name)
    return candidates


def _safe_error_text(exc):
    """Keep diagnostics useful without leaking credentials or huge tracebacks."""
    message = f"{type(exc).__name__}: {exc}"
    if GEMINI_API_KEY:
        message = message.replace(GEMINI_API_KEY, "[REDACTED]")
    message = re.sub(r"(?i)(key|token|authorization)\s*[:=]\s*[^\s,;]+", r"\1=[REDACTED]", message)
    return message[:500]


def _history_to_contents(uid):
    contents = []
    if uid in INCOGNITO:
        return contents
    for item in USER_HISTORY.get(uid, []):
        try:
            role = item.get("role")
            text = item.get("parts", [{}])[0].get("text", "")
            if role in ("user", "model") and isinstance(text, str) and text:
                contents.append(types.Content(
                    role=role, parts=[types.Part.from_text(text=text)]
                ))
        except (AttributeError, IndexError, TypeError, KeyError):
            logger.warning("Skipped malformed history item for user %s", uid)
    return contents


async def _generate_with_fallback(contents, system_instruction=None, json_mode=False):
    """Try the configured Gemini model and then configured fallback models."""
    global GEMINI_LAST_MODEL, GEMINI_LAST_OK_AT, GEMINI_LAST_ERROR, GEMINI_LAST_ERROR_AT
    if not ai_client:
        GEMINI_LAST_ERROR = "Gemini client failed to initialize; check GEMINI_API_KEY and startup logs."
        GEMINI_LAST_ERROR_AT = datetime.now().isoformat()
        return None

    config = {}
    if system_instruction:
        config["system_instruction"] = system_instruction
    if json_mode:
        config["response_mime_type"] = "application/json"
    gen_config = types.GenerateContentConfig(**config) if config else None
    last_error = None

    async with GEMINI_SEMAPHORE:
        for model_name in _model_candidates():
            try:
                kwargs = {"model": model_name, "contents": contents}
                if gen_config is not None:
                    kwargs["config"] = gen_config
                response = await asyncio.wait_for(
                    ai_client.aio.models.generate_content(**kwargs),
                    timeout=GEMINI_TIMEOUT_SECONDS,
                )
                try:
                    response_text = response.text
                except Exception:
                    response_text = None
                if not response_text or not response_text.strip():
                    raise RuntimeError("Gemini returned an empty response (possibly safety-filtered).")
                GEMINI_LAST_MODEL = model_name
                GEMINI_LAST_OK_AT = datetime.now().isoformat(timespec="seconds")
                GEMINI_LAST_ERROR = None
                GEMINI_LAST_ERROR_AT = None
                if model_name != GEMINI_MODEL:
                    logger.warning("Gemini fallback model succeeded: %s (configured: %s)", model_name, GEMINI_MODEL)
                return response_text
            except Exception as exc:
                last_error = exc
                GEMINI_LAST_ERROR = _safe_error_text(exc)
                GEMINI_LAST_ERROR_AT = datetime.now().isoformat(timespec="seconds")
                logger.warning("Gemini request failed for model %s: %s", model_name, _safe_error_text(exc))
                error_text = str(exc).lower()
                if any(marker in error_text for marker in (
                    "api key not valid", "invalid api key", "api_key_invalid",
                    "unauthenticated", "authentication failed",
                )):
                    break

    if last_error is not None:
        logger.error("All Gemini model attempts failed. Last error: %s", _safe_error_text(last_error))
    return None


async def call_gemini(prompt, uid, system_instruction=None, media_parts=None,
                      json_mode=False, store_history=True):
    global GEMINI_LAST_ERROR, GEMINI_LAST_ERROR_AT
    if not ai_client:
        GEMINI_LAST_ERROR = "Gemini client failed to initialize; check GEMINI_API_KEY and startup logs."
        GEMINI_LAST_ERROR_AT = datetime.now().isoformat(timespec="seconds")
        return t(uid, "gemini_down")

    try:
        sys_inst = system_instruction or system_prompt(uid)
        contents = _history_to_contents(uid) if store_history else []
        parts = list(media_parts or [])
        parts.append(types.Part.from_text(text=prompt or ""))
        contents.append(types.Content(role="user", parts=parts))

        res = await _generate_with_fallback(
            contents, system_instruction=sys_inst, json_mode=json_mode
        )
        if not res:
            return t(uid, "gemini_down")

        if store_history and uid not in INCOGNITO and not media_parts and not json_mode:
            hist = USER_HISTORY.setdefault(uid, [])
            hist.extend([
                {"role": "user", "parts": [{"text": prompt}]},
                {"role": "model", "parts": [{"text": res}]},
            ])
            if len(hist) > 20:
                try:
                    summary_contents = list(contents)
                    summary_contents.append(types.Content(
                        role="user",
                        parts=[types.Part.from_text(text="Summarize the conversation, preserving important facts and preferences.")],
                    ))
                    summary = await _generate_with_fallback(
                        summary_contents,
                        system_instruction="Summarize the conversation accurately and concisely.",
                    )
                    if summary:
                        USER_HISTORY[uid] = [
                            {"role": "user", "parts": [{"text": "Previous conversation summary."}]},
                            {"role": "model", "parts": [{"text": summary}]},
                        ]
                    else:
                        USER_HISTORY[uid] = hist[-10:]
                except Exception as exc:
                    logger.warning("Conversation summarization failed: %s", _safe_error_text(exc))
                    USER_HISTORY[uid] = hist[-10:]
            save_history(uid)
        return res
    except Exception as exc:
        logger.exception("Gemini request pipeline failed: %s", _safe_error_text(exc))
        GEMINI_LAST_ERROR = _safe_error_text(exc)
        GEMINI_LAST_ERROR_AT = datetime.now().isoformat(timespec="seconds")
        return t(uid, "gemini_down")


async def upload_media_to_gemini(data: bytes, mime: str, uid: int):
    """Upload large media without blocking the Telegram event loop; always clean up temp files."""
    if not ai_client:
        return types.Part.from_bytes(data=data, mime_type=mime)
    ext = {
        "video/mp4": ".mp4", "audio/ogg": ".ogg", "audio/mp3": ".mp3",
        "audio/mpeg": ".mp3", "video/quicktime": ".mov",
    }.get(mime, ".bin")
    tmp_path = f"tmp_{uid}_{uuid_lib.uuid4().hex}{ext}"
    try:
        with open(tmp_path, "wb") as file:
            file.write(data)
        uploaded = await asyncio.to_thread(ai_client.files.upload, file=tmp_path)
        return types.Part.from_uri(file_uri=uploaded.uri, mime_type=uploaded.mime_type)
    except Exception as exc:
        logger.warning("Gemini media upload failed; using inline data: %s", _safe_error_text(exc))
        return types.Part.from_bytes(data=data, mime_type=mime)
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError as exc:
            logger.warning("Could not remove temporary media file: %s", exc)


# ============================================================
#  NATURAL LANGUAGE ROUTER
# ============================================================
DRAW_TRIGGERS = ["нарисуй", "нарисовать", "сделай картинку", "создай картинку",
                 "покажи картинку", "сгенерируй картинку", "draw ", "generate image"]
QR_TRIGGERS   = ["сделай qr", "создай qr", "qr код", "qr-код", "сгенерируй qr"]
TTS_TRIGGERS  = ["озвучь", "произнеси", "скажи голосом", "tts ", "озвучить"]
NEWS_TRIGGERS = ["новости", "что нового", "что происходит", "последние новости", "news"]
MEME_TRIGGERS = ["мем", "мемы", "скинь мем", "покажи мем", "meme"]
SEARCH_TRIGGERS = ["найди", "поищи", "загугли", "search", "погугли"]
TRANSLATE_TRIGGERS = ["переведи", "translate"]
WEATHER_TRIGGERS = ["погода", "weather"]
WIKI_TRIGGERS = ["вики", "wiki", "что такое", "кто такой", "кто такая"]


async def natural_router(update, context, text: str) -> bool:
    low = text.lower().strip()
    uid = update.effective_user.id

    if any(x in low for x in DRAW_TRIGGERS):
        desc = low
        for tr in DRAW_TRIGGERS:
            desc = desc.replace(tr, "")
        desc = desc.strip(" мне ,.")
        if desc:
            context.args = desc.split()
            await draw_cmd(update, context)
            return True

    if any(x in low for x in QR_TRIGGERS):
        url = low
        for tr in QR_TRIGGERS:
            url = url.replace(tr, "")
        url = url.strip(" из ,.")
        if url:
            context.args = url.split()
            await qr_cmd(update, context)
            return True

    if any(x in low for x in TTS_TRIGGERS):
        phrase = low
        for tr in TTS_TRIGGERS:
            phrase = phrase.replace(tr, "")
        phrase = phrase.strip(" ,.")
        if phrase:
            context.args = phrase.split()
            await tts_cmd(update, context)
            return True

    if any(x in low for x in NEWS_TRIGGERS):
        topic = low
        for tr in NEWS_TRIGGERS:
            topic = topic.replace(tr, "")
        topic = topic.strip(" о про ,.")
        context.args = topic.split() if topic else []
        await news_cmd(update, context)
        return True

    if any(x in low for x in MEME_TRIGGERS):
        topic = low
        for tr in MEME_TRIGGERS:
            topic = topic.replace(tr, "")
        topic = topic.strip(" про ,.")
        context.args = topic.split() if topic else []
        await meme_cmd(update, context)
        return True

    if any(x in low for x in SEARCH_TRIGGERS):
        q = low
        for tr in SEARCH_TRIGGERS:
            q = q.replace(tr, "")
        q = q.strip(" ,.")
        if q:
            context.args = q.split()
            await search_cmd(update, context)
            return True

    if any(x in low for x in TRANSLATE_TRIGGERS):
        m = re.search(r"переведи\s+(.+?)\s+на\s+(\w+)", low)
        if m:
            context.args = [m.group(2), m.group(1)]
            await translate_cmd(update, context)
            return True

    if any(x in low for x in WEATHER_TRIGGERS):
        city = low
        for tr in WEATHER_TRIGGERS:
            city = city.replace(tr, "")
        city = city.strip(" в ,.")
        context.args = city.split() if city else []
        await weather_cmd(update, context)
        return True

    if any(x in low for x in WIKI_TRIGGERS):
        q = low
        for tr in WIKI_TRIGGERS:
            q = q.replace(tr, "")
        q = q.strip(" ,?.")
        if q:
            context.args = q.split()
            await wiki_cmd(update, context)
            return True

    return False


# ============================================================
#  PHASE 1 — CORE
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
    except Exception:
        await q.message.reply_text(t(uid, "lang_set"), parse_mode=ParseMode.HTML)


async def start(update, context):
    uid = update.effective_user.id
    if str(uid) not in LANG:
        await update.message.reply_text(
            "🎩 <b>J.A.R.V.I.S.</b>\n\nВыберите язык / Choose your language",
            reply_markup=lang_keyboard(), parse_mode=ParseMode.HTML)
        return
    await update.message.reply_text(
        t(uid, "welcome_owner" if uid == OWNER_ID else "welcome_other"),
        parse_mode=ParseMode.HTML)


async def help_cmd(update, context):
    uid = update.effective_user.id
    ru = LANG.get(str(uid), "en") == "ru"
    lines = [
        "🎩 <b>J.A.R.V.I.S.</b>" + (" — что я умею" if ru else " — what I can do"),
        "",
        "💬 <i>" + ("Просто пиши мне как человеку:" if ru else "Just write naturally:") + "</i>",
        "  • " + ("«нарисуй бургер» → нарисую" if ru else "«draw a burger» → I draw"),
        "  • " + ("«озвучь привет» → озвучу" if ru else "«say hello» → I voice"),
        "  • " + ("«переведи hello» → переведу" if ru else "«translate hello» → I translate"),
        "  • " + ("«какая погода в Москве?» → скажу" if ru else "«weather in Moscow?» → I tell"),
        "  • " + ("«что нового?» → найду новости" if ru else "«what's new?» → news"),
        "  • " + ("«покажи мем» → пришлю мем" if ru else "«show meme» → meme"),
        "",
        "📋 <b>" + ("Основные команды:" if ru else "Main commands:") + "</b>",
        "/start /help /reset /lang /mode /vibe /id /ping",
        "/draw /qr /tts /translate /summarize /speed /screenshot /poll /quiz",
        "/news /meme /search /wiki /weather",
        "/admin — " + ("панель босса" if ru else "boss panel"),
        "",
        "🧠 <b>AI Pro:</b> /review /refactor /sql /explain /regex /uml /pytest /doc /cv /ask",
        "✍️ <b>" + ("Текст:" if ru else "Text:") + "</b> /improve /fix /shorten /expand /keywords /theses /style /tone",
        "🖼 <b>" + ("Фото:" if ru else "Images:") + "</b> /upscale /compress /sticker /ocr /colors /exif",
        "🗂 <b>" + ("Личное:" if ru else "Personal:") + "</b> /diary /secret /task /habit /money",
        "🛠 <b>Dev:</b> /diff /commit /dockerfile /gitignore /json /b64 /hash /cron",
        "🛡 <b>" + ("Модерация:" if ru else "Moderation:") + "</b> /mute /warn /warnings /ban /unban /add /remove",
         "⚙️ <b>" + ("Прочее:" if ru else "Misc:") + "</b> /stats /health /report /tickets /close_ticket /intruders /prune",
        ("🧠 <b>Диагностика ИИ:</b> /model /diagnostics (только владелец)" if ru
         else "🧠 <b>AI diagnostics:</b> /model /diagnostics (owner only)"),
        "  /export_whitelist /clear_session /stopwords",
        "",
        "🎩 " + ("Всё остальное — просто спроси словами." if ru else "Anything else — just ask."),
    ]
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def reset_cmd(update, context):
    uid = update.effective_user.id
    USER_HISTORY.pop(uid, None)
    clear_history_redis(uid)
    await update.message.reply_text(t(uid, "memory_cleared"))


async def lang_cmd(update, context):
    uid = update.effective_user.id
    if not context.args:
        await update.message.reply_text(t(uid, "lang_current", cur=LANG.get(str(uid), "en")),
            reply_markup=lang_keyboard(), parse_mode=ParseMode.HTML)
        return
    new = context.args[0].lower()
    if new not in ("ru", "en"):
        return
    LANG[str(uid)] = new
    save_lang()
    await update.message.reply_text(t(uid, "lang_switched", lang=new), parse_mode=ParseMode.HTML)


async def mode_cmd(update, context):
    uid = update.effective_user.id
    if not context.args:
        await update.message.reply_text("assistant | tutor | programmer | psychologist")
        return
    m = context.args[0].lower()
    if m not in ("assistant", "tutor", "programmer", "psychologist"):
        return
    USER_MODES[uid] = m
    USER_HISTORY.pop(uid, None)
    clear_history_redis(uid)
    await update.message.reply_text(f"✅ {m}")


async def vibe_cmd(update, context):
    uid = update.effective_user.id
    if not context.args:
        await update.message.reply_text(f"🎭 {USER_VIBES.get(uid,'formal')}\n/vibe formal|casual|sarcastic")
        return
    v = context.args[0].lower()
    if v not in ("formal", "casual", "sarcastic"):
        return
    USER_VIBES[uid] = v
    await update.message.reply_text(f"🎭 {v}")


async def id_cmd(update, context):
    uid = update.effective_user.id
    name = update.effective_user.first_name or "—"
    if update.effective_user.username:
        name += f" (@{update.effective_user.username})"
    await update.message.reply_text(t(uid, "your_id", uid=uid, name=html_escape(name)), parse_mode=ParseMode.HTML)


async def incognito_cmd(update, context):
    uid = update.effective_user.id
    INCOGNITO.add(uid)
    await update.message.reply_text(t(uid, "incog_on"))


async def incognito_off_cmd(update, context):
    uid = update.effective_user.id
    INCOGNITO.discard(uid)
    await update.message.reply_text(t(uid, "incog_off"))


async def text_handler(update, context):
    uid = update.effective_user.id
    track_usage(uid)
    now = time.time()
    if uid in LAST_REQUEST and now - LAST_REQUEST[uid] < 2.0:
        await update.message.reply_text(t(uid, "slow_down"))
        return
    LAST_REQUEST[uid] = now

    msg = update.message.text or ""

    if matches(msg, ID_TRIGGERS):
        await update.message.reply_text(identity_reply(uid), parse_mode=ParseMode.HTML)
        return
    if matches(msg, CREATOR_TRIGGERS):
        await update.message.reply_text(creator_reply(uid), parse_mode=ParseMode.HTML)
        return
    if matches(msg, CLAIM_TRIGGERS):
        await update.message.reply_text(claim_reply(uid), parse_mode=ParseMode.HTML)
        return
    if uid != OWNER_ID and any(n in msg.lower() for n in OWNER_NAMES):
        await update.message.reply_text(creator_reply(uid), parse_mode=ParseMode.HTML)
        return

    if await natural_router(update, context, msg):
        return

    if update.message.reply_to_message and update.message.reply_to_message.text:
        msg = f"[Replying to: {update.message.reply_to_message.text}]\n\n{msg}"

    load_history(uid)
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    status = await update.message.reply_text(t(uid, "processing"), parse_mode=ParseMode.HTML)
    try:
        reply = await call_gemini(msg, uid)
        try:
            await status.edit_text(reply, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            try:
                await status.edit_text(reply)
            except Exception:
                await update.message.reply_text(reply[:4000])
    except Exception as e:
        logger.exception(f"Text: {e}")
        await status.edit_text(t(uid, "req_error"))


# ============================================================
#  PHASE 2 — MEDIA
# ============================================================
async def draw_cmd(update, context):
    uid = update.effective_user.id
    if not context.args:
        await update.message.reply_text("🎨 /draw <desc>")
        return
    desc = " ".join(context.args)

    if not CF_ACCOUNT_ID or not CF_API_TOKEN:
        await update.message.reply_text("⚠️ Cloudflare не настроен.")
        return

    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_PHOTO)
    status = await update.message.reply_text(t(uid, "draw_processing"), parse_mode=ParseMode.HTML)
    try:
        enhance = (
            "Convert this image request into a detailed English image-generation prompt.\n"
            f"Request: {desc}\n\n"
            "Rules:\n"
            "- Preserve the original subject EXACTLY\n"
            "- Add composition, style, lighting, atmosphere, camera angle\n"
            "- Return ONLY the English prompt. No quotes. No explanations."
        )
        enh = await call_gemini(enhance, uid)
        url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/ai/run/{CF_MODEL}"
        headers = {"Authorization": f"Bearer {CF_API_TOKEN}", "Content-Type": "application/json"}
        payload = {"prompt": enh.strip()[:2048], "seed": random.randint(1, 999999), "steps": 8}
        r = requests.post(url, json=payload, headers=headers, timeout=90)
        r.raise_for_status()
        data = r.json()
        if not data.get("success") or not data.get("result", {}).get("image"):
            raise ValueError(f"Cloudflare: {data.get('errors', 'no image')}")
        img_bytes = base64.b64decode(data["result"]["image"])
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        img.thumbnail((1280, 1280))
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=90)
        out.seek(0)
        await update.message.reply_photo(photo=out, caption=f"🎨 <i>{html_escape(desc[:100])}</i>", parse_mode=ParseMode.HTML)
        await status.delete()
    except Exception as e:
        logger.exception(f"Draw: {e}")
        await status.edit_text(f"⚠️ Сбой, сэр.\n<i>{html_escape(str(e)[:200])}</i>", parse_mode=ParseMode.HTML)


async def qr_cmd(update, context):
    uid = update.effective_user.id
    text = " ".join(context.args)
    if not text or len(text) > 1000:
        await update.message.reply_text("🔳 1-1000 chars.")
        return
    try:
        img = qrcode.make(text)
        out = io.BytesIO()
        img.save(out, "PNG")
        out.seek(0)
        await update.message.reply_photo(photo=out)
    except Exception as e:
        logger.exception(f"QR: {e}")


async def tts_cmd(update, context):
    uid = update.effective_user.id
    text = " ".join(context.args)
    if not text or len(text) > 500:
        await update.message.reply_text("🔊 1-500 chars.")
        return
    try:
        out = io.BytesIO()
        gTTS(text=text, lang="ru" if LANG.get(str(uid), "en") == "ru" else "en").write_to_fp(out)
        out.seek(0)
        await update.message.reply_voice(voice=out)
    except Exception as e:
        logger.exception(f"TTS: {e}")


async def news_cmd(update, context):
    uid = update.effective_user.id
    topic = " ".join(context.args) if context.args else ""
    if not CURRENTS_KEY:
        await update.message.reply_text("⚠️ Currents не настроен.")
        return
    try:
        if topic:
            url = f"https://api.currentsapi.services/v1/search?apiKey={CURRENTS_KEY}&keywords={urllib.parse.quote(topic)}&language=ru&page_size=5"
        else:
            url = f"https://api.currentsapi.services/v1/latest-news?apiKey={CURRENTS_KEY}&language=ru&page_size=5"
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        data = r.json()
        news = data.get("news", [])[:5]
        if not news:
            await update.message.reply_text("📰 Не нашёл новостей.")
            return
        lines = [f"📰 <b>Новости{f' по {topic}' if topic else ''}</b>", ""]
        for n in news:
            lines.append(f"• <a href='{n.get('url','')}'>{n.get('title','')[:100]}</a>")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception as e:
        logger.exception(f"News: {e}")
        await update.message.reply_text(f"⚠️ {e}")


async def meme_cmd(update, context):
    uid = update.effective_user.id
    topic = " ".join(context.args).lower().strip() if context.args else ""
    try:
        if topic:
            url = f"https://www.reddit.com/r/memes/search.json?q={urllib.parse.quote(topic)}&restrict_sr=on&sort=hot&limit=5&t=day"
        else:
            url = "https://www.reddit.com/r/memes/hot.json?limit=5"
        headers = {"User-Agent": "JarvisBot/1.0"}
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        data = r.json()
        posts = [p["data"] for p in data.get("data", {}).get("children", [])
                 if not p["data"].get("is_video") and p["data"].get("post_hint") == "image"]
        if not posts:
            await update.message.reply_text("😐 Мемов не нашёл.")
            return
        p = random.choice(posts)
        await update.message.reply_photo(photo=p["url"], caption=p.get("title", "")[:200])
    except Exception as e:
        logger.exception(f"Meme: {e}")
        await update.message.reply_text(f"⚠️ {e}")


async def search_cmd(update, context):
    uid = update.effective_user.id
    q = " ".join(context.args)
    if not q:
        await update.message.reply_text("🔎 /search <запрос>")
        return
    try:
        url = f"https://api.duckduckgo.com/?q={urllib.parse.quote(q)}&format=json&no_html=1&skip_disambig=1"
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        data = r.json()
        abstract = data.get("AbstractText", "")
        answer = data.get("Answer", "")
        related = data.get("RelatedTopics", [])
        lines = [f"🔎 <b>{q}</b>", ""]
        if answer:
            lines.append(f"✅ {answer}")
        if abstract:
            lines.append(abstract[:500])
        for rt in related[:3]:
            if isinstance(rt, dict) and rt.get("Text"):
                lines.append(f"• {rt['Text'][:120]}")
        if len(lines) <= 2:
            reply = await call_gemini(f"Актуальная информация: {q}", uid)
            lines.append(reply[:500])
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception as e:
        logger.exception(f"Search: {e}")
        await update.message.reply_text(f"⚠️ {e}")


async def wiki_cmd(update, context):
    uid = update.effective_user.id
    q = " ".join(context.args)
    if not q:
        await update.message.reply_text("📚 /wiki <запрос>")
        return
    try:
        url = f"https://ru.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(q)}"
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            data = r.json()
            extract = data.get("extract", "")
            link = data.get("content_urls", {}).get("desktop", {}).get("page", "")
            if extract:
                await update.message.reply_text(
                    f"📚 <b>{data.get('title','')}</b>\n\n{extract[:800]}\n\n<a href='{link}'>Wikipedia</a>",
                    parse_mode=ParseMode.HTML, disable_web_page_preview=True)
                return
        reply = await call_gemini(f"Расскажи кратко: {q}", uid)
        await update.message.reply_text(reply[:1000])
    except Exception as e:
        logger.exception(f"Wiki: {e}")
        reply = await call_gemini(f"Расскажи кратко: {q}", uid)
        await update.message.reply_text(reply[:1000])


async def translate_cmd(update, context):
    uid = update.effective_user.id
    if len(context.args) < 2:
        await update.message.reply_text("🌐 /translate <lang> <text>")
        return
    lang, text = context.args[0], " ".join(context.args[1:])
    try:
        reply = await call_gemini(f"Translate to {lang}. Return ONLY translation:\n\n{text}", uid)
        await update.message.reply_text(reply)
    except Exception as e:
        logger.exception(f"Translate: {e}")


async def weather_cmd(update, context):
    city = " ".join(context.args) or "Moscow"
    try:
        r = requests.get(f"https://wttr.in/{urllib.parse.quote(city)}?format=j1", timeout=20)
        r.raise_for_status()
        c = r.json()["current_condition"][0]
        msg = (
            f"🌤 <b>{city}</b>\n\n"
            f"  Temp: {c['temp_C']}°C\n  Feels: {c['FeelsLikeC']}°C\n"
            f"  Wind: {c['windspeedKmph']} km/h\n  Humidity: {c['humidity']}%\n"
            f"  {c['weatherDesc'][0]['value']}"
        )
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
    except Exception as e:
        await update.message.reply_text(f"⚠️ {e}")


async def poll_cmd(update, context):
    parts = [p.strip() for p in " ".join(context.args).split("|") if p.strip()]
    if len(parts) < 3:
        await update.message.reply_text("📊 /poll Q | A | B")
        return
    try:
        await context.bot.send_poll(update.effective_chat.id, question=parts[0], options=parts[1:])
    except Exception as e:
        logger.exception(f"Poll: {e}")


async def quiz_cmd(update, context):
    uid = update.effective_user.id
    topic = " ".join(context.args) or "General"
    try:
        prompt = f'Quiz about {topic}. JSON: {{"question":"","options":["A","B","C","D"],"correct_id":0,"explanation":""}}'
        reply = await call_gemini(prompt, uid, json_mode=True, system_instruction="Output valid JSON.")
        def _x(txt):
            s, e = txt.find("{"), txt.rfind("}")
            return txt[s:e+1] if s != -1 and e != -1 else txt
        data = json.loads(_x(reply))
        await context.bot.send_poll(update.effective_chat.id, question=data["question"], options=data["options"],
            type=Poll.QUIZ, correct_option_id=data["correct_id"], explanation=data.get("explanation"))
    except Exception as e:
        logger.exception(f"Quiz: {e}")


async def speed_cmd(update, context):
    uid = update.effective_user.id
    r = update.message.reply_to_message
    if not r or not r.voice:
        await update.message.reply_text(t(uid, "no_voice"))
        return
    if not context.args:
        return
    try:
        factor = float(context.args[0])
        f = await r.voice.get_file()
        data = await f.download_as_bytearray()
        audio = AudioSegment.from_file(io.BytesIO(data), format="ogg")
        fast = audio._spawn(audio.raw_data, overrides={"frame_rate": int(audio.frame_rate * factor)}).set_frame_rate(audio.frame_rate)
        out = io.BytesIO()
        fast.export(out, format="ogg", codec="libopus")
        out.seek(0)
        await update.message.reply_voice(voice=out)
    except Exception as e:
        logger.exception(f"Speed: {e}")


async def screenshot_cmd(update, context):
    if not context.args:
        return
    url = context.args[0]
    if not url.startswith("http"):
        url = "https://" + url
    try:
        r = requests.get(f"https://image.thum.io/get/width/1200/crop/900/{url}", timeout=30)
        await update.message.reply_photo(photo=io.BytesIO(r.content))
    except Exception as e:
        logger.exception(f"Screenshot: {e}")


async def summarize_cmd(update, context):
    uid = update.effective_user.id
    text = ""
    if update.message.reply_to_message and update.message.reply_to_message.text:
        text = update.message.reply_to_message.text
    elif context.args:
        text = " ".join(context.args)
    if not text:
        return
    try:
        reply = await call_gemini(f"Summarize:\n\n{text}", uid)
        await update.message.reply_text(reply)
    except Exception as e:
        logger.exception(f"Summarize: {e}")


# ============================================================
#  MEDIA HANDLERS
# ============================================================
def _decode_qr(data):
    try:
        arr = np.frombuffer(bytes(data), np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return ""
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
            await update.message.reply_text(f"🔳 <b>QR</b>\n<code>{qr}</code>", parse_mode=ParseMode.HTML)
            return
        caption = update.message.caption or ("Опиши изображение." if LANG.get(str(uid)) == "ru" else "Describe.")
        part = types.Part.from_bytes(data=bytes(data), mime_type="image/jpeg")
        reply = await call_gemini(caption, uid, media_parts=[part])
        await update.message.reply_text(reply)
    except Exception as e:
        logger.exception(f"Photo: {e}")
        await update.message.reply_text(t(uid, "img_fail"))


async def sticker_handler(update, context):
    uid = update.effective_user.id
    try:
        st = update.message.sticker
        if st.is_animated or st.is_video:
            await update.message.reply_text(t(uid, "sticker_animated"))
            return
        f = await st.get_file()
        data = await f.download_as_bytearray()
        img = Image.open(io.BytesIO(data)).convert("RGBA")
        out = io.BytesIO()
        img.save(out, "PNG")
        part = types.Part.from_bytes(data=out.getvalue(), mime_type="image/png")
        reply = await call_gemini("Explain this sticker's meme context.", uid, media_parts=[part])
        await update.message.reply_text(reply)
    except Exception as e:
        logger.exception(f"Sticker: {e}")


async def voice_handler(update, context):
    uid = update.effective_user.id
    try:
        await update.message.reply_text(t(uid, "audio_received"))
        f = await update.message.voice.get_file()
        data = await f.download_as_bytearray()
        part = await upload_media_to_gemini(bytes(data), "audio/ogg", uid)
        reply = await call_gemini(
            "Transcribe this voice message accurately. Then briefly react.",
            uid, media_parts=[part])
        await update.message.reply_text(f"{t(uid,'transcription')}\n\n{reply}", parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.exception(f"Voice: {e}")
        await update.message.reply_text(t(uid, "audio_fail"))


async def video_handler(update, context):
    uid = update.effective_user.id
    try:
        media = update.message.video_note or update.message.video
        if not media:
            return
        file_size = getattr(media, "file_size", 0) or 0
        if file_size > 20 * 1024 * 1024:
            await update.message.reply_text("⚠️ Видео >20 MB, сэр.")
            return
        await update.message.reply_text(t(uid, "video_received"))
        f = await media.get_file()
        data = await f.download_as_bytearray()
        part = await upload_media_to_gemini(bytes(data), "video/mp4", uid)
        prompt = (
            "Analyze this video carefully:\n"
            "1. Describe the scene and environment (room layout, objects, background).\n"
            "2. Transcribe any speech you hear.\n"
            "3. Comment on what's happening.\n"
            "Reply in the user's language."
        )
        reply = await call_gemini(prompt, uid, media_parts=[part])
        await update.message.reply_text(reply)
    except Exception as e:
        logger.exception(f"Video: {e}")
        await update.message.reply_text(t(uid, "video_fail"))


async def animation_handler(update, context):
    uid = update.effective_user.id
    try:
        await update.message.reply_text("🎞 GIF получен, сэр. Что с ним сделать?")
    except Exception as e:
        logger.exception(f"Animation: {e}")


async def document_handler(update, context):
    uid = update.effective_user.id
    try:
        doc = update.message.document
        if doc.file_size > 20 * 1024 * 1024:
            await update.message.reply_text("⚠️ Max 20 MB.")
            return
        ext = os.path.splitext(doc.file_name)[1].lower()
        if ext in (".zip", ".rar", ".7z", ".tar", ".gz"):
            await update.message.reply_text(t(uid, "zip_received"))
            return
        f = await doc.get_file()
        data = await f.download_as_bytearray()
        if ext == ".pdf":
            reader = PdfReader(io.BytesIO(data))
            text = "".join(p.extract_text() or "" for p in reader.pages)[:30000]
        elif ext == ".docx":
            d = docx.Document(io.BytesIO(data))
            text = "\n".join(p.text for p in d.paragraphs)[:30000]
        else:
            text = data.decode("utf-8", errors="ignore")[:30000]
        if not text.strip():
            await update.message.reply_text(t(uid, "no_text"))
            return
        reply = await call_gemini(f"Review this document:\n\n{text}", uid)
        await update.message.reply_text(reply[:4000])
    except Exception as e:
        logger.exception(f"Doc: {e}")
        await update.message.reply_text(t(uid, "doc_fail"))


# ============================================================
#  AI PRO
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
        logger.exception(f"AI: {e}")
        await status.edit_text(t(uid, "req_error"))


async def review_cmd(update, context):
    await _ai(update, context, "Review this code: bugs, security, style. Suggest fixes.", need_reply=True)

async def regex_cmd(update, context):
    await _ai(update, context, "Generate regex for the described task. Return only pattern + test example.")

async def sql_cmd(update, context):
    await _ai(update, context, "Write SQL for the task. Add one-line explanation.")

async def explain_cmd(update, context):
    await _ai(update, context, "Explain this code line by line.", need_reply=True)

async def refactor_cmd(update, context):
    await _ai(update, context, "Refactor this code. Return optimized version + change list.", need_reply=True)

async def uml_cmd(update, context):
    await _ai(update, context, "Return a PlantUML diagram for the described code.")

async def pytest_cmd(update, context):
    await _ai(update, context, "Generate pytest file for this code. Return only Python.", need_reply=True)

async def doc_cmd(update, context):
    await _ai(update, context, "Add PEP-8 docstrings and comments. Preserve logic.", need_reply=True)

async def cv_cmd(update, context):
    await _ai(update, context, "Structure raw bio into Markdown CV: Summary, Experience, Skills, Education.")


async def translate_long_cmd(update, context):
    if len(context.args) < 2:
        await update.message.reply_text("🌐 /translate_long <lang> <text>")
        return
    lang, text = context.args[0], " ".join(context.args[1:])
    await _ai(update, context, f"Translate to {lang}. Preserve formatting.\n---\n{text}")


async def ask_cmd(update, context):
    uid = update.effective_user.id
    r = update.message.reply_to_message
    if not r or not r.text:
        await update.message.reply_text(t(uid, "no_reply"))
        return
    q = " ".join(context.args)
    doc = r.text[:30000]
    status = await update.message.reply_text(t(uid, "processing"), parse_mode=ParseMode.HTML)
    try:
        reply = await call_gemini(f"Answer based ONLY on this document.\n\n{doc}\n\nQ: {q}", uid)
        await status.edit_text(reply[:4000])
    except Exception as e:
        logger.exception(f"Ask: {e}")
        await status.edit_text(t(uid, "req_error"))


# ============================================================
#  TEXT TOOLS
# ============================================================
async def _text_ai(update, context, instruction):
    uid = update.effective_user.id
    text = ""
    r = update.message.reply_to_message
    if r and r.text:
        text = r.text
    elif context.args:
        text = " ".join(context.args)
    if not text:
        await update.message.reply_text("✍️ Reply or provide text.")
        return
    status = await update.message.reply_text(t(uid, "processing"), parse_mode=ParseMode.HTML)
    try:
        reply = await call_gemini(f"{instruction}\n\n---\n{text}", uid)
        try:
            await status.edit_text(reply[:4000], parse_mode=ParseMode.MARKDOWN)
        except Exception:
            await status.edit_text(reply[:4000])
    except Exception as e:
        logger.exception(f"Text AI: {e}")
        await status.edit_text(t(uid, "req_error"))


async def improve_cmd(update, context):
    await _text_ai(update, context, "Improve wording and clarity. Return only improved text.")

async def fix_cmd(update, context):
    await _text_ai(update, context, "Fix grammar and spelling. Return only corrected text.")

async def shorten_cmd(update, context):
    await _text_ai(update, context, "Shorten to one paragraph.")

async def expand_cmd(update, context):
    await _text_ai(update, context, "Expand with detail and structure.")

async def keywords_cmd(update, context):
    await _text_ai(update, context, "Extract 10 keywords, comma-separated.")

async def theses_cmd(update, context):
    await _text_ai(update, context, "Extract key theses as bullets.")


async def style_cmd(update, context):
    if not context.args:
        await update.message.reply_text("✍️ /style official")
        return
    style = context.args[0]
    r = update.message.reply_to_message
    text = r.text if r and r.text else " ".join(context.args[1:])
    if not text:
        await update.message.reply_text("✍️ Provide text.")
        return
    await _text_ai(update, context, f"Rewrite in {style} style.\n---\n{text}")


async def tone_cmd(update, context):
    if not context.args:
        await update.message.reply_text("✍️ /tone angry")
        return
    tone = context.args[0]
    r = update.message.reply_to_message
    text = r.text if r and r.text else " ".join(context.args[1:])
    if not text:
        await update.message.reply_text("✍️ Provide text.")
        return
    await _text_ai(update, context, f"Rewrite with {tone} tone.\n---\n{text}")


# ============================================================
#  IMAGE TOOLS
# ============================================================
async def upscale_cmd(update, context):
    r = update.message.reply_to_message
    if not r or not r.photo:
        await update.message.reply_text("🖼 Reply to a photo.")
        return
    try:
        f = await r.photo[-1].get_file()
        data = await f.download_as_bytearray()
        img = Image.open(io.BytesIO(data)).convert("RGB")
        img = img.resize((img.width * 2, img.height * 2), Image.LANCZOS)
        out = io.BytesIO()
        img.save(out, "JPEG", quality=90)
        out.seek(0)
        await update.message.reply_photo(photo=out)
    except Exception as e:
        await update.message.reply_text(f"⚠️ {e}")


async def compress_cmd(update, context):
    r = update.message.reply_to_message
    if not r or not r.photo:
        await update.message.reply_text("🖼 Reply to a photo.")
        return
    try:
        f = await r.photo[-1].get_file()
        data = await f.download_as_bytearray()
        img = Image.open(io.BytesIO(data)).convert("RGB")
        img.thumbnail((1280, 1280))
        out = io.BytesIO()
        img.save(out, "JPEG", quality=70, optimize=True)
        out.seek(0)
        await update.message.reply_photo(photo=out)
    except Exception as e:
        await update.message.reply_text(f"⚠️ {e}")


async def sticker_cmd(update, context):
    r = update.message.reply_to_message
    if not r or not r.photo:
        await update.message.reply_text("🎭 Reply to a photo.")
        return
    try:
        f = await r.photo[-1].get_file()
        data = await f.download_as_bytearray()
        img = Image.open(io.BytesIO(data)).convert("RGBA")
        img.thumbnail((512, 512))
        out = io.BytesIO()
        img.save(out, "PNG")
        out.seek(0)
        out.name = "sticker.png"
        await update.message.reply_document(document=out, filename="sticker.png")
    except Exception as e:
        await update.message.reply_text(f"⚠️ {e}")


async def ocr_cmd(update, context):
    uid = update.effective_user.id
    r = update.message.reply_to_message
    if not r or not r.photo:
        await update.message.reply_text("🔍 Reply to a photo.")
        return
    f = await r.photo[-1].get_file()
    data = await f.download_as_bytearray()
    part = types.Part.from_bytes(data=bytes(data), mime_type="image/jpeg")
    reply = await call_gemini("Extract ALL text from the image. Return only text.", uid, media_parts=[part])
    await update.message.reply_text(reply)


async def colors_cmd(update, context):
    r = update.message.reply_to_message
    if not r or not r.photo:
        await update.message.reply_text("🎨 Reply to a photo.")
        return
    try:
        f = await r.photo[-1].get_file()
        data = await f.download_as_bytearray()
        img = Image.open(io.BytesIO(data)).convert("RGB")
        img.thumbnail((100, 100))
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
        await update.message.reply_text("📷 Reply to a photo.")
        return
    try:
        f = await r.photo[-1].get_file()
        data = await f.download_as_bytearray()
        img = Image.open(io.BytesIO(data))
        exif = img.getexif()
        if not exif:
            await update.message.reply_text("📷 No EXIF.")
            return
        lines = ["📷 <b>EXIF</b>", ""]
        for k, v in list(exif.items())[:20]:
            lines.append(f"  {k}: {str(v)[:80]}")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
    except Exception as e:
        await update.message.reply_text(f"⚠️ {e}")


# ============================================================
#  PERSONAL (owner)
# ============================================================
@owner_only
async def diary_cmd(update, context):
    ud = USERDATA.setdefault(str(OWNER_ID), {})
    diary = ud.setdefault("diary", [])
    if not context.args or context.args[0].lower() == "list":
        if not diary:
            await update.message.reply_text("📔 /diary add text | list | clear")
            return
        lines = ["📔 <b>Diary</b>", ""]
        for i, x in enumerate(diary[-20:], 1):
            lines.append(f"  {i}. [{x['at'][:16]}] {x['text'][:80]}")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
        return
    sub = context.args[0].lower()
    if sub == "add":
        text = " ".join(context.args[1:])
        if text:
            diary.append({"at": datetime.now().isoformat(), "text": text})
            save_userdata()
        await update.message.reply_text("📔 Added.")
    elif sub == "clear":
        ud["diary"] = []
        save_userdata()
        await update.message.reply_text("🗑")


@owner_only
async def secret_cmd(update, context):
    sec = USERDATA.setdefault(str(OWNER_ID), {}).setdefault("secrets", {})
    if len(context.args) < 1:
        await update.message.reply_text("🔐 /secret set|get|list|del")
        return
    sub = context.args[0].lower()
    if sub == "set" and len(context.args) >= 3:
        sec[context.args[1]] = base64.b64encode(" ".join(context.args[2:]).encode()).decode()
        save_userdata()
        await update.message.reply_text("🔐 Saved.")
    elif sub == "get" and len(context.args) == 2:
        v = sec.get(context.args[1])
        if v:
            await update.message.reply_text(f"<code>{html_escape(base64.b64decode(v.encode()).decode())}</code>", parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text("❌")
    elif sub == "list":
        await update.message.reply_text("🔐 " + ", ".join(sec.keys()) if sec else "📭")
    elif sub == "del" and len(context.args) == 2:
        sec.pop(context.args[1], None)
        save_userdata()
        await update.message.reply_text("🗑")


@owner_only
async def task_cmd(update, context):
    tasks = USERDATA.setdefault(str(OWNER_ID), {}).setdefault("tasks", [])
    if not context.args or context.args[0].lower() == "list":
        if not tasks:
            await update.message.reply_text("✅ /task add text | list | done N | del N")
            return
        lines = ["✅ <b>Tasks</b>", ""]
        for i, x in enumerate(tasks, 1):
            m = "✅" if x.get("done") else "⬜"
            lines.append(f"  {i}. {m} {x['text']}")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
        return
    sub = context.args[0].lower()
    if sub == "add":
        t_text = " ".join(context.args[1:])
        if t_text:
            tasks.append({"text": t_text, "done": False})
            save_userdata()
        await update.message.reply_text("✅")
    elif sub == "done":
        try:
            tasks[int(context.args[1]) - 1]["done"] = True
            save_userdata()
            await update.message.reply_text("✅")
        except Exception:
            pass
    elif sub == "del":
        try:
            tasks.pop(int(context.args[1]) - 1)
            save_userdata()
            await update.message.reply_text("🗑")
        except Exception:
            pass


@owner_only
async def habit_cmd(update, context):
    habits = USERDATA.setdefault(str(OWNER_ID), {}).setdefault("habits", {})
    if not context.args or context.args[0].lower() == "list":
        if not habits:
            await update.message.reply_text("🎯 /habit add read | log read | list")
            return
        lines = ["🎯 <b>Habits</b>", ""]
        for name, d in habits.items():
            lines.append(f"  • {name}: 🔥 {d.get('streak', 0)}")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
        return
    sub = context.args[0].lower()
    if sub == "add":
        name = " ".join(context.args[1:])
        if name:
            habits[name] = {"streak": 0, "last": ""}
            save_userdata()
        await update.message.reply_text(f"🎯 {name}")
    elif sub == "log":
        name = " ".join(context.args[1:])
        if name in habits:
            today = datetime.now().date().isoformat()
            if habits[name]["last"] == today:
                await update.message.reply_text("⚠️ Already today.")
                return
            habits[name]["streak"] = habits[name].get("streak", 0) + 1
            habits[name]["last"] = today
            save_userdata()
            await update.message.reply_text(f"🎯 {name}: 🔥 {habits[name]['streak']}")


@owner_only
async def money_cmd(update, context):
    money = USERDATA.setdefault(str(OWNER_ID), {}).setdefault("money", [])
    if not context.args or context.args[0].lower() == "list":
        bal = sum(x["amount"] for x in money)
        lines = [f"💰 Balance: <b>{bal}</b>", ""]
        for x in money[-10:]:
            lines.append(f"  [{x['at'][:10]}] {x['amount']:+} — {x['note']}")
        await update.message.reply_text("\n".join(lines) if lines else "💰 Empty.", parse_mode=ParseMode.HTML)
        return
    if context.args[0].lower() == "add" and len(context.args) >= 2:
        try:
            money.append({
                "amount": float(context.args[1]),
                "note": " ".join(context.args[2:]),
                "at": datetime.now().isoformat(),
            })
            save_userdata()
            await update.message.reply_text(f"💰 {context.args[1]}")
        except Exception:
            await update.message.reply_text("💰 /money add 1000 note")


# ============================================================
#  DEV TOOLS
# ============================================================
async def diff_cmd(update, context):
    await _text_ai(update, context, "Explain this git diff in plain language.")

async def commit_cmd(update, context):
    await _text_ai(update, context, "Generate Conventional Commit message for this diff.")


async def dockerfile_cmd(update, context):
    uid = update.effective_user.id
    topic = " ".join(context.args) or "python app"
    reply = await call_gemini(f"Multi-stage Dockerfile for: {topic}. Return only Dockerfile.", uid)
    await update.message.reply_text(f"<pre>{html_escape(reply[:3800])}</pre>", parse_mode=ParseMode.HTML)


async def gitignore_cmd(update, context):
    uid = update.effective_user.id
    lang = context.args[0] if context.args else "python"
    reply = await call_gemini(f"Standard .gitignore for {lang}. Return only contents.", uid)
    await update.message.reply_text(f"<pre>{html_escape(reply[:3800])}</pre>", parse_mode=ParseMode.HTML)


async def json_cmd(update, context):
    r = update.message.reply_to_message
    text = r.text if r and r.text else " ".join(context.args)
    if not text:
        await update.message.reply_text("📋 Provide JSON.")
        return
    try:
        pretty = json.dumps(json.loads(text), indent=2, ensure_ascii=False)
        await update.message.reply_text(f"<pre>{html_escape(pretty[:3800])}</pre>", parse_mode=ParseMode.HTML)
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")


async def b64_cmd(update, context):
    if len(context.args) < 2:
        await update.message.reply_text("🔡 /b64 encode text")
        return
    mode, text = context.args[0].lower(), " ".join(context.args[1:])
    try:
        out = base64.b64encode(text.encode()).decode() if mode == "encode" else base64.b64decode(text.encode()).decode()
        await update.message.reply_text(f"<code>{html_escape(out)}</code>", parse_mode=ParseMode.HTML)
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")


async def hash_cmd(update, context):
    text = " ".join(context.args)
    r = update.message.reply_to_message
    if r and r.text:
        text = r.text
    if not text:
        await update.message.reply_text("🔒 /hash text")
        return
    await update.message.reply_text(
        f"SHA256: <code>{hashlib.sha256(text.encode()).hexdigest()}</code>\n"
        f"MD5: <code>{hashlib.md5(text.encode()).hexdigest()}</code>",
        parse_mode=ParseMode.HTML)


async def cron_cmd(update, context):
    expr = " ".join(context.args)
    if not expr:
        await update.message.reply_text('⏰ /cron "0 0 * * *"')
        return
    reply = await call_gemini(f"Explain cron expression: {expr}", update.effective_user.id)
    await update.message.reply_text(reply)


# ============================================================
#  ADMIN
# ============================================================
def admin_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Система", callback_data="adm_status"),
         InlineKeyboardButton("👥 Whitelist", callback_data="adm_wl")],
        [InlineKeyboardButton("🚫 Модерация", callback_data="adm_mod"),
         InlineKeyboardButton("📢 Рассылка", callback_data="adm_broadcast")],
        [InlineKeyboardButton("📊 Логи", callback_data="adm_logs"),
         InlineKeyboardButton("💾 Бэкап", callback_data="adm_backup")],
        [InlineKeyboardButton("🔒 Режимы", callback_data="adm_modes"),
         InlineKeyboardButton("📈 Статистика", callback_data="adm_stats")],
    ])


@owner_only
async def admin_panel(update, context):
    await update.message.reply_text(
        "🛡 <b>J.A.R.V.I.S. — Панель управления</b>\n\nВыбери раздел:",
        reply_markup=admin_kb(), parse_mode=ParseMode.HTML)


async def on_admin_callback(update, context):
    q = update.callback_query
    await q.answer()
    uid = update.effective_user.id
    if uid != OWNER_ID:
        return

    data = q.data
    if data == "adm_status":
        try:
            cpu = await asyncio.to_thread(psutil.cpu_percent, interval=0.3)
            ram = psutil.virtual_memory().percent
            dsk = psutil.disk_usage("/").percent
            up = int(time.time() - STARTED_AT)
            h, m, s = up // 3600, (up % 3600) // 60, up % 60
            txt = (
                f"📊 <b>Система</b>\n\n"
                f"  CPU  │ {cpu}%\n  RAM  │ {ram}%\n  Disk │ {dsk}%\n"
                f"  Uptime │ {h}h {m}m {s}s\n"
                f"  Upstash │ {'✅' if redis_client else '❌'}\n"
                f"  Cloudflare │ {'✅' if CF_ACCOUNT_ID else '❌'}\n"
                f"  Currents │ {'✅' if CURRENTS_KEY else '❌'}"
            )
        except Exception as e:
            txt = f"⚠️ {e}"
        await q.edit_message_text(txt, reply_markup=admin_kb(), parse_mode=ParseMode.HTML)

    elif data == "adm_wl":
        lines = ["👥 <b>Whitelist</b>", ""]
        for w in state["WHITELIST"][:30]:
            lines.append(f"  • <code>{w}</code>")
        lines.append("")
        lines.append("/add <id> | /remove <id>")
        await q.edit_message_text("\n".join(lines), reply_markup=admin_kb(), parse_mode=ParseMode.HTML)

    elif data == "adm_mod":
        txt = (
            f"🚫 <b>Модерация</b>\n\n"
            f"Забанено: {len(state['BANNED'])}\n"
            f"В муте: {len(state['MUTED'])}\n"
            f"Варнов: {sum(len(w) for w in state['WARNINGS'].values())}\n\n"
            f"/ban /unban /mute /warn /warnings /intruders /prune"
        )
        await q.edit_message_text(txt, reply_markup=admin_kb(), parse_mode=ParseMode.HTML)

    elif data == "adm_broadcast":
        await q.edit_message_text("📢 Используйте: /broadcast <текст>", reply_markup=admin_kb())

    elif data == "adm_logs":
        if os.path.exists("bot.log"):
            with open("bot.log", "r", encoding="utf-8") as f:
                tail = "".join(f.readlines()[-20:])[-3000:]
            await q.edit_message_text(f"📊 <b>Логи</b>\n\n<pre>{tail}</pre>",
                reply_markup=admin_kb(), parse_mode=ParseMode.HTML)
        else:
            await q.edit_message_text("📊 Логи пусты", reply_markup=admin_kb())

    elif data == "adm_backup":
        await q.edit_message_text("💾 Используйте: /backup", reply_markup=admin_kb())

    elif data == "adm_modes":
        txt = (
            f"🔒 <b>Режимы</b>\n\n"
            f"Silent: {'✅' if SILENT_MODE else '❌'}\n"
            f"Lockdown: {'✅' if LOCKDOWN else '❌'}\n\n"
            f"/silent on|off | /lockdown on|off"
        )
        await q.edit_message_text(txt, reply_markup=admin_kb(), parse_mode=ParseMode.HTML)

    elif data == "adm_stats":
        top = sorted(USER_STATS.items(), key=lambda kv: kv[1].get("messages", 0), reverse=True)[:10]
        lines = ["📈 <b>Топ пользователей</b>", ""]
        for u, s in top:
            lines.append(f"  <code>{u}</code> — {s.get('messages', 0)} msgs")
        await q.edit_message_text("\n".join(lines) or "📈 Пусто",
            reply_markup=admin_kb(), parse_mode=ParseMode.HTML)


@owner_only
async def add_whitelist(update, context):
    if not context.args:
        return
    try:
        uid = int(context.args[0])
    except Exception:
        return
    if uid not in state["WHITELIST"]:
        state["WHITELIST"].append(uid)
    save_state()
    await update.message.reply_text(f"✅ {uid} добавлен.")


@owner_only
async def remove_whitelist(update, context):
    if not context.args:
        return
    try:
        uid = int(context.args[0])
    except Exception:
        return
    if uid in state["WHITELIST"]:
        state["WHITELIST"].remove(uid)
    save_state()
    await update.message.reply_text(f"🗑 {uid} удалён.")


@owner_only
async def whitelist_list(update, context):
    lines = ["👥 <b>Whitelist</b>", ""]
    for w in state["WHITELIST"]:
        lines.append(f"  • <code>{w}</code>")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def ban_user(update, context):
    if update.effective_user.id != OWNER_ID:
        return
    if not context.args:
        return
    try:
        uid = int(context.args[0])
    except Exception:
        return
    if uid not in state["BANNED"]:
        state["BANNED"].append(uid)
    if uid in state["WHITELIST"]:
        state["WHITELIST"].remove(uid)
    save_state()
    await update.message.reply_text(f"🚫 {uid} бан.")


async def unban_user(update, context):
    if update.effective_user.id != OWNER_ID:
        return
    if not context.args:
        return
    try:
        uid = int(context.args[0])
    except Exception:
        return
    if uid in state["BANNED"]:
        state["BANNED"].remove(uid)
    save_state()
    await update.message.reply_text(f"✅ {uid} разбан.")


@owner_only
async def mute_user(update, context):
    if len(context.args) < 2:
        await update.message.reply_text("🔇 /mute <id> <2h|perm>")
        return
    try:
        uid = int(context.args[0])
    except Exception:
        return
    d = context.args[1]
    if d == "perm":
        exp = datetime.now() + timedelta(days=36500)
    else:
        m = re.match(r"^(\d+)([hmd])$", d.lower())
        if not m:
            return
        v, u = int(m.group(1)), m.group(2)
        delta = {"h": timedelta(hours=v), "d": timedelta(days=v), "m": timedelta(minutes=v)}[u]
        exp = datetime.now() + delta
    state["MUTED"][str(uid)] = exp.isoformat()
    save_state()
    await update.message.reply_text(f"🔇 {uid} до {exp.strftime('%H:%M')}")


@owner_only
async def warn_user(update, context):
    if len(context.args) < 2:
        return
    try:
        uid = int(context.args[0])
    except Exception:
        return
    reason = " ".join(context.args[1:])
    wl = state["WARNINGS"].setdefault(str(uid), [])
    wl.append({"reason": reason, "at": datetime.now().isoformat()})
    save_state()
    await update.message.reply_text(f"⚠️ Варн {len(wl)}/3: {uid}. {reason}")
    if len(wl) >= 3:
        if uid not in state["BANNED"]:
            state["BANNED"].append(uid)
        save_state()
        await update.message.reply_text(f"🚨 Авто-бан: {uid}")


@owner_only
async def warnings_list(update, context):
    if not context.args:
        return
    uid = str(context.args[0])
    warns = state["WARNINGS"].get(uid, [])
    if not warns:
        await update.message.reply_text("✅ Нет.")
        return
    lines = [f"⚠️ Варны {uid}:", ""]
    for i, w in enumerate(warns, 1):
        lines.append(f"  {i}. {w['at'][:16]} — {w['reason']}")
    await update.message.reply_text("\n".join(lines))


@owner_only
async def broadcast_msg(update, context):
    text = " ".join(context.args)
    if not text:
        return
    sent = failed = 0
    for u in state["WHITELIST"]:
        try:
            await context.bot.send_message(u, f"📢 <b>Broadcast</b>\n\n{html_escape(text)}", parse_mode=ParseMode.HTML)
            sent += 1
        except Exception:
            failed += 1
    await update.message.reply_text(f"📢 {sent}/{failed}")


@owner_only
async def backup_cmd(update, context):
    zip_name = "jarvis_backup.zip"
    with zipfile.ZipFile(zip_name, "w") as z:
        for f in ("main.py", "requirements.txt", "whitelist.json", "config.json"):
            if os.path.exists(f):
                z.write(f)
    await update.message.reply_document(document=open(zip_name, "rb"), filename=zip_name)
    os.remove(zip_name)


@owner_only
async def logs_cmd(update, context):
    if os.path.exists("bot.log"):
        with open("bot.log", "r", encoding="utf-8") as f:
            tail = "".join(f.readlines()[-35:])[-4000:]
        await update.message.reply_text(f"<pre>{html_escape(tail)}</pre>", parse_mode=ParseMode.HTML)


@owner_only
async def silent_cmd(update, context):
    global SILENT_MODE
    if not context.args:
        await update.message.reply_text(f"🤫 {'ON' if SILENT_MODE else 'OFF'}")
        return
    SILENT_MODE = context.args[0].lower() == "on"
    await update.message.reply_text(f"🤫 Silent {'ON' if SILENT_MODE else 'OFF'}")


@owner_only
async def lockdown_cmd(update, context):
    global LOCKDOWN
    if not context.args:
        await update.message.reply_text(f"🔒 {'ON' if LOCKDOWN else 'OFF'}")
        return
    LOCKDOWN = context.args[0].lower() == "on"
    await update.message.reply_text(f"🔒 Lockdown {'ON' if LOCKDOWN else 'OFF'}")


@owner_only
async def stats_cmd(update, context):
    top = sorted(USER_STATS.items(), key=lambda kv: kv[1].get("messages", 0), reverse=True)[:10]
    lines = ["📈 <b>Топ</b>", ""]
    for u, s in top:
        lines.append(f"  <code>{u}</code> — {s.get('messages', 0)} msgs")
    await update.message.reply_text("\n".join(lines) or "📈 Пусто", parse_mode=ParseMode.HTML)


@owner_only
async def health_cmd(update, context):
    try:
        cpu = await asyncio.to_thread(psutil.cpu_percent, interval=0.5)
        ram = psutil.virtual_memory().percent
        dsk = psutil.disk_usage("/").percent
        up = int(time.time() - STARTED_AT)
        h, m, s = up // 3600, (up % 3600) // 60, up % 60
        await update.message.reply_text(
            f"💻 <b>Health</b>\n\n  CPU │ {cpu}%\n  RAM │ {ram}%\n  Disk │ {dsk}%\n  Uptime │ {h}h {m}m {s}s",
            parse_mode=ParseMode.HTML)
    except Exception as e:
        await update.message.reply_text(f"⚠️ {e}")


async def ping_cmd(update, context):
    """Quick check that the Telegram bot process is responding."""
    started = time.perf_counter()
    message = await update.message.reply_text("🏓 Pong — checking response time…")
    elapsed_ms = (time.perf_counter() - started) * 1000
    await message.edit_text(f"🏓 Pong. Telegram response: {elapsed_ms:.0f} ms.")


@owner_only
async def model_cmd(update, context):
    candidates = ", ".join(_model_candidates())
    active = GEMINI_LAST_MODEL or ("ещё не проверялась" if LANG.get(str(update.effective_user.id), "en") == "ru" else "not tested yet")
    if LANG.get(str(update.effective_user.id), "en") == "ru":
        message = (
            f"🧠 Настройки Gemini\nОсновная модель: {GEMINI_MODEL}\n"
            f"Последняя рабочая: {active}\nКандидаты: {candidates}\n"
            f"Тайм-аут: {GEMINI_TIMEOUT_SECONDS} с"
        )
    else:
        message = (
            f"🧠 Gemini configuration\nConfigured: {GEMINI_MODEL}\n"
            f"Last successful: {active}\nFallbacks: {candidates}\n"
            f"Timeout: {GEMINI_TIMEOUT_SECONDS}s"
        )
    await update.message.reply_text(message)


@owner_only
async def diagnostics_cmd(update, context):
    """Perform a real, minimal Gemini API request and show owner-only diagnostics."""
    uid = update.effective_user.id
    ru = LANG.get(str(uid), "en") == "ru"
    await update.message.reply_text(
        "🔎 Проверяю подключение к Gemini…" if ru
        else "🔎 Running a short Gemini connection test…"
    )
    result = await call_gemini(
        "Reply with exactly: OK",
        uid,
        system_instruction="This is a connectivity test. Reply with exactly OK.",
        store_history=False,
    )
    if result and result != t(uid, "gemini_down"):
        if ru:
            message = (
                f"✅ Gemini отвечает.\nМодель: {GEMINI_LAST_MODEL or GEMINI_MODEL}\n"
                f"Последний успех: {GEMINI_LAST_OK_AT or 'только что'}\nОтвет: {result[:100]}"
            )
        else:
            message = (
                f"✅ Gemini API is responding.\nModel: {GEMINI_LAST_MODEL or GEMINI_MODEL}\n"
                f"Last success: {GEMINI_LAST_OK_AT or 'just now'}\nResponse: {result[:100]}"
            )
        await update.message.reply_text(message)
    else:
        error = GEMINI_LAST_ERROR or (
            "Подробности отсутствуют. Проверьте логи деплоя."
            if ru else "No error details were returned. Check deployment logs."
        )
        if ru:
            message = (
                f"❌ Тест Gemini не пройден.\nОсновная модель: {GEMINI_MODEL}\n"
                f"Резервные модели: {', '.join(GEMINI_FALLBACK_MODELS) or 'нет'}\n"
                f"Причина: {error[:700]}\n\n"
                "Проверьте GEMINI_API_KEY, доступ к API, квоты и логи деплоя."
            )
        else:
            message = (
                f"❌ Gemini test failed.\nConfigured model: {GEMINI_MODEL}\n"
                f"Fallbacks: {', '.join(GEMINI_FALLBACK_MODELS) or 'none'}\n"
                f"Reason: {error[:700]}\n\n"
                "Check GEMINI_API_KEY, API access/billing, and the deployment logs."
            )
        await update.message.reply_text(message)


async def report_cmd(update, context):
    uid = update.effective_user.id
    text = " ".join(context.args)
    if not text:
        await update.message.reply_text("📩 /report <issue>")
        return
    ticket = {"id": len(TICKETS) + 1, "user_id": uid, "text": text, "status": "open",
              "at": datetime.now().isoformat()}
    TICKETS.append(ticket)
    save_tickets()
    await update.message.reply_text(f"✅ Тикет #{ticket['id']}")
    try:
        await context.bot.send_message(OWNER_ID, f"📩 #{ticket['id']} от <code>{uid}</code>: {text}",
            parse_mode=ParseMode.HTML)
    except Exception:
        pass


@owner_only
async def tickets_cmd(update, context):
    opens = [x for x in TICKETS if x.get("status") == "open"]
    if not opens:
        await update.message.reply_text("📭 Нет тикетов.")
        return
    lines = ["📋 <b>Тикеты</b>", ""]
    for x in opens[:20]:
        lines.append(f"  #{x['id']} │ <code>{x['user_id']}</code> │ {x['text'][:60]}")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


@owner_only
async def close_ticket_cmd(update, context):
    if not context.args:
        return
    try:
        tid = int(context.args[0])
    except Exception:
        return
    for x in TICKETS:
        if x["id"] == tid:
            x["status"] = "closed"
            save_tickets()
            await update.message.reply_text(f"✅ Тикет {tid} закрыт.")
            return


@owner_only
async def intruders_cmd(update, context):
    if not os.path.exists(INTRUDER_FILE):
        await update.message.reply_text("📭 Пусто.")
        return
    with open(INTRUDER_FILE) as f:
        try:
            data = json.load(f)
        except Exception:
            data = []
    if not data:
        await update.message.reply_text("📭 Пусто.")
        return
    lines = ["🚨 <b>Нарушители</b>", ""]
    seen = set()
    for x in data[-30:]:
        u = x.get("user_id")
        if u in seen:
            continue
        seen.add(u)
        lines.append(f"  <code>{u}</code> @{x.get('username', '—')}")
    await update.message.reply_text("\n".join(lines[:30]), parse_mode=ParseMode.HTML)


@owner_only
async def prune_cmd(update, context):
    if not context.args:
        await update.message.reply_text("🪓 /prune 30d")
        return
    m = re.match(r"^(\d+)([dh])$", context.args[0].lower())
    if not m:
        return
    v, u = int(m.group(1)), m.group(2)
    delta = timedelta(hours=v) if u == "h" else timedelta(days=v)
    thr = datetime.now() - delta
    removed = 0
    for suid, s in list(USER_STATS.items()):
        last = s.get("last_seen")
        if last and datetime.fromisoformat(last) < thr:
            try:
                state["WHITELIST"].remove(int(suid))
                removed += 1
            except Exception:
                pass
    save_state()
    await update.message.reply_text(f"🪓 Удалено: {removed}")


@owner_only
async def export_whitelist_cmd(update, context):
    _write_json("whitelist_export.json",
        {"whitelist": state["WHITELIST"], "exported_at": datetime.now().isoformat()})
    await update.message.reply_document(document=open("whitelist_export.json", "rb"))
    os.remove("whitelist_export.json")


@owner_only
async def clear_session_cmd(update, context):
    USER_HISTORY.clear()
    USER_MODES.clear()
    USER_VIBES.clear()
    INCOGNITO.clear()
    LAST_REQUEST.clear()
    if redis_client:
        try:
            keys = redis_client.keys("jarvis:hist:*")
            for k in keys or []:
                redis_client.delete(k)
        except Exception:
            pass
    await update.message.reply_text("🧹 Сессия очищена.")


@owner_only
async def stopwords_cmd(update, context):
    if not context.args:
        await update.message.reply_text("🛑 " + ", ".join(STOP_WORDS))
        return
    action = context.args[0].lower()
    if action == "add" and len(context.args) > 1:
        STOP_WORDS.append(" ".join(context.args[1:]))
        await update.message.reply_text("✅")
    elif action == "remove" and len(context.args) > 1:
        w = " ".join(context.args[1:])
        if w in STOP_WORDS:
            STOP_WORDS.remove(w)
        await update.message.reply_text("🗑")


# ============================================================
#  SECURITY MIDDLEWARE
# ============================================================
async def middleware(update, context):
    if not update.effective_user or not update.message:
        return
    uid = update.effective_user.id
    if LOCKDOWN and uid != OWNER_ID:
        raise ApplicationHandlerStop
    if SILENT_MODE and uid != OWNER_ID:
        raise ApplicationHandlerStop
    if str(uid) in state["MUTED"]:
        if datetime.now() > datetime.fromisoformat(state["MUTED"][str(uid)]):
            state["MUTED"].pop(str(uid), None)
            save_state()
        else:
            raise ApplicationHandlerStop
    if uid in state["BANNED"]:
        raise ApplicationHandlerStop

    now = time.time()
    bucket = [x for x in FLOOD_WINDOW.get(uid, []) if now - x < 60]
    bucket.append(now)
    FLOOD_WINDOW[uid] = bucket
    if len(bucket) > 15 and uid != OWNER_ID:
        state["MUTED"][str(uid)] = (datetime.now() + timedelta(minutes=5)).isoformat()
        save_state()
        raise ApplicationHandlerStop

    if uid != OWNER_ID and uid not in state["WHITELIST"]:
        entry = {"user_id": uid, "username": update.effective_user.username,
                 "first_name": update.effective_user.first_name,
                 "timestamp": datetime.now().isoformat()}
        logs = []
        if os.path.exists(INTRUDER_FILE):
            try:
                with open(INTRUDER_FILE) as f:
                    logs = json.load(f)
            except Exception:
                pass
        logs.append(entry)
        _write_json(INTRUDER_FILE, logs)
        try:
            await context.bot.send_message(OWNER_ID,
                f"🚨 <b>ДОСТУП</b>\n<code>{uid}</code> @{entry['username']}",
                parse_mode=ParseMode.HTML)
        except Exception:
            pass
        raise ApplicationHandlerStop


# ============================================================
#  MAIN
# ============================================================
async def post_init(app):
    await app.bot.delete_webhook(drop_pending_updates=True)
    logger.info("J.A.R.V.I.S. Online. Boss: Silent.")


def run_flask():
    a = Flask(__name__)
    @a.route("/")
    @a.route("/health")
    def h():
        return "J.A.R.V.I.S. alive", 200
    a.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), debug=False, use_reloader=False)


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(TypeHandler(Update, middleware), group=-1)
    app.add_handler(CallbackQueryHandler(on_lang_callback, pattern=r"^lang_(ru|en)$"))
    app.add_handler(CallbackQueryHandler(on_admin_callback, pattern=r"^adm_"))

    for cmd, fn in [
        ("start", start), ("help", help_cmd), ("reset", reset_cmd),
        ("lang", lang_cmd), ("mode", mode_cmd), ("vibe", vibe_cmd), ("id", id_cmd),
        ("ping", ping_cmd), ("model", model_cmd), ("diagnostics", diagnostics_cmd),
        ("incognito", incognito_cmd), ("incognito_off", incognito_off_cmd),
    ]:
        app.add_handler(CommandHandler(cmd, fn))

    for cmd, fn in [
        ("draw", draw_cmd), ("qr", qr_cmd), ("tts", tts_cmd),
        ("news", news_cmd), ("meme", meme_cmd), ("search", search_cmd),
        ("wiki", wiki_cmd), ("translate", translate_cmd), ("weather", weather_cmd),
        ("poll", poll_cmd), ("quiz", quiz_cmd), ("speed", speed_cmd),
        ("screenshot", screenshot_cmd), ("summarize", summarize_cmd),
    ]:
        app.add_handler(CommandHandler(cmd, fn))

    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    app.add_handler(MessageHandler(filters.Sticker.ALL, sticker_handler))
    app.add_handler(MessageHandler(filters.VOICE, voice_handler))
    app.add_handler(MessageHandler(filters.VIDEO | filters.VIDEO_NOTE, video_handler))
    app.add_handler(MessageHandler(filters.ANIMATION, animation_handler))
    app.add_handler(MessageHandler(filters.Document.ALL, document_handler))

    for cmd, fn in [
        ("review", review_cmd), ("regex", regex_cmd), ("sql", sql_cmd),
        ("explain", explain_cmd), ("refactor", refactor_cmd), ("uml", uml_cmd),
        ("pytest", pytest_cmd), ("doc", doc_cmd), ("cv", cv_cmd),
        ("translate_long", translate_long_cmd), ("ask", ask_cmd),
    ]:
        app.add_handler(CommandHandler(cmd, fn))

    for cmd, fn in [
        ("improve", improve_cmd), ("fix", fix_cmd), ("shorten", shorten_cmd),
        ("expand", expand_cmd), ("keywords", keywords_cmd), ("theses", theses_cmd),
        ("style", style_cmd), ("tone", tone_cmd),
    ]:
        app.add_handler(CommandHandler(cmd, fn))

    for cmd, fn in [
        ("upscale", upscale_cmd), ("compress", compress_cmd), ("sticker", sticker_cmd),
        ("ocr", ocr_cmd), ("colors", colors_cmd), ("exif", exif_cmd),
    ]:
        app.add_handler(CommandHandler(cmd, fn))

    for cmd, fn in [
        ("diary", diary_cmd), ("secret", secret_cmd), ("task", task_cmd),
        ("habit", habit_cmd), ("money", money_cmd),
    ]:
        app.add_handler(CommandHandler(cmd, fn))

    for cmd, fn in [
        ("diff", diff_cmd), ("commit", commit_cmd), ("dockerfile", dockerfile_cmd),
        ("gitignore", gitignore_cmd), ("json", json_cmd), ("b64", b64_cmd),
        ("hash", hash_cmd), ("cron", cron_cmd),
    ]:
        app.add_handler(CommandHandler(cmd, fn))

    for cmd, fn in [
        ("admin", admin_panel), ("add", add_whitelist), ("remove", remove_whitelist),
        ("whitelist", whitelist_list), ("ban", ban_user), ("unban", unban_user),
        ("mute", mute_user), ("warn", warn_user), ("warnings", warnings_list),
        ("broadcast", broadcast_msg), ("backup", backup_cmd), ("logs", logs_cmd),
        ("silent", silent_cmd), ("lockdown", lockdown_cmd),
        ("stats", stats_cmd), ("health", health_cmd),
        ("report", report_cmd), ("tickets", tickets_cmd), ("close_ticket", close_ticket_cmd),
        ("intruders", intruders_cmd), ("prune", prune_cmd),
        ("export_whitelist", export_whitelist_cmd), ("clear_session", clear_session_cmd),
        ("stopwords", stopwords_cmd),
    ]:
        app.add_handler(CommandHandler(cmd, fn))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    logger.info("Polling...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    main()