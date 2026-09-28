# Telegram Publisher — نسخة جاهزة لـ Replit

نظام Telegram bot كلوحة تحكم لإدارة النشر من حسابات Telegram الشخصية عبر Telethon/MTProto.

## المزايا
- ربط حساب Telegram شخصي برقم الهاتف + كود Telegram + كلمة مرور التحقق بخطوتين إن وجدت.
- حفظ جلسة الحساب الشخصي مشفّرة بـ Fernet.
- حسابات متعددة لكل مستخدم.
- أماكن نشر متعددة لكل حساب (قنوات/مجموعات/مستخدمين يمكن للحساب الوصول لهم).
- منشور نصي أو صورة + وصف.
- نشر فوري أو جدولة لمرة واحدة أو تكرار كل N دقيقة.
- لوحة عربية Inline Keyboard.
- Owner يمكنه تفعيل/تعطيل المستخدمين.

## Secrets المطلوبة في Replit
BOT_TOKEN
API_ID
API_HASH
OWNER_ID
SESSION_ENCRYPTION_KEY

اختياري:
DATABASE_URL (افتراضياً SQLite محلي)
TIMEZONE (افتراضياً Asia/Baghdad)

لا تضع أي Secret داخل الكود أو المحادثة.

## توليد مفتاح التشفير
من Shell:
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
انسخ الناتج إلى Secret باسم SESSION_ENCRYPTION_KEY.

## التشغيل
python -m app.main

## ملاحظة
هذا النظام يعتمد على صلاحيات الحساب الشخصي داخل Telegram. الحساب يجب أن يكون عضواً/مشرفاً في القنوات أو المجموعات التي تريد النشر فيها، وتبقى كل قيود Telegram على الإرسال سارية.
