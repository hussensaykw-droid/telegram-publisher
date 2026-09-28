import re, asyncio, tempfile, os
from datetime import datetime
from zoneinfo import ZoneInfo
from aiogram import Router, F, Bot
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select, delete
from telethon import TelegramClient
from telethon.sessions import StringSession
from .db import User, TelegramAccount, Destination, Post, PostDestination, Schedule
from .keyboards import *
from .states import AccountFlow, DestFlow, PostFlow
from .services import TelegramService

router=Router()

def norm_phone(s):
    trans=str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹","01234567890123456789")
    s=s.translate(trans).strip().replace(" ","").replace("-","").replace("(","").replace(")","")
    if s.startswith("00"): s="+"+s[2:]
    if not s.startswith("+"): s="+"+s
    if not re.fullmatch(r"\+[1-9]\d{7,14}",s): raise ValueError("رقم الهاتف غير صحيح. مثال: +9647XXXXXXXXX")
    return s

async def get_user(session, tid, owner):
    u=(await session.execute(select(User).where(User.telegram_id==tid))).scalar_one_or_none()
    if not u:
        u=User(telegram_id=tid,role="owner" if tid==owner else "user",active=(tid==owner)); session.add(u); await session.commit()
    return u

async def home(message, session, settings):
    u=await get_user(session,message.from_user.id,settings.owner_id)
    if not u.active: return await message.answer("⛔ حسابك غير مفعّل.")
    await message.answer("🐣 أهلاً بك في لوحة التحكم\n\nاختر العملية:",reply_markup=main_menu(u.role=="owner"))

@router.message(CommandStart())
async def start(message,state,session,settings):
    await state.clear(); await home(message,session,settings)

@router.callback_query(F.data=="home")
async def cb_home(call,state,session,settings):
    await call.answer(); await state.clear(); await call.message.edit_text("🐣 لوحة التحكم",reply_markup=main_menu((await get_user(session,call.from_user.id,settings.owner_id)).role=="owner"))

@router.callback_query(F.data=="info")
async def info(call): await call.answer(); await call.message.edit_text("ℹ️ لوحة نشر من الحسابات الشخصية عبر MTProto.\nالجلسات تحفظ مشفّرة. تأكد أن حسابك يملك صلاحية النشر في القناة/المجموعة.",reply_markup=back())

@router.callback_query(F.data=="cancel")
async def cancel(call,state): await call.answer("تم الإلغاء"); await state.clear(); await call.message.edit_text("تم الإلغاء.",reply_markup=back())

@router.callback_query(F.data=="accounts")
async def accounts(call,state,session):
    await call.answer(); u=await get_user(session,call.from_user.id,0)
    rows=(await session.execute(select(TelegramAccount).where(TelegramAccount.owner_user_id==u.id,TelegramAccount.active==True))).scalars().all()
    await call.message.edit_text("👤 حساباتي\n\nاختر حساباً أو أضف حساباً جديداً:",reply_markup=accounts_kb(rows))

@router.callback_query(F.data=="account_add")
async def account_add(call,state): await call.answer(); await state.set_state(AccountFlow.phone); await call.message.edit_text("📱 أرسل رقم حساب Telegram بصيغة دولية.\nمثال: +9647XXXXXXXXX",reply_markup=cancel_kb())

@router.message(AccountFlow.phone)
async def account_phone(message,state,session,settings):
    try: phone=norm_phone(message.text or "")
    except ValueError as e: return await message.answer(f"❌ {e}")
    svc=TelegramService(settings,settings.cipher)
    try:
        client,phone_hash=await svc.login_send_code(phone)
    except Exception as e: return await message.answer(f"❌ تعذر إرسال رمز الدخول. تأكد من API_ID/API_HASH والرقم.\n{type(e).__name__}")
    await state.update_data(phone=phone,phone_hash=phone_hash,login_client=client)
    await state.set_state(AccountFlow.code)
    await message.answer("📨 تم طلب رمز الدخول من Telegram.\nأرسل الرمز هنا فقط، ولا ترسله لأي شخص آخر.")

