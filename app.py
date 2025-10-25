import os
import asyncio
import secrets
import traceback
import uvicorn
from urllib.parse import urlparse

import aiohttp
import aiofiles
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pyrogram.file_id import FileId
from pyrogram import raw
from pyrogram.session import Session, Auth
import math

# Zaroori files se import karo
from config import Config
from database import db

# --- START: GLOBAL VARIABLES AND BOT/APP INITIALIZATION ---

# FastAPI app
app = FastAPI()
templates = Jinja2Templates(directory="templates")
class_cache = {}

# Pyrogram Bot
bot = Client(
    "SimpleStreamBot",
    api_id=Config.API_ID,
    api_hash=Config.API_HASH,
    bot_token=Config.BOT_TOKEN,
    in_memory=True
)

# Multi-client Dictionaries
multi_clients = {}
work_loads = {}

# --- END: INITIALIZATION ---

# --- START: PYROGRAM BOT HANDLERS ---

@bot.on_message(filters.command("start") & filters.private)
async def start_command(client, message: Message):
    await message.reply_text(f"Hello, {message.from_user.first_name}! I am alive.")

async def handle_file_upload(message: Message, user_id: int):
    try:
        sent_message = await bot.copy_message(
            chat_id=Config.STORAGE_CHANNEL,
            from_chat_id=message.chat.id,
            message_id=message.id
        )
        unique_id = secrets.token_urlsafe(8)
        await db.save_link(unique_id, sent_message.id)
        final_link = f"{Config.BASE_URL}/show/{unique_id}"
        button = InlineKeyboardMarkup([[InlineKeyboardButton("Open Link 🔗", url=final_link)]])
        await message.reply_text("Link generated!", reply_markup=button, quote=True)
    except Exception as e:
        print(f"Error in handle_file_upload: {traceback.format_exc()}")
        await message.reply_text("Sorry, something went wrong.")

@bot.on_message(filters.private & (filters.document | filters.video | filters.audio))
async def file_handler(client, message: Message):
    await handle_file_upload(message, message.from_user.id)

# --- END: PYROGRAM BOT HANDLERS ---


# --- START: FASTAPI WEB SERVER ROUTES ---

# ByteStreamer class yahan define karo
class ByteStreamer:
    # ... (poora class code yahan daalo)
    def __init__(self, client: Client): self.client = client
    @staticmethod
    async def get_location(file_id: FileId): return raw.types.InputDocumentFileLocation(id=file_id.media_id, access_hash=file_id.access_hash, file_reference=file_id.file_reference, thumb_size=file_id.thumbnail_size)
    async def yield_file(self, file_id: FileId, index: int, offset: int, first_part_cut: int, last_part_cut: int, part_count: int, chunk_size: int):
        client = self.client; work_loads[index] += 1
        media_session = client.media_sessions.get(file_id.dc_id);
        if media_session is None:
            if file_id.dc_id != await client.storage.dc_id():
                auth_key = await Auth(client, file_id.dc_id, await client.storage.test_mode()).create(); media_session = Session(client, file_id.dc_id, auth_key, await client.storage.test_mode(), is_media=True); await media_session.start(); exported_auth = await client.invoke(raw.functions.auth.ExportAuthorization(dc_id=file_id.dc_id)); await media_session.invoke(raw.functions.auth.ImportAuthorization(id=exported_auth.id, bytes=exported_auth.bytes))
            else: media_session = client.session
            client.media_sessions[file_id.dc_id] = media_session
        location = await self.get_location(file_id); current_part = 1
        try:
            while current_part <= part_count:
                r = await media_session.invoke(raw.functions.upload.GetFile(location=location, offset=offset, limit=chunk_size), retries=0)
                if isinstance(r, raw.types.upload.File):
                    chunk = r.bytes;
                    if not chunk: break
                    if part_count == 1: yield chunk[first_part_cut:last_part_cut]
                    elif current_part == 1: yield chunk[first_part_cut:]
                    elif current_part == part_count: yield chunk[:last_part_cut]
                    else: yield chunk
                    current_part += 1; offset += chunk_size
                else: break
        finally: work_loads[index] -= 1

