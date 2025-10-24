import os
import time
import asyncio
import secrets
import aiohttp
import aiofiles
import traceback  # Error details ke liye import
from urllib.parse import urlparse
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import FloodWait

from config import Config

# webserver se import ki zaroorat nahi, main.py se handle hoga
# in-memory dictionaries ko webserver.py mein hi rehne do, wahan se access honge
from webserver import multi_clients, work_loads

# --- Bot Initialization ---
bot = Client(
    "SimpleStreamBot",
    api_id=Config.API_ID,
    api_hash=Config.API_HASH,
    bot_token=Config.BOT_TOKEN,
    workers=100
)


# --- Multi-Client Initialization ---
class TokenParser:
    @staticmethod
    def parse_from_env():
        return {
            c + 1: t
            for c, (_, t) in enumerate(
                filter(lambda n: n[0].startswith("MULTI_TOKEN"), sorted(os.environ.items()))
            )
        }


async def start_client(client_id, bot_token):
    try:
        print(f"Attempting to start Client: {client_id}")
        client = await Client(
            name=str(client_id), api_id=Config.API_ID, api_hash=Config.API_HASH,
            bot_token=bot_token, sleep_threshold=100, no_updates=True, in_memory=True
        ).start()
        work_loads[client_id] = 0
        multi_clients[client_id] = client
        print(f"Client {client_id} started successfully.")
    except FloodWait as e:
        print(f"FloodWait for Client {client_id}. Waiting for {e.value} seconds...")
        await asyncio.sleep(e.value + 5)  # Adding 5 extra seconds
        await start_client(client_id, bot_token)  # Retry starting
    except Exception as e:
        print(f"!!! CRITICAL ERROR: Failed to start Client {client_id} - Error: {e}")


async def initialize_clients(main_bot_instance):
    multi_clients[0] = main_bot_instance
    work_loads[0] = 0

    all_tokens = TokenParser.parse_from_env()
    if not all_tokens:
        print("No additional clients found. Using default bot only.")
        return

    print(f"Found {len(all_tokens)} extra clients. Starting them one by one with a delay.")
    for i, token in all_tokens.items():
        await start_client(i, token)
        await asyncio.sleep(10)  # 10 second gap between starting each bot

    if len(multi_clients) > 1:
        print(f"Multi-Client Mode Enabled. Total Clients: {len(multi_clients)}")
    else:
        print("Single Client Mode.")


# --- Helper Functions ---
def get_readable_file_size(size_in_bytes):
    if not size_in_bytes: return '0B'
    power, n = 1024, 0
    power_labels = {0: '', 1: 'K', 2: 'M', 3: 'G'}
    while size_in_bytes >= power and n < len(power_labels):
        size_in_bytes /= power; n += 1
    return f"{size_in_bytes:.2f} {power_labels[n]}B"


async def edit_message_with_retry(message, text):
    try:
        await message.edit_text(text)
    except FloodWait as e:
        print(f"FloodWait received while editing message. Waiting for {e.value} seconds.")
        await asyncio.sleep(e.value + 5)  # Adding 5 extra seconds
        await message.edit_text(text)
    except Exception as e:
        print(f"Error editing message: {e}")


# --- Bot Handlers with SUPER Debugging ---

print("Bot script loaded. Handlers are being registered...")

# YEH NAYA FUNCTION HAR MESSAGE KO CHECK KAREGA
@bot.on_message(filters.private, group=-1) # group=-1 ensures this runs first
async def catch_all_private_messages(client, message: Message):
    """Yeh function har private message ko log karega, command ho ya file."""
    try:
        await bot.send_message(
            chat_id=Config.LOG_CHANNEL,
            text=(
                f"**[DEBUG] Received Message**\n\n"
                f"**From User ID:** `{message.from_user.id}`\n"
                f"**Message Type:** `{message.media or 'TEXT'}`\n"
                f"**Content:**\n`{message.text or message.caption or 'No Text'}`"
            )
        )
    except Exception as e:
        # Agar log channel mein hi message nahi jaa raha, toh print karo
        print(f"!!! CRITICAL: Could not send log to LOG_CHANNEL. Check channel ID and bot permissions. Error: {e}")

    # Iske baad, Pyrogram doosre handlers (jaise /start, file_handler) ko check karega
    message.continue_propagation()


