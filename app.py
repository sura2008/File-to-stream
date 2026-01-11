# app.py (FULL UPDATED VERSION WITH POLLING)

import os
import asyncio
import secrets
import traceback
import uvicorn
import re
import logging
import math
import requests  # Required for polling

from contextlib import asynccontextmanager
from pyrogram import Client, filters, enums
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, ChatMemberUpdated
from pyrogram.errors import FloodWait, UserNotParticipant
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from pyrogram.file_id import FileId
from pyrogram import raw
from pyrogram.session import Session, Auth

from config import Config
from database import db

# =====================================================================================
# --- BACKGROUND POLLING SERVICE (THE NEW FEATURE) ---
# =====================================================================================

async def poll_huggingface_queue():
    """
    Runs in the background. Checks HF Worker for messages every 30s.
    """
    if not Config.HF_WORKER_URL:
        print("⚠️ HF_WORKER_URL not set. Background polling disabled.")
        return

    # ✅ Endpoints derived from your Config
    POLL_URL = f"{Config.HF_WORKER_URL}/botmessages"
    DONE_URL = f"{Config.HF_WORKER_URL}/donebotmessages"

    print("🔄 Started Background Polling Service (Interval: 30s)...")

    while True:
        try:
            # 1. Check for Pending Messages
            # We run requests in a thread to avoid blocking the streaming server
            response = await asyncio.to_thread(requests.get, POLL_URL, timeout=10)

            if response.status_code == 200:
                data = response.json()
                messages = data.get("messages", [])

                if messages:
                    print(f"📬 Found {len(messages)} pending messages!")
                    sent_ids = []

                    for msg in messages:
                        try:
                            # 2. Send Message via Telegram
                            await bot.send_message(
                                chat_id=msg['chat_id'], 
                                text=msg['text'], 
                                parse_mode=enums.ParseMode.HTML
                            )
                            sent_ids.append(msg['id'])
                            await asyncio.sleep(0.5) # Anti-flood delay
                        except Exception as e:
                            print(f"❌ Failed to send to {msg.get('chat_id')}: {e}")

                    # 3. Confirm Delivery to Hugging Face (Delete from Queue)
                    if sent_ids:
                        payload = {"message_ids": sent_ids}
                        await asyncio.to_thread(requests.post, DONE_URL, json=payload, timeout=10)
                        print(f"✅ Confirmed {len(sent_ids)} messages sent.")
            
            else:
                # If HF is sleeping or erroring, just print briefly
                pass

        except Exception as e:
            print(f"⚠️ Polling Error: {e}")

        # 4. Wait 30 Seconds before next check
        await asyncio.sleep(30)

# =====================================================================================
# --- SETUP: BOT, WEB SERVER & LIFESPAN ---
# =====================================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Starts Database, Bot, and Background Poller."""
    print("--- Lifespan: Server starting... ---")
    await db.connect()
    
    try:
        print("Starting main Pyrogram bot...")
        await bot.start()
        
        me = await bot.get_me()
        Config.BOT_USERNAME = me.username
        print(f"✅ Main Bot [@{Config.BOT_USERNAME}] started successfully.")

        # Multi-Client Setup
        multi_clients[0] = bot
        work_loads[0] = 0
        await initialize_clients()
        
        # --- START THE POLLER HERE ---
        asyncio.create_task(poll_huggingface_queue())
        
        # --- SAFE CHANNEL CHECK ---
        print(f"Verifying storage channel ({Config.STORAGE_CHANNEL})...")
        try:
            await bot.get_chat(Config.STORAGE_CHANNEL)
            print("✅ Storage channel accessible.")
        except Exception as e:
            print(f"!!! WARNING: Bot cannot access Storage Channel yet: {e}")

        if Config.FORCE_SUB_CHANNEL:
            try:
                await bot.get_chat(Config.FORCE_SUB_CHANNEL)
            except Exception:
                print("!!! WARNING: Bot is not admin in Force Sub Channel.")

    except Exception:
        print(f"!!! FATAL ERROR during startup: {traceback.format_exc()}")
    
    yield
    
    print("--- Lifespan: Server shutting down... ---")
    if bot.is_initialized:
        await bot.stop()
    await db.disconnect()

app = FastAPI(lifespan=lifespan)
templates = Jinja2Templates(directory="templates")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class HideDLFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "GET /dl/" not in record.getMessage()

