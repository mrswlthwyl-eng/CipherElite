import os
import sys
import asyncio
from telethon import TelegramClient, events
from telethon.tl.types import KeyboardButtonUrl

# ========== قراءة المتغيرات من نظام Elite Deployer ==========
API_ID = int(os.getenv("API_ID", 0))
API_HASH = os.getenv("API_HASH", "")
ELITE_SESSION = os.getenv("ELITE_SESSION", "")
SUDO_USERS = [int(x) for x in os.getenv("SUDO_USERS", "0").split(",") if x.strip()]
LOG_CHAT_ID = int(os.getenv("LOG_CHAT_ID", 0))

if not API_ID or not API_HASH or not ELITE_SESSION:
    print("❌ تأكد من إعداد: API_ID, API_HASH, ELITE_SESSION")
    sys.exit(1)

# ========== الكلمات المفتاحية ==========
KEYWORDS = ["توصيل", "مشاوير", "سيارة", "يوصل", "احتاج", "موصلات", "بنزين"]

# ========== إعداد العميل ==========
client = TelegramClient(ELITE_SESSION, API_ID, API_HASH)

@client.on(events.NewMessage())
async def handler(event):
    if event.out:
        return
    
    text = event.raw_text.lower()
    matched = [kw for kw in KEYWORDS if kw in text]
    if not matched:
        return
    
    sender = await event.get_sender()
    user_id = sender.id
    full_name = sender.first_name or ''
    if sender.last_name:
        full_name += ' ' + sender.last_name
    username = sender.username
    
    chat = await event.get_chat()
    chat_title = chat.title or 'مجموعة بدون اسم'
    chat_id = chat.id
    
    # رابط الرسالة
    if chat_id < 0:
        message_link = f"https://t.me/c/{str(chat_id)[4:]}/{event.id}"
    else:
        message_link = f"https://t.me/{chat.username}/{event.id}" if chat.username else None
    
    # رابط التواصل مع الطالب
    user_link = f"https://t.me/+{user_id}"
    
    # بناء الرسالة
    final_msg = f"""
╭━━━ 🚗 طلب توصيل جديد ━━━╮

📝 نص الرسالة:
{event.raw_text}

━━━━━━━━━━━━━━━━━━━━

👤 الاسم: {full_name}
🆔 الأيدي: {user_id}
{'🔗 @' + username if username else '🔗 بدون username'}

📡 المجموعة: {chat_title}
🆔 أيدي المجموعة: {chat_id}

{'🔗 الضغط للذهاب للرسالة الأصلية: ' + message_link if message_link else ''}

━━━━━━━━━━━━━━━━━━━━

🧲 الكلمات المطابقة:
{', '.join(matched)}

╰━━━━━━━━━━━━━━━━━━━━╯
"""
    
    # أزرار للتواصل
    buttons = [[KeyboardButtonUrl("💬 تواصل مع الطالب", user_link)]]
    
    try:
        await client.send_message(LOG_CHAT_ID, final_msg, buttons=buttons)
        print(f"✅ تم نقل رسالة من {full_name} في {chat_title}")
    except Exception as e:
        print(f"❌ خطأ في الإرسال: {e}")

async def main():
    print("🚀 جاري الاتصال بحسابك...")
    await client.start()
    print("✅ الحساب متصل!")
    print(f"📡 يراقب {len(KEYWORDS)} كلمة مفتاحية")
    print("⏳ ينتظر الرسائل...")
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
