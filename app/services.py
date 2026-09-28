import asyncio, tempfile, os
from pathlib import Path
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError
from .security import SessionCipher

class TelegramService:
    def __init__(self, settings, cipher): self.settings=settings; self.cipher=cipher
    def client(self, session_string=""):
        return TelegramClient(StringSession(session_string), self.settings.api_id, self.settings.api_hash)
    async def login_send_code(self, phone):
        c=self.client(); await c.connect()
        try:
            sent=await c.send_code_request(phone)
            return c, sent.phone_code_hash
        except Exception:
            await c.disconnect(); raise
    async def login_code(self, client, phone, code, phone_code_hash):
        try:
            await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
        except SessionPasswordNeededError:
            return None, None, True
        me=await client.get_me()
        return me, client.session.save(), False

    async def login_password(self, client, password):
        await client.sign_in(password=password)
        me=await client.get_me()
        session=client.session.save()
        await client.disconnect()
        return me, session
    async def check_session(self, encrypted):
        session=self.cipher.decrypt(encrypted)
        c=self.client(session); await c.connect()
        try:
            me=await c.get_me()
            return me
        finally: await c.disconnect()
    async def publish(self, encrypted, chat_id, text=None, local_file=None):
        session=self.cipher.decrypt(encrypted)
        c=self.client(session); await c.connect()
        try:
            if local_file:
                return await c.send_file(chat_id, local_file, caption=text or "")
            return await c.send_message(chat_id, text or "")
        finally: await c.disconnect()
