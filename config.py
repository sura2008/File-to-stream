import os
from dotenv import load_dotenv

load_dotenv(".env")

class Config:
    API_ID = int(os.environ.get("API_ID", 0))
    API_HASH = os.environ.get("API_HASH", "")
    BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
    
    # Storage & Log Channels
    try: STORAGE_CHANNEL = int(os.environ.get("STORAGE_CHANNEL", 0))
    except: STORAGE_CHANNEL = 0
    
    try: LOG_CHANNEL = int(os.environ.get("LOG_CHANNEL", 0))
    except: LOG_CHANNEL = 0
    
    try: LOG_CHANNEL_2 = int(os.environ.get("LOG_CHANNEL_2", 0))
    except: LOG_CHANNEL_2 = 0

    # Auto-Upload Channels
    raw_channels = os.environ.get("AUTO_UPLOAD_CHANNELS", "")
    AUTO_UPLOAD_CHANNELS = []
    if raw_channels:
        for x in raw_channels.replace(",", " ").split():
            clean_x = x.strip()
            if clean_x.lstrip('-').isdigit():
                AUTO_UPLOAD_CHANNELS.append(int(clean_x))

    ADMINS = [int(x) for x in os.environ.get("ADMINS", "").split()]

    BASE_URL = os.environ.get("BASE_URL", "").rstrip('/')
    DATABASE_URL = os.environ.get("DATABASE_URL", "")
    
    try: FORCE_SUB_CHANNEL = int(os.environ.get("FORCE_SUB_CHANNEL", 0))
    except: FORCE_SUB_CHANNEL = 0
        
    # ---------------------------------------------------------
    # 🔄 CONTROLLER (For File Uploading / Auto-Upload)
    # ---------------------------------------------------------
    # Kept your original variable name for backward compatibility
    raw_upload_urls = os.environ.get("HF_WORKERS", "") 
    HF_UPLOAD_WORKERS = [url.strip().rstrip('/') for url in raw_upload_urls.split(",") if url.strip()]

    # ---------------------------------------------------------
    # 🚀 STREAMING WORKERS (For File Streaming / Download) [NEW]
    # ---------------------------------------------------------
    # Renamed to avoid conflict. Set this in Render Env Vars.
    raw_stream_urls = os.environ.get("HF_STREAMING_URLS", "")
    if not raw_stream_urls:
        raw_stream_urls = os.environ.get("HF_STREAMING_WORKER", "") # Singular fallback
        
    HF_STREAMING_URLS = [url.strip().rstrip('/') for url in raw_stream_urls.split(",") if url.strip()]
    
    # 🔍 Debugging Prints
    if not HF_UPLOAD_WORKERS:
        print("⚠️ Config: No Upload Controller found (HF_WORKERS). Auto-upload disabled.")
    else:
        print(f"✅ Config: Upload Controllers Loaded: {len(HF_UPLOAD_WORKERS)}")

    if not HF_STREAMING_URLS:
        print("⚠️ Config: No Streaming Workers found (HF_STREAMING_URLS). Using Render fallback.")
    else:
        print(f"✅ Config: Streaming Workers Loaded: {len(HF_STREAMING_URLS)}")
        
