"""
J.A.R.V.I.S. Core System - Main Executable
Phase 1: AI Core (15 functions)
Phase 2: Media & Generation (15 functions)
Phase 3: Administration & Moderation (15 functions)
Phase 4: Advanced AI Intellect (15 functions)
Phase 5: Special Protocols & Resilience (15 functions)
Framework: python-telegram-bot v21 (async)
"""

import os
import json
import logging
import zipfile
import re
import time
import io
import urllib.parse
import asyncio
import secrets
import base64
import hashlib
import psutil
import subprocess
from datetime import datetime, timedelta, timezone

from telegram import (
    Update, ReplyKeyboardMarkup, KeyboardButton, Poll, InlineKeyboardMarkup, InlineKeyboardButton
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters, ContextTypes, TypeHandler, ApplicationHandlerStop, Application
)
from telegram.constants import ChatMemberStatus, ParseMode, ChatAction

from google import genai
from google.genai import types
import qrcode
from pyzbar.pyzbar import decode
from gtts import gTTS
from PIL import Image
import requests
from pydub import AudioSegment
from pypdf import PdfReader
import docx

# ==============================================================================
# LOGGING & CONFIG
# ==============================================================================
logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[logging.FileHandler("bot.log", encoding='utf-8'), logging.StreamHandler()]
)
logger = logging.getLogger("JARVIS")

CONFIG_FILE = 'config.json'
DATA_FILE = 'whitelist.json'
INTRUDER_FILE = 'intruder_telemetry.json'
STATS_FILE = 'usage_stats.json'
TICKETS_FILE = 'tickets.json'

