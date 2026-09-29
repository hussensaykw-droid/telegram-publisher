import re
from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select, delete
from telethon import TelegramClient
from .db import User, TelegramAccount, Destination, Post, PostDestination, Schedule, Draft
from .keyboards import *
from .states import AccountFlow, DestFlow, PostFlow
from .services import TelegramService
from .account_guard import validate_account, invalidate_account

router = Router()

def norm_phone(s):
    trans = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹","01234567890123456789")
    s = (s or "").translate(trans).strip().replace(" ","").replace("-","").replace("(","").replace(")","")
    if s.startswith("00"): s = "+" + s[2:]
    if not s.startswith("+"): s = "+" + s
    if not re.fullmatch(r"\+[1-9]\d{7,14}", s):
        raise ValueError("رقم الهاتف غير صحيح. مثال: +9647XXXXXXXXX")
    return s

async def get_user(session, tid, owner):
    u = (await session.execute(select(User).where(User.telegram_id == tid))).scalar_one_or_none()
    if not u:
        u = User(telegram_id=tid, role="owner" if tid == owner else "user", active=(tid == owner))
        session.add(u)
        await session.commit()
    return u

async def valid_accounts(session, u, settings):
    accounts = (await session.execute(
        select(TelegramAccount).where(
            TelegramAccount.owner_user_id == u.id,
            TelegramAccount.active == True
        )
    )).scalars().all()
    valid = []
    removed = 0
    for account in accounts:
        if await validate_account(session, account, settings):
            valid.append(account)
        else:
            removed += 1
    return valid, removed

async def get_valid_account(session, u, account_id, settings):
    account = (await session.execute(select(TelegramAccount).where(
        TelegramAccount.id == account_id,
        TelegramAccount.owner_user_id == u.id,
        TelegramAccount.active == True
    ))).scalar_one_or_none()
    if not account:
        return None, False
    ok = await validate_account(session, account, settings)
    return (account if ok else None), (not ok)

async def home(message, session, settings):
    u = await get_user(session, message.from_user.id, settings.owner_id)
    if not u.active:
        return await message.answer("⏳ طلبك بانتظار موافقة المالك.")
    await message.answer("🐣 أهلاً بك في لوحة التحكم", reply_markup=main_menu(u.role == "owner"))

@router.message(CommandStart())
async def start(message, state, session, settings):
    await state.clear()
    await home(message, session, settings)

@router.callback_query(F.data == "home")
async def cb_home(call, state, session, settings):
    await call.answer()
    await state.clear()
    u = await get_user(session, call.from_user.id, settings.owner_id)
    if not u.active:
        return await call.message.edit_text("⏳ طلبك بانتظار موافقة المالك.")
    await call.message.edit_text("🐣 لوحة التحكم", reply_markup=main_menu(u.role == "owner"))

@router.callback_query(F.data == "info")
async def info(call):
    await call.answer()
    await call.message.edit_text(
        "ℹ️ النشر يتم من حساب Telegram الشخصي عبر MTProto.\n"
        "الجلسة محفوظة مشفّرة في قاعدة البيانات.\n"
        "أماكن النشر هنا كروبات/مجموعات فقط، وليس قنوات.",
        reply_markup=back()
    )

@router.callback_query(F.data == "cancel")
async def cancel(call, state):
    await call.answer("تم الإلغاء")
    await state.clear()
    await call.message.edit_text("تم الإلغاء.", reply_markup=back())

# ---------- Account ----------
@router.callback_query(F.data == "accounts")
async def accounts(call, session, settings):
    u = await get_user(session, call.from_user.id, settings.owner_id)
    if not u.active:
        return await call.answer("حسابك غير مفعّل", show_alert=True)
    rows, removed = await valid_accounts(session, u, settings)
    await call.answer()
    note = "\n\n⚠️ تم اكتشاف حساب Telegram خرج من الجلسات، فانحذفت جلسة دخوله من البوت. سجّل الدخول من جديد حتى تستخدمه." if removed else ""
    await call.message.edit_text("👤 حساباتي\n\nالحسابات المحفوظة تبقى بعد إعادة تشغيل البوت." + note,
                                 reply_markup=accounts_kb(rows))

@router.callback_query(F.data == "account_add")
async def account_add(call, state):
    await call.answer()
    await state.set_state(AccountFlow.phone)
    await call.message.edit_text(
        "📱 أرسل رقم حساب Telegram بصيغة دولية.\nمثال: +9647XXXXXXXXX",
        reply_markup=cancel_kb()
    )

