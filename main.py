# ============================================================
# main.py
# Telegram Delivery Monitor
#
# رسالة واحدة فقط لكل طلب
# روابط تفتح الخاص مباشرة إذا وجد يوزر
# أو توجه لرسالة الطالب في المجموعة لفتح الخاص بضغطة واحدة
# ============================================================

import asyncio
import logging
import os
import re
import time
from contextlib import suppress
from html import escape

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import (
    AuthKeyDuplicatedError,
    FloodWaitError,
    RPCError,
)


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger("delivery-monitor")


# ============================================================
# ENVIRONMENT
# ============================================================

def get_required(name):
    value = os.getenv(name)
    if not value or not value.strip():
        raise RuntimeError(f"❌ متغير Railway مفقود: {name}")
    return value.strip()


def get_int(name):
    value = get_required(name)
    try:
        return int(value)
    except ValueError:
        raise RuntimeError(f"❌ المتغير {name} يجب أن يكون رقمًا: {value}")


# ============================================================
# TELEGRAM SETTINGS
# ============================================================

API_ID = get_int("API_ID")
API_HASH = get_required("API_HASH")
SESSION = get_required("SESSION")
TARGET_CHANNEL = get_int("TARGET_CHANNEL")


# ============================================================
# FILTER
# ============================================================

try:
    from filters import KEYWORDS, matched_keywords
except ImportError:
    KEYWORDS = [
        "توصيل", "مشوار", "من _الى", "احتاج سيارة", "احتاج سواق",
        "شهري", "مندوب", "سواق", "سواقه", "تاكسي", "سيارة", "باص",
        "نقل", "ابي توصيل", "تواصل", "من رايحة", "تعرفون باص",
        "سواقة", "تعرفون سواق", "ابغى باص", "توصيل طلب", "يوصلي",
        "يوديني مشوار", "بحث", "تقرير", "بحوث", "يسوي", "مشروع",
        "واجب", "جامعة", "دراسة",
    ]

    def normalize_text(text):
        if not text:
            return ""
        text = str(text).lower()
        replacements = {"أ": "ا", "إ": "ا", "آ": "ا", "ة": "ه", "ى": "ي"}
        for old, new in replacements.items():
            text = text.replace(old, new)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    NORMALIZED_KEYWORDS = [(k, normalize_text(k)) for k in KEYWORDS if k]

    def matched_keywords(text):
        normalized = normalize_text(text)
        if not normalized:
            return []
        matches = [orig for orig, kw in NORMALIZED_KEYWORDS if kw and kw in normalized]
        return list(dict.fromkeys(matches))


# ============================================================
# TELEGRAM CLIENT
# ============================================================

client = TelegramClient(
    StringSession(SESSION),
    API_ID,
    API_HASH,
    connection_retries=10,
    retry_delay=2,
    request_retries=5,
    auto_reconnect=True,
    sequential_updates=False,
    catch_up=True,
    flood_sleep_threshold=60,
    entity_cache_limit=10000,
)

send_lock = asyncio.Lock()


# ============================================================
# BUILD SOURCE MESSAGE LINK
# ============================================================

def build_message_link(chat, chat_id, message_id):
    if not chat_id:
        return None

    chat_username = getattr(chat, "username", None)
    if chat_username:
        return f"https://t.me/{chat_username}/{message_id}"

    raw_chat_id = str(chat_id)
    if raw_chat_id.startswith("-100"):
        internal_id = raw_chat_id[4:]
        return f"https://t.me/c/{internal_id}/{message_id}"

    return None


def build_chat_link(chat):
    if not chat:
        return None
    chat_username = getattr(chat, "username", None)
    if chat_username:
        return f"https://t.me/{chat_username}"
    return None


# ============================================================
# BUILD MESSAGE (SINGLE MESSAGE TEMPLATE)
# ============================================================

def build_message(event, text, matches, sender, chat):
    message_id = event.id
    chat_id = event.chat_id

    chat_title = getattr(chat, "title", None) if chat else "مجموعة غير معروفة"
    if not chat_title:
        chat_title = "مجموعة غير معروفة"

    sender_id = 0
    sender_name = "مستخدم"
    username = None

    if sender:
        first_name = getattr(sender, "first_name", None) or ""
        last_name = getattr(sender, "last_name", None) or ""
        sender_name = f"{first_name} {last_name}".strip() or "مستخدم"
        sender_id = getattr(sender, "id", 0)
        username = getattr(sender, "username", None)

    # رابط الرسالة الأصلية داخل المجموعة
    message_link = build_message_link(chat, chat_id, message_id)

    # تحديد رابط التواصل الأضمن للمستخدم
    if username:
        # إذا يوجد يوزر، الرابط يفتح الخاص مباشرة
        direct_link = f"https://t.me/{escape(username)}"
        username_line = f'🔗 <a href="{direct_link}">@{escape(username)}</a>'
        action_button = f'💬 <a href="{direct_link}">اضغط للفتح المباشر للخاص</a>'
    elif message_link:
        # إذا لا يوجد يوزر، الرابط ينقل لرسالة الطالب في المجموعة لفتح الخاص بضغطة واحدة
        direct_link = message_link
        username_line = "🔗 بدون username"
        action_button = f'💬 <a href="{direct_link}">اضغط للتواصل مع الطالب (عبر المجموعة)</a>'
    else:
        direct_link = None
        username_line = "🔗 بدون username"
        action_button = "❌ تعذر إنشاء رابط التواصل"

    # تنسيق الاسم والأيدي بروابط تعمل 100%
    if direct_link:
        clickable_name = f'<a href="{direct_link}">{escape(sender_name)}</a>'
        clickable_id = f'<a href="{direct_link}">{sender_id}</a>'
    else:
        clickable_name = escape(sender_name)
        clickable_id = str(sender_id)

    # رابط المجموعة
    chat_link = build_chat_link(chat)
    if chat_link:
        chat_line = f'<a href="{chat_link}">{escape(chat_title)}</a>'
    else:
        chat_line = escape(chat_title)

    keyword_text = ", ".join(str(item) for item in matches) or "مطابقة"

    # الرسالة الموحدة
    return (
        "╭━━━ 🚗 <b>طلب توصيل جديد</b> ━━━╮\n\n"
        "📝 <b>نص الرسالة:</b>\n"
        f"{escape(text)}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 <b>الاسم:</b> {clickable_name}\n"
        f"🆔 <b>الأيدي:</b> {clickable_id}\n"
        f"{username_line}\n\n"
        f"{action_button}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "📡 <b>المجموعة:</b>\n"
        f"{chat_line}\n"
        f"🆔 <b>أيدي المجموعة:</b> <code>{chat_id}</code>\n\n"
        f"🧲 <b>الكلمات المطابقة:</b> {escape(keyword_text)}\n\n"
        "╰━━━━━━━━━━━━━━━━━━━━╯"
    )


