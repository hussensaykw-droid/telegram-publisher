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
        rows.append([InlineKeyboardButton(text="👥 طلبات الدخول", callback_data="users")])
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
    rows = [[InlineKeyboardButton(text=f"📍 {d.title}", callback_data=f"dest:{d.id}")] for d in destinations]
    rows.append([InlineKeyboardButton(text="➕ إضافة كروب", callback_data="dest_add")])
    rows.append([InlineKeyboardButton(text="⬅️ رجوع", callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def approval_kb(user_id):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ قبول", callback_data=f"user_accept:{user_id}"),
        InlineKeyboardButton(text="❌ رفض", callback_data=f"user_reject:{user_id}")
    ]])