BOT_TOKEN = os.environ.get("BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
ENV_OWNER_ID = int(os.environ.get("OWNER_ID", "0"))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is required.")
if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY is required.")
if not ENV_OWNER_ID:
    raise RuntimeError("OWNER_ID is required.")

OWNER_ID = ENV_OWNER_ID
STARTED_AT = time.time()

if not os.path.exists(CONFIG_FILE):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump({"OWNER_ID": OWNER_ID, "MODEL": GEMINI_MODEL}, f, indent=4)

with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
    config = json.load(f)

# ==============================================================================
# GLOBAL STATE
# ==============================================================================
USER_HISTORY = {}
USER_MODES = {}
INCOGNITO_USERS = set()
LAST_REQUEST = {}
USER_STATS = {}
STOP_WORDS = ["spam", "scam", "free money", "click here now"]
FLOOD_WINDOW = {}
TICKETS = []
TICKETS_LOCK = asyncio.Lock()

state = {
    "WHITELIST": [],
    "WHITELIST_EXPIRY": {},
    "BANNED": [],
    "BANNED_TIMED": {},
    "MUTED": {},
    "WARNINGS": {}
}

if os.path.exists(DATA_FILE):
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            state.update(json.load(f))
    except Exception as e:
        logger.error(f"Could not load {DATA_FILE}: {e}")

if os.path.exists(STATS_FILE):
    try:
        with open(STATS_FILE, 'r', encoding='utf-8') as f:
            USER_STATS = json.load(f)
    except Exception:
        USER_STATS = {}

if os.path.exists(TICKETS_FILE):
    try:
        with open(TICKETS_FILE, 'r', encoding='utf-8') as f:
            TICKETS = json.load(f)
    except Exception:
        TICKETS = []

# ==============================================================================
# UTILS
# ==============================================================================
def _atomic_write_json(path: str, data) -> None:
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
    logger.info(f"MODERATION: [{action}] by {actor} on {target}. Reason: {reason}")

def parse_duration(duration_str: str):
    if duration_str.lower() == 'perm':
        return "perm"
    match = re.match(r"^(\d+)([smhd])$", duration_str.lower())
    if not match:
        return None
    val, unit = int(match.group(1)), match.group(2)
    if unit == 's': return timedelta(seconds=val)
    if unit == 'm': return timedelta(minutes=val)
    if unit == 'h': return timedelta(hours=val)
    if unit == 'd': return timedelta(days=val)
    return None

def track_usage(uid: int):
    s = USER_STATS.get(str(uid), {"messages": 0, "commands": 0, "last_seen": None})
    s["messages"] = s.get("messages", 0) + 1
    s["last_seen"] = datetime.now().isoformat()
    USER_STATS[str(uid)] = s

def track_command(uid: int, cmd: str):
    s = USER_STATS.get(str(uid), {"messages": 0, "commands": 0, "last_seen": None})
    s["commands"] = s.get("commands", 0) + 1
    s["last_seen"] = datetime.now().isoformat()
    USER_STATS[str(uid)] = s

def owner_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if update.effective_user.id != OWNER_ID:
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

async def check_group_permissions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    chat = update.effective_chat
    if chat.type not in ['group', 'supergroup']:
        return True
    try:
        bot_member = await context.bot.get_chat_member(chat.id, context.bot.id)
        if bot_member.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
            await update.message.reply_text("Sir, I don't have admin rights in this group.")
            return False
        if update.effective_user.id == OWNER_ID:
            return True
        user_member = await context.bot.get_chat_member(chat.id, update.effective_user.id)
        if user_member.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
            await update.message.reply_text("Access denied. Group admin rights required.")
            return False
        return True
    except Exception as e:
        logger.error(f"Permissions error: {e}")
        return False

# ==============================================================================
# PHASE 1: AI CORE
# ==============================================================================
ai_client = None
try:
    ai_client = genai.Client(api_key=GEMINI_API_KEY)
    logger.info("AI Matrix initialized.")
except Exception as e:
    logger.error(f"Failed to initialize Gemini: {e}")

SYSTEM_PROMPTS = {
    "assistant": "You are J.A.R.V.I.S., a highly intelligent, polite, and efficient AI assistant. Keep responses clear and structured.",
    "tutor": "You are a patient and knowledgeable English tutor. Correct mistakes, explain grammar, give examples. Reply in Russian for explanations, English for examples.",
    "programmer": "You are a senior software engineer. Provide optimized, secure code with brief explanations. Focus on best practices.",
    "psychologist": "You are an empathetic, non-judgmental active listener. Offer supportive and grounded insights. Never diagnose."
}

async def call_gemini(prompt_text, user_id, system_instruction=None, media_parts=None, json_mode=False):
    if not ai_client:
        return "⚠️ Neural matrix temporarily unavailable."
    try:
        mode = USER_MODES.get(user_id, "assistant")
        sys_inst = system_instruction or SYSTEM_PROMPTS.get(mode, SYSTEM_PROMPTS["assistant"])

        contents = []
        if user_id not in INCOGNITO_USERS and user_id in USER_HISTORY:
            for msg in USER_HISTORY[user_id]:
                contents.append(
                    types.Content(
                        role=msg["role"],
                        parts=[types.Part.from_text(text=msg["parts"][0]["text"])]
                    )
                )

        parts = []
        if media_parts:
            parts.extend(media_parts)
        parts.append(types.Part.from_text(text=prompt_text))
        contents.append(types.Content(role="user", parts=parts))

        config_kwargs = {"system_instruction": sys_inst}
        if json_mode:
            config_kwargs["response_mime_type"] = "application/json"

        gen_config = types.GenerateContentConfig(**config_kwargs)

        response = ai_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=contents,
            config=gen_config
        )

        res_text = response.text if response.text else "⚠️ Processing returned empty result."

        if user_id not in INCOGNITO_USERS and not media_parts and not json_mode:
            if user_id not in USER_HISTORY:
                USER_HISTORY[user_id] = []
            USER_HISTORY[user_id].append({"role": "user", "parts": [{"text": prompt_text}]})
            USER_HISTORY[user_id].append({"role": "model", "parts": [{"text": res_text}]})

            if len(USER_HISTORY[user_id]) > 20:
                try:
                    summary_prompt = "Summarize this conversation preserving all key facts, names, code links, decisions. Output as a compact paragraph."
                    summary_contents = contents.copy()
                    summary_contents.append(types.Content(role="user", parts=[types.Part.from_text(text=summary_prompt)]))
                    summary_resp = ai_client.models.generate_content(
                        model=GEMINI_MODEL,
                        contents=summary_contents
                    )
                    USER_HISTORY[user_id] = [
                        {"role": "user", "parts": [{"text": "Previous context summary."}]},
                        {"role": "model", "parts": [{"text": summary_resp.text}]}
                    ]
                except Exception:
                    USER_HISTORY[user_id] = USER_HISTORY[user_id][-10:]
        return res_text
    except Exception as e:
        logger.exception(f"Gemini API Error for UID {user_id}: {e}")
        # PHASE 5: Fallback to Pollinations text API for owner
        if user_id == OWNER_ID:
            try:
                url = f"https://text.pollinations.ai/{urllib.parse.quote(prompt_text[:500])}"
                r = requests.get(url, timeout=30)
                if r.status_code == 200 and r.text.strip():
                    return r.text.strip()
            except Exception as fe:
                logger.exception(f"Fallback API error: {fe}")
        return "⚠️ Neural matrix temporarily unavailable."

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    track_command(uid, "/start")
    if uid == OWNER_ID:
        await update.message.reply_text("J.A.R.V.I.S. at your service, Sir. Systems nominal. Type /help for full command list.")
    else:
        await update.message.reply_text("J.A.R.V.I.S. Online. Ready for interaction.")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🤖 *J.A.R.V.I.S. — Full Command List*\n\n"
        "*Phase 1 — Core:*\n"
        "/start /help /reset /mode /incognito /incognito_off\n\n"
        "*Phase 2 — Media:*\n"
        "/draw /qr /tts /poll /quiz /speed /screenshot /translate /summarize\n\n"
        "*Phase 3 — Admin (owner):*\n"
        "/admin /add /remove /whitelist /ban /unban /mute /warn /warnings\n"
        "/broadcast /send /backup /logs /export_logs\n\n"
        "*Phase 4 — AI Pro:*\n"
        "/review /regex /sql /explain /refactor /uml /pytest /doc /cv\n"
        "/translate_long /ask\n\n"
        "*Phase 5 — Protocols:*\n"
        "/export_whitelist /clear_session /report /tickets /close_ticket /stats /health /stopwords\n\n"
        "📄 Just send text, images, docs, voice or stickers to interact."
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

async def reset_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    track_command(update.effective_user.id, "/reset")
    USER_HISTORY.pop(update.effective_user.id, None)
    await update.message.reply_text("Memory cleared. Context reset.")

async def mode_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    track_command(update.effective_user.id, "/mode")
    if not context.args:
        cur = USER_MODES.get(update.effective_user.id, "assistant")
        await update.message.reply_text(f"Current: {cur}\nAvailable: {', '.join(SYSTEM_PROMPTS)}")
        return
    mode = context.args[0].lower()
    if mode in SYSTEM_PROMPTS:
        USER_MODES[update.effective_user.id] = mode
        USER_HISTORY.pop(update.effective_user.id, None)
        await update.message.reply_text(f"Mode switched to: {mode}.")
    else:
        await update.message.reply_text("Unknown mode. Use /help.")

async def incognito_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    INCOGNITO_USERS.add(update.effective_user.id)
    await update.message.reply_text("Incognito mode ON. History not saved.")

