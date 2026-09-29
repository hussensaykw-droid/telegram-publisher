from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def main_menu(owner=False):
    rows = [
        [InlineKeyboardButton(text="👤 حساباتي", callback_data="accounts")],
        [InlineKeyboardButton(text="➕ إضافة منشور", callback_data="post_add"),
         InlineKeyboardButton(text="📋 منشوراتي", callback_data="posts")],
        [InlineKeyboardButton(text="⏰ الجدولة", callback_data="schedules"),
         InlineKeyboardButton(text="📍 أماكن النشر", callback_data="destinations")],
        [InlineKeyboardButton(text="▶️ النشر النشط", callback_data="running")],
    ]
    if owner:
        rows.append([InlineKeyboardButton(text="👥 المستخدمون", callback_data="users")])
    rows.append([InlineKeyboardButton(text="ℹ️ المعلومات", callback_data="info")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def back():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ رجوع", callback_data="home")]
    ])

def cancel_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ إلغاء", callback_data="cancel")]
    ])

def accounts_kb(accounts):
    rows = [[InlineKeyboardButton(text=f"📱 {a.title}", callback_data=f"acct:{a.id}")] for a in accounts]
    rows.append([InlineKeyboardButton(text="➕ إضافة حساب شخصي", callback_data="account_add")])
    rows.append([InlineKeyboardButton(text="⬅️ رجوع", callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def destinations_kb(destinations):
    rows = []
    for d in destinations:
        action = "⏸️ إيقاف" if d.active else "▶️ إرجاع"
        rows.append([InlineKeyboardButton(text=f"📍 {d.title}", callback_data=f"destinfo:{d.id}"),
                     InlineKeyboardButton(text=action, callback_data=f"dest_toggle:{d.id}")])
        rows.append([
            InlineKeyboardButton(text="🔄 تحديث بيانات الكروب", callback_data=f"dest_refresh:{d.id}"),
            InlineKeyboardButton(text="🗑️ حذف", callback_data=f"dest_delete:{d.id}")
        ])
    rows.append([InlineKeyboardButton(text="➕ إضافة كروب", callback_data="dest_add")])
    rows.append([InlineKeyboardButton(text="⬅️ رجوع", callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def approval_kb(user_id):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ قبول", callback_data=f"user_accept:{user_id}"),
        InlineKeyboardButton(text="❌ رفض", callback_data=f"user_reject:{user_id}")
    ]])


def users_manage_kb(active_users, pending_users, owner_id):
    rows = []
    for x in active_users:
        rows.append([InlineKeyboardButton(text=f"👤 {x.telegram_id}", callback_data=f"user_noop:{x.telegram_id}"),
                     InlineKeyboardButton(text="🚫 إزالة", callback_data=f"user_remove:{x.telegram_id}")])
    for x in pending_users:
        rows.append([InlineKeyboardButton(text=f"⏳ {x.telegram_id}", callback_data=f"user_noop:{x.telegram_id}")])
        rows.append([InlineKeyboardButton(text="✅ إبقاء/قبول", callback_data=f"user_accept:{x.telegram_id}"),
                     InlineKeyboardButton(text="❌ رفض", callback_data=f"user_reject:{x.telegram_id}")])
    # Show inactive users separately only when they are not pending anymore.
    inactive = [x for x in pending_users if not x.active]
    # All inactive users are pending in the current schema, so re-entry will
    # appear here again. Owner can accept them whenever needed.
    rows.append([InlineKeyboardButton(text="⬅️ رجوع", callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
