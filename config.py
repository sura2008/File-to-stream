import os
from dotenv import load_dotenv

load_dotenv(".env")

class Config:
    API_ID = int(os.environ.get("API_ID", 0))
    API_HASH = os.environ.get("API_HASH", "")
    BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
    
    # Storage Channel (Files are copied here)
    try: STORAGE_CHANNEL = int(os.environ.get("STORAGE_CHANNEL", 0))
    except: STORAGE_CHANNEL = 0
    
    # Log Channel 1 (For Stream/Download logs)
    try: LOG_CHANNEL = int(os.environ.get("LOG_CHANNEL", 0))
    except: LOG_CHANNEL = 0

    # 🆕 Log Channel 2 (For Permanent Link logs)
    try: LOG_CHANNEL_2 = int(os.environ.get("LOG_CHANNEL_2", 0))
    except: LOG_CHANNEL_2 = 0

    # 🆕 Auto-Upload Channel (Bot monitors this)
    try: AUTO_UPLOAD_CHANNEL = int(os.environ.get("AUTO_UPLOAD_CHANNEL", 0))
    except: AUTO_UPLOAD_CHANNEL = 0

    ADMINS = [int(x) for x in os.environ.get("ADMINS", "").split()]

    BASE_URL = os.environ.get("BASE_URL", "").rstrip('/')
    DATABASE_URL = os.environ.get("DATABASE_URL", "")
    
    try: FORCE_SUB_CHANNEL = int(os.environ.get("FORCE_SUB_CHANNEL", 0))
    except: FORCE_SUB_CHANNEL = 0
        
    # Controller URL (Medium Worker)
    HF_WORKERS = os.environ.get("HF_WORKER_URLS", "").split(",")
    