logging.getLogger("uvicorn.access").addFilter(HideDLFilter())

bot = Client(
    "SimpleStreamBot", 
    api_id=Config.API_ID, 
    api_hash=Config.API_HASH, 
    bot_token=Config.BOT_TOKEN, 
    in_memory=True
)

multi_clients = {}
work_loads = {}
class_cache = {}

# =====================================================================================
# --- MULTI-CLIENT LOGIC ---
# =====================================================================================

class TokenParser:
    @staticmethod
    def parse_from_env():
        return {c + 1: t for c, (_, t) in enumerate(filter(lambda n: n[0].startswith("MULTI_TOKEN"), sorted(os.environ.items())))}

async def start_client(client_id, bot_token):
    try:
        client = await Client(name=str(client_id), api_id=Config.API_ID, api_hash=Config.API_HASH, bot_token=bot_token, no_updates=True, in_memory=True).start()
        work_loads[client_id] = 0
        multi_clients[client_id] = client
        print(f"✅ Client {client_id} started.")
    except Exception as e:
        print(f"Failed to start Client {client_id}: {e}")

async def initialize_clients():
    tokens = TokenParser.parse_from_env()
    if tokens:
        print(f"Found {len(tokens)} extra clients. Starting...")
        await asyncio.gather(*[start_client(i, t) for i, t in tokens.items()])

# =====================================================================================
# --- HELPER FUNCTIONS ---
# =====================================================================================

def get_readable_file_size(size_in_bytes):
    if not size_in_bytes: return '0B'
    power = 1024
    n = 0
    power_labels = {0: 'B', 1: 'KB', 2: 'MB', 3: 'GB'}
    while size_in_bytes >= power and n < len(power_labels) - 1:
        size_in_bytes /= power
        n += 1
    return f"{size_in_bytes:.2f} {power_labels[n]}"

def mask_filename(name: str):
    if not name: return "Protected File"
    base, ext = os.path.splitext(name)
    return f"{base[:10]}...{ext}"

# =====================================================================================
# --- BOT HANDLERS (COMMANDS & UPLOADS) ---
# =====================================================================================

@bot.on_message(filters.command("start") & filters.private)
async def start_command(client: Client, message: Message):
    if len(message.command) > 1 and message.command[1].startswith("verify_"):
        unique_id = message.command[1].split("_", 1)[1]
        
        if Config.FORCE_SUB_CHANNEL:
            try:
                await client.get_chat_member(Config.FORCE_SUB_CHANNEL, message.from_user.id)
            except UserNotParticipant:
                link = f"https://t.me/{str(Config.FORCE_SUB_CHANNEL).replace('@', '')}"
                btn = [[InlineKeyboardButton("📢 Join Channel", url=link)], 
                       [InlineKeyboardButton("✅ Try Again", url=f"https://t.me/{Config.BOT_USERNAME}?start={message.command[1]}")]]
                await message.reply_text("You must join our channel first!", reply_markup=InlineKeyboardMarkup(btn), quote=True)
                return

        final_link = f"{Config.BASE_URL}/show/{unique_id}"
        await message.reply_text(
            f"✅ **Link Generated!**\n\n🔗 `{final_link}`", 
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Open Link", url=final_link)]]),
            quote=True
        )
    else:
        await message.reply_text("👋 **Welcome!** Send me a file and I will generate a stream link for it.")

@bot.on_message(filters.private & (filters.document | filters.video | filters.audio))
async def handle_file_upload(client: Client, message: Message):
    try:
        sent_message = await message.copy(chat_id=Config.STORAGE_CHANNEL)
        unique_id = secrets.token_urlsafe(8)
        await db.save_link(unique_id, sent_message.id)
        
        verify_link = f"https://t.me/{Config.BOT_USERNAME}?start=verify_{unique_id}"
        
        buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton("🚀 Get Stream Link", url=verify_link)],
            [InlineKeyboardButton("🏛 Upload to Internet Archive", callback_data=f"ia_upload_{sent_message.id}")]
        ])
        
        await message.reply_text("__✅ File Uploaded! Choose an option:__", reply_markup=buttons, quote=True)
    except Exception as e:
        print(f"Upload Error: {e}")
        await message.reply_text(f"❌ Error saving file: {e}")

# =====================================================================================
# --- HUGGING FACE HANDOFF HANDLER ---
# =====================================================================================