@router.message(AccountFlow.phone)
async def account_phone(message, state, settings):
    try:
        phone = norm_phone(message.text)
    except ValueError as e:
        return await message.answer(f"❌ {e}")
    svc = TelegramService(settings, settings.cipher)
    try:
        client, phone_hash = await svc.login_send_code(phone)
    except Exception as e:
        return await message.answer(f"❌ تعذر إرسال رمز الدخول.\n{type(e).__name__}")
    await state.update_data(phone=phone, phone_hash=phone_hash, login_client=client)
    await state.set_state(AccountFlow.code)
    await message.answer("📨 تم طلب رمز الدخول. أرسل الرمز هنا فقط.")

@router.message(AccountFlow.code)
async def account_code(message, state, session, settings):
    d = await state.get_data()
    client = d.get("login_client")
    if not client:
        return await message.answer("انتهت جلسة تسجيل الدخول. أعد الربط.")
    try:
        me, sess, needs_password = await TelegramService(settings, settings.cipher).login_code(
            client, d["phone"], (message.text or "").strip().replace(" ",""), d["phone_hash"]
        )
        if needs_password:
            await state.set_state(AccountFlow.password)
            return await message.answer("🔐 الحساب عليه تحقق بخطوتين. أرسل كلمة مرور 2FA.")
    except Exception as e:
        return await message.answer(f"❌ رمز الدخول غير صحيح أو انتهت الجلسة.\n{type(e).__name__}")
    await state.update_data(session=sess)
    await state.set_state(AccountFlow.title)
    await message.answer("✅ تم تسجيل الدخول. أرسل اسماً للحساب.")

@router.message(AccountFlow.password)
async def account_password(message, state, settings):
    d = await state.get_data()
    client = d.get("login_client")
    if not client:
        return await message.answer("انتهت جلسة تسجيل الدخول. أعد الربط.")
    try:
        me, sess = await TelegramService(settings, settings.cipher).login_password(client, message.text)
    except Exception as e:
        return await message.answer(f"❌ كلمة مرور 2FA غير صحيحة.\n{type(e).__name__}")
    await state.update_data(session=sess)
    await state.set_state(AccountFlow.title)
    await message.answer("✅ تم التحقق. أرسل اسماً للحساب.")

@router.message(AccountFlow.title)
async def account_title(message, state, session, settings):
    d = await state.get_data()
    u = await get_user(session, message.from_user.id, settings.owner_id)
    if not u.active:
        await state.clear()
        return await message.answer("⛔ حسابك غير مفعّل.")
    a = TelegramAccount(
        owner_user_id=u.id,
        title=(message.text or "حساب Telegram")[:128],
        phone=d["phone"],
        encrypted_session=settings.cipher.encrypt(d["session"]),
    )
    session.add(a)
    await session.commit()
    await state.clear()
    await message.answer("🎉 تم حفظ حساب Telegram بشكل دائم.", reply_markup=main_menu(u.role == "owner"))

# ---------- Destinations: groups only ----------
@router.callback_query(F.data == "destinations")
async def destinations(call, session, settings):
    u = await get_user(session, call.from_user.id, settings.owner_id)
    rows = (await session.execute(
        select(Destination).where(Destination.owner_user_id == u.id).order_by(Destination.id.asc())
    )).scalars().all()
    await call.answer()
    if not rows:
        text = "📍 لا توجد كروبات محفوظة.\n\nأضف كروب حتى يظهر هنا."
    else:
        active = sum(1 for d in rows if d.active)
        paused = len(rows) - active
        text = (
            "📍 أماكن النشر\n\n"
            f"🟢 مفعّلة: {active} | ⏸️ متوقفة: {paused}\n\n"
            "اضغط ⏸️ لإزالة الكروب مؤقتاً، واضغط ▶️ لإرجاعه بأي وقت.\n"
            "🔄 تحديث بيانات الكروب يصلح الوجهات القديمة أيضاً."
        )
    await call.message.edit_text(text, reply_markup=destinations_kb(rows))