@router.message(AccountFlow.code)
async def account_code(message,state,session,settings):
    d=await state.get_data(); code=(message.text or "").strip().replace(" ","")
    client=d.get("login_client")
    if not client: return await message.answer("انتهت جلسة تسجيل الدخول. اضغط إضافة حساب وحاول مرة ثانية.")
    svc=TelegramService(settings,settings.cipher)
    try:
        me,sess,needs_password=await svc.login_code(client,d["phone"],code,d["phone_hash"])
        if needs_password:
            await state.set_state(AccountFlow.password); await message.answer("🔐 الحساب عليه تحقق بخطوتين. أرسل كلمة مرور 2FA."); return
    except Exception as e:
        try: await client.disconnect()
        except Exception: pass
        return await message.answer(f"❌ رمز الدخول غير صحيح أو انتهت صلاحيته. حاول بدء الربط من جديد.\n{type(e).__name__}")
    await state.update_data(session=sess,me_id=me.id,me_name=(getattr(me,'first_name',None) or str(me.id)))
    await state.set_state(AccountFlow.title); await message.answer("✅ تم تسجيل الدخول. أرسل اسماً للحساب مثل: حسابي الرئيسي")

@router.message(AccountFlow.password)
async def account_password(message,state,session,settings):
    d=await state.get_data(); client=d.get("login_client")
    if not client: return await message.answer("انتهت جلسة تسجيل الدخول. أعد الربط.")
    svc=TelegramService(settings,settings.cipher)
    try:
        me,sess=await svc.login_password(client,message.text)
    except Exception as e:
        try: await client.disconnect()
        except Exception: pass
        return await message.answer(f"❌ كلمة مرور 2FA غير صحيحة أو انتهت الجلسة. {type(e).__name__}")
    await state.update_data(session=sess,me_id=me.id,me_name=(getattr(me,'first_name',None) or str(me.id)))
    await state.set_state(AccountFlow.title); await message.answer("✅ تم التحقق. أرسل اسماً للحساب.")

@router.message(AccountFlow.title)
async def account_title(message,state,session,settings):
    d=await state.get_data(); u=await get_user(session,message.from_user.id,settings.owner_id)
    a=TelegramAccount(owner_user_id=u.id,title=(message.text or "حساب Telegram")[:128],phone=d["phone"],encrypted_session=settings.cipher.encrypt(d["session"]))
    session.add(a); await session.commit(); await state.clear(); await message.answer("🎉 تمت إضافة الحساب الشخصي بنجاح.",reply_markup=main_menu(u.role=="owner"))

@router.callback_query(F.data=="destinations")
async def destinations(call,session,settings):
    u=await get_user(session,call.from_user.id,settings.owner_id); rows=(await session.execute(select(Destination).where(Destination.owner_user_id==u.id,Destination.active==True))).scalars().all(); await call.answer(); await call.message.edit_text("📍 أماكن النشر:",reply_markup=destinations_kb(rows))