@bot.on_message(filters.command("start") & filters.private)
async def start_command(client, message: Message):
    try:
        await message.reply_text("Hello! Send me a file or a direct download URL to get a shareable link.")
    except Exception as e:
        # Agar reply fail ho, toh log channel mein error bhejo
        error_trace = traceback.format_exc()
        print(f"!!! ERROR in /start command: {e}\n{error_trace}")
        await bot.send_message(
            chat_id=Config.LOG_CHANNEL,
            text=f"**ERROR in /start command!**\n\n**User ID:** `{message.from_user.id}`\n\n**Error:**\n`{e}`\n\n**Traceback:**\n`{error_trace}`"
        )


async def handle_file_upload(message: Message, user_id: int):
    try:
        sent_message = await message.copy(chat_id=Config.STORAGE_CHANNEL)
        unique_id = secrets.token_urlsafe(8)
        show_link = f"{Config.BASE_URL}/show/{unique_id}"

        log_text = (
            f"**File Processed Successfully**\n\n"
            f"**User:** `{user_id}`\n"
            f"**Original Msg ID:** `{message.id}`\n"
            f"**Storage Msg ID:** `{sent_message.id}`\n"
            f"**Unique ID:** `{unique_id}`\n"
            f"**Link:** {show_link}"
        )
        await bot.send_message(Config.LOG_CHANNEL, log_text)

        await message.reply_text(f"Here is your shareable link:\n`{show_link}`", quote=True)

    except Exception as e:
        error_trace = traceback.format_exc()
        print(f"!!! ERROR in handle_file_upload: {e}\n{error_trace}")
        await bot.send_message(
            chat_id=Config.LOG_CHANNEL,
            text=f"**ERROR handling file!**\n\n**User ID:** `{user_id}`\n\n**Error:**\n`{e}`\n\n**Traceback:**\n`{error_trace}`"
        )
        await message.reply_text("Sorry, something went wrong. The developer has been notified.")


@bot.on_message(filters.private & (filters.document | filters.video | filters.audio))
async def file_handler(client, message: Message):
    await handle_file_upload(message, message.from_user.id)


@bot.on_message(filters.command("url") & filters.private)
async def url_upload_handler(client, message: Message):
    if len(message.command) < 2:
        await message.reply_text("Usage: `/url <direct_download_url>`"); return

    url = message.command[1]
    file_name = os.path.basename(urlparse(url).path) or f"file_{int(time.time())}"
    status_msg = await message.reply_text("Processing your link...")

    if not os.path.exists('downloads'): os.makedirs('downloads')
    file_path = os.path.join('downloads', file_name)
    last_edit_time = 0

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=None) as resp:
                if resp.status != 200:
                    await status_msg.edit_text(f"Download failed! Status: {resp.status}"); return
                total_size = int(resp.headers.get('content-length', 0))
                downloaded_size = 0
                async with aiofiles.open(file_path, 'wb') as f:
                    async for chunk in resp.content.iter_chunked(1024 * 1024):
                        await f.write(chunk)
                        downloaded_size += len(chunk)
                        current_time = time.time()
                        if current_time - last_edit_time > 2:
                            last_edit_time = current_time
                            await edit_message_with_retry(status_msg, f"**Downloading...**\n`{get_readable_file_size(downloaded_size)}` of `{get_readable_file_size(total_size)}`")
    except Exception as e:
        error_trace = traceback.format_exc()
        print(f"!!! ERROR during download from URL: {e}\n{error_trace}")
        await status_msg.edit_text(f"Download Error: {e}")
        if os.path.exists(file_path): os.remove(file_path)
        return

    last_edit_time = 0
    async def progress(current, total):
        nonlocal last_edit_time
        current_time = time.time()
        if current_time - last_edit_time > 2:
            last_edit_time = current_time
            await edit_message_with_retry(status_msg, f"**Uploading...**\n`{get_readable_file_size(current)}` of `{get_readable_file_size(total)}`")

    try:
        sent_message = await client.send_document(chat_id=Config.STORAGE_CHANNEL, document=file_path, progress=progress)
    except Exception as e:
        error_trace = traceback.format_exc()
        print(f"!!! ERROR during upload to Telegram: {e}\n{error_trace}")
        await status_msg.edit_text(f"Upload to Telegram failed: {e}")
        return
    finally:
        if os.path.exists(file_path): os.remove(file_path)

    await handle_file_upload(sent_message, message.from_user.id)
    await status_msg.delete()
