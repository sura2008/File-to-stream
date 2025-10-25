# app.py (FINAL, CLEAN, AND EASY-TO-READ CODE)

import os
import asyncio
import secrets
import traceback
import uvicorn
from contextlib import asynccontextmanager

from pyrogram import Client, filters, enums
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, ChatMemberUpdated
from pyrogram.errors import FloodWait, UserNotParticipant
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pyrogram.file_id import FileId
from pyrogram import raw
from pyrogram.session import Session, Auth
import math

# Project ki dusri files se important cheezein import karo
from config import Config
from database import db

# =====================================================================================
# --- SETUP: BOT AUR WEB SERVER KO TAIYAAR KARNA ---
# =====================================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Yeh function bot ko web server ke saath start aur stop karta hai.
    """
    print("--- Lifespan event: STARTUP ---")
    
    # 1. Database se connect karo
    await db.connect()
    
    try:
        # 2. Pyrogram bot ko background mein start karo
        print("Starting Pyrogram client in background...")
        await bot.start()
        
        # Bot ka username Config mein save karo taaki deep links kaam karein
        me = await bot.get_me()
        Config.BOT_USERNAME = me.username
        print(f"Bot [@{Config.BOT_USERNAME}] started successfully.")
        
        # 3. Storage channel ko check karo
        print(f"Verifying channel access for {Config.STORAGE_CHANNEL}...")
        await bot.get_chat(Config.STORAGE_CHANNEL)
        print("✅ Storage channel is accessible.")

        # 4. Force sub channel ko check karo (agar set hai toh)
        if Config.FORCE_SUB_CHANNEL:
            try:
                print(f"Verifying channel access for {Config.FORCE_SUB_CHANNEL}...")
                await bot.get_chat(Config.FORCE_SUB_CHANNEL)
                print("✅ Force Sub channel is accessible.")
            except Exception as e:
                print(f"!!! WARNING: Bot is not an admin in FORCE_SUB_CHANNEL. Force Sub will not work. Error: {e}")
        
        # 5. Agar channel mein koi anjaan member hai, toh use hatao
        try:
            await cleanup_channel(bot)
        except Exception as e:
            print(f"Warning: Initial channel cleanup failed, but continuing startup. Error: {e}")

        # 6. Multi-client setup (abhi ke liye sirf main bot)
        multi_clients[0] = bot
        work_loads[0] = 0
        
        print("--- Lifespan startup complete. Bot is running in the background. ---")
    
    except Exception as e:
        print(f"!!! FATAL ERROR during bot startup in lifespan: {traceback.format_exc()}")
    
    yield  # Ab web server requests lena shuru karega
    
    # Server band hone par yeh code chalega
    print("--- Lifespan event: SHUTDOWN ---")
    if bot.is_initialized:
        await bot.stop()
    print("--- Lifespan shutdown complete ---")

# FastAPI app ko lifespan ke saath initialize karo
app = FastAPI(lifespan=lifespan)
templates = Jinja2Templates(directory="templates")

# Pyrogram bot ko initialize karo
bot = Client("SimpleStreamBot", api_id=Config.API_ID, api_hash=Config.API_HASH, bot_token=Config.BOT_TOKEN, in_memory=True)

# Global Dictionaries
multi_clients = {}
work_loads = {}
class_cache = {}

# =====================================================================================
# --- HELPER FUNCTIONS: Chote-mote kaam karne wale functions ---
# =====================================================================================

def get_readable_file_size(size_in_bytes):
    """File size ko KB, MB, GB mein convert karta hai."""
    if not size_in_bytes:
        return '0B'
    
    power = 1024
    n = 0
    power_labels = {0: 'B', 1: 'KB', 2: 'MB', 3: 'GB'}
    
    while size_in_bytes >= power and n < len(power_labels) - 1:
        size_in_bytes /= power
        n += 1
        
    return f"{size_in_bytes:.2f} {power_labels[n]}"

def mask_filename(name: str):
    """File ka naam thoda chupa deta hai."""
    if not name:
        return "Protected File"
    
    resolutions = ["2160p", "1080p", "720p", "480p", "360p"]
    res_part = ""
    
    for res in resolutions:
        if res in name:
            res_part = f" {res}"
            name = name.replace(res, "")
            break
            
    base, ext = os.path.splitext(name)
    masked_base = ''.join(c if (i % 3 == 0 and c.isalnum()) else '*' for i, c in enumerate(base))
    return f"{masked_base}{res_part}{ext}"

# =====================================================================================
# --- PYROGRAM BOT HANDLERS: Telegram se aane wale commands ko handle karna ---
# =====================================================================================

@bot.on_message(filters.command("start") & filters.private)
async def start_command(client: Client, message: Message):
    """/start command aur Force Subscribe ki verification ko handle karta hai."""
    user_id = message.from_user.id
    user_name = message.from_user.first_name
    
    # Check karo ki /start ke saath koi "verify_..." jaisa code hai ya nahi
    if len(message.command) > 1 and message.command[1].startswith("verify_"):
        unique_id = message.command[1].split("_", 1)[1]
        
        # Agar Force Subscribe channel set hai, toh user ki membership check karo
        if Config.FORCE_SUB_CHANNEL:
            try:
                # Bot check karega ki user member hai ya nahi
                await client.get_chat_member(Config.FORCE_SUB_CHANNEL, user_id)
            except UserNotParticipant:
                # Agar user member nahi hai, toh use join karne ko bolo
                channel_username = str(Config.FORCE_SUB_CHANNEL).replace('@', '')
                channel_link = f"https://t.me/{channel_username}"
                
                join_button = InlineKeyboardButton("📢 Join Channel", url=channel_link)
                retry_button = InlineKeyboardButton("✅ Try Again", url=f"https://t.me/{Config.BOT_USERNAME}?start={message.command[1]}")
                
                keyboard = InlineKeyboardMarkup([[join_button], [retry_button]])
                
                await message.reply_text(
                    "**You must join our channel to get the download link!**\n\n"
                    "Click the button below to join, then click 'Try Again'.",
                    reply_markup=keyboard,
                    quote=True
                )
                return # Function ko yahin rok do

        # Agar user member hai (ya force sub on nahi hai), toh use asli link do
        final_link = f"{Config.BLOGGER_PAGE_URL}?id={unique_id}" if Config.BLOGGER_PAGE_URL else f"{Config.BASE_URL}/show/{unique_id}"
        
        reply_text = f"✅ Verification successful!\n\nTap to copy your link:\n`{final_link}`"
        
        button = InlineKeyboardMarkup([[InlineKeyboardButton("Open Your Link 🔗", url=final_link)]])
        
        await message.reply_text(reply_text, reply_markup=button, quote=True, disable_web_page_preview=True)

    else:
        # Agar simple /start command hai, toh welcome message do
        reply_text = f"""
