# config.py (FINAL VERSION)

import os
from dotenv import load_dotenv

load_dotenv(".env")

class Config:
    API_ID = int(os.environ.get("API_ID", 0))
    API_HASH = os.environ.get("API_HASH", "")
    BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
    OWNER_ID = int(os.environ.get("OWNER_ID", 0))
    
    # --- YEH CODE USERNAME AUR ID DONO HANDLE KAR LEGA ---
    _storage_channel_str = os.environ.get("STORAGE_CHANNEL")
    if _storage_channel_str:
        try:
            # Pehle try karo ki yeh ek number (ID) hai
            STORAGE_CHANNEL = int(_storage_channel_str)
        except ValueError:
            # Agar number nahi hai, toh yeh ek username (string) hai
            STORAGE_CHANNEL = _storage_channel_str
    else:
        STORAGE_CHANNEL = 0 # Default value agar set na ho
    # --- BADLAV KHATAM ---
    
    BASE_URL = os.environ.get("BASE_URL", "").rstrip('/')
    DATABASE_URL = os.environ.get("DATABASE_URL", "")
    BLOGGER_PAGE_URL = os.environ.get("BLOGGER_PAGE_URL", "")