@app.get("/show/{unique_id}")
async def show_file_page(request: Request, unique_id: str):
    storage_msg_id = await db.get_link(unique_id)
    if not storage_msg_id: raise HTTPException(404)
    file_msg = await bot.get_messages(Config.STORAGE_CHANNEL, storage_msg_id)
    media = file_msg.document or file_msg.video or file_msg.audio
    # ... baaki ka logic for template
    return templates.TemplateResponse("show.html", {"request": request, "file_name": media.file_name, "file_size": "N/A", "is_media": True, "direct_dl_link": f"/dl/{storage_msg_id}/file"})

@app.get("/dl/{msg_id}/{file_name}")
async def stream_handler(request: Request, msg_id: int, file_name: str):
    # ... (poora stream_handler logic yahan daalo)
    index = min(work_loads, key=work_loads.get, default=0); client = multi_clients.get(index)
    if not client: raise HTTPException(503)
    if client in class_cache: tg_connect = class_cache[client]
    else: tg_connect = ByteStreamer(client); class_cache[client] = tg_connect
    message = await client.get_messages(Config.STORAGE_CHANNEL, msg_id)
    media = message.document or message.video or message.audio
    file_id = FileId.decode(media.file_id)
    file_size = media.file_size
    range_header = request.headers.get("Range", 0)
    from_bytes, until_bytes = 0, file_size - 1
    if range_header: from_bytes_str, until_bytes_str = range_header.replace("bytes=", "").split("-"); from_bytes = int(from_bytes_str);
    if until_bytes_str: until_bytes = int(until_bytes_str)
    chunk_size = 1024 * 1024; req_length = until_bytes - from_bytes + 1; offset = from_bytes - (from_bytes % chunk_size); first_part_cut = from_bytes - offset; last_part_cut = (until_bytes % chunk_size) + 1; part_count = math.ceil(req_length / chunk_size)
    body = tg_connect.yield_file(file_id, index, offset, first_part_cut, last_part_cut, part_count, chunk_size)
    return StreamingResponse(content=body, status_code=206 if range_header else 200, headers={"Content-Type": media.mime_type or "application/octet-stream", "Content-Range": f"bytes {from_bytes}-{until_bytes}/{file_size}", "Content-Length": str(req_length), "Accept-Ranges": "bytes", "Content-Disposition": f'inline; filename="{media.file_name}"'})


# --- END: FASTAPI WEB SERVER ROUTES ---

# --- START: MAIN EXECUTION BLOCK ---

async def main():
    """Starts Bot and Web Server together."""
    print("Starting services...")
    
    # DB Connect
    await db.connect()
    
    # Start the bot
    await bot.start()
    print("Bot started successfully.")
    
    # Verify channel access
    try:
        print(f"Verifying channel access for {Config.STORAGE_CHANNEL}...")
        # YAHAN ASLI FIX HO SAKTA HAI.
        # get_chat() ke bajaye, seedha ek aasan sa command call karo.
        await bot.send_message(Config.STORAGE_CHANNEL, "Bot is online!")
        print("Channel is accessible.")
    except Exception as e:
        print(f"FATAL: Could not access STORAGE_CHANNEL. Error: {e}")
        return

    # Multi-client setup
    multi_clients[0] = bot
    work_loads[0] = 0
    # ... (Baaki multi-client logic yahan daal sakte hain)

    # Uvicorn server ko configure karo
    port = int(os.environ.get("PORT", 8000))
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config)
    
    # Dono ko ek saath chalao
    await asyncio.gather(
        server.serve(),
        idle() # Pyrogram ko idle rakhta hai
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Shutdown signal received.")