@bot.on_callback_query(filters.regex(r"^ia_upload_"))
async def ia_upload_handler(client, callback_query):
    if not Config.HF_WORKER_URL:
        await callback_query.answer("❌ Error: HF_WORKER_URL not set in Render settings.", show_alert=True)
        return

    try:
        message_id = int(callback_query.data.split("_")[2])
        user_msg = callback_query.message.reply_to_message
        
        if not user_msg:
            await callback_query.answer("❌ Error: Original file message not found.", show_alert=True)
            return

        media = user_msg.document or user_msg.video or user_msg.audio
        if not media:
            await callback_query.answer("❌ Error: No media found.", show_alert=True)
            return

        file_name = media.file_name or "video.mp4"
        safe_file_name = "".join(c for c in file_name if c.isalnum() or c in (' ', '.', '_', '-')).rstrip()
        
        stream_link = f"{Config.BASE_URL}/dl/{message_id}/{safe_file_name}"
        
        payload = {
            "stream_link": stream_link,
            "file_name": file_name,
            "chat_id": user_msg.chat.id,
            "message_id": user_msg.id
        }

        await callback_query.edit_message_text(
            f"🚀 **Connecting to Archive Worker...**\n\n"
            f"📡 **Endpoint:** `{stream_link}`\n"
            f"⏳ Sending request to Hugging Face..."
        )
        
        # We send the upload request to HF
        # IMPORTANT: This is just the TRIGGER. The actual notification will come via the Polling Service later.
        response = await asyncio.to_thread(requests.post, f"{Config.HF_WORKER_URL}/upload", json=payload, timeout=5)
        
        if response.status_code == 200:
            await callback_query.edit_message_text(
                "✅ **Task Accepted!**\n\n"
                "The worker has started downloading.\n"
                "__You will receive a notification when the permanent link is ready.__"
            )
        else:
            await callback_query.edit_message_text(f"❌ Worker Rejected: {response.text}")

    except Exception as e:
        print(f"Handoff Error: {e}")
        await callback_query.edit_message_text(f"❌ Failed to connect to worker: {e}")

# =====================================================================================
# --- WEB SERVER (STREAMING ENGINE) ---
# =====================================================================================

@app.get("/")
async def health():
    return {"status": "ok", "message": "Render Bot is awake."}

@app.get("/show/{unique_id}", response_class=HTMLResponse)
async def show_page(request: Request, unique_id: str):
    storage_msg_id = await db.get_link(unique_id)
    if not storage_msg_id: raise HTTPException(404, "Link Expired")
    
    try:
        msg = await multi_clients[0].get_messages(Config.STORAGE_CHANNEL, storage_msg_id)
        media = msg.document or msg.video or msg.audio
        if not media: raise Exception
    except:
        pass
        
    file_name = "Secure File"
    file_size = "Unknown"
    is_media = False
    
    try:
         if 'media' in locals() and media:
            file_name = media.file_name or "file"
            file_size = get_readable_file_size(media.file_size)
            is_media = (media.mime_type or "").startswith(("video", "audio"))
    except: pass

    safe_name = "".join(c for c in file_name if c.isalnum() or c in (' ', '.', '_', '-')).rstrip()
    
    context = {
        "request": request,
        "file_name": file_name,
        "file_size": file_size,
        "is_media": is_media,
        "direct_dl_link": f"{Config.BASE_URL}/dl/{storage_msg_id}/{safe_name}",
    }
    return templates.TemplateResponse("show.html", context)

@app.get("/api/file/{unique_id}", response_class=JSONResponse)
async def get_file_details_api(request: Request, unique_id: str):
    message_id = await db.get_link(unique_id)
    if not message_id:
        raise HTTPException(status_code=404, detail="Link expired or invalid.")
    
    main_bot = multi_clients.get(0)
    if not main_bot:
        raise HTTPException(status_code=503, detail="Bot is not ready.")
    
    try:
        message = await main_bot.get_messages(Config.STORAGE_CHANNEL, message_id)
        media = message.document or message.video or message.audio
        if not media: raise Exception
    except Exception:
        raise HTTPException(status_code=404, detail="File not found on Telegram.")

    file_name = media.file_name or "file"
    safe_file_name = "".join(c for c in file_name if c.isalnum() or c in (' ', '.', '_', '-')).rstrip()
    mime_type = media.mime_type or "application/octet-stream"
    
    response_data = {
        "file_name": mask_filename(file_name),
        "file_size": get_readable_file_size(media.file_size),
        "is_media": mime_type.startswith(("video", "audio")),
        "direct_dl_link": f"{Config.BASE_URL}/dl/{message_id}/{safe_file_name}",
        "mx_player_link": f"intent:{Config.BASE_URL}/dl/{message_id}/{safe_file_name}#Intent;action=android.intent.action.VIEW;type={mime_type};end",
        "vlc_player_link": f"intent:{Config.BASE_URL}/dl/{message_id}/{safe_file_name}#Intent;action=android.intent.action.VIEW;type={mime_type};package=org.videolan.vlc;end"
    }
    return response_data

