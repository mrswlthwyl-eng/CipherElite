# ============================================================
# plugins/delivery_monitor.py
#
# CipherElite Delivery Monitor
#
# يعمل داخل CipherElite باستخدام Telegram Client الأصلي
# لا ينشئ Session جديدة
# لا يغير main.py
# لا يغير startup.py
#
# الوظائف:
# - مراقبة الرسائل الجديدة في المجموعات
# - فلترة طلبات التوصيل والمشاوير
# - إرسال الطلبات إلى LOG_CHAT_ID
# - اسم المستخدم قابل للضغط
# - Telegram ID قابل للضغط
# - Username قابل للضغط إذا موجود
# - رابط الرسالة الأصلية
# - تجاهل البوتات
# - معالجة FloodWait
# ============================================================

import asyncio
import logging
import re
from contextlib import suppress
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

VERSION = "1.0.0"


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
# KEYWORDS
# ============================================================

KEYWORDS = [
    "توصيل",
    "مشوار",
    "مشاوير",
    "من _الى",
    "من الى",

    "احتاج سيارة",
    "احتاج سواق",
    "احتاج سائق",

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

    "ابي توصيل",
    "أبي توصيل",

    "ابغى توصيل",
    "أبغى توصيل",

    "تواصل",

    "من رايحة",

    "تعرفون باص",

    "تعرفون سواق",
    "تعرفون سائق",

    "ابغى باص",
    "أبغى باص",

    "توصيل طلب",

    "يوصلني",
    "يوصلي",

    "يوديني",
    "يوديني مشوار",
]


# ============================================================
# NORMALIZATION
# ============================================================

def normalize_text(text):
    """
    توحيد الحروف العربية والمسافات
    لتقليل اختلافات الكتابة.
    """

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


NORMALIZED_KEYWORDS = [
    (
        original,
        normalize_text(original),
    )
    for original in KEYWORDS
]


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

        if not keyword:
            continue

        if keyword in normalized:

            matches.append(
                original
            )

    return list(
        dict.fromkeys(
            matches
        )
    )


# ============================================================
# HTML ESCAPE
# ============================================================

def safe_text(value):

    if value is None:
        return ""

    return escape(
        str(value)
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


    # --------------------------------------------------------
    # ID
    # --------------------------------------------------------

    user_id = getattr(
        sender,
        "id",
        0,
    )


    # --------------------------------------------------------
    # NAME
    # --------------------------------------------------------

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
    # CLICKABLE NAME
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

        clickable_name = (
            safe_text(full_name)
        )

        clickable_id = (
            "غير معروف"
        )


    # --------------------------------------------------------
    # USERNAME
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


    # --------------------------------------------------------
    # PUBLIC USERNAME
    # --------------------------------------------------------

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


    # --------------------------------------------------------
    # PRIVATE SUPERGROUP
    # --------------------------------------------------------

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
# BUILD MESSAGE
# ============================================================

def build_delivery_message(
    event,
    text,
    matches,
    sender,
    chat,
):

    # --------------------------------------------------------
    # CHAT TITLE
    # --------------------------------------------------------

    if chat:

        chat_title = (
            getattr(
                chat,
                "title",
                None,
            )
            or "مجموعة غير معروفة"
        )

    else:

        chat_title = (
            "مجموعة غير معروفة"
        )


    # --------------------------------------------------------
    # USER
    # --------------------------------------------------------

    (
        clickable_name,
        clickable_id,
        username_line,
        user_id,
    ) = build_user_info(
        sender
    )


    # --------------------------------------------------------
    # SOURCE MESSAGE LINK
    # --------------------------------------------------------

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


    # --------------------------------------------------------
    # KEYWORDS
    # --------------------------------------------------------

    keyword_text = ", ".join(
        matches
    )


    if not keyword_text:

        keyword_text = "مطابقة"


    # --------------------------------------------------------
    # FINAL MESSAGE
    # --------------------------------------------------------

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

    return message, user_id


# ============================================================
# PROCESS MESSAGE
# ============================================================

async def process_delivery_message(
    client,
    event,
):

    try:

        # ====================================================
        # GROUPS ONLY
        # ====================================================

        if not event.is_group:

            return


        # ====================================================
        # TEXT
        # ====================================================

        text = (
            event.raw_text
            or ""
        ).strip()


        if not text:

            return


        # ====================================================
        # FILTER
        # ====================================================

        matches = matched_keywords(
            text
        )


        if not matches:

            return


        # ====================================================
        # SENDER
        # ====================================================

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


        # ====================================================
        # IGNORE BOTS
        # ====================================================

        if sender:

            if getattr(
                sender,
                "bot",
                False,
            ):

                return


        # ====================================================
        # CHAT
        # ====================================================

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


        # ====================================================
        # BUILD
        # ====================================================

        final_message, user_id = (
            build_delivery_message(
                event,
                text,
                matches,
                sender,
                chat,
            )
        )


        # ====================================================
        # SEND
        # ====================================================

        await client.send_message(

            TARGET_CHAT_ID,

            final_message,

            parse_mode="html",

            link_preview=False,

        )


        logger.info(

            "Delivery message sent | "
            f"chat={event.chat_id} | "
            f"message={event.id} | "
            f"user={user_id} | "
            f"keywords={matches}"

        )


    except FloodWaitError as e:

        seconds = max(
            int(e.seconds),
            1,
        )

        logger.warning(
            f"FloodWait: {seconds}s"
        )

        await asyncio.sleep(
            seconds
        )


    except RPCError as e:

        logger.error(

            f"Telegram RPC error: "
            f"{type(e).__name__}: {e}"

        )


    except asyncio.CancelledError:

        raise


    except Exception as e:

        logger.exception(
            f"Delivery monitor error: {e}"
        )


# ============================================================
# PLUGIN INIT
# ============================================================

def init(client):

    # --------------------------------------------------------
    # CHECK TARGET
    # --------------------------------------------------------

    if not TARGET_CHAT_ID:

        logger.warning(
            "⚠️ LOG_CHAT_ID غير مضبوط."
        )

        return


    # --------------------------------------------------------
    # EVENT HANDLER
    # --------------------------------------------------------

    @client.on(
        events.NewMessage()
    )
    async def delivery_handler(event):

        await process_delivery_message(
            client,
            event,
        )


    logger.info(
        "🚗 Delivery Monitor loaded successfully"
    )

    logger.info(
        f"📢 Target: {TARGET_CHAT_ID}"
    )

    logger.info(
        f"🧲 Keywords: {len(KEYWORDS)}"
    )