@router.callback_query(F.data == "dest_add")
async def dest_add(call, state, session, settings):
    u = await get_user(session, call.from_user.id, settings.owner_id)
    accts, removed = await valid_accounts(session, u, settings)
    if not accts:
        msg = "لا يوجد حساب Telegram صالح. أضف الحساب وسجّل الدخول من جديد." if removed else "أضف حساباً شخصياً أولاً"
        return await call.answer(msg, show_alert=True)
    rows = [[InlineKeyboardButton(text=a.title, callback_data=f"dacc:{a.id}")] for a in accts]
    rows.append([InlineKeyboardButton(text="❌ إلغاء", callback_data="cancel")])
    await state.set_state(DestFlow.account)
    await call.answer()
    await call.message.edit_text("اختر الحساب الذي ينتمي للكروب:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

@router.callback_query(F.data.startswith("dacc:"))
async def dest_account(call, state):
    await call.answer()
    await state.update_data(account_id=int(call.data.split(":")[1]))
    await state.set_state(DestFlow.chat)
    await call.message.edit_text(
        "📍 أرسل @username للكروب.\n"
        "وللكروب الخاص أرسل chat_id إذا كان معروفاً.\n\n"
        "سيتم حفظ بيانات Telegram الداخلية للكروب حتى يقدر الحساب ينشر فيه لاحقاً."
    )

@router.message(DestFlow.chat)
async def dest_chat(message, state, session, settings):
    d = await state.get_data()
    u = await get_user(session, message.from_user.id, settings.owner_id)
    a = (await session.execute(select(TelegramAccount).where(
        TelegramAccount.id == d["account_id"],
        TelegramAccount.owner_user_id == u.id
    ))).scalar_one_or_none()
    if not a:
        return await message.answer("الحساب غير موجود.")
    if not await validate_account(session, a, settings):
        return await message.answer("⚠️ جلسة حساب Telegram منتهية أو تم تسجيل خروجها. سجّل الدخول للحساب من جديد ثم أضف الكروب.")
    try:
        cid, title = await TelegramService(settings, settings.cipher).resolve_group(
            a.encrypted_session, (message.text or "").strip()
        )
        existing = (await session.execute(select(Destination).where(
            Destination.owner_user_id == u.id,
            Destination.account_id == a.id,
            Destination.chat_id == cid
        ))).scalar_one_or_none()
        if existing:
            existing.title = title
            existing.active = True
        else:
            session.add(Destination(
                owner_user_id=u.id, account_id=a.id, chat_id=cid, title=title, active=True
            ))
        await session.commit()
    except Exception as e:
        await session.rollback()
        return await message.answer(f"❌ لم أستطع حفظ الكروب.\n{e}")
    await state.clear()
    await message.answer(f"✅ تم حفظ الكروب: {title}\n\nتقدر توقفه أو ترجعه من 📍 أماكن النشر.", reply_markup=main_menu(u.role == "owner"))

@router.callback_query(F.data.startswith("dest_toggle:"))
async def dest_toggle(call, session, settings):
    u = await get_user(session, call.from_user.id, settings.owner_id)
    did = int(call.data.split(":")[1])
    dest = (await session.execute(select(Destination).where(
        Destination.id == did, Destination.owner_user_id == u.id
    ))).scalar_one_or_none()
    if not dest:
        return await call.answer("الكروب غير موجود.", show_alert=True)
    dest.active = not dest.active
    await session.commit()
    await call.answer("▶️ تم إرجاع الكروب" if dest.active else "⏸️ تم إيقاف الكروب")
    rows = (await session.execute(
        select(Destination).where(Destination.owner_user_id == u.id).order_by(Destination.id.asc())
    )).scalars().all()
    await call.message.edit_text(
        "📍 أماكن النشر\n\n"
        "اضغط ⏸️ لإزالة الكروب مؤقتاً، واضغط ▶️ لإرجاعه بأي وقت.\n"
        "🔄 تحديث بيانات الكروب يصلح الوجهات القديمة أيضاً.",
        reply_markup=destinations_kb(rows)
    )

@router.callback_query(F.data.startswith("dest_refresh:"))
async def dest_refresh(call, session, settings):
    u = await get_user(session, call.from_user.id, settings.owner_id)
    did = int(call.data.split(":")[1])
    dest = (await session.execute(select(Destination).where(
        Destination.id == did, Destination.owner_user_id == u.id
    ))).scalar_one_or_none()
    if not dest:
        return await call.answer("الكروب غير موجود.", show_alert=True)
    acct = (await session.execute(select(TelegramAccount).where(
        TelegramAccount.id == dest.account_id, TelegramAccount.owner_user_id == u.id, TelegramAccount.active == True
    ))).scalar_one_or_none()
    if not acct:
        return await call.answer("حساب Telegram المرتبط غير موجود أو متوقف.", show_alert=True)
    await call.answer("🔄 جاري تحديث بيانات الكروب...")
    try:
        new_ref, title = await TelegramService(settings, settings.cipher).refresh_saved_group(
            acct.encrypted_session, dest.chat_id
        )
        dest.chat_id = new_ref
        dest.title = title
        await session.commit()
    except Exception as e:
        await session.rollback()
        return await call.answer(f"تعذر تحديث الكروب: {type(e).__name__}", show_alert=True)
    rows = (await session.execute(
        select(Destination).where(Destination.owner_user_id == u.id).order_by(Destination.id.asc())
    )).scalars().all()
    await call.message.edit_text(
        f"✅ تم تحديث بيانات: {title}\n\n"
        "تقدر توقفه أو ترجعه بأي وقت من الأزرار أدناه.",
        reply_markup=destinations_kb(rows)
    )

@router.callback_query(F.data.startswith("destinfo:"))
async def dest_info(call, session, settings):
    u = await get_user(session, call.from_user.id, settings.owner_id)
    did = int(call.data.split(":")[1])
    dest = (await session.execute(select(Destination).where(
        Destination.id == did, Destination.owner_user_id == u.id
    ))).scalar_one_or_none()
    if not dest:
        return await call.answer("الكروب غير موجود.", show_alert=True)
    await call.answer()
    state = "🟢 مفعّل" if dest.active else "⏸️ متوقف"
    await call.message.edit_text(
        f"📍 {dest.title}\n\nالحالة: {state}\nرقم الحفظ: #{dest.id}\n\n"
        "زر الإيقاف/الإرجاع يتحكم باستخدام الكروب في المنشورات الجديدة والجدولات.",
        reply_markup=destinations_kb([dest])
    )

# ---------- Persistent drafts/posts ----------
@router.callback_query(F.data == "post_add")
async def post_add(call, state, session, settings):
    u = await get_user(session, call.from_user.id, settings.owner_id)
    if not u.active:
        return await call.answer("حسابك غير مفعّل", show_alert=True)
    accts, removed = await valid_accounts(session, u, settings)
    if not accts:
        return await call.answer("⚠️ لازم يكون عندك حساب Telegram صالح ومسجّل دخول. أضف الحساب من 👤 حساباتي.", show_alert=True)
    await state.set_state(PostFlow.draft)
    await call.answer()
    await call.message.edit_text(
        "➕ أرسل نص المنشور، أو أرسل صورة مع الوصف.\n"
        "سيتم حفظ المنشور مباشرة حتى لو خرجت من البوت.",
        reply_markup=cancel_kb()
    )

@router.message(PostFlow.draft)
async def post_draft(message, state, session, settings):
    u = await get_user(session, message.from_user.id, settings.owner_id)
    if message.photo:
        text = message.caption or ""
        media = message.photo[-1].file_id
    elif message.text:
        text = message.text
        media = None
    else:
        return await message.answer("أرسل نصاً أو صورة فقط.")
    draft = Draft(owner_user_id=u.id, text=text, media_file_id=media)
    session.add(draft)
    await session.commit()
    await state.update_data(draft_id=draft.id)
    await state.set_state(PostFlow.account)
    await message.answer(f"💾 تم حفظ المنشور #{draft.id}.\nالآن اختر الحساب للنشر.")

@router.message(PostFlow.account)
async def post_account_text(message, state, session, settings):
    if (message.text or "").strip() != "اختيار الحساب":
        return await message.answer("اكتب: اختيار الحساب")
    u = await get_user(session, message.from_user.id, settings.owner_id)
    accts, removed = await valid_accounts(session, u, settings)
    if not accts:
        return await message.answer("⚠️ لا توجد حسابات Telegram صالحة. سجّل الدخول من جديد.")
    rows = [[InlineKeyboardButton(text=f"📱 {a.title}", callback_data=f"postacct:{a.id}")]
            for a in accts]
    rows.append([InlineKeyboardButton(text="❌ إلغاء", callback_data="cancel")])
    await message.answer("اختر الحساب:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

@router.callback_query(F.data.startswith("postacct:"))
async def post_account(call, state, session, settings):
    await call.answer()
    d = await state.get_data()
    account_id = int(call.data.split(":")[1])
    u = await get_user(session, call.from_user.id, settings.owner_id)
    acct, removed = await get_valid_account(session, u, account_id, settings)
    if not acct:
        return await call.message.edit_text("⚠️ جلسة حساب Telegram منتهية. سجّل الدخول للحساب من جديد قبل استخدامه.", reply_markup=back())
    ds = (await session.execute(select(Destination).where(
        Destination.owner_user_id == u.id,
        Destination.account_id == account_id,
        Destination.active == True
    ))).scalars().all()
    if not ds:
        return await call.message.edit_text("لا توجد كروبات محفوظة لهذا الحساب.", reply_markup=back())
    await state.update_data(account_id=account_id)
    await state.set_state(PostFlow.destinations)
    await call.message.edit_text(
        "اختر أرقام الكروبات مفصولة بفواصل:\n" +
        "\n".join(f"{x.id} — {x.title}" for x in ds) +
        "\n\nمثال: 1,2"
    )

@router.message(PostFlow.destinations)
async def post_destinations(message, state, session, settings):
    d = await state.get_data()
    u = await get_user(session, message.from_user.id, settings.owner_id)
    try:
        ids = [int(x.strip()) for x in (message.text or "").split(",") if x.strip()]
    except ValueError:
        return await message.answer("اكتب أرقاماً مثل: 1,2")
    ds = (await session.execute(select(Destination).where(
        Destination.id.in_(ids),
        Destination.owner_user_id == u.id,
        Destination.account_id == d["account_id"],
        Destination.active == True
    ))).scalars().all()
    if len(ds) != len(ids):
        return await message.answer("بعض أرقام الكروبات غير صحيحة.")
    await state.update_data(dest_ids=ids)
    await state.set_state(PostFlow.when)
    await message.answer("⏰ أرسل موعد أول نشر:\nYYYY-MM-DD HH:MM\nمثال: 2026-09-28 20:30")

@router.message(PostFlow.when)
async def post_when(message, state, settings):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    d = await state.get_data()
    try:
        dt = datetime.strptime((message.text or "").strip(), "%Y-%m-%d %H:%M")
        dt = dt.replace(tzinfo=ZoneInfo(settings.timezone)).replace(tzinfo=None)
    except ValueError:
        return await message.answer("❌ الصيغة خطأ. مثال: 2026-09-28 20:30")
    if dt < datetime.now(ZoneInfo(settings.timezone)).replace(tzinfo=None):
        return await message.answer("❌ الموعد صار بالماضي.")
    await state.update_data(next_run_at=dt.isoformat())
    await state.set_state(PostFlow.repeat)
    await message.answer(
        "🔁 كم دقيقة بين كل نشر؟\n"
        "اكتب 0 = مرة واحدة.\n"
        "اكتب 5 = إرسال نفس المنشور كل 5 دقائق."
    )

@router.message(PostFlow.repeat)
async def post_repeat(message, state, session, settings):
    from datetime import datetime
    d = await state.get_data()
    try:
        repeat = int((message.text or "").strip())
    except ValueError:
        return await message.answer("❌ اكتب رقماً بالدقائق.")
    if repeat < 0:
        return await message.answer("❌ الرقم لا يمكن أن يكون سالباً.")
    u = await get_user(session, message.from_user.id, settings.owner_id)
    account, removed = await get_valid_account(session, u, d.get("account_id"), settings)
    if not account:
        await state.clear()
        return await message.answer("⚠️ جلسة حساب Telegram منتهية. تم حذف جلسة الدخول من البوت. سجّل الحساب من جديد ثم أعد إنشاء النشر.")
    draft = await session.get(Draft, d["draft_id"])
    if not draft or not draft.active:
        return await message.answer("❌ المنشور المحفوظ غير موجود.")
    p = Post(
        owner_user_id=u.id,
        account_id=d["account_id"],
        text=draft.text,
        media_file_id=draft.media_file_id
    )
    session.add(p)
    await session.flush()
    for did in d["dest_ids"]:
        session.add(PostDestination(post_id=p.id, destination_id=did))
    dt = datetime.fromisoformat(d["next_run_at"])
    session.add(Schedule(post_id=p.id, interval_minutes=repeat, next_run_at=dt, active=True))
    draft.active = False
    await session.commit()
    await state.clear()
    await message.answer(
        f"✅ تم حفظ المنشور #{p.id}.\n"
        f"أول نشر: {dt}\n"
        f"التكرار: {'مرة واحدة' if repeat == 0 else f'كل {repeat} دقائق'}",
        reply_markup=main_menu(u.role == "owner")
    )

# ---------- Lists ----------
@router.callback_query(F.data == "posts")
async def posts(call, session, settings):
    u = await get_user(session, call.from_user.id, settings.owner_id)
    ps = (await session.execute(
        select(Post).where(Post.owner_user_id == u.id, Post.active == True)
        .order_by(Post.id.desc()).limit(20)
    )).scalars().all()
    txt = "📋 المنشورات المحفوظة:\n\n" + "\n".join(
        f"#{p.id} {'🖼️' if p.media_file_id else '📝'} {(p.text or '')[:70]}"
        for p in ps
    ) if ps else "📋 لا توجد منشورات محفوظة."
    await call.answer()
    await call.message.edit_text(txt, reply_markup=back())

@router.callback_query(F.data == "schedules")
async def schedules(call, session, settings):
    u = await get_user(session, call.from_user.id, settings.owner_id)
    ss = (await session.execute(
        select(Schedule).join(Post, Schedule.post_id == Post.id).where(
            Post.owner_user_id == u.id, Schedule.active == True
        )
    )).scalars().all()
    txt = "⏰ الجدولة النشطة:\n\n" + "\n".join(
        f"#{s.id} — {'كل '+str(s.interval_minutes)+' دقيقة' if s.interval_minutes else 'مرة واحدة'} — {s.next_run_at}"
        for s in ss
    ) if ss else "⏰ لا توجد جدولة نشطة."
    await call.answer()
    await call.message.edit_text(txt, reply_markup=back())

@router.callback_query(F.data == "running")
async def running(call):
    await call.answer()
    await call.message.edit_text(
        "▶️ النشر يعمل تلقائياً طالما التطبيق شغال.\n"
        "مثال: التكرار = 5 يعني نفس المنشور كل 5 دقائق.",
        reply_markup=back()
    )

# ---------- Owner approval ----------
@router.callback_query(F.data == "users")
async def users(call, session, settings):
    u = await get_user(session, call.from_user.id, settings.owner_id)
    if u.role != "owner":
        return await call.answer("غير مصرح", show_alert=True)
    pending = (await session.execute(select(User).where(
        User.active == False, User.role == "user"
    ))).scalars().all()
    if not pending:
        return await call.message.edit_text("👥 لا توجد طلبات دخول معلّقة.", reply_markup=back())
    for x in pending:
        await call.message.answer(
            f"👤 طلب دخول جديد\nID: <code>{x.telegram_id}</code>",
            reply_markup=approval_kb(x.telegram_id)
        )
    await call.answer()

@router.callback_query(F.data.startswith("user_accept:"))
async def user_accept(call, session, settings):
    u = await get_user(session, call.from_user.id, settings.owner_id)
    if u.role != "owner":
        return await call.answer("غير مصرح", show_alert=True)
    tid = int(call.data.split(":")[1])
    target = (await session.execute(select(User).where(User.telegram_id == tid))).scalar_one_or_none()
    if not target:
        return await call.answer("المستخدم غير موجود", show_alert=True)
    target.active = True
    await session.commit()
    await call.answer("تم قبول المستخدم")
    try:
        await call.bot.send_message(tid, "✅ تمت الموافقة على دخولك للبوت.")
    except Exception:
        pass
    await call.message.edit_text(f"✅ تم قبول المستخدم {tid}")

@router.callback_query(F.data.startswith("user_reject:"))
async def user_reject(call, session, settings):
    u = await get_user(session, call.from_user.id, settings.owner_id)
    if u.role != "owner":
        return await call.answer("غير مصرح", show_alert=True)
    tid = int(call.data.split(":")[1])
    target = (await session.execute(select(User).where(User.telegram_id == tid))).scalar_one_or_none()
    if not target:
        return await call.answer("المستخدم غير موجود", show_alert=True)
    await session.delete(target)
    await session.commit()
    await call.answer("تم رفض الطلب")
    await call.message.edit_text(f"❌ تم رفض المستخدم {tid}")
