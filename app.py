import os
import asyncio
import secrets
import traceback
import uvicorn
import re
import logging
import math
import requests
import base64
import random
import time

from contextlib import asynccontextmanager
from pyrogram import Client, filters, enums
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, ChatMemberUpdated, CallbackQuery
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
# --- BACKGROUND POLLING SERVICE ---
# =====================================================================================

async def poll_huggingface_queue():
    if not Config.HF_WORKERS:
        print("⚠️ No Workers configured. Polling disabled.")
        return

    print(f"🔄 Started Polling for {len(Config.HF_WORKERS)} Workers...")
    VIEWER_BASE = "https://v0-file-opener-video-player.vercel.app/view?value="

    while True:
        for worker_url in Config.HF_WORKERS:
            try:
                response = await asyncio.to_thread(requests.get, f"{worker_url}/botmessages", timeout=5)

                if response.status_code == 200:
                    data = response.json()
                    messages = data.get("messages", [])

                    if messages:
                        sent_ids = []
                        for msg in messages:
                            try:
                                url_match = re.search(r"href=['\"](.*?)['\"]", msg['text'])
                                if url_match:
                                    raw_url = url_match.group(1)
                                    url_bytes = raw_url.encode('ascii')
                                    base64_bytes = base64.b64encode(url_bytes)
                                    base64_code = base64_bytes.decode('ascii')
                                    final_viewer_link = f"{VIEWER_BASE}{base64_code}"
                                    
                                    filename_match = re.search(r"📂 <b>File:</b> (.*)\n", msg['text'])
                                    filename = filename_match.group(1) if filename_match else "File"

                                    result_text = (
                                        f"✅ <b>Permanent Link Ready!</b>\n\n"
                                        f"📂 <b>File:</b> {filename}\n\n"
                                        f"👇 <b>Click below to Watch/Download</b>"
                                    )
                                    
                                    buttons = InlineKeyboardMarkup([
                                        [InlineKeyboardButton("▶️ Open Online Player", url=final_viewer_link)]
                                    ])

                                    await bot.send_message(
                                        chat_id=msg['chat_id'], 
                                        text=result_text, 
                                        parse_mode=enums.ParseMode.HTML,
                                        reply_markup=buttons
                                    )
                                else:
                                    await bot.send_message(msg['chat_id'], msg['text'], parse_mode=enums.ParseMode.HTML)

                                sent_ids.append(msg['id'])
                                await asyncio.sleep(0.5) 
                            except Exception as e:
                                print(f"❌ Failed to send to {msg.get('chat_id')}: {e}")

                        if sent_ids:
                            payload = {"message_ids": sent_ids}
                            await asyncio.to_thread(requests.post, f"{worker_url}/donebotmessages", json=payload, timeout=10)
            
            except Exception:
                continue
        
        await asyncio.sleep(30)
        # =====================================================================================
# --- SETUP, LOGGING & ADMIN COMMANDS ---
# =====================================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()
    try:
        await bot.start()
        me = await bot.get_me()
        Config.BOT_USERNAME = me.username
        print(f"✅ Bot Started: @{Config.BOT_USERNAME}")

        multi_clients[0] = bot
        work_loads[0] = 0
        await initialize_clients()
        
        asyncio.create_task(poll_huggingface_queue())
        
        if Config.LOG_CHANNEL:
            try:
                await bot.send_message(Config.LOG_CHANNEL, "🟢 **Bot Started & Connected to Logs**")
            except:
                print("❌ Bot cannot access LOG_CHANNEL.")

    except Exception as e:
        print(f"Startup Error: {e}")
    
    yield
    if bot.is_initialized: await bot.stop()
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

class TokenParser:
    @staticmethod
    def parse_from_env():
        return {c + 1: t for c, (_, t) in enumerate(filter(lambda n: n[0].startswith("MULTI_TOKEN"), sorted(os.environ.items())))}

async def start_client(client_id, bot_token):
    try:
        client = await Client(name=str(client_id), api_id=Config.API_ID, api_hash=Config.API_HASH, bot_token=bot_token, no_updates=True, in_memory=True).start()
        work_loads[client_id] = 0
        multi_clients[client_id] = client
    except Exception: pass

async def initialize_clients():
    tokens = TokenParser.parse_from_env()
    if tokens: await asyncio.gather(*[start_client(i, t) for i, t in tokens.items()])

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

