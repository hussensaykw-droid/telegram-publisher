from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import (
    SessionPasswordNeededError,
    AuthKeyUnregisteredError,
    SessionRevokedError,
    UserDeactivatedError,
    UserDeactivatedBanError,
    UnauthorizedError,
)
from telethon.tl.types import InputPeerChannel, InputPeerChat, Channel, Chat

class TelegramSessionInvalid(Exception):
    """Stored Telegram session is no longer authorized."""


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
        try:
            session = self.cipher.decrypt(encrypted)
            c = self.client(session)
            await c.connect()
            try:
                me = await c.get_me()
                if me is None:
                    raise TelegramSessionInvalid("Telegram session is no longer authorized")
                return me
            finally:
                await c.disconnect()
        except (AuthKeyUnregisteredError, SessionRevokedError, UserDeactivatedError, UserDeactivatedBanError, UnauthorizedError) as e:
            raise TelegramSessionInvalid("Telegram session is no longer authorized") from e

    @staticmethod
    def encode_entity(ent):
        """Persist enough Telegram peer data to address a private group later."""
        if isinstance(ent, Channel):
            if getattr(ent, "broadcast", False):
                raise ValueError("القنوات غير مدعومة. أضف كروب/مجموعة فقط.")
            if not getattr(ent, "megagroup", False):
                raise ValueError("هذا ليس كروباً/مجموعة مدعومة.")
            access_hash = getattr(ent, "access_hash", None)
            if access_hash is None:
                raise ValueError("تعذر الحصول على بيانات الكروب من Telegram.")
            return f"channel:{ent.id}:{access_hash}"
        if isinstance(ent, Chat):
            return f"chat:{ent.id}"
        raise ValueError("أرسل كروب/مجموعة Telegram وليس حساباً شخصياً أو قناة.")

    async def resolve_group(self, encrypted, chat):
        session = self.cipher.decrypt(encrypted)
        c = self.client(session)
        await c.connect()
        try:
            ent = await c.get_entity(chat)
            ref = self.encode_entity(ent)
            title = getattr(ent, "title", None) or getattr(ent, "username", None) or str(chat)
            return ref, title
        finally:
            await c.disconnect()

    async def refresh_saved_group(self, encrypted, saved_ref):
        """Repair old numeric destination IDs by finding the entity in the account dialogs."""
        session = self.cipher.decrypt(encrypted)
        c = self.client(session)
        await c.connect()
        try:
            ref = str(saved_ref or "").strip()
            ent = None
            if ref.startswith("channel:"):
                _, cid, access_hash = ref.split(":", 2)
                ent = await c.get_entity(InputPeerChannel(int(cid), int(access_hash)))
            elif ref.startswith("chat:"):
                _, cid = ref.split(":", 1)
                ent = await c.get_entity(InputPeerChat(int(cid)))
            else:
                target = int(ref)
                async for dialog in c.iter_dialogs():
                    e = dialog.entity
                    if getattr(e, "id", None) == target:
                        ent = e
                        break
                if ent is None:
                    raise ValueError(f'Cannot find any entity corresponding to "{ref}"')
            new_ref = self.encode_entity(ent)
            title = getattr(ent, "title", None) or getattr(ent, "username", None) or ref
            return new_ref, title
        finally:
            await c.disconnect()

    async def publish(self, encrypted, chat_id, text=None, local_file=None):
        try:
            session = self.cipher.decrypt(encrypted)
            c = self.client(session)
            await c.connect()
            try:
                ref = str(chat_id or "").strip()
                peer = None
                if ref.startswith("channel:"):
                    _, cid, access_hash = ref.split(":", 2)
                    peer = InputPeerChannel(int(cid), int(access_hash))
                elif ref.startswith("chat:"):
                    _, cid = ref.split(":", 1)
                    peer = InputPeerChat(int(cid))
                else:
                    # Backward compatibility for destinations saved before entity refs.
                    target = int(ref)
                    async for dialog in c.iter_dialogs():
                        e = dialog.entity
                        if getattr(e, "id", None) == target:
                            peer = e
                            break
                    if peer is None:
                        raise ValueError(f'Cannot find any entity corresponding to "{ref}"')
                if local_file:
                    return await c.send_file(peer, local_file, caption=text or "")
                return await c.send_message(peer, text or "")
            finally:
                await c.disconnect()
        except (AuthKeyUnregisteredError, SessionRevokedError, UserDeactivatedError, UserDeactivatedBanError, UnauthorizedError) as e:
            raise TelegramSessionInvalid("Telegram session is no longer authorized") from e