async def incognito_off_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    INCOGNITO_USERS.discard(update.effective_user.id)
    await update.message.reply_text("Incognito mode OFF. History saving restored.")

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    track_usage(uid)
    now = time.time()

    if uid in LAST_REQUEST and now - LAST_REQUEST[uid] < 2.0:
        await update.message.reply_text("Slow down, Sir.")
        return
    LAST_REQUEST[uid] = now

    msg_text = update.message.text
    for w in STOP_WORDS:
        if w.lower() in msg_text.lower() and uid != OWNER_ID:
            try:
                await context.bot.send_message(OWNER_ID, f"⚠️ Stop-word triggered by {uid} (@{update.effective_user.username}): {msg_text[:200]}")
            except Exception:
                pass

    if update.message.reply_to_message and update.message.reply_to_message.text:
        msg_text = f"[Replying to: {update.message.reply_to_message.text}]\n\n{msg_text}"

    logger.info(f"MSG by {uid} (@{update.effective_user.username}): {msg_text[:50]}")

    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    status_msg = await update.message.reply_text("🧠 Processing...")

    try:
        reply = await call_gemini(msg_text, uid)
        try:
            await status_msg.edit_text(reply, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            try:
                await status_msg.edit_text(reply)
            except Exception:
                await update.message.reply_text(reply[:4000])
    except Exception as e:
        logger.exception(f"Text handler error: {e}")
        await status_msg.edit_text("⚠️ Request processing error.")

# ==============================================================================
# PHASE 2: MEDIA
# ==============================================================================
async def draw_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    track_command(update.effective_user.id, "/draw")
    if not context.args:
        await update.message.reply_text("Format: /draw <description>")
        return
    desc = " ".join(context.args)
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_PHOTO)
    status_msg = await update.message.reply_text("🎨 Drawing...")
    try:
        ai_prompt = "Convert this into a detailed English image-generation prompt. Add composition, lighting, style, atmosphere, camera details. Return ONLY the prompt: " + desc
        enhanced_prompt = await call_gemini(ai_prompt, update.effective_user.id, system_instruction="You output only prompts.")
        encoded = urllib.parse.quote(enhanced_prompt.strip())
        url = f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&nologo=true"
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        if len(resp.content) > 10 * 1024 * 1024:
            raise ValueError("File too large.")
        img = Image.open(io.BytesIO(resp.content)).convert("RGB")
        img.thumbnail((1280, 1280))
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=85)
        out.seek(0)
        await update.message.reply_photo(photo=out)
        await status_msg.delete()
    except Exception as e:
        logger.exception(f"Draw error: {e}")
        await status_msg.edit_text("⚠️ Graphics subsystem failure.")

async def qr_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    track_command(update.effective_user.id, "/qr")
    text = " ".join(context.args)
    if not text or len(text) > 1000:
        await update.message.reply_text("Text must be 1-1000 chars.")
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
        await update.message.reply_text("⚠️ Generation failure.")

async def tts_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    track_command(update.effective_user.id, "/tts")
    text = " ".join(context.args)
    if not text or len(text) > 500:
        await update.message.reply_text("Text must be 1-500 chars.")
        return
    try:
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.RECORD_VOICE)
        out = io.BytesIO()
        gTTS(text=text, lang='ru').write_to_fp(out)
        out.seek(0)
        await update.message.reply_voice(voice=out)
    except Exception as e:
        logger.exception(f"TTS error: {e}")
        await update.message.reply_text("⚠️ Speech synthesis error.")

async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    track_usage(update.effective_user.id)
    try:
        photo_file = await update.message.photo[-1].get_file()
        file_bytes = await photo_file.download_as_bytearray()
        try:
            img = Image.open(io.BytesIO(file_bytes))
            decoded = decode(img)
            if decoded:
                texts = "\n".join([d.data.decode("utf-8") for d in decoded])
                await update.message.reply_text(f"🔳 QR decoded:\n{texts}")
                return
        except Exception:
            pass
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
        caption = update.message.caption or "Describe this image in detail."
        part = types.Part.from_bytes(data=bytes(file_bytes), mime_type="image/jpeg")
        reply = await call_gemini(caption, update.effective_user.id, media_parts=[part])
        await update.message.reply_text(reply)
    except Exception as e:
        logger.exception(f"Photo handler error: {e}")
        await update.message.reply_text("⚠️ Image analysis error.")

async def sticker_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.message.sticker.is_animated or update.message.sticker.is_video:
            return
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
        file = await update.message.sticker.get_file()
        byte_arr = await file.download_as_bytearray()
        img = Image.open(io.BytesIO(byte_arr)).convert("RGBA")
        out = io.BytesIO()
        img.save(out, format="PNG")
        part = types.Part.from_bytes(data=out.getvalue(), mime_type="image/png")
        reply = await call_gemini("Explain this sticker's meme context.", update.effective_user.id, media_parts=[part])
        await update.message.reply_text(reply)
    except Exception as e:
        logger.exception(f"Sticker handler error: {e}")
        await update.message.reply_text("⚠️ Sticker analysis error.")

async def voice_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    track_usage(update.effective_user.id)
    try:
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
        file = await update.message.voice.get_file()
        byte_arr = await file.download_as_bytearray()
        part = types.Part.from_bytes(data=bytes(byte_arr), mime_type="audio/ogg")
        reply = await call_gemini(
            "Transcribe this audio and add a short insightful reaction or answer.",
            update.effective_user.id,
            media_parts=[part]
        )
        await update.message.reply_text(f"🎙 Transcription and response:\n\n{reply}")
    except Exception as e:
        logger.exception(f"Voice handler error: {e}")
        await update.message.reply_text("⚠️ Audio processing error.")