async def send_log(user, file_name, file_size, stream_link, dl_link):
    if not Config.LOG_CHANNEL: return
    
    log_msg = (
        f"<b>#NEW_FILE</b>\n\n"
        f"👤 <b>User:</b> <a href='tg://user?id={user.id}'>{user.first_name}</a>\n"
        f"🆔 <b>ID:</b> <code>{user.id}</code>\n"
        f"📂 <b>File:</b> {file_name}\n"
        f"📦 <b>Size:</b> {file_size}\n\n"
        f"🔗 <b>Stream:</b> {stream_link}\n"
        f"🔗 <b>DL:</b> {dl_link}"
    )
    try:
        await bot.send_message(Config.LOG_CHANNEL, log_msg, parse_mode=enums.ParseMode.HTML, disable_web_page_preview=True)
    except Exception as e:
        print(f"Log Error: {e}")

# --- ADMIN BLOCKING SYSTEM ---
@bot.on_message(filters.command(["ban", "unban"]) & filters.user(Config.ADMINS))
async def admin_ban_handler(client, message):
    if not message.reply_to_message and len(message.command) < 2:
        await message.reply("Usage: Reply to user OR `/ban user_id` OR `/ban @username`")
        return

    cmd = message.command[0]
    target_id = None
    
    if message.reply_to_message:
        match = re.search(r"ID: <code>(\d+)</code>", message.reply_to_message.text)
        if match:
            target_id = int(match.group(1))
        elif message.reply_to_message.from_user:
            target_id = message.reply_to_message.from_user.id
    elif len(message.command) > 1:
        arg = message.command[1]
        if arg.isdigit():
            target_id = int(arg)
        elif arg.startswith("@"):
            target_id = await db.get_user_by_username(arg)

    if not target_id:
        await message.reply("❌ User not found.")
        return

    if cmd == "ban":
        await db.ban_user(target_id)
        await message.reply(f"🚫 User `{target_id}` BANNED.")
        try: await bot.send_message(target_id, "🚫 <b>You have been banned.</b>")
        except: pass
    else:
        await db.unban_user(target_id)
        await message.reply(f"✅ User `{target_id}` UNBANNED.")
        try: await bot.send_message(target_id, "✅ <b>You have been unbanned.</b>")
        except: pass

@bot.on_message(filters.command("stats") & filters.user(Config.ADMINS))
async def stats_command(client, message):
    total = await db.total_users_count()
    await message.reply(f"📊 **Total Users:** `{total}`")
    # =====================================================================================
# --- BOT HANDLERS & WEB SERVER ---
# =====================================================================================

@bot.on_message(filters.command("start") & filters.private)
async def start_command(client: Client, message: Message):
    await db.add_user(message.from_user.id, message.from_user.first_name, message.from_user.username)
    if await db.is_user_banned(message.from_user.id):
        await message.reply("🚫 <b>You are banned.</b>")
        return

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
        await message.reply_text("👋 **Welcome!** Send me a file to generate a link.")

@bot.on_message(filters.private & (filters.document | filters.video | filters.audio))
async def handle_file_upload(client: Client, message: Message):
    await db.add_user(message.from_user.id, message.from_user.first_name, message.from_user.username)
    if await db.is_user_banned(message.from_user.id):
        await message.reply("🚫 <b>You are banned.</b>")
        return

    try:
        sent_message = await message.copy(chat_id=Config.STORAGE_CHANNEL)
        unique_id = secrets.token_urlsafe(8)
        await db.save_link(unique_id, sent_message.id)
        
        media = message.document or message.video or message.audio
        file_name = media.file_name or "Unknown_File"
        file_size = get_readable_file_size(media.file_size)
        
        stream_link = f"{Config.BASE_URL}/show/{unique_id}"
        render_dl_link = f"{Config.BASE_URL}/dl/{sent_message.id}/{file_name.replace(' ', '_')}"
        
        render_bytes = render_dl_link.encode('ascii')
        render_base64 = base64.b64encode(render_bytes).decode('ascii')
        opener_link = f"https://v0-file-opener-video-player.vercel.app/view?value={render_base64}"
        
        asyncio.create_task(send_log(message.from_user, file_name, file_size, opener_link, render_dl_link))

        response_text = (
            f"<b><u>Your Link Generated !</u></b>\n\n"
            f"📧 <b>FILE NAME :-</b> <code>{file_name}</code>\n\n"
            f"📦 <b>FILE SIZE :-</b> {file_size}\n\n"
            f"<b><u>Tap To Copy Link</u></b> 👇\n\n"
            f"🖥 <b>Stream :</b> <code>{stream_link}</code>\n\n"
            f"📥 <b>Download :</b> <code>{render_dl_link}</code>\n\n"
            f"🚸 <b>NOTE : LINK WON'T EXPIRE TILL I DELETE 🤡</b>"
        )
        
        buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("• STREAM •", url=opener_link),
                InlineKeyboardButton("• DOWNLOAD •", url=render_dl_link)
            ],
            [
                InlineKeyboardButton("• GET PERMANENT LINK •", callback_data=f"ia_upload_{sent_message.id}")
            ],
            [
                InlineKeyboardButton("• CLOSE •", callback_data="close_data")
            ]
        ])
        
        await message.reply_text(response_text, reply_markup=buttons, quote=True, parse_mode=enums.ParseMode.HTML)

    except Exception as e:
        print(f"Upload Error: {e}")
        await message.reply_text(f"❌ Error: {e}")

