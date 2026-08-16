# ============================================================
# plugins/delivery_monitor.py
#
# CipherElite Delivery Monitor
#
# SINGLE FILE VERSION
#
# الوظائف:
# - فحص جميع مجموعات الحساب عند التشغيل
# - استخراج IDs المجموعات
# - مراقبة الرسائل الواردة من جميع المجموعات
# - التقاط رسائل الأعضاء الآخرين
# - فلترة طلبات التوصيل والمشاوير
# - إرسال الرسائل المطابقة إلى LOG_CHAT_ID
# - اسم الطالب قابل للضغط
# - Telegram ID قابل للضغط
# - Username قابل للضغط عند وجوده
# - رابط الرسالة الأصلية
# - تجاهل البوتات
# - منع التكرار
# - معالجة FloodWait
# - إعادة فحص المجموعات دوريًا
# - لا يحتاج تعديل main.py أو startup.py
# ============================================================

import asyncio
import logging
import re
import time
from html import escape

from telethon import events
from telethon.errors import (
    FloodWaitError,
    RPCError,
)

from config.config import Config


# ============================================================
# VERSION
# ============================================================

VERSION = "2.0.0"


# ============================================================
# LOGGER
# ============================================================

logger = logging.getLogger(
    "cipherelite.delivery_monitor"
)


# ============================================================
# TARGET CHAT
# ============================================================

TARGET_CHAT_ID = getattr(
    Config,
    "LOG_CHAT_ID",
    0,
)


# ============================================================
# SETTINGS
# ============================================================

# إعادة فحص المجموعات كل 10 دقائق
GROUP_SCAN_INTERVAL = 600

# الحد الأقصى للرسائل التي نتذكرها لمنع التكرار
MAX_PROCESSED_MESSAGES = 20000

# عدد مهام معالجة الرسائل المتزامنة
MAX_CONCURRENT_TASKS = 20


# ============================================================
# KEYWORDS
# ============================================================

KEYWORDS = [

    "توصيل",
    "مشوار",
    "مشاوير",

    "من _الى",
    "من الى",

    "احتاج",

    "احتاج سيارة",
    "احتاج سواق",
    "احتاج سائق",

    "احتاج توصيل",
    "احتاج مواصلات",

    "شهري",

    "مندوب",

    "سواق",
    "سواقه",
    "سائق",
    "سائقه",

    "تاكسي",

    "سيارة",

    "باص",

    "نقل",

    "موصلات",

    "ابي توصيل",
    "أبي توصيل",

    "ابغى توصيل",
    "أبغى توصيل",

    "ابي باص",
    "أبي باص",

    "ابغى باص",
    "أبغى باص",

    "توصيل طلب",

    "يوصلني",
    "يوصلي",

    "يوديني",
    "يوديني مشوار",

    "تعرفون باص",

    "تعرفون سواق",
    "تعرفون سائق",

    "من رايحة",
    "من رايحه",

    "تواصل",

]


# ============================================================
# NORMALIZATION
# ============================================================

def normalize_text(text):

    if not text:
        return ""

    text = str(text).lower()

    replacements = {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ٱ": "ا",
        "ة": "ه",
        "ى": "ي",
    }

    for old, new in replacements.items():
        text = text.replace(
            old,
            new,
        )

    # إزالة التشكيل
    text = re.sub(
        r"[\u064B-\u065F\u0670]",
        "",
        text,
    )

    # توحيد المسافات
    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


# ============================================================
# PREPARE KEYWORDS
# ============================================================

NORMALIZED_KEYWORDS = tuple(
    (
        original,
        normalize_text(original),
    )
    for original in KEYWORDS
    if original
)


# ============================================================
# MATCH KEYWORDS
# ============================================================

def matched_keywords(text):

    normalized = normalize_text(
        text
    )

    if not normalized:
        return []

    matches = []

    for original, keyword in NORMALIZED_KEYWORDS:

        if keyword and keyword in normalized:

            matches.append(
                original
            )

    return list(
        dict.fromkeys(matches)
    )


# ============================================================
# SAFE HTML
# ============================================================

def safe_text(value):

    if value is None:
        return ""

    return escape(
        str(value)
    )