# ============================================================
# PROCESS MESSAGE
# ============================================================

async def process_message(event):
    started = time.perf_counter()

    try:
        if not event.is_group:
            return

        text = (event.raw_text or "").strip()
        if not text:
            return

        matches = matched_keywords(text)
        if not matches:
            return

        chat = getattr(event, "chat", None)
        if chat is None:
            try:
                chat = await event.get_chat()
            except Exception as e:
                logger.warning(f"⚠️ تعذر جلب المجموعة: {e}")
                chat = None

        sender = getattr(event, "sender", None)
        if sender is None:
            try:
                sender = await event.get_sender()
            except Exception as e:
                logger.warning(f"⚠️ تعذر جلب المرسل: {e}")
                sender = None

        if sender and getattr(sender, "bot", False):
            logger.info(f"🤖 تم تجاهل رسالة بوت | message={event.id}")
            return

        formatted = build_message(
            event,
            text,
            matches,
            sender,
            chat,
        )

        # إرسال رسالة واحدة فقط للقناة
        async with send_lock:
            await client.send_message(
                TARGET_CHANNEL,
                formatted,
                parse_mode="html",
                link_preview=False,
            )

        elapsed = time.perf_counter() - started
        logger.info(
            f"✅ SENT | chat={event.chat_id} | message={event.id} | "
            f"keywords={matches[:5]} | {elapsed:.3f}s"
        )

    except FloodWaitError as e:
        seconds = max(int(e.seconds), 1)
        logger.warning(f"⏳ FloodWait: {seconds}s")
        await asyncio.sleep(seconds)

    except RPCError as e:
        logger.error(f"❌ Telegram RPC error | {type(e).__name__}: {e}")

    except asyncio.CancelledError:
        raise

    except Exception as e:
        logger.exception(f"❌ Message processing error | {type(e).__name__}: {e}")


# ============================================================
# EVENT HANDLER
# ============================================================

@client.on(events.NewMessage())
async def new_message(event):
    asyncio.create_task(process_message(event))


# ============================================================
# MAIN
# ============================================================

async def main():
    print("=" * 65)
    print("🚗 TELEGRAM DELIVERY MONITOR (SINGLE MESSAGE VERSION)")
    print("📢 TARGET:", TARGET_CHANNEL)
    print("=" * 65)

    while True:
        try:
            logger.info("🔌 جاري الاتصال بـ Telegram...")
            await client.connect()

            if not await client.is_user_authorized():
                logger.critical("❌ SESSION غير صالحة أو الحساب غير مصرح.")
                return

            me = await client.get_me()
            account_name = me.first_name or ""
            account_username = f"@{me.username}" if me.username else "بدون username"

            logger.info(
                f"✅ الحساب متصل | name={account_name} | id={me.id} | username={account_username}"
            )

            try:
                logger.info("🔄 تشغيل catch_up...")
                await client.catch_up()
                logger.info("✅ catch_up اكتمل.")
            except Exception as e:
                logger.warning(f"⚠️ catch_up error: {e}")

            logger.info("👂 الحساب يراقب المجموعات الآن...")
            await client.run_until_disconnected()

        except AuthKeyDuplicatedError:
            logger.critical("🚨 AuthKeyDuplicatedError: نفس SESSION مستخدمة في مكان آخر.")
            return

        except FloodWaitError as e:
            seconds = max(int(e.seconds), 1)
            logger.warning(f"⏳ Telegram طلب الانتظار {seconds} ثانية.")
            await asyncio.sleep(seconds)

        except RPCError as e:
            logger.error(f"❌ RPC ERROR | {type(e).__name__}: {e}")
            await asyncio.sleep(5)

        except asyncio.CancelledError:
            raise

        except Exception as e:
            logger.exception(f"❌ Connection error | {type(e).__name__}: {e}")
            await asyncio.sleep(5)

        finally:
            if client.is_connected():
                with suppress(Exception):
                    await client.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 تم إيقاف البرنامج.")

