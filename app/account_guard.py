from sqlalchemy import select
from .db import TelegramAccount, Destination, Post, Schedule
from .services import TelegramService, TelegramSessionInvalid

async def invalidate_account(session, account):
    """Remove the stored Telegram login while preserving posts for editing/deletion."""
    if not account:
        return
    account.active = False
    account.encrypted_session = ""

    destinations = (await session.execute(
        select(Destination).where(Destination.account_id == account.id)
    )).scalars().all()
    for dest in destinations:
        dest.active = False

    posts = (await session.execute(
        select(Post).where(Post.account_id == account.id)
    )).scalars().all()
    for post in posts:
        schedules = (await session.execute(
            select(Schedule).where(Schedule.post_id == post.id, Schedule.active == True)
        )).scalars().all()
        for sch in schedules:
            sch.active = False

async def validate_account(session, account, settings):
    """Return True if the stored Telegram session is still authorized.
    If Telegram revoked/logged out the session, clear the stored login and stop its schedules.
    """
    if not account or not account.active or not account.encrypted_session:
        return False
    try:
        await TelegramService(settings, settings.cipher).check_session(account.encrypted_session)
        return True
    except TelegramSessionInvalid:
        await invalidate_account(session, account)
        await session.commit()
        return False