async def document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        doc = update.message.document
        if doc.file_size > 10 * 1024 * 1024:
            await update.message.reply_text("⚠️ File too large (max 10 MB).")
            return
        ext = os.path.splitext(doc.file_name)[1].lower()
        if ext not in ['.txt', '.pdf', '.docx']:
            return
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
        file = await doc.get_file()
        byte_arr = await file.download_as_bytearray()
        extracted_text = ""
        if ext == '.txt':
            extracted_text = byte_arr.decode('utf-8', errors='ignore')
        elif ext == '.pdf':
            reader = PdfReader(io.BytesIO(byte_arr))
            extracted_text = "".join([page.extract_text() for page in reader.pages if page.extract_text()])
        elif ext == '.docx':
            docx_file = docx.Document(io.BytesIO(byte_arr))
            extracted_text = "\n".join([p.text for p in docx_file.paragraphs])
        extracted_text = extracted_text[:30000]
        if not extracted_text.strip():
            await update.message.reply_text("Could not extract text.")
            return
        reply = await call_gemini(f"Summarize this document:\n\n{extracted_text}", update.effective_user.id)
        await update.message.reply_text(reply)
    except Exception as e:
        logger.exception(f"Doc handler error: {e}")
        await update.message.reply_text("⚠️ Document analysis error.")

async def poll_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args)
    parts = [p.strip() for p in text.split("|") if p.strip()]
    if len(parts) < 3 or len(parts) > 11:
        await update.message.reply_text("Format: /poll Q | Opt1 | Opt2 ... (2-10 options)")
        return
    try:
        await context.bot.send_poll(update.effective_chat.id, question=parts[0], options=parts[1:])
    except Exception as e:
        logger.exception(f"Poll error: {e}")

async def quiz_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    topic = " ".join(context.args) or "Random General Knowledge"
    try:
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
        prompt = f"Generate a multiple choice quiz about {topic}. Return strict JSON: {{\"question\": \"...\", \"options\": [\"A\", \"B\", \"C\", \"D\"], \"correct_id\": 0, \"explanation\": \"...\"}}. correct_id is 0-3."
        reply = await call_gemini(prompt, update.effective_user.id, json_mode=True, system_instruction="Output strictly valid JSON.")
        def extract_json(text):
            start = text.find('{')
            end = text.rfind('}')
            if start != -1 and end != -1:
                return text[start:end+1]
            return text
        clean_json = extract_json(reply)
        try:
            data = json.loads(clean_json)
        except json.JSONDecodeError:
            retry_prompt = prompt + " Return ONLY a valid JSON object. No markdown."
            reply = await call_gemini(retry_prompt, update.effective_user.id, json_mode=True, system_instruction="Output strictly valid JSON.")
            clean_json = extract_json(reply)
            data = json.loads(clean_json)
        await context.bot.send_poll(
            update.effective_chat.id,
            question=data["question"],
            options=data["options"],
            type=Poll.QUIZ,
            correct_option_id=data["correct_id"],
            explanation=data.get("explanation")
        )
    except Exception as e:
        logger.exception(f"Quiz error: {e}")
        await update.message.reply_text("⚠️ Quiz generation error.")

async def speed_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message or not update.message.reply_to_message.voice:
        await update.message.reply_text("Reply to a voice message.")
        return
    if not context.args: return
    try:
        factor = float(context.args[0])
        if factor <= 1.0 or factor > 4.0:
            await update.message.reply_text("Factor must be between 1.1 and 4.")
            return
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.RECORD_VOICE)
        file = await update.message.reply_to_message.voice.get_file()
        byte_arr = await file.download_as_bytearray()
        audio = AudioSegment.from_file(io.BytesIO(byte_arr), format="ogg")
        fast_audio = audio._spawn(audio.raw_data, overrides={"frame_rate": int(audio.frame_rate * factor)}).set_frame_rate(audio.frame_rate)
        out = io.BytesIO()
        fast_audio.export(out, format="ogg", codec="libopus")
        out.seek(0)
        await update.message.reply_voice(voice=out)
    except Exception as e:
        logger.exception(f"Speed error: {e}")
        await update.message.reply_text("⚠️ Audio processing error.")

async def screenshot_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args: return
    url = context.args[0]
    if not url.startswith("http"): url = "https://" + url
    try:
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_PHOTO)
        resp = requests.get(f"https://image.thum.io/get/width/1200/crop/900/{url}", timeout=30)
        resp.raise_for_status()
        await update.message.reply_photo(photo=io.BytesIO(resp.content))
    except Exception as e:
        logger.exception(f"Screenshot error: {e}")
        await update.message.reply_text("⚠️ Screenshot error.")

async def translate_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2: return
    lang = context.args[0]
    text = " ".join(context.args[1:])
    try:
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
        reply = await call_gemini(f"Translate this to {lang}:\n\n{text}", update.effective_user.id, system_instruction="Return ONLY the translation.")
        await update.message.reply_text(reply)
    except Exception as e:
        logger.exception(f"Translate error: {e}")

async def summarize_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = ""
    if update.message.reply_to_message and update.message.reply_to_message.text:
        text = update.message.reply_to_message.text
    elif context.args:
        text = " ".join(context.args)
    if not text: return
    try:
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
        reply = await call_gemini(f"Summarize the following text clearly:\n\n{text}", update.effective_user.id)
        await update.message.reply_text(reply)
    except Exception as e:
        logger.exception(f"Summarize error: {e}")

# ==============================================================================
# PHASE 3: ADMIN
# ==============================================================================
async def _do_ban(context: ContextTypes.DEFAULT_TYPE, uid: int, reason: str, actor_id: int):
    if uid not in state["BANNED"]: state["BANNED"].append(uid)
    if uid in state["WHITELIST"]: state["WHITELIST"].remove(uid)
    save_state()
    log_mod_action(actor_id, uid, "BAN", reason)
    try:
        await context.bot.send_message(OWNER_ID, f"🚨 Ban applied to {uid}. Reason: {reason}")
    except Exception:
        pass

