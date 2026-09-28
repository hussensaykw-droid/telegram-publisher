import asyncio, logging, tempfile, os, random
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from aiogram import Bot, Dispatcher, BaseMiddleware
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy import select
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from .config import load_settings
from .db import init_db, Schedule, ScheduleConfig, Post, PostDestination, Destination, TelegramAccount
from .security import SessionCipher
from .bot import router
from .schedule_ui import router as schedule_router
from .services import TelegramService
logging.basicConfig(level=logging.INFO)

async def publish_due(bot, session_factory, settings, cipher):
    now = datetime.now(ZoneInfo(settings.timezone)).replace(tzinfo=None)
    async with session_factory() as s:
        rows = (await s.execute(select(Schedule).where(Schedule.active == True, Schedule.next_run_at <= now))).scalars().all()
        for sch in rows:
            post = await s.get(Post, sch.post_id)
            if not post or not post.active:
                sch.active = False
                await s.commit(); continue
            cfg = (await s.execute(select(ScheduleConfig).where(ScheduleConfig.schedule_id == sch.id))).scalar_one_or_none()
            dests = (await s.execute(select(Destination).join(PostDestination, PostDestination.destination_id == Destination.id).where(PostDestination.post_id == post.id, Destination.active == True))).scalars().all()
            acct = await s.get(TelegramAccount, post.account_id)
            if not acct or not acct.active:
                sch.active = False
                await s.commit(); continue
            tmp = None
            published_any = False
            try:
                if not dests:
                    logging.warning('schedule %s has no active destinations; waiting for one to be enabled', sch.id)
                else:
                    if post.media_file_id:
                        f = await bot.get_file(post.media_file_id)
                        fd, tmp = tempfile.mkstemp(suffix='.jpg'); os.close(fd)
                        await bot.download_file(f.file_path, tmp)
                    svc = TelegramService(settings, cipher)
                    for d in dests:
                        try:
                            await svc.publish(acct.encrypted_session, d.chat_id, post.text, tmp)
                            published_any = True
                            await asyncio.sleep(1)
                        except Exception:
                            logging.exception('destination publish failed for schedule %s, destination %s (%s)', sch.id, d.id, d.title)
                    if published_any and cfg:
                        cfg.published_count += 1
            except Exception:
                logging.exception('scheduled publish failed for schedule %s', sch.id)
            finally:
                if tmp:
                    try: os.remove(tmp)
                    except OSError: pass
            if cfg:
                if cfg.publish_limit > 0 and cfg.published_count >= cfg.publish_limit:
                    sch.active = False
                else:
                    delay = random.randint(cfg.min_interval_seconds, cfg.max_interval_seconds)
                    sch.next_run_at = now + timedelta(seconds=delay)
            elif sch.interval_minutes > 0:
                while sch.next_run_at <= now:
                    sch.next_run_at += timedelta(minutes=sch.interval_minutes)
            else:
                sch.active = False
            await s.commit()

async def main():
    settings = load_settings()
    Path('data').mkdir(exist_ok=True)
    cipher = SessionCipher(settings.encryption_key)
    settings = type(settings)(**{**settings.__dict__, 'cipher': cipher})
    engine, sf = await init_db(settings.database_url)
    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    class MW(BaseMiddleware):
        async def __call__(self, handler, event, data):
            async with sf() as session:
                data['session'] = session
                data['settings'] = settings
                return await handler(event, data)
    schedule_router.message.middleware(MW())
    schedule_router.callback_query.middleware(MW())
    router.message.middleware(MW())
    router.callback_query.middleware(MW())
    dp.include_router(schedule_router)
    dp.include_router(router)
    scheduler = AsyncIOScheduler(timezone=settings.timezone)
    scheduler.add_job(publish_due, 'interval', seconds=10, args=[bot, sf, settings, cipher], max_instances=1, coalesce=True)
    scheduler.start()
    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()
        await engine.dispose()
if __name__ == '__main__':
    asyncio.run(main())