# ============================================================
# RUNTIME STATE
# ============================================================

processed_messages = set()

groups = {}

scan_task = None

processing_semaphore = asyncio.Semaphore(
    MAX_CONCURRENT_TASKS
)


# ============================================================
# REMEMBER MESSAGE
# ============================================================

def remember_message(chat_id, message_id):

    key = (
        int(chat_id or 0),
        int(message_id or 0),
    )

    if key in processed_messages:

        return False

    processed_messages.add(
        key
    )

    # تنظيف الذاكرة عند تجاوز الحد
    if len(processed_messages) > MAX_PROCESSED_MESSAGES:

        remove_count = (
            len(processed_messages)
            - MAX_PROCESSED_MESSAGES
        )

        for _ in range(
            max(remove_count, 1)
        ):

            try:
                processed_messages.pop()

            except KeyError:
                break

    return True


# ============================================================
# SCAN GROUPS
# ============================================================

async def scan_all_groups(client):

    global groups

    logger.warning(
        "🔎 Starting Telegram groups scan..."
    )

    new_groups = {}

    try:

        async for dialog in client.iter_dialogs():

            try:

                entity = dialog.entity

                # ------------------------------------------------
                # فقط المجموعات
                # ------------------------------------------------

                if not getattr(
                    dialog,
                    "is_group",
                    False,
                ):
                    continue

                chat_id = getattr(
                    entity,
                    "id",
                    None,
                )

                if not chat_id:
                    continue

                title = (
                    getattr(
                        entity,
                        "title",
                        None,
                    )
                    or "مجموعة بدون اسم"
                )

                username = getattr(
                    entity,
                    "username",
                    None,
                )

                new_groups[int(chat_id)] = {
                    "id": int(chat_id),
                    "title": title,
                    "username": username,
                }

            except Exception as e:

                logger.debug(
                    f"Group scan item error: {e}"
                )

        groups = new_groups

        logger.warning(
            f"📊 Groups detected: {len(groups)}"
        )

        # --------------------------------------------------------
        # عرض المجموعات
        # --------------------------------------------------------

        for group in groups.values():

            logger.info(
                "📡 GROUP | "
                f"{group['title']} | "
                f"ID={group['id']}"
            )

        logger.warning(
            "✅ Group scan completed"
        )

        return True

    except Exception as e:

        logger.exception(
            f"❌ Group scan failed: {e}"
        )

        return False


# ============================================================
# PERIODIC GROUP SCAN
# ============================================================

async def group_scan_loop(client):

    while True:

        try:

            await asyncio.sleep(
                GROUP_SCAN_INTERVAL
            )

            logger.info(
                "🔄 Periodic group scan..."
            )

            await scan_all_groups(
                client
            )

        except asyncio.CancelledError:

            raise

        except Exception as e:

            logger.exception(
                f"Periodic scan error: {e}"
            )

            await asyncio.sleep(
                10
            )


# ============================================================
# USER INFORMATION
# ============================================================

def build_user_info(sender):

    if sender is None:

        return (
            "مستخدم",
            "غير معروف",
            "🔗 بدون username",
            0,
        )

    user_id = getattr(
        sender,
        "id",
        0,
    )

    first_name = (
        getattr(
            sender,
            "first_name",
            None,
        )
        or ""
    )

    last_name = (
        getattr(
            sender,
            "last_name",
            None,
        )
        or ""
    )

    full_name = (
        f"{first_name} {last_name}"
    ).strip()

    if not full_name:

        full_name = "مستخدم"

    # --------------------------------------------------------
    # الاسم قابل للضغط
    # --------------------------------------------------------

    if user_id:

        clickable_name = (
            f'<a href="tg://user?id={user_id}">'
            f'{safe_text(full_name)}'
            f'</a>'
        )

        clickable_id = (
            f'<a href="tg://user?id={user_id}">'
            f'{user_id}'
            f'</a>'
        )

    else:

        clickable_name = safe_text(
            full_name
        )

        clickable_id = (
            "غير معروف"
        )

    # --------------------------------------------------------
    # Username
    # --------------------------------------------------------

    username = getattr(
        sender,
        "username",
        None,
    )

    if username:

        username_line = (
            f'🔗 <a href="https://t.me/'
            f'{safe_text(username)}">'
            f'@{safe_text(username)}'
            f'</a>'
        )

    else:

        username_line = (
            "🔗 بدون username"
        )

    return (
        clickable_name,
        clickable_id,
        username_line,
        user_id,
    )