@owner_only
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [KeyboardButton("👥 Whitelist"), KeyboardButton("🚫 Bans")],
        [KeyboardButton("📊 Logs"), KeyboardButton("📢 Broadcast")],
        [KeyboardButton("💾 Backup"), KeyboardButton("ℹ️ Status")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("Admin panel activated, Sir.", reply_markup=reply_markup)

@owner_only
async def admin_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "👥 Whitelist":
        await whitelist_list(update, context)
    elif text == "🚫 Bans":
        bans = ", ".join(map(str, state["BANNED"])) or "Empty"
        await update.message.reply_text(f"Banned IDs: {bans}")
    elif text == "📊 Logs":
        await logs_cmd(update, context)
    elif text == "📢 Broadcast":
        await update.message.reply_text("Use: /broadcast <text>")
    elif text == "💾 Backup":
        await backup_cmd(update, context)
    elif text == "ℹ️ Status":
        await health_cmd(update, context)

@owner_only
async def add_whitelist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 1:
        await update.message.reply_text("Format: /add <user_id> [duration|perm]")
        return
    uid = int(context.args[0])
    if uid not in state["WHITELIST"]:
        state["WHITELIST"].append(uid)
    msg = f"User {uid} added to whitelist."
    if len(context.args) >= 2:
        duration = parse_duration(context.args[1])
        if duration == "perm":
            msg += " Expires: Never"
        elif duration:
            expiry = (datetime.now() + duration).isoformat()
            state["WHITELIST_EXPIRY"][str(uid)] = expiry
            msg += f" Expires: {expiry}"
    save_state()
    log_mod_action(OWNER_ID, uid, "ADD_WHITELIST", "Manual addition")
    await update.message.reply_text(msg)

@owner_only
async def remove_whitelist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args: return
    uid = int(context.args[0])
    if uid in state["WHITELIST"]:
        state["WHITELIST"].remove(uid)
    state["WHITELIST_EXPIRY"].pop(str(uid), None)
    save_state()
    await update.message.reply_text(f"Access revoked for ID {uid}.")

@owner_only
async def whitelist_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = ["Authorized users:"]
    for uid in state["WHITELIST"]:
        expiry = state["WHITELIST_EXPIRY"].get(str(uid), "Never")
        lines.append(f"• ID: {uid} | Until: {expiry}")
    await update.message.reply_text("\n".join(lines) if len(lines) > 1 else "Whitelist empty.")

async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == 'private' and update.effective_user.id != OWNER_ID: return
    if not await check_group_permissions(update, context): return
    if not context.args: return
    uid = int(context.args[0])
    reason_args = context.args[1:]
    duration = None
    if reason_args:
        parsed = parse_duration(reason_args[0])
        if parsed:
            duration = parsed
            reason_args = reason_args[1:]
    reason = " ".join(reason_args) or "No reason"
    await _do_ban(context, uid, reason, update.effective_user.id)
    if duration and duration != "perm":
        expiry = (datetime.now() + duration).isoformat()
        state["BANNED_TIMED"][str(uid)] = expiry
        save_state()
    elif str(uid) in state["BANNED_TIMED"]:
        del state["BANNED_TIMED"][str(uid)]
        save_state()
    if update.effective_chat.type in ['group', 'supergroup']:
        try:
            await context.bot.ban_chat_member(update.effective_chat.id, uid)
        except Exception as e:
            logger.error(f"Ban chat error: {e}")
    time_str = "forever" if not duration or duration == "perm" else f"for {duration}"
    await update.message.reply_text(f"Isolation protocol applied to {uid} ({time_str}). Reason: {reason}")

async def unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == 'private' and update.effective_user.id != OWNER_ID: return
    if not await check_group_permissions(update, context): return
    if not context.args: return
    uid = int(context.args[0])
    if uid in state["BANNED"]: state["BANNED"].remove(uid)
    state["BANNED_TIMED"].pop(str(uid), None)
    save_state()
    if update.effective_chat.type in ['group', 'supergroup']:
        try:
            await context.bot.unban_chat_member(update.effective_chat.id, uid)
        except Exception:
            pass
    await update.message.reply_text(f"Ban lifted from {uid}.")

async def mute_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == 'private' and update.effective_user.id != OWNER_ID: return
    if not await check_group_permissions(update, context): return
    if len(context.args) < 2:
        await update.message.reply_text("Format: /mute <user_id> <duration|perm>")
        return
    uid = int(context.args[0])
    duration = parse_duration(context.args[1])
    if not duration: return
    if duration == "perm":
        expiry = datetime.now() + timedelta(days=36500)
    else:
        expiry = datetime.now() + duration
    state["MUTED"][str(uid)] = expiry.isoformat()
    save_state()
    log_mod_action(update.effective_user.id, uid, "MUTE", context.args[1])
    await update.message.reply_text(f"User {uid} muted until {expiry.strftime('%Y-%m-%d %H:%M')}.")

async def warn_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == 'private' and update.effective_user.id != OWNER_ID: return
    if not await check_group_permissions(update, context): return
    if len(context.args) < 2: return
    uid_str = str(context.args[0])
    uid = int(uid_str)
    reason = " ".join(context.args[1:])
    if uid_str not in state["WARNINGS"]: state["WARNINGS"][uid_str] = []
    state["WARNINGS"][uid_str].append({
        "reason": reason,
        "by": update.effective_user.id,
        "at": datetime.now().isoformat()
    })
    save_state()
    warn_count = len(state["WARNINGS"][uid_str])
    await update.message.reply_text(f"Warning {warn_count}/3 to user {uid}. Reason: {reason}")
    log_mod_action(update.effective_user.id, uid, "WARN", reason)
    if warn_count >= 3:
        await _do_ban(context, uid, "Auto-ban: 3 warnings", update.effective_user.id)
        if update.effective_chat.type in ['group', 'supergroup']:
            try: await context.bot.ban_chat_member(update.effective_chat.id, uid)
            except Exception: pass
        await update.message.reply_text(f"🚨 Auto-ban applied to {uid}.")

async def warnings_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == 'private' and update.effective_user.id != OWNER_ID: return
    if not await check_group_permissions(update, context): return
    if not context.args: return
    uid = str(context.args[0])
    warns = state["WARNINGS"].get(uid, [])
    if not warns:
        await update.message.reply_text("No warnings.")
        return
    lines = [f"Warnings for {uid}:"]
    for i, w in enumerate(warns, 1):
        lines.append(f"{i}. {w['at'][:16]} | By: {w['by']} | {w['reason']}")
    await update.message.reply_text("\n".join(lines))

@owner_only
async def broadcast_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args)
    if not text: return
    sent, failed = 0, 0
    for uid in state["WHITELIST"]:
        try:
            await context.bot.send_message(uid, f"📢 System message:\n\n{text}")
            sent += 1
        except Exception:
            failed += 1
    await update.message.reply_text(f"Delivery report: Sent {sent}, Failed {failed}.")