👋 **Hello, {user_name}!**

Welcome to Sharing Box Bot. I can help you create permanent, shareable links for your files.

**How to use me:**
Just send or forward any file to this chat.

I will instantly give you a special link that you can share with anyone!
"""
        await message.reply_text(reply_text)

async def handle_file_upload(message: Message, user_id: int):
    """File milne par verification link generate karta hai."""
    try:
        sent_message = await message.copy(chat_id=Config.STORAGE_CHANNEL)
        unique_id = secrets.token_urlsafe(8)
        await db.save_link(unique_id, sent_message.id)
        
        # Ab direct link ke bajaye, verification link generate karo
        verify_link = f"https://t.me/{Config.BOT_USERNAME}?start=verify_{unique_id}"
        
        button = InlineKeyboardMarkup([[InlineKeyboardButton("Click Here to Get Link 🔗", url=verify_link)]])
        
        await message.reply_text(
            "✅ Your file has been processed!\n\n"
            "Click the button below to verify and get the final link.",
            reply_markup=button,
            quote=True
        )
    except Exception as e:
        print(f"!!! ERROR in handle_file_upload: {traceback.format_exc()}")
        await message.reply_text("Sorry, something went wrong.")

@bot.on_message(filters.private & (filters.document | filters.video | filters.audio))
async def file_handler(_, message: Message):
    """Har file (doc, video, audio) ko handle karta hai."""
    await handle_file_upload(message, message.from_user.id)

# --- GATEKEEPER LOGIC ---

@bot.on_chat_member_updated(filters.chat(Config.STORAGE_CHANNEL))
async def simple_gatekeeper(client: Client, member_update: ChatMemberUpdated):
    """Channel mein join karne wale anjaan logo ko kick karta hai."""
    try:
        if (member_update.new_chat_member and member_update.new_chat_member.status == enums.ChatMemberStatus.MEMBER):
            user = member_update.new_chat_member.user
            if user.id == Config.OWNER_ID or user.is_self:
                return
            print(f"Gatekeeper: Anjaan user '{user.first_name}' ({user.id}) ne join kiya. Kick kar raha hai...")
            await client.ban_chat_member(Config.STORAGE_CHANNEL, user.id)
            await client.unban_chat_member(Config.STORAGE_CHANNEL, user.id)
            print(f"Gatekeeper: User {user.id} ko safaltapoorvak kick kar diya.")
    except Exception as e:
        print(f"Gatekeeper Error: {e}")

async def cleanup_channel(client: Client):
    """Bot start hone par channel ko saaf karta hai."""
    print("Gatekeeper: Startup par channel cleanup shuru kar raha hai...")
    allowed_members = {Config.OWNER_ID, client.me.id}
    try:
        async for member in client.get_chat_members(Config.STORAGE_CHANNEL):
            if member.user.id in allowed_members:
                continue
            if member.status in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER]:
                continue
            try:
                print(f"Gatekeeper Cleanup: Anjaan member {member.user.id} mila. Kick kar raha hai...")
                await client.ban_chat_member(Config.STORAGE_CHANNEL, member.user.id)
                await asyncio.sleep(1)
            except FloodWait as e:
                await asyncio.sleep(e.value)
            except Exception as e:
                print(f"Gatekeeper Cleanup: {member.user.id} ko kick nahi kar paaya. Error: {e}")
        print("Gatekeeper: Channel cleanup poora hua.")
    except Exception as e:
        print(f"Gatekeeper Cleanup: Members ki list nahi mil paayi. Error: {e}")

# =====================================================================================
# --- FASTAPI WEB SERVER: Browser se aane wali requests ko handle karna ---
# =====================================================================================

class ByteStreamer:
    """Telegram se file ke parts download karne ka kaam karta hai."""
    def __init__(self, client: Client):
        self.client = client
    
    @staticmethod
    async def get_location(file_id: FileId):
        return raw.types.InputDocumentFileLocation(
            id=file_id.media_id, access_hash=file_id.access_hash,
            file_reference=file_id.file_reference, thumb_size=file_id.thumbnail_size
        )
        
    async def yield_file(self, file_id: FileId, index: int, offset: int, first_part_cut: int, last_part_cut: int, part_count: int, chunk_size: int):
        client = self.client
        work_loads[index] += 1
        media_session = client.media_sessions.get(file_id.dc_id)
        if media_session is None:
            if file_id.dc_id != await client.storage.dc_id():
                auth = await Auth(client, file_id.dc_id, await client.storage.test_mode()).create()
                media_session = Session(client, file_id.dc_id, auth, await client.storage.test_mode(), is_media=True)
                await media_session.start()
                exported_auth = await client.invoke(raw.functions.auth.ExportAuthorization(dc_id=file_id.dc_id))
                await media_session.invoke(raw.functions.auth.ImportAuthorization(id=exported_auth.id, bytes=exported_auth.bytes))
            else:
                media_session = client.session
            client.media_sessions[file_id.dc_id] = media_session
        
        location = await self.get_location(file_id)
        current_part = 1
        try:
            while current_part <= part_count:
                chunk_result = await media_session.invoke(
                    raw.functions.upload.GetFile(location=location, offset=offset, limit=chunk_size),
                    retries=0
                )
                if not isinstance(chunk_result, raw.types.upload.File):
                    break
                
                chunk = chunk_result.bytes
                if not chunk:
                    break

                if part_count == 1: yield chunk[first_part_cut:last_part_cut]
                elif current_part == 1: yield chunk[first_part_cut:]
                elif current_part == part_count: yield chunk[:last_part_cut]
                else: yield chunk
                
                current_part += 1
                offset += chunk_size
        finally:
            work_loads[index] -= 1

@app.get("/show/{unique_id}", response_class=HTMLResponse)
async def show_page(request: Request, unique_id: str):
    """Download page dikhata hai."""
    message_id = await db.get_link(unique_id)
    if not message_id:
        raise HTTPException(status_code=404, detail="Link expired or invalid.")
    
    main_bot = multi_clients.get(0)
    if not main_bot:
        raise HTTPException(status_code=503, detail="Bot is not ready.")
        
    try:
        message = await main_bot.get_messages(Config.STORAGE_CHANNEL, message_id)
    except Exception:
        raise HTTPException(status_code=404, detail="File not found on Telegram.")
        
    media = message.document or message.video or message.audio
    if not media:
        raise HTTPException(status_code=404, detail="Media not found in the message.")
        
    file_name = media.file_name or "file"
    safe_file_name = "".join(c for c in file_name if c.isalnum() or c in (' ', '.', '_', '-')).rstrip()
    mime_type = media.mime_type or "application/octet-stream"

    context = {
        "request": request,
        "file_name": mask_filename(file_name),
        "file_size": get_readable_file_size(media.file_size),
        "is_media": mime_type.startswith(("video", "audio")),
        "direct_dl_link": f"{Config.BASE_URL}/dl/{message_id}/{safe_file_name}",
        "mx_player_link": f"intent:{Config.BASE_URL}/dl/{message_id}/{safe_file_name}#Intent;action=android.intent.action.VIEW;type={mime_type};end",
        "vlc_player_link": f"vlc://{Config.BASE_URL}/dl/{message_id}/{safe_file_name}"
    }
    return templates.TemplateResponse("show.html", context)

@app.get("/dl/{message_id}/{file_name}")
async def stream_media(request: Request, message_id: int, file_name: str):
    """File ko stream ya download karwata hai."""
    client = multi_clients.get(min(work_loads, key=work_loads.get, default=0))
    if not client:
        raise HTTPException(status_code=503, detail="No available clients.")
        
    streamer = class_cache.get(client) or ByteStreamer(client)
    class_cache[client] = streamer
    
    try:
        message = await client.get_messages(Config.STORAGE_CHANNEL, message_id)
        media = message.document or message.video or message.audio
        if not media or message.empty:
            raise FileNotFoundError
            
        file_id = FileId.decode(media.file_id)
        file_size = media.file_size
        range_header = request.headers.get("Range", "")
        
        from_bytes, until_bytes = 0, file_size - 1
        if range_header:
            range_parts = range_header.replace("bytes=", "").split("-")
            from_bytes = int(range_parts[0])
            if len(range_parts) > 1 and range_parts[1]:
                until_bytes = int(range_parts[1])
        
        if (until_bytes >= file_size) or (from_bytes < 0):
            raise HTTPException(status_code=416)
            
        req_length = until_bytes - from_bytes + 1
        chunk_size = 1024 * 1024
        offset = (from_bytes // chunk_size) * chunk_size
        first_part_cut = from_bytes - offset
        last_part_cut = (until_bytes % chunk_size) + 1
        part_count = math.ceil(req_length / chunk_size)
        
        body = streamer.yield_file(file_id, 0, offset, first_part_cut, last_part_cut, part_count, chunk_size)
        
        status_code = 206 if range_header else 200
        headers = {
            "Content-Type": media.mime_type or "application/octet-stream",
            "Accept-Ranges": "bytes",
            "Content-Disposition": f'inline; filename="{media.file_name}"',
            "Content-Length": str(req_length)
        }
        if range_header:
            headers["Content-Range"] = f"bytes {from_bytes}-{until_bytes}/{file_size}"
            
        return StreamingResponse(body, status_code=status_code, headers=headers)
        
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found.")
    except Exception:
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail="Internal streaming error.")

# =====================================================================================
# --- MAIN EXECUTION BLOCK: Script ko yahan se chalaya jaata hai ---
# =====================================================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    # Uvicorn ko 'warning' level par chalao taaki faltu ke logs na aaye
    uvicorn.run("app:app", host="0.0.0.0", port=port, log_level="warning")