# ============================================================
# MESSAGE LINK
# ============================================================

def build_message_link(
    chat,
    chat_id,
    message_id,
):

    if not chat_id:
        return None

    chat_username = getattr(
        chat,
        "username",
        None,
    )

    if chat_username:

        return (
            f"https://t.me/"
            f"{chat_username}/"
            f"{message_id}"
        )

    raw_chat_id = str(
        chat_id
    )

    if raw_chat_id.startswith(
        "-100"
    ):

        internal_id = (
            raw_chat_id[4:]
        )

        return (
            f"https://t.me/c/"
            f"{internal_id}/"
            f"{message_id}"
        )

    return None


# ============================================================
# BUILD DELIVERY MESSAGE
# ============================================================

def build_delivery_message(
    event,
    text,
    matches,
    sender,
    chat,
):

    chat_title = (
        getattr(
            chat,
            "title",
            None,
        )
        or "مجموعة غير معروفة"
    )

    (
        clickable_name,
        clickable_id,
        username_line,
        user_id,
    ) = build_user_info(
        sender
    )

    message_link = build_message_link(
        chat,
        event.chat_id,
        event.id,
    )

    if message_link:

        source_line = (
            f'🔗 <a href="{safe_text(message_link)}">'
            "الضغط للذهاب للرسالة الأصلية"
            "</a>"
        )

    else:

        source_line = (
            "🔗 رابط الرسالة الأصلية غير متاح"
        )

    keyword_text = ", ".join(
        matches
    )

    if not keyword_text:

        keyword_text = "مطابقة"

    message = (

        "╭━━━ 🚗 "
        "<b>طلب توصيل جديد</b> "
        "━━━╮\n\n"

        "📝 <b>نص الرسالة:</b>\n"

        f"{safe_text(text)}\n\n"

        "━━━━━━━━━━━━━━━━━━━━\n\n"

        f"👤 <b>الاسم:</b> "
        f"{clickable_name}\n"

        f"🆔 <b>الأيدي:</b> "
        f"{clickable_id}\n"

        f"{username_line}\n\n"

        f"📡 <b>المجموعة:</b> "
        f"{safe_text(chat_title)}\n"

        f"🆔 <b>أيدي المجموعة:</b> "
        f"<code>{event.chat_id}</code>\n\n"

        f"{source_line}\n\n"

        "━━━━━━━━━━━━━━━━━━━━\n\n"

        "🧲 <b>الكلمات المطابقة:</b>\n"

        f"{safe_text(keyword_text)}\n\n"

        "╰━━━━━━━━━━━━━━━━━━━━╯"

    )

    return (
        message,
        user_id,
    )


# ============================================================
# PROCESS MESSAGE
# ============================================================