@owner_only
async def send_direct(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2: return
    uid = int(context.args[0])
    text = " ".join(context.args[1:])
    try:
        await context.bot.send_message(uid, text)
        await update.message.reply_text("Message delivered, Sir.")
    except Exception as e:
        await update.message.reply_text(f"Delivery error: {e}")

@owner_only
async def backup_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    zip_name = 'jarvis_backup.zip'
    with zipfile.ZipFile(zip_name, 'w') as zipf:
        for fname in ['main.py', 'requirements.txt', 'whitelist.json', 'config.json', 'tickets.json', 'usage_stats.json']:
            if os.path.exists(fname):
                zipf.write(fname)
    await update.message.reply_document(document=open(zip_name, 'rb'), filename=zip_name)
    os.remove(zip_name)

@owner_only
async def logs_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not os.path.exists("bot.log"): return
    with open("bot.log", "r", encoding="utf-8") as f:
        lines = f.readlines()[-100:]
    log_text = "".join(lines[-35:])
    if len(log_text) > 4000: log_text = log_text[-4000:]
    await update.message.reply_text(f"Recent system events:\n<pre>{log_text}</pre>", parse_mode=ParseMode.HTML)

@owner_only
async def export_logs_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if os.path.exists("bot.log"):
        await update.message.reply_document(document=open("bot.log", "rb"))

# ==============================================================================
# PHASE 4: ADVANCED AI
# ==============================================================================
async def _ai_command(update: Update, context: ContextTypes.DEFAULT_TYPE, instruction: str, need_reply: bool = False):
    text = ""
    if need_reply:
        r = update.message.reply_to_message
        if not r or not (r.text or r.caption):
            await update.message.reply_text("Reply to a message with code/text first.")
            return
        text = r.text or r.caption
    else:
        text = " ".join(context.args)
    if not text and not need_reply:
        await update.message.reply_text("Provide arguments. Example: /regex email addresses")
        return
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    status = await update.message.reply_text("🧠 Processing...")
    try:
        reply = await call_gemini(f"{instruction}\n\nINPUT:\n{text}", update.effective_user.id)
        try:
            await status.edit_text(reply[:4000], parse_mode=ParseMode.MARKDOWN)
        except Exception:
            await status.edit_text(reply[:4000])
        if len(reply) > 4000:
            for i in range(4000, len(reply), 4000):
                await update.message.reply_text(reply[i:i+4000])
    except Exception as e:
        logger.exception(f"AI command error: {e}")
        await status.edit_text("⚠️ Processing error.")

async def review_cmd(update, context):
    await _ai_command(update, context, "Review this code. List bugs, security issues, style problems. Suggest fixes with examples. Use Markdown.", need_reply=True)

async def regex_cmd(update, context):
    await _ai_command(update, context, "Generate a regex pattern for the described task. Return ONLY the pattern and one test example.")

async def sql_cmd(update, context):
    await _ai_command(update, context, "Write a SQL query for the described task. Add a one-line explanation.")

async def explain_cmd(update, context):
    await _ai_command(update, context, "Explain this code line by line in Russian. Be concise.", need_reply=True)

async def refactor_cmd(update, context):
    await _ai_command(update, context, "Refactor this code for readability and performance. Return the optimized version and a change list.", need_reply=True)

async def uml_cmd(update, context):
    await _ai_command(update, context, "Return a PlantUML text diagram for the described or given code.", need_reply=False)

async def pytest_cmd(update, context):
    await _ai_command(update, context, "Generate a complete pytest file with test cases for this code. Return only Python code.", need_reply=True)

async def doc_cmd(update, context):
    await _ai_command(update, context, "Return this code with PEP-8 docstrings and inline comments added. Preserve logic.", need_reply=True)

async def cv_cmd(update, context):
    await _ai_command(update, context, "Structure the following raw bio into a professional Markdown CV with sections: Summary, Experience, Skills, Education.")

async def translate_long_cmd(update, context):
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /translate_long <lang> <text>")
        return
    lang = context.args[0]
    text = " ".join(context.args[1:])
    if len(text) < 100:
        text = (update.message.reply_to_message.text if update.message.reply_to_message else text)
    await _ai_command(update, context, f"Translate the following into {lang}. Preserve formatting.")

async def ask_cmd(update, context):
    if not update.message.reply_to_message or not update.message.reply_to_message.text:
        await update.message.reply_text("Reply to a document/text with /ask <question>.")
        return
    question = " ".join(context.args)
    doc_text = update.message.reply_to_message.text[:30000]
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    status = await update.message.reply_text("🧠 Analyzing document...")
    try:
        reply = await call_gemini(f"Answer this question based ONLY on the document.\n\nDocument:\n{doc_text}\n\nQuestion: {question}", update.effective_user.id)
        await status.edit_text(reply[:4000])
    except Exception as e:
        logger.exception(f"Ask error: {e}")
        await status.edit_text("⚠️ Error.")

# ==============================================================================
# PHASE 5: SPECIAL PROTOCOLS
# ==============================================================================
@owner_only
async def export_whitelist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = {
        "whitelist": state["WHITELIST"],
        "expiry": state["WHITELIST_EXPIRY"],
        "exported_at": datetime.now().isoformat()
    }
    _atomic_write_json("whitelist_export.json", data)
    await update.message.reply_document(document=open("whitelist_export.json", "rb"))
    os.remove("whitelist_export.json")

@owner_only
async def clear_session_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    USER_HISTORY.clear()
    USER_MODES.clear()
    INCOGNITO_USERS.clear()
    LAST_REQUEST.clear()
    await update.message.reply_text("Session memory purged. Whitelist and mods preserved.")

async def report_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args)
    if not text:
        await update.message.reply_text("Usage: /report <your issue>")
        return
    t = {
        "id": len(TICKETS) + 1,
        "user_id": update.effective_user.id,
        "username": update.effective_user.username,
        "text": text,
        "status": "open",
        "at": datetime.now().isoformat()
    }
    TICKETS.append(t)
    save_tickets()
    await update.message.reply_text(f"Ticket #{t['id']} created.")
    try:
        await context.bot.send_message(OWNER_ID, f"📩 New ticket #{t['id']} from {update.effective_user.id}: {text}")
    except Exception:
        pass

