from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError

class TelegramService:
    def __init__(self, settings, cipher):
        self.settings = settings
        self.cipher = cipher

    def client(self, session_string=""):
        return TelegramClient(
            StringSession(session_string),
            self.settings.api_id,
            self.settings.api_hash,
        )

    async def login_send_code(self, phone):
        c = self.client()
        await c.connect()
        try:
            sent = await c.send_code_request(phone)
            return c, sent.phone_code_hash
        except Exception:
            await c.disconnect()
            raise

    async def login_code(self, client, phone, code, phone_code_hash):
        try:
            await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
        except SessionPasswordNeededError:
            return None, None, True
        me = await client.get_me()
        session = client.session.save()
        await client.disconnect()
        return me, session, False

    async def login_password(self, client, password):
        await client.sign_in(password=password)
        me = await client.get_me()
        session = client.session.save()
        await client.disconnect()
        return me, session

    async def check_session(self, encrypted):
        session = self.cipher.decrypt(encrypted)
        c = self.client(session)
        await c.connect()
        try:
            return await c.get_me()
        finally:
            await c.disconnect()

    async def resolve_group(self, encrypted, chat):
        session = self.cipher.decrypt(encrypted)
        c = self.client(session)
        await c.connect()
        try:
            ent = await c.get_entity(chat)
            # Telegram channels are Channel objects with broadcast=True.
            # Megagroups have megagroup=True and are allowed.
            if getattr(ent, "broadcast", False):
                raise ValueError("القنوات غير مدعومة. أضف كروب/مجموعة فقط.")
            title = getattr(ent, "title", None) or getattr(ent, "username", None) or str(chat)
            cid = str(getattr(ent, "id", chat))
            return cid, title
        finally:
            await c.disconnect()

    async def publish(self, encrypted, chat_id, text=None, local_file=None):
        session = self.cipher.decrypt(encrypted)
        c = self.client(session)
        await c.connect()
        try:
            if local_file:
                return await c.send_file(chat_id, local_file, caption=text or "")
            return await c.send_message(chat_id, text or "")
        finally:
            await c.disconnect()
