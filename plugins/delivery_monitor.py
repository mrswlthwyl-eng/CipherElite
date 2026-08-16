# ============================================================
# plugins/delivery_monitor.py
#
# CipherElite Delivery Monitor
#
# - يستخدم Telegram Client الأصلي الخاص بـ CipherElite
# - لا ينشئ Session جديدة
# - لا ينشئ TelegramClient جديد
# - يراقب الرسائل الواردة من المجموعات
# - يلتقط رسائل المستخدمين الآخرين
# - يفلتر طلبات التوصيل والمشاوير
# - يرسل المطابق إلى LOG_CHAT_ID
# - الاسم قابل للضغط
# - Telegram ID قابل للضغط
# - Username قابل للضغط عند وجوده
# - رابط الرسالة الأصلية
# - يتجاهل البوتات
# - يمنع تكرار معالجة نفس الرسالة
# - يمنع معالجة قناة الإرسال نفسها
# - يدعم FloodWait
# - يحتوي على Logs للتشخيص
# ============================================================

import asyncio
import logging
import re
import time
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

    "احتاج",

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

    "احتاج توصيل",
    "احتاج مواصلات",

    "موصلات",

    "تواصل",

    "من رايحة",
    "من رايحه",

    "تعرفون باص",

    "تعرفون سواق",
    "تعرفون سائق",

    "ابغى باص",
    "أبغى باص",

    "ابي باص",
    "أبي باص",

    "توصيل طلب",

    "يوصلني",
    "يوصلي",

    "يوديني",
    "يوديني مشوار",

]


# ============================================================
# RUNTIME STATE
# ============================================================

# منع معالجة الرسالة نفسها أكثر من مرة
processed_messages = set()

# حد أقصى للذاكرة
MAX_PROCESSED_MESSAGES = 20000

# قفل الإرسال
send_lock = asyncio.Lock()

# وقت آخر Log تشخيصي
last_debug_log = 0.0


# ============================================================
# NORMALIZATION
# ============================================================

def normalize_text(text):

    if not text:

        return ""

    text = str(
        text
    ).lower()


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


    # --------------------------------------------------------
    # إزالة التشكيل
    # --------------------------------------------------------

    text = re.sub(
        r"[\u064B-\u065F\u0670]",
        "",
        text,
    )


    # --------------------------------------------------------
    # توحيد المسافات
    # --------------------------------------------------------

    text = re.sub(
        r"\s+",
        " ",
        text,
    )


    return text.strip()


# ============================================================
# NORMALIZED KEYWORDS
# ============================================================

NORMALIZED_KEYWORDS = [

    (
        original,
        normalize_text(original),
    )

    for original in KEYWORDS

    if original

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
# SAFE HTML
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

        f"{first_name} "
        f"{last_name}"

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
    # PRIVATE / SUPERGROUP
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
# BUILD DELIVERY MESSAGE
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
    # MESSAGE LINK
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
    # FINAL
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
# MESSAGE KEY
# ============================================================

def get_message_key(event):

    return (

        int(event.chat_id or 0),

        int(event.id or 0),

    )


# ============================================================
# REMEMBER MESSAGE
# ============================================================

def remember_message(key):

    processed_messages.add(
        key
    )


    # --------------------------------------------------------
    # منع تضخم الذاكرة
    # --------------------------------------------------------

    if len(
        processed_messages
    ) > MAX_PROCESSED_MESSAGES:

        # حذف جزء من العناصر
        # بشكل آمن وبسيط

        amount = (

            len(processed_messages)
            - MAX_PROCESSED_MESSAGES

        )


        for _ in range(
            max(amount, 1)
        ):

            try:

                processed_messages.pop()

            except KeyError:

                break


# ============================================================
# PROCESS MESSAGE
# ============================================================

async def process_delivery_message(
    client,
    event,
):

    started = time.perf_counter()


    try:

        # ====================================================
        # IMPORTANT:
        # Incoming messages only
        # ====================================================

        if getattr(
            event,
            "out",
            False,
        ):

            return


        # ====================================================
        # GROUPS
        # ====================================================

        if not event.is_group:

            return


        # ====================================================
        # TARGET CHAT
        # ====================================================

        # لا نعالج رسائل قناة الإرسال نفسها

        if (
            TARGET_CHAT_ID
            and event.chat_id
            == TARGET_CHAT_ID
        ):

            return


        # ====================================================
        # MESSAGE ID
        # ====================================================

        message_key = get_message_key(
            event
        )


        if message_key in processed_messages:

            return


        remember_message(
            message_key
        )


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

                logger.info(

                    "Ignored bot message | "

                    f"chat={event.chat_id} | "

                    f"message={event.id}"

                )

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


        # ====================================================
        # SEND
        # ====================================================

        async with send_lock:

            await client.send_message(

                TARGET_CHAT_ID,

                final_message,

                parse_mode="html",

                link_preview=False,

            )


        # ====================================================
        # LOG
        # ====================================================

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

            f"⏳ Telegram FloodWait: "
            f"{seconds}s"

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
# PLUGIN INIT
# ============================================================

def init(client):

    # --------------------------------------------------------
    # TARGET CHECK
    # --------------------------------------------------------

    if not TARGET_CHAT_ID:

        logger.error(

            "❌ LOG_CHAT_ID غير مضبوط."

        )

        return


    # --------------------------------------------------------
    # EVENT HANDLER
    #
    # incoming=True مهم:
    # يستقبل الرسائل الواردة من الآخرين.
    # --------------------------------------------------------

    @client.on(
        events.NewMessage(
            incoming=True
        )
    )
    async def delivery_handler(event):

        try:

            await process_delivery_message(

                client,

                event,

            )

        except Exception as e:

            logger.exception(

                "Unhandled delivery handler error: "

                f"{e}"

            )


    # --------------------------------------------------------
    # STARTUP LOG
    # --------------------------------------------------------

    logger.info(
        "🚗 Delivery Monitor loaded successfully"
    )

    logger.info(
        "👂 Monitoring INCOMING group messages"
    )

    logger.info(
        f"📢 Target: {TARGET_CHAT_ID}"
    )

    logger.info(
        f"🧲 Keywords: {len(KEYWORDS)}"
    )

    logger.info(
        "👤 Other users: ENABLED"
    )

    logger.info(
        "🤖 Bots: IGNORED"
    )