class ByteStreamer:
    def __init__(self, client: Client):
        self.client = client

    async def yield_file(self, file_id: FileId, index, offset, first_part_cut, last_part_cut, part_count, chunk_size):
        client = self.client
        work_loads[index] += 1
        
        media_session = client.media_sessions.get(file_id.dc_id)
        if media_session is None:
            if file_id.dc_id != await client.storage.dc_id():
                auth_key = await Auth(client, file_id.dc_id, await client.storage.test_mode()).create()
                media_session = Session(client, file_id.dc_id, auth_key, await client.storage.test_mode(), is_media=True)
                await media_session.start()
                exported_auth = await client.invoke(raw.functions.auth.ExportAuthorization(dc_id=file_id.dc_id))
                await media_session.invoke(raw.functions.auth.ImportAuthorization(id=exported_auth.id, bytes=exported_auth.bytes))
            else:
                media_session = client.session
            client.media_sessions[file_id.dc_id] = media_session
        
        location = raw.types.InputDocumentFileLocation(
            id=file_id.media_id, access_hash=file_id.access_hash,
            file_reference=file_id.file_reference, thumb_size=file_id.thumbnail_size
        )
        
        current_part = 1
        try:
            while current_part <= part_count:
                r = await media_session.invoke(
                    raw.functions.upload.GetFile(location=location, offset=offset, limit=chunk_size), retries=0
                )
                if isinstance(r, raw.types.upload.File):
                    chunk = r.bytes
                    if not chunk: break
                    if part_count == 1: yield chunk[first_part_cut:last_part_cut]
                    elif current_part == 1: yield chunk[first_part_cut:]
                    elif current_part == part_count: yield chunk[:last_part_cut]
                    else: yield chunk
                    current_part += 1
                    offset += chunk_size
                else: break
        finally:
            work_loads[index] -= 1

@app.get("/dl/{mid}/{fname}")
async def stream_media(request: Request, mid: int, fname: str):
    try:
        index = min(work_loads, key=work_loads.get, default=0)
        client = multi_clients[index]
        
        streamer = class_cache.get(client) or ByteStreamer(client)
        class_cache[client] = streamer
        
        msg = await client.get_messages(Config.STORAGE_CHANNEL, mid)
        media = msg.document or msg.video or msg.audio
        if not media: raise FileNotFoundError

        file_id = FileId.decode(media.file_id)
        file_size = media.file_size
        
        range_header = request.headers.get("Range", 0)
        from_bytes, until_bytes = 0, file_size - 1
        
        if range_header:
            s = range_header.replace("bytes=", "").split("-")
            from_bytes = int(s[0])
            if s[1]: until_bytes = int(s[1])
            
        req_length = until_bytes - from_bytes + 1
        chunk_size = 1024 * 1024 # 1MB
        offset = (from_bytes // chunk_size) * chunk_size
        first_part_cut = from_bytes - offset
        last_part_cut = (until_bytes % chunk_size) + 1
        part_count = math.ceil(req_length / chunk_size)
        
        body = streamer.yield_file(file_id, index, offset, first_part_cut, last_part_cut, part_count, chunk_size)
        
        headers = {
            "Content-Type": media.mime_type or "application/octet-stream",
            "Content-Disposition": f'inline; filename="{media.file_name}"',
            "Content-Length": str(req_length),
            "Accept-Ranges": "bytes"
        }
        status_code = 206 if range_header else 200
        if range_header:
            headers["Content-Range"] = f"bytes {from_bytes}-{until_bytes}/{file_size}"
            
        return StreamingResponse(body, status_code=status_code, headers=headers)
        
    except Exception as e:
        print(f"Stream Error: {e}")
        raise HTTPException(404, "File not found or Stream failed.")

if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), log_level="info")
                