@owner_only
async def tickets_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    open_t = [t for t in TICKETS if t.get("status") == "open"]
    if not open_t:
        await update.message.reply_text("No open tickets.")
        return
    lines = ["📋 Open tickets:"]
    for t in open_t[:20]:
        lines.append(f"#{t['id']} | {t['user_id']} | {t['text'][:80]}")
    await update.message.reply_text("\n".join(lines))

@owner_only
async def close_ticket_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args: return
    tid = int(context.args[0])
    for t in TICKETS:
        if t["id"] == tid:
            t["status"] = "closed"
            save_tickets()
            await update.message.reply_text(f"Ticket #{tid} closed.")
            return
    await update.message.reply_text("Ticket not found.")

@owner_only
async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    top = sorted(USER_STATS.items(), key=lambda x: x[1].get("messages", 0), reverse=True)[:10]
    lines = ["📊 Top users by messages:"]
    for uid, s in top:
        lines.append(f"• {uid}: {s.get('messages', 0)} msgs, {s.get('commands', 0)} cmds")
    await update.message.reply_text("\n".join(lines))

@owner_only
async def health_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        cpu = psutil.cpu_percent(interval=0.5)
        ram = psutil.virtual_memory().percent
        disk = psutil.disk_usage("/").percent
        uptime = int(time.time() - STARTED_AT)
        h, m, s = uptime // 3600, (uptime % 3600) // 60, uptime % 60
        await update.message.reply_text(
            f"💻 Health:\nCPU: {cpu}%\nRAM: {ram}%\nDisk: {disk}%\nUptime: {h}h {m}m {s}s"
        )
    except Exception as e:
        logger.exception(f"Health error: {e}")
        await update.message.reply_text("Health check failed.")

@owner_only
async def stopwords_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Stop-words: " + ", ".join(STOP_WORDS))
        return
    action = context.args[0].lower()
    if action == "add" and len(context.args) > 1:
        STOP_WORDS.append(" ".join(context.args[1:]))
        await update.message.reply_text("Stop-word added.")
    elif action == "remove" and len(context.args) > 1:
        w = " ".join(context.args[1:])
        if w in STOP_WORDS: STOP_WORDS.remove(w)
        await update.message.reply_text("Removed (if existed).")