@router.callback_query(F.data=="dest_add")
async def dest_add(call,state,session,settings):
    u=await get_user(session,call.from_user.id,settings.owner_id); accts=(await session.execute(select(TelegramAccount).where(TelegramAccount.owner_user_id==u.id,TelegramAccount.active==True))).scalars().all()
    if not accts: return await call.answer("أضف حساباً شخصياً أولاً",show_alert=True)
    rows=[[InlineKeyboardButton(text=a.title,callback_data=f"dacc:{a.id}")] for a in accts]; rows.append([InlineKeyboardButton(text="❌ إلغاء",callback_data="cancel")]); await state.set_state(DestFlow.account); await call.message.edit_text("اختر الحساب الذي سيستخدم النشر:",reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

@router.callback_query(F.data.startswith("dacc:"))
async def dest_account(call,state): await call.answer(); await state.update_data(account_id=int(call.data.split(":")[1])); await state.set_state(DestFlow.chat); await call.message.edit_text("📍 أرسل @username أو رقم chat_id للمجموعة/القناة.\nمثال: @mychannel")

@router.message(DestFlow.chat)
async def dest_chat(message,state,session,settings):
    d=await state.get_data(); u=await get_user(session,message.from_user.id,settings.owner_id); a=(await session.execute(select(TelegramAccount).where(TelegramAccount.id==d["account_id"],TelegramAccount.owner_user_id==u.id))).scalar_one_or_none()
    if not a: return await message.answer("الحساب غير موجود.")
    chat=(message.text or "").strip()
    try:
        c=TelegramService(settings,settings.cipher); me=await c.check_session(a.encrypted_session)
        # Resolve entity and store stable numeric/string id.
        tele=c.client(settings.cipher.decrypt(a.encrypted_session)); await tele.connect(); ent=await tele.get_entity(chat); title=getattr(ent,"title",None) or getattr(ent,"username",None) or chat; cid=str(getattr(ent,"id",chat));
        if hasattr(ent,"megagroup") or hasattr(ent,"broadcast"):
            pass
        await tele.disconnect()
    except Exception as e: return await message.answer(f"❌ لم أستطع الوصول للمكان بالحساب. تأكد من العضوية/الصلاحية والاسم.\n{type(e).__name__}")
    session.add(Destination(owner_user_id=u.id,account_id=a.id,chat_id=cid,title=title));
    try: await session.commit()
    except Exception: await session.rollback(); return await message.answer("⚠️ هذا المكان مضاف مسبقاً أو تعذر حفظه.")
    await state.clear(); await message.answer(f"✅ تمت إضافة: {title}",reply_markup=main_menu(u.role=="owner"))

@router.callback_query(F.data=="post_add")
async def post_add(call,state,session,settings):
    u=await get_user(session,call.from_user.id,settings.owner_id); accts=(await session.execute(select(TelegramAccount).where(TelegramAccount.owner_user_id==u.id,TelegramAccount.active==True))).scalars().all()
    if not accts: return await call.answer("أضف حساباً شخصياً أولاً",show_alert=True)
    await state.set_state(PostFlow.content); await call.answer(); await call.message.edit_text("➕ أرسل الآن نص المنشور أو صورة مع الوصف.\nإذا أرسلت صورة، اكتب الوصف في خانة caption.",reply_markup=cancel_kb())

@router.message(PostFlow.content)
async def post_content(message,state):
    if message.photo:
        await state.update_data(text=message.caption or "",media_file_id=message.photo[-1].file_id)
    elif message.text:
        await state.update_data(text=message.text,media_file_id=None)
    else: return await message.answer("أرسل نصاً أو صورة فقط.")
    await state.set_state(PostFlow.account)
    await message.answer("تم حفظ المنشور مؤقتاً. أرسل: اختيار الحساب")

@router.message(PostFlow.account)
async def post_account_text(message,state,session,settings):
    if (message.text or '').strip() != 'اختيار الحساب':
        return await message.answer("أرسل كلمة: اختيار الحساب")
    u=await get_user(session,message.from_user.id,settings.owner_id)
    accts=(await session.execute(select(TelegramAccount).where(TelegramAccount.owner_user_id==u.id,TelegramAccount.active==True))).scalars().all()
    if not accts: return await message.answer("لا توجد حسابات شخصية. أضف حساباً أولاً.")
    rows=[[InlineKeyboardButton(text=f"📱 {a.title}",callback_data=f"postacct:{a.id}")] for a in accts]
    rows.append([InlineKeyboardButton(text="❌ إلغاء",callback_data="cancel")])
    await message.answer("اختر الحساب:",reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

@router.callback_query(F.data.startswith("postacct:"))
async def post_account(call,state,session,settings):
    await call.answer(); await state.update_data(account_id=int(call.data.split(":")[1])); u=await get_user(session,call.from_user.id,settings.owner_id); ds=(await session.execute(select(Destination).where(Destination.owner_user_id==u.id,Destination.account_id==int(call.data.split(":")[1]),Destination.active==True))).scalars().all()
    if not ds: return await call.message.edit_text("لا توجد أماكن نشر لهذا الحساب. أضف مكاناً أولاً.",reply_markup=back())
    await state.set_state(PostFlow.destinations); await call.message.edit_text("اختر مكان نشر واحداً أو أكثر بإرسال أرقامها مفصولة بفواصل:\n"+"\n".join(f"{d.id} — {d.title}" for d in ds)+"\n\nمثال: 1,2")

@router.callback_query(F.data=="posts")
async def posts(call,session,settings):
    u=await get_user(session,call.from_user.id,settings.owner_id); ps=(await session.execute(select(Post).where(Post.owner_user_id==u.id).order_by(Post.id.desc()).limit(20))).scalars().all(); await call.answer(); txt="📋 آخر المنشورات:\n\n"+"\n".join(f"#{p.id} {'🖼️' if p.media_file_id else '📝'} {(p.text or '')[:60]}" for p in ps) if ps else "📋 لا توجد منشورات."; await call.message.edit_text(txt,reply_markup=back())

@router.callback_query(F.data=="schedules")
async def schedules(call,session,settings):
    u=await get_user(session,call.from_user.id,settings.owner_id); ss=(await session.execute(select(Schedule).join(Post,Schedule.post_id==Post.id).where(Post.owner_user_id==u.id,Schedule.active==True))).scalars().all(); txt="⏰ الجدولة النشطة:\n\n"+"\n".join(f"#{s.id} — {s.next_run_at} — {'كل '+str(s.interval_minutes)+' دقيقة' if s.interval_minutes else 'مرة واحدة'}" for s in ss) if ss else "⏰ لا توجد جدولة نشطة."; await call.answer(); await call.message.edit_text(txt,reply_markup=back())

@router.callback_query(F.data=="running")
async def running(call): await call.answer(); await call.message.edit_text("▶️ النشر يعمل من خلال المجدول طالما الـWorkflow شغال.",reply_markup=back())

@router.callback_query(F.data=="users")
async def users(call,session,settings):
    u=await get_user(session,call.from_user.id,settings.owner_id)
    if u.role!="owner": return await call.answer("غير مصرح",show_alert=True)
    us=(await session.execute(select(User))).scalars().all(); await call.answer(); await call.message.edit_text("👥 المستخدمون:\n\n"+"\n".join(f"{x.telegram_id} — {x.role} — {'فعال' if x.active else 'موقوف'}" for x in us),reply_markup=back())


@router.message(PostFlow.destinations)
async def post_destinations(message,state,session,settings):
    d=await state.get_data(); u=await get_user(session,message.from_user.id,settings.owner_id)
    try: ids=[int(x.strip()) for x in (message.text or '').split(',') if x.strip()]
    except ValueError: return await message.answer("اكتب أرقاماً مثل: 1,2")
    ds=(await session.execute(select(Destination).where(Destination.id.in_(ids),Destination.owner_user_id==u.id,Destination.account_id==d['account_id'],Destination.active==True))).scalars().all()
    if len(ds)!=len(ids): return await message.answer("بعض أرقام أماكن النشر غير صحيحة.")
    await state.update_data(dest_ids=ids); await state.set_state(PostFlow.when)
    await message.answer("⏰ أرسل موعد النشر بصيغة:\nYYYY-MM-DD HH:MM\nمثال: 2026-09-28 20:30")

@router.message(PostFlow.when)
async def post_when(message,state,settings):
    d=await state.get_data()
    try:
        dt=datetime.strptime((message.text or '').strip(),'%Y-%m-%d %H:%M').replace(tzinfo=ZoneInfo(settings.timezone)).replace(tzinfo=None)
    except ValueError: return await message.answer("❌ الصيغة خطأ. مثال: 2026-09-28 20:30")
    if dt < datetime.now(ZoneInfo(settings.timezone)).replace(tzinfo=None): return await message.answer("❌ الموعد صار بالماضي. أرسل موعداً قادماً.")
    await state.update_data(next_run_at=dt.isoformat()); await state.set_state(PostFlow.repeat)
    await message.answer("🔁 كم دقيقة بين كل نشر؟\nاكتب 0 إذا تريدها مرة واحدة.\nمثال: 1440 = كل يوم")

@router.message(PostFlow.repeat)
async def post_repeat(message,state,session,settings):
    d=await state.get_data()
    try: repeat=int((message.text or '').strip())
    except ValueError: return await message.answer("❌ اكتب رقماً بالدقائق، أو 0.")
    if repeat<0: return await message.answer("❌ الرقم لا يمكن أن يكون سالباً.")
    u=await get_user(session,message.from_user.id,settings.owner_id)
    p=Post(owner_user_id=u.id,account_id=d['account_id'],text=d.get('text'),media_file_id=d.get('media_file_id')); session.add(p); await session.flush()
    for did in d['dest_ids']: session.add(PostDestination(post_id=p.id,destination_id=did))
    dt=datetime.fromisoformat(d['next_run_at']); session.add(Schedule(post_id=p.id,interval_minutes=repeat,next_run_at=dt,active=True)); await session.commit(); await state.clear()
    await message.answer(f"✅ تمت جدولة المنشور #{p.id}.\nموعد أول نشر: {dt}\nالتكرار: {'مرة واحدة' if repeat==0 else f'كل {repeat} دقيقة'}",reply_markup=main_menu(u.role=='owner'))