@bot.on_callback_query(filters.regex("close_data"))
async def close_handler(client, callback_query):
    await callback_query.message.delete()

@bot.on_callback_query(filters.regex(r"^ia_upload_"))
async def ia_upload_handler(client, callback_query):
    if await db.is_user_banned(callback_query.from_user.id):
        await callback_query.answer("🚫 You are banned.", show_alert=True)
        return

    if not Config.HF_WORKERS:
        await callback_query.answer("❌ Error: No Workers configured.", show_alert=True)
        return

    try:
        old = callback_query.message.reply_markup.inline_keyboard
        proc_markup = InlineKeyboardMarkup([
            [old[0][0], old[0][1]], 
            [InlineKeyboardButton("⏳ Processing...", callback_data="ignore")], 
            old[2]
        ])
        await callback_query.edit_message_reply_markup(reply_markup=proc_markup)
    except: 
        pass

    try:
        message_id = int(callback_query.data.split("_")[2])
        user_msg = callback_query.message.reply_to_message or callback_query.message
        
        stored_msg = await client.get_messages(Config.STORAGE_CHANNEL, message_id)
        media = stored_msg.document or stored_msg.video or stored_msg.audio
        
        safe_name = "".join(c for c in (media.file_name or "vid.mp4") if c.isalnum() or c in ('.', '_', '-')).rstrip()
        stream_link = f"{Config.BASE_URL}/dl/{message_id}/{safe_name}"
        
        payload = {
            "stream_link": stream_link, 
            "file_name": media.file_name, 
            "chat_id": user_msg.chat.id, 
            "message_id": user_msg.id
        }

        success = False
        workers = Config.HF_WORKERS.copy()
        random.shuffle(workers)
        
        for worker_url in workers:
            try:
                response = await asyncio.to_thread(requests.post, f"{worker_url}/upload", json=payload, timeout=3)
                
                if response.status_code == 200:
                    await callback_query.answer("✅ Task Accepted! We will notify you.", show_alert=True)
                    success = True
                    break 
            except:
                continue 
        
        if not success:
            raise Exception("All workers failed.")

    except Exception as e:
        print(f"❌ Handoff Failed: {e}")
        await callback_query.answer("❌ All Servers Busy. Restoring button...", show_alert=True)
        
        try:
            restore_markup = InlineKeyboardMarkup([
                [old[0][0], old[0][1]], 
                [InlineKeyboardButton("• GET PERMANENT LINK •", callback_data=f"ia_upload_{message_id}")], 
                old[2]
            ])
            await callback_query.edit_message_reply_markup(reply_markup=restore_markup)
        except: 
            pass

@bot.on_callback_query(filters.regex("ignore"))
async def ignore_callback(client, callback_query):
    await callback_query.answer("⏳ Processing...", show_alert=True)

@app.get("/")
async def health(): return {"status": "ok"}

@app.get("/show/{unique_id}", response_class=HTMLResponse)
async def show_page(request: Request, unique_id: str):
    storage_msg_id = await db.get_link(unique_id)
    if not storage_msg_id: raise HTTPException(404, "Link Expired")
    try:
        msg = await multi_clients[0].get_messages(Config.STORAGE_CHANNEL, storage_msg_id)
        media = msg.document or msg.video or msg.audio
        file_name = media.file_name or "File"
        safe_name = "".join(c for c in file_name if c.isalnum() or c in (' ', '.', '_', '-')).rstrip()
        file_size = get_readable_file_size(media.file_size)
        direct_link = f"{Config.BASE_URL}/dl/{storage_msg_id}/{safe_name}"
        context = {
            "request": request,
            "file_name": file_name,
            "file_size": file_size,
            "is_media": (media.mime_type or "").startswith(("video", "audio")),
            "direct_dl_link": direct_link,
            "render_url": direct_link 
        }
        return templates.TemplateResponse("show.html", context)
    except: raise HTTPException(404, "File Not Found")

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
        chunk_size = 1024 * 1024
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
    uvicorn.run("app:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
            
        