# ==============================================================================
# SECURITY MIDDLEWARE + BACKGROUND JOBS
# ==============================================================================
async def cleanup_expired_job(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now()
    changed = False
    for uid_str in [u for u, e in list(state["WHITELIST_EXPIRY"].items()) if now > datetime.fromisoformat(e)]:
        uid = int(uid_str)
        if uid in state["WHITELIST"]: state["WHITELIST"].remove(uid)
        del state["WHITELIST_EXPIRY"][uid_str]
        changed = True
    for uid_str in [u for u, e in list(state.get("BANNED_TIMED", {}).items()) if now > datetime.fromisoformat(e)]:
        uid = int(uid_str)
        if uid in state["BANNED"]: state["BANNED"].remove(uid)
        del state["BANNED_TIMED"][uid_str]
        changed = True
    for uid_str in [u for u, e in list(state["MUTED"].items()) if now > datetime.fromisoformat(e)]:
        del state["MUTED"][uid_str]
        changed = True
    if changed:
        save_state()

async def auto_backup_job(context: ContextTypes.DEFAULT_TYPE):
    try:
        zip_name = f"auto_backup_{datetime.now().strftime('%Y%m%d_%H%M')}.zip"
        with zipfile.ZipFile(zip_name, 'w') as zipf:
            for fname in ['main.py', 'requirements.txt', 'whitelist.json', 'config.json']:
                if os.path.exists(fname):
                    zipf.write(fname)
        await context.bot.send_document(OWNER_ID, document=open(zip_name, 'rb'), filename=zip_name)
        os.remove(zip_name)
    except Exception as e:
        logger.exception(f"Auto-backup error: {e}")

async def global_security_middleware(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.message:
        return
    uid = update.effective_user.id
    str_uid = str(uid)
    now = datetime.now()

    if str_uid in state["MUTED"]:
        mute_dt = datetime.fromisoformat(state["MUTED"][str_uid])
        if now > mute_dt:
            del state["MUTED"][str_uid]
            save_state()
        else:
            raise ApplicationHandlerStop

    if uid in state["BANNED"]:
        raise ApplicationHandlerStop

    # Flood protection
    now_ts = time.time()
    bucket = FLOOD_WINDOW.get(uid, [])
    bucket = [t for t in bucket if now_ts - t < 60]
    bucket.append(now_ts)
    FLOOD_WINDOW[uid] = bucket
    if len(bucket) > 10 and uid != OWNER_ID:
        try:
            await context.bot.send_message(OWNER_ID, f"🌊 Flood detected from {uid}. Auto-mute 5m.")
        except Exception:
            pass
        state["MUTED"][str_uid] = (datetime.now() + timedelta(minutes=5)).isoformat()
        save_state()
        raise ApplicationHandlerStop

    if uid != OWNER_ID and uid not in state["WHITELIST"]:
        intruder_data = {
            "first_name": update.effective_user.first_name,
            "last_name": update.effective_user.last_name,
            "user_id": uid,
            "username": update.effective_user.username,
            "chat_id": update.effective_chat.id,
            "timestamp": now.isoformat(),
            "text_preview": update.message.text[:100] if update.message.text else "[Media/Other]"
        }
        intruder_logs = []
        if os.path.exists(INTRUDER_FILE):
            try:
                with open(INTRUDER_FILE, 'r', encoding='utf-8') as f:
                    intruder_logs = json.load(f)
            except json.JSONDecodeError:
                pass
        intruder_logs.append(intruder_data)
        _atomic_write_json(INTRUDER_FILE, intruder_logs)
        alert = (
            f"🚨 <b>UNAUTHORIZED ACCESS</b> 🚨\n"
            f"ID: <code>{uid}</code>\n"
            f"User: @{intruder_data['username']} ({intruder_data['first_name']})\n"
            f"Chat: {intruder_data['chat_id']}\n"
            f"Query: {intruder_data['text_preview']}"
        )
        try:
            await context.bot.send_message(OWNER_ID, alert, parse_mode=ParseMode.HTML)
        except Exception:
            pass
        raise ApplicationHandlerStop

# ==============================================================================
# MAIN
# ==============================================================================
async def post_init(application: Application):
    await application.bot.delete_webhook(drop_pending_updates=True)
    logger.info("Webhooks cleared. J.A.R.V.I.S. Systems Online.")

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(TypeHandler(Update, global_security_middleware), group=-1)
    app.job_queue.run_repeating(cleanup_expired_job, interval=60)
    # Weekly auto-backup: every Monday 03:00 (interval in seconds = 7*24*3600)
    app.job_queue.run_repeating(auto_backup_job, interval=7*24*3600, first=10)

    # Phase 1
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("reset", reset_cmd))
    app.add_handler(CommandHandler("mode", mode_cmd))
    app.add_handler(CommandHandler("incognito", incognito_cmd))
    app.add_handler(CommandHandler("incognito_off", incognito_off_cmd))

    # Phase 2
    app.add_handler(CommandHandler("draw", draw_cmd))
    app.add_handler(CommandHandler("qr", qr_cmd))
    app.add_handler(CommandHandler("tts", tts_cmd))
    app.add_handler(CommandHandler("poll", poll_cmd))
    app.add_handler(CommandHandler("quiz", quiz_cmd))
    app.add_handler(CommandHandler("speed", speed_cmd))
    app.add_handler(CommandHandler("screenshot", screenshot_cmd))
    app.add_handler(CommandHandler("translate", translate_cmd))
    app.add_handler(CommandHandler("summarize", summarize_cmd))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    app.add_handler(MessageHandler(filters.Sticker.ALL, sticker_handler))
    app.add_handler(MessageHandler(filters.VOICE, voice_handler))
    app.add_handler(MessageHandler(filters.Document.ALL, document_handler))

    # Phase 3
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("add", add_whitelist))
    app.add_handler(CommandHandler("remove", remove_whitelist))
    app.add_handler(CommandHandler("whitelist", whitelist_list))
    app.add_handler(CommandHandler("ban", ban_user))
    app.add_handler(CommandHandler("unban", unban_user))
    app.add_handler(CommandHandler("mute", mute_user))
    app.add_handler(CommandHandler("warn", warn_user))
    app.add_handler(CommandHandler("warnings", warnings_list))
    app.add_handler(CommandHandler("broadcast", broadcast_msg))
    app.add_handler(CommandHandler("send", send_direct))
    app.add_handler(CommandHandler("backup", backup_cmd))
    app.add_handler(CommandHandler("logs", logs_cmd))
    app.add_handler(CommandHandler("export_logs", export_logs_cmd))
    app.add_handler(MessageHandler(filters.Regex(r"^(👥 Whitelist|🚫 Bans|📊 Logs|📢 Broadcast|💾 Backup|ℹ️ Status)$"), admin_buttons))

    # Phase 4
    app.add_handler(CommandHandler("review", review_cmd))
    app.add_handler(CommandHandler("regex", regex_cmd))
    app.add_handler(CommandHandler("sql", sql_cmd))
    app.add_handler(CommandHandler("explain", explain_cmd))
    app.add_handler(CommandHandler("refactor", refactor_cmd))
    app.add_handler(CommandHandler("uml", uml_cmd))
    app.add_handler(CommandHandler("pytest", pytest_cmd))
    app.add_handler(CommandHandler("doc", doc_cmd))
    app.add_handler(CommandHandler("cv", cv_cmd))
    app.add_handler(CommandHandler("translate_long", translate_long_cmd))
    app.add_handler(CommandHandler("ask", ask_cmd))

    # Phase 5
    app.add_handler(CommandHandler("export_whitelist", export_whitelist_cmd))
    app.add_handler(CommandHandler("clear_session", clear_session_cmd))
    app.add_handler(CommandHandler("report", report_cmd))
    app.add_handler(CommandHandler("tickets", tickets_cmd))
    app.add_handler(CommandHandler("close_ticket", close_ticket_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("health", health_cmd))
    app.add_handler(CommandHandler("stopwords", stopwords_cmd))

    # Fallback text
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    logger.info("Starting polling...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()