async def process_delivery_message(
    client,
    event,
):

    async with processing_semaphore:

        started = time.perf_counter()

        try:

            # ------------------------------------------------
            # الرسائل الواردة فقط
            # ------------------------------------------------

            if getattr(
                event,
                "out",
                False,
            ):

                return

            # ------------------------------------------------
            # Groups only
            # ------------------------------------------------

            if not event.is_group:

                return

            # ------------------------------------------------
            # لا تعالج قناة الإرسال
            # ------------------------------------------------

            if (
                TARGET_CHAT_ID
                and event.chat_id
                == TARGET_CHAT_ID
            ):

                return

            # ------------------------------------------------
            # منع التكرار
            # ------------------------------------------------

            if not remember_message(
                event.chat_id,
                event.id,
            ):

                return

            # ------------------------------------------------
            # النص
            # ------------------------------------------------

            text = (
                event.raw_text
                or ""
            ).strip()

            if not text:

                return

            # ------------------------------------------------
            # الفلترة
            # ------------------------------------------------

            matches = matched_keywords(
                text
            )

            if not matches:

                return

            # ------------------------------------------------
            # Sender
            # ------------------------------------------------

            sender = getattr(
                event,
                "sender",
                None,
            )

            if sender is None:

                try:

                    sender = (
                        await event.get_sender()
                    )

                except Exception:

                    sender = None

            # ------------------------------------------------
            # Ignore bots
            # ------------------------------------------------

            if sender:

                if getattr(
                    sender,
                    "bot",
                    False,
                ):

                    return

            # ------------------------------------------------
            # Chat
            # ------------------------------------------------

            chat = getattr(
                event,
                "chat",
                None,
            )

            if chat is None:

                try:

                    chat = (
                        await event.get_chat()
                    )

                except Exception:

                    chat = None

            # ------------------------------------------------
            # Build
            # ------------------------------------------------

            (
                final_message,
                user_id,
            ) = build_delivery_message(

                event,

                text,

                matches,

                sender,

                chat,

            )

            # ------------------------------------------------
            # Send
            # ------------------------------------------------

            await client.send_message(

                TARGET_CHAT_ID,

                final_message,

                parse_mode="html",

                link_preview=False,

            )

            elapsed = (
                time.perf_counter()
                - started
            )

            logger.info(

                "✅ DELIVERY SENT | "

                f"chat={event.chat_id} | "

                f"message={event.id} | "

                f"user={user_id} | "

                f"keywords={matches} | "

                f"{elapsed:.3f}s"

            )

        except FloodWaitError as e:

            seconds = max(
                int(e.seconds),
                1,
            )

            logger.warning(
                f"⏳ FloodWait: {seconds}s"
            )

            await asyncio.sleep(
                seconds
            )

        except RPCError as e:

            logger.error(

                "❌ Telegram RPC error | "

                f"{type(e).__name__}: {e}"

            )

        except asyncio.CancelledError:

            raise

        except Exception as e:

            logger.exception(

                "❌ Delivery monitor error | "

                f"{type(e).__name__}: {e}"

            )


# ============================================================
# EVENT HANDLER
# ============================================================

async def delivery_handler(
    client,
    event,
):

    # تشغيل المعالجة بدون تعطيل استقبال الرسائل التالية
    asyncio.create_task(
        process_delivery_message(
            client,
            event,
        )
    )


# ============================================================
# PLUGIN INIT
# ============================================================

def init(client):

    global scan_task

    # --------------------------------------------------------
    # Target
    # --------------------------------------------------------

    if not TARGET_CHAT_ID:

        logger.error(
            "❌ LOG_CHAT_ID غير مضبوط."
        )

        return

    # --------------------------------------------------------
    # تسجيل Handler واحد لجميع الرسائل الواردة
    # --------------------------------------------------------

    client.add_event_handler(

        lambda event: delivery_handler(
            client,
            event,
        ),

        events.NewMessage(
            incoming=True
        ),

    )

    # --------------------------------------------------------
    # Startup scan
    # --------------------------------------------------------

    async def startup_scan():

        global scan_task

        try:

            await scan_all_groups(
                client
            )

            # بدء الفحص الدوري

            if scan_task is None:

                scan_task = asyncio.create_task(

                    group_scan_loop(
                        client
                    )

                )

        except asyncio.CancelledError:

            raise

        except Exception as e:

            logger.exception(
                f"Startup scan error: {e}"
            )

    # --------------------------------------------------------
    # تنفيذ الفحص بعد بدء الـEvent Loop
    # --------------------------------------------------------

    asyncio.create_task(
        startup_scan()
    )

    # --------------------------------------------------------
    # Logs
    # --------------------------------------------------------

    logger.warning(
        "🚗 Delivery Monitor loaded successfully"
    )

    logger.warning(
        "👂 Monitoring incoming group messages"
    )

    logger.warning(
        "⚡ Fast event-based monitoring enabled"
    )

    logger.warning(
        f"📢 Target: {TARGET_CHAT_ID}"
    )

    logger.warning(
        f"🧲 Keywords: {len(KEYWORDS)}"
    )

    logger.warning(
        "♻️ Automatic group rescan: 10 minutes"
    )
