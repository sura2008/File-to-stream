# database.py

import motor.motor_asyncio
import datetime
from config import Config

class Database:
    def __init__(self):
        self._client = None
        self.db = None
        self.col_links = None
        self.col_users = None

    async def connect(self):
        if Config.DATABASE_URL:
            print("Connecting to the database...")
            self._client = motor.motor_asyncio.AsyncIOMotorClient(Config.DATABASE_URL)
            self.db = self._client["StreamLinksDB"]
            self.col_links = self.db["links"]
            self.col_users = self.db["users"]
            print("✅ Database connection established.")

    async def disconnect(self):
        if self._client: self._client.close()

    # --- LINK METHODS ---
    async def save_link(self, unique_id, message_id):
        if self.col_links is not None:
            await self.col_links.insert_one({'_id': unique_id, 'message_id': message_id})

    async def get_link(self, unique_id):
        if self.col_links is not None:
            doc = await self.col_links.find_one({'_id': unique_id})
            return doc.get('message_id') if doc else None
        return None

    # --- USER & BAN SYSTEM ---
    async def add_user(self, user_id, first_name, username):
        """Adds or updates a user."""
        if self.col_users is not None:
            user_data = {
                '_id': user_id,
                'first_name': first_name,
                'username': username,
                'last_active': datetime.datetime.now()
            }
            await self.col_users.update_one({'_id': user_id}, {'$set': user_data}, upsert=True)

    async def is_user_banned(self, user_id):
        if self.col_users is not None:
            user = await self.col_users.find_one({'_id': user_id})
            return user.get('banned', False) if user else False
        return False

    async def ban_user(self, user_id):
        if self.col_users is not None:
            await self.col_users.update_one({'_id': user_id}, {'$set': {'banned': True}}, upsert=True)

    async def unban_user(self, user_id):
        if self.col_users is not None:
            await self.col_users.update_one({'_id': user_id}, {'$set': {'banned': False}})
    
    async def get_user_by_username(self, username):
        """Find a user ID by their username."""
        if self.col_users is not None:
            username = username.lstrip('@')
            user = await self.col_users.find_one({'username': {'$regex': f'^{username}$', '$options': 'i'}})
            return user['_id'] if user else None
        return None

    async def total_users_count(self):
        if self.col_users is not None:
            return await self.col_users.count_documents({})
        return 0

db = Database()
