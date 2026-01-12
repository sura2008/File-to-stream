# config.py

import os
from dotenv import load_dotenv

load_dotenv(".env")

class Config:
    API_ID = int(os.environ.get("API_ID", 0))
    API_HASH = os.environ.get("API_HASH", "")
    BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
    OWNER_ID = int(os.environ.get("OWNER_ID", 0))
    
    # Storage Channel ID
    _storage_channel_str = os.environ.get("STORAGE_CHANNEL")
    if _storage_channel_str:
        try: STORAGE_CHANNEL = int(_storage_channel_str)
        except ValueError: STORAGE_CHANNEL = _storage_channel_str
    else: STORAGE_CHANNEL = 0
    
    # Log Channel ID (For Logs & Ban System)
    _log_channel_str = os.environ.get("LOG_CHANNEL")
    if _log_channel_str:
        try: LOG_CHANNEL = int(_log_channel_str)
        except ValueError: LOG_CHANNEL = _log_channel_str
    else: LOG_CHANNEL = 0

    # Admins List (ID separated by space)
    ADMINS = [int(x) for x in os.environ.get("ADMINS", "").split()]

    BASE_URL = os.environ.get("BASE_URL", "").rstrip('/')
    DATABASE_URL = os.environ.get("DATABASE_URL", "")
    
    # Force Subscribe Channel
    _fsub_channel_str = os.environ.get("FORCE_SUB_CHANNEL")
    if _fsub_channel_str:
        try: FORCE_SUB_CHANNEL = int(_fsub_channel_str)
        except ValueError: FORCE_SUB_CHANNEL = _fsub_channel_str
    else: FORCE_SUB_CHANNEL = 0
        
    # 🚀 MULTI-WORKER SETUP
    # Add multiple URLs separated by comma in Render Env Vars
    # Example: https://worker1.hf.space,https://worker2.hf.space
    WORKER_URLS_STR = os.environ.get("HF_WORKER_URLS", "")
    HF_WORKERS = [url.strip().rstrip('/') for url in WORKER_URLS_STR.split(',') if url.strip()]
    
    # Fallback if user uses old variable
    if not HF_WORKERS and os.environ.get("HF_WORKER_URL"):
        HF_WORKERS = [os.environ.get("HF_WORKER_URL", "").rstrip('/')]

    BOT_USERNAME = ""
    
