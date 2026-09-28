import re, random
from datetime import datetime, timedelta
from aiogram import Router, F
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select
from .db import User, Destination, Post, PostDestination, Schedule, ScheduleConfig, Draft
from .states import PostFlow
from .keyboards import main_menu

router = Router()

class ScheduleFlow(StatesGroup):
    interval = State()
    count = State()

def ar_num(s):
    return (s or '').translate(str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹','01234567890123456789'))

def parse_duration(value):
    s = ar_num(value).strip().lower().replace(' ', '')
    m = re.fullmatch(r'(\d+(?:\.\d+)?)(s|sec|secs|second|seconds|ث|ثانية|ثواني|m|min|mins|minute|minutes|د|دقيقة|دقائق)?(?:-(\d+(?:\.\d+)?)(s|sec|secs|second|seconds|ث|ثانية|ثواني|m|min|mins|minute|minutes|د|دقيقة|دقائق)?)?', s)
    if not m:
        raise ValueError
    a = float(m.group(1)); u1 = m.group(2) or 'm'; b = m.group(3); u2 = m.group(4) or u1
    def sec(v,u):
        if u in {'s','sec','secs','second','seconds','ث','ثانية','ثواني'}: return int(v)
        return int(v*60)
    lo = sec(a,u1); hi = sec(float(b),u2) if b else lo
    if lo <= 0 or hi <= 0 or hi < lo or hi > 86400:
        raise ValueError
    return lo, hi

def fmt_seconds(lo, hi):
    def f(x):
        if x % 60 == 0: return f'{x//60} دقيقة'
        return f'{x} ثانية'
    return f'كل {f(lo)}' if lo == hi else f'بين {f(lo)} و {f(hi)}'

def running_kb(rows):
    buttons = []
    for s, cfg in rows:
        buttons.append([InlineKeyboardButton(text=f'⏸️ إيقاف #{s.id}', callback_data=f'stop_schedule:{s.id}')])
    buttons.append([InlineKeyboardButton(text='⬅️ رجوع', callback_data='home')])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


class EditPostFlow(StatesGroup):
    text = State()

def posts_kb(rows):
    buttons = []
    for p in rows:
        label = f'{"🖼️" if p.media_file_id else "📝"} #{p.id}'
        buttons.append([
            InlineKeyboardButton(text=f'✏️ تعديل {label}', callback_data=f'edit_post:{p.id}'),
            InlineKeyboardButton(text=f'🗑️ حذف {label}', callback_data=f'delete_post:{p.id}')
        ])
    buttons.append([InlineKeyboardButton(text='➕ إضافة رسالة', callback_data='post_add')])
    buttons.append([InlineKeyboardButton(text='▶️ النشر النشط', callback_data='running')])
    buttons.append([InlineKeyboardButton(text='⬅️ رجوع', callback_data='home')])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

async def _active_posts(session, u):
    return (await session.execute(
        select(Post).where(
            Post.owner_user_id == u.id,
            Post.active == True
        ).order_by(Post.id.desc()).limit(20)
    )).scalars().all()

@router.callback_query(F.data == 'posts')
async def manage_posts(call, session, settings):
    u = await _user(session, call.from_user.id, settings.owner_id)
    rows = await _active_posts(session, u)
    await call.answer()
    if not rows:
        return await call.message.edit_text(
            '📋 لا توجد منشورات محفوظة حالياً.',
            reply_markup=posts_kb([])
        )
    lines = []
    for p in rows:
        body = (p.text or '').replace('\n', ' ')[:60]
        lines.append(f'#{p.id} {"🖼️" if p.media_file_id else "📝"} {body or "بدون نص"}')
    await call.message.edit_text(
        '📋 إدارة المنشورات\n\n' +
        '\n'.join(lines) +
        '\n\nاختر المنشور ثم تعديل أو حذف:',
        reply_markup=posts_kb(rows)
    )

@router.callback_query(F.data.startswith('edit_post:'))
async def edit_post(call, state, session, settings):
    u = await _user(session, call.from_user.id, settings.owner_id)
    pid = int(call.data.split(':')[1])
    p = (await session.execute(
        select(Post).where(
            Post.id == pid,
            Post.owner_user_id == u.id,
            Post.active == True
        )
    )).scalar_one_or_none()
    if not p:
        return await call.answer('المنشور غير موجود.', show_alert=True)
    await state.update_data(edit_post_id=pid)
    await state.set_state(EditPostFlow.text)
    await call.answer()
    await call.message.edit_text(
        f'✏️ تعديل المنشور #{pid}\n\n'
        'أرسل النص الجديد، أو أرسل صورة مع وصف جديد.\n'
        'إذا كان المنشور صورة، إرسال نص فقط يغيّر الوصف ويبقي الصورة.\n\n'
        '/cancel للإلغاء'
    )

@router.message(EditPostFlow.text)
async def save_edited_post(message, state, session, settings):
    d = await state.get_data()
    pid = d.get('edit_post_id')
    u = await _user(session, message.from_user.id, settings.owner_id)
    p = (await session.execute(
        select(Post).where(
            Post.id == pid,
            Post.owner_user_id == u.id,
            Post.active == True
        )
    )).scalar_one_or_none()
    if not p:
        await state.clear()
        return await message.answer('❌ المنشور غير موجود.')
    if message.photo:
        p.media_file_id = message.photo[-1].file_id
        p.text = message.caption or ''
    elif message.text:
        p.text = message.text
    else:
        return await message.answer('❌ أرسل نصاً أو صورة مع وصف.')
    await session.commit()
    await state.clear()
    rows = await _active_posts(session, u)
    await message.answer(
        f'✅ تم تعديل المنشور #{pid}.',
        reply_markup=posts_kb(rows)
    )

@router.callback_query(F.data.startswith('delete_post:'))
async def delete_post(call, session, settings):
    u = await _user(session, call.from_user.id, settings.owner_id)
    pid = int(call.data.split(':')[1])
    p = (await session.execute(
        select(Post).where(
            Post.id == pid,
            Post.owner_user_id == u.id,
            Post.active == True
        )
    )).scalar_one_or_none()
    if not p:
        return await call.answer('المنشور غير موجود أو محذوف.', show_alert=True)
    schedules = (await session.execute(
        select(Schedule).where(Schedule.post_id == p.id)
    )).scalars().all()
    for sch in schedules:
        sch.active = False
    p.active = False
    await session.commit()
    await call.answer('🗑️ تم حذف المنشور')
    rows = await _active_posts(session, u)
    if not rows:
        return await call.message.edit_text(
            '🗑️ تم حذف المنشور.\n\n📋 لا توجد منشورات محفوظة حالياً.',
            reply_markup=posts_kb([])
        )
    lines = []
    for x in rows:
        body = (x.text or '').replace('\n', ' ')[:60]
        lines.append(f'#{x.id} {"🖼️" if x.media_file_id else "📝"} {body or "بدون نص"}')
    await call.message.edit_text(
        '📋 إدارة المنشورات\n\n' + '\n'.join(lines),
        reply_markup=posts_kb(rows)
    )

@router.message(PostFlow.destinations)
async def new_destinations(message, state, session, settings):
    d = await state.get_data(); u = await _user(session, message.from_user.id, settings.owner_id)
    try: ids = [int(x.strip()) for x in ar_num(message.text).split(',') if x.strip()]
    except Exception: return await message.answer('اكتب أرقام الكروبات مثل: 1,2')
    ds = (await session.execute(select(Destination).where(Destination.id.in_(ids), Destination.owner_user_id == u.id, Destination.account_id == d['account_id'], Destination.active == True))).scalars().all()
    if len(ds) != len(ids): return await message.answer('بعض أرقام الكروبات غير صحيحة.')
    await state.update_data(dest_ids=ids)
    await state.set_state(ScheduleFlow.interval)
    await message.answer('🤷‍♂️ ضبط مدة النشر\n\nالمدة الحالية: غير محددة\n\nأرسل المدة بالثواني أو الدقائق:\n10s = 10 ثواني\n1m = دقيقة\n5m-10m = عشوائي بين 5 و10 دقائق\n5 = 5 دقائق\n\n/cancel للإلغاء')

@router.message(ScheduleFlow.interval)
async def interval(message, state):
    try: lo, hi = parse_duration(message.text)
    except Exception:
        return await message.answer('❌ الصيغة غير صحيحة. مثال: 10s أو 1m أو 5m-10m')
    await state.update_data(min_seconds=lo, max_seconds=hi)
    await state.set_state(ScheduleFlow.count)
    await message.answer(f'⏱️ تم ضبط المدة: {fmt_seconds(lo,hi)}\n\n🔢 كم مرة تريد النشر؟\nأرسل رقم المرات.\n0 = يستمر بدون حد\nمثال: 10 = ينشر 10 مرات')

@router.message(ScheduleFlow.count)
async def count(message, state, session, settings):
    try: count = int(ar_num(message.text).strip())
    except Exception: return await message.answer('❌ أرسل رقم المرات فقط. مثال: 10')
    if count < 0: return await message.answer('❌ العدد لا يمكن أن يكون سالباً.')
    d = await state.get_data(); u = await _user(session, message.from_user.id, settings.owner_id)
    draft = await session.get(Draft, d.get('draft_id'))
    if not draft or not draft.active: return await message.answer('❌ المنشور المحفوظ غير موجود.')
    p = Post(owner_user_id=u.id, account_id=d['account_id'], text=draft.text, media_file_id=draft.media_file_id)
    session.add(p); await session.flush()
    for did in d['dest_ids']: session.add(PostDestination(post_id=p.id, destination_id=did))
    lo, hi = d['min_seconds'], d['max_seconds']
    first = datetime.now().replace(microsecond=0) + timedelta(seconds=random.randint(lo,hi))
    sch = Schedule(post_id=p.id, interval_minutes=0, next_run_at=first, active=True)
    session.add(sch); await session.flush()
    session.add(ScheduleConfig(schedule_id=sch.id, min_interval_seconds=lo, max_interval_seconds=hi, publish_limit=count, published_count=0))
    draft.active = False
    await session.commit(); await state.clear()
    lim = 'بدون حد' if count == 0 else str(count)
    await message.answer(f'✅ تم تشغيل النشر #{sch.id}\nالمدة: {fmt_seconds(lo,hi)}\nعدد النشر: {lim}', reply_markup=main_menu(u.role == 'owner'))

async def _user(session, tid, owner):
    u = (await session.execute(select(User).where(User.telegram_id == tid))).scalar_one_or_none()
    if not u:
        u = User(telegram_id=tid, role='owner' if tid == owner else 'user', active=(tid == owner)); session.add(u); await session.commit()
    return u

async def _active(session, u):
    return (await session.execute(select(Schedule, ScheduleConfig).join(Post, Schedule.post_id == Post.id).outerjoin(ScheduleConfig, ScheduleConfig.schedule_id == Schedule.id).where(Post.owner_user_id == u.id, Schedule.active == True))).all()

@router.callback_query(F.data.in_({'running','schedules'}))
async def show_active(call, session, settings):
    u = await _user(session, call.from_user.id, settings.owner_id); rows = await _active(session,u)
    if not rows: text='⏸️ لا توجد منشورات نشطة حالياً.'
    else:
        parts=[]
        for s,c in rows:
            if c: parts.append(f'#{s.id} — {fmt_seconds(c.min_interval_seconds,c.max_interval_seconds)} — {"∞" if c.publish_limit==0 else f"{c.published_count}/{c.publish_limit}"}')
            else: parts.append(f'#{s.id} — كل {s.interval_minutes} دقيقة')
        text='▶️ النشر النشط:\n\n'+'\n'.join(parts)+'\n\nاضغط إيقاف لإيقاف أي منشور.'
    await call.answer(); await call.message.edit_text(text, reply_markup=running_kb(rows))

@router.callback_query(F.data.startswith('stop_schedule:'))
async def stop_schedule(call, session, settings):
    u = await _user(session, call.from_user.id, settings.owner_id); sid=int(call.data.split(':')[1])
    sch=(await session.execute(select(Schedule).join(Post, Schedule.post_id==Post.id).where(Schedule.id==sid, Post.owner_user_id==u.id, Schedule.active==True))).scalar_one_or_none()
    if not sch: return await call.answer('الجدولة غير موجودة أو متوقفة.', show_alert=True)
    sch.active=False; await session.commit(); await call.answer('⏸️ تم إيقاف النشر')
    rows=await _active(session,u)
    text='⏸️ تم إيقاف النشر.\n\n'+('لا توجد منشورات نشطة حالياً.' if not rows else 'النشر النشط:')
    await call.message.edit_text(text, reply_markup=running_kb(rows))
