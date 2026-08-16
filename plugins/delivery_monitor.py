# ============================================================
# CipherElite Delivery Monitor
#
# File:
# plugins/delivery_monitor.py
#
# الوظائف:
# - فحص جميع مجموعات الحساب عند التشغيل
# - تسجيل Group IDs
# - مراقبة رسائل جميع المجموعات
# - استقبال رسائل الأعضاء
# - تجاهل رسائل الحساب نفسه
# - تجاهل البوتات
# - فلترة كلمات التوصيل
# - إرسال الطلب إلى LOG_CHAT_ID
# - زر "فتح الخاص" الحقيقي عند توفر InputUser
# - دعم المستخدم الذي لا يملك username
# - رابط الرسالة الأصلية
# - إعادة فحص المجموعات الجديدة تلقائياً
# - العمل بشكل مستمر مع نفس Telethon Client
# - لا يحتاج Session جديدة
# - لا يحتاج تعديل main.py
# - لا يحتاج تعديل startup.py
# ============================================================

import asyncio
import logging
import re
from html import escape

from telethon import events, Button
from telethon.errors import (
    FloodWaitError,
    RPCError,
)
from telethon.tl.types import InputKeyboardButtonUserProfile

from config.config import Config


# ============================================================
# VERSION
# ============================================================

VERSION = "4.0.0"


# ============================================================
# LOGGER
# ============================================================

logger = logging.getLogger(
    "cipherelite.delivery_monitor"
)


# ============================================================
# TARGET CHAT
# ============================================================

try:
    TARGET_CHAT_ID = int(
        getattr(Config, "LOG_CHAT_ID", 0) or 0
    )
except Exception:
    TARGET_CHAT_ID = 0


# ============================================================
# SETTINGS
# ============================================================

GROUP_REFRESH_SECONDS = 300

SEND_TIMEOUT = 20

# لمنع تكرار نفس الرسالة
MAX_PROCESSED_CACHE = 5000


# ============================================================
# KEYWORDS
# ============================================================

KEYWORDS = [

    # --------------------------------------------------------
    # توصيل
    # --------------------------------------------------------

    "توصيل",
    "توصيل طلب",
    "احتاج توصيل",
    "احتاج مواصلات",

    "ابي توصيل",
    "أبي توصيل",

    "ابغى توصيل",
    "أبغى توصيل",

    "احتاج سيارة",
    "احتاج سواق",
    "احتاج سائق",

    "ابي سيارة",
    "أبي سيارة",

    "ابغى سيارة",
    "أبغى سيارة",

    "ابي سواق",
    "أبي سواق",

    "ابغى سواق",
    "أبغى سواق",

    "ابي سائق",
    "أبي سائق",

    "ابغى سائق",
    "أبغى سائق",

    # --------------------------------------------------------
    # مشاوير
    # --------------------------------------------------------

    "مشوار",
    "مشاوير",

    "يوديني",
    "يوديني مشوار",

    "يوصلني",
    "يوصلي",

    "من الى",
    "من _الى",

    # --------------------------------------------------------
    # سائق
    # --------------------------------------------------------

    "سواق",
    "سواقه",

    "سائق",
    "سائقه",

    "تعرفون سواق",
    "تعرفون سائق",

    "تعرفون باص",

    # --------------------------------------------------------
    # سيارات
    # --------------------------------------------------------

    "سيارة",
    "سياره",

    "باص",

    "تاكسي",

    # --------------------------------------------------------
    # نقل
    # --------------------------------------------------------

    "نقل",
    "مندوب",
    "موصلات",

    # --------------------------------------------------------
    # دوام
    # --------------------------------------------------------

    "شهري",
    "دوام",

]


# ============================================================
# NORMALIZATION
# ============================================================

def normalize_text(text):
    """
    توحيد النص العربي لتقليل اختلافات الكتابة.
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


# ============================================================
# NORMALIZED KEYWORDS
# ============================================================

NORMALIZED_KEYWORDS = [
    (
        original,
        normalize_text(original),
    )
    for original in KEYWORDS
]


# ============================================================
# GLOBAL STATE
# ============================================================

GROUP_IDS = set()

GROUP_INFO = {}

PROCESSED_MESSAGES = set()

CLIENT = None

OWNER_ID = 0

MONITOR_STARTED = False

REFRESH_TASK = None


# ============================================================
# SAFE HTML
# ============================================================

def safe(value):

    if value is None:
        return ""

    return escape(
        str(value)
    )


# ============================================================
# MATCH KEYWORDS
# ============================================================

def get_matches(text):

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
# MESSAGE CACHE
# ============================================================

def message_cache_key(event):

    try:

        return (
            int(event.chat_id),
            int(event.id),
        )

    except Exception:

        return None


def already_processed(event):

    key = message_cache_key(
        event
    )

    if key is None:
        return False

    if key in PROCESSED_MESSAGES:
        return True

    PROCESSED_MESSAGES.add(
        key
    )

    # الحفاظ على حجم الذاكرة
    if len(PROCESSED_MESSAGES) > MAX_PROCESSED_CACHE:

        # إزالة مجموعة من العناصر القديمة
        remove_count = (
            len(PROCESSED_MESSAGES)
            - MAX_PROCESSED_CACHE
        )

        for item in list(
            PROCESSED_MESSAGES
        )[:remove_count]:

            PROCESSED_MESSAGES.discard(
                item
            )

    return False


# ============================================================
# GET USER INFO
# ============================================================

def get_user_info(sender):

    if sender is None:

        return (
            "مستخدم",
            0,
            None,
        )

    try:

        user_id = int(
            getattr(
                sender,
                "id",
                0,
            )
            or 0
        )

    except Exception:

        user_id = 0

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

    username = (
        getattr(
            sender,
            "username",
            None,
        )
        or None
    )

    full_name = (
        f"{first_name} {last_name}"
    ).strip()

    if not full_name:

        full_name = "مستخدم"

    return (
        full_name,
        user_id,
        username,
    )


# ============================================================
# MESSAGE LINK
# ============================================================

def get_message_link(
    chat,
    chat_id,
    message_id,
):

    if not chat_id:
        return None

    # --------------------------------------------------------
    # Public username
    # --------------------------------------------------------

    username = getattr(
        chat,
        "username",
        None,
    )

    if username:

        return (
            f"https://t.me/"
            f"{username}/"
            f"{message_id}"
        )

    # --------------------------------------------------------
    # Private supergroup
    # --------------------------------------------------------

    raw_id = str(
        chat_id
    )

    if raw_id.startswith(
        "-100"
    ):

        internal_id = raw_id[4:]

        return (
            f"https://t.me/c/"
            f"{internal_id}/"
            f"{message_id}"
        )

    return None


# ============================================================
# BUILD MESSAGE
# ============================================================

def build_message(
    event,
    text,
    matches,
    sender,
    chat,
):

    (
        full_name,
        user_id,
        username,
    ) = get_user_info(
        sender
    )

    # --------------------------------------------------------
    # Chat
    # --------------------------------------------------------

    chat_title = (
        getattr(
            chat,
            "title",
            None,
        )
        or "مجموعة غير معروفة"
    )

    # --------------------------------------------------------
    # Clickable name
    # --------------------------------------------------------

    if user_id:

        clickable_name = (
            f'<a href="tg://user?id={user_id}">'
            f'{safe(full_name)}'
            f'</a>'
        )

        clickable_id = (
            f'<a href="tg://user?id={user_id}">'
            f'{user_id}'
            f'</a>'
        )

    else:

        clickable_name = safe(
            full_name
        )

        clickable_id = (
            "غير معروف"
        )

    # --------------------------------------------------------
    # Username
    # --------------------------------------------------------

    if username:

        username_line = (
            f'🔗 <a href="https://t.me/'
            f'{safe(username)}">'
            f'@{safe(username)}'
            f'</a>'
        )

    else:

        username_line = (
            "🔗 بدون username"
        )

    # --------------------------------------------------------
    # Original message
    # --------------------------------------------------------

    message_link = get_message_link(
        chat,
        event.chat_id,
        event.id,
    )

    if message_link:

        source_line = (
            f'🔗 <a href="{safe(message_link)}">'
            "الذهاب للرسالة الأصلية"
            "</a>"
        )

    else:

        source_line = (
            "🔗 رابط الرسالة الأصلية غير متاح"
        )

    # --------------------------------------------------------
    # Keywords
    # --------------------------------------------------------

    keyword_text = ", ".join(
        matches
    )

    # --------------------------------------------------------
    # Final message
    # --------------------------------------------------------

    message = (

        "╭━━━ 🚗 "
        "<b>طلب توصيل جديد</b> "
        "━━━╮\n\n"

        "📝 <b>نص الرسالة:</b>\n"

        f"{safe(text)}\n\n"

        "━━━━━━━━━━━━━━━━━━━━\n\n"

        f"👤 <b>الاسم:</b> "
        f"{clickable_name}\n"

        f"🆔 <b>الأيدي:</b> "
        f"{clickable_id}\n"

        f"{username_line}\n\n"

        f"📡 <b>المجموعة:</b> "
        f"{safe(chat_title)}\n"

        f"🆔 <b>أيدي المجموعة:</b> "
        f"<code>{event.chat_id}</code>\n\n"

        f"{source_line}\n\n"

        "━━━━━━━━━━━━━━━━━━━━\n\n"

        "🧲 <b>الكلمات المطابقة:</b>\n"

        f"{safe(keyword_text)}\n\n"

        "╰━━━━━━━━━━━━━━━━━━━━╯"

    )

    return (
        message,
        user_id,
    )


# ============================================================
# SEND RESULT
# ============================================================

async def send_result(
    client,
    message,
    user_id,
):

    if not TARGET_CHAT_ID:

        logger.error(
            "LOG_CHAT_ID is not configured."
        )

        return False

    # --------------------------------------------------------
    # Real Telegram User Profile button
    # --------------------------------------------------------

    if user_id:

        try:

            input_user = (
                await client.get_input_entity(
                    user_id
                )
            )

            profile_button = (
                InputKeyboardButtonUserProfile(
                    text="👤 فتح الخاص",
                    user_id=input_user,
                )
            )

            buttons = [
                [
                    profile_button
                ]
            ]

            await client.send_message(
                TARGET_CHAT_ID,
                message,
                parse_mode="html",
                link_preview=False,
                buttons=buttons,
            )

            return True

        except Exception as e:

            logger.warning(
                "UserProfile button failed: "
                f"{type(e).__name__}: {e}"
            )

    # --------------------------------------------------------
    # Fallback
    # --------------------------------------------------------

    if user_id:

        try:

            buttons = [
                [
                    Button.url(
                        "👤 فتح الخاص",
                        f"tg://user?id={user_id}",
                    )
                ]
            ]

            await client.send_message(
                TARGET_CHAT_ID,
                message,
                parse_mode="html",
                link_preview=False,
                buttons=buttons,
            )

            return True

        except Exception as e:

            logger.warning(
                "Fallback profile button failed: "
                f"{type(e).__name__}: {e}"
            )

    # --------------------------------------------------------
    # Normal message
    # --------------------------------------------------------

    try:

        await client.send_message(
            TARGET_CHAT_ID,
            message,
            parse_mode="html",
            link_preview=False,
        )

        return True

    except Exception as e:

        logger.error(
            f"Could not send result: {e}"
        )

        return False


# ============================================================
# SCAN ALL GROUPS
# ============================================================

async def scan_groups(
    client,
):

    global GROUP_IDS
    global GROUP_INFO

    new_ids = set()

    new_info = {}

    try:

        async for dialog in client.iter_dialogs():

            # ------------------------------------------------
            # Groups only
            # ------------------------------------------------

            if not dialog.is_group:

                continue

            entity = dialog.entity

            chat_id = getattr(
                entity,
                "id",
                None,
            )

            if not chat_id:

                continue

            try:

                chat_id = int(
                    chat_id
                )

            except Exception:

                continue

            # ------------------------------------------------
            # Telethon group IDs
            # ------------------------------------------------

            # Store the Telegram dialog ID as exposed by event.chat_id.
            #
            # For filtering we use the actual event chat_id.
            # This is the same identifier Telethon provides
            # to NewMessage events.

            new_ids.add(
                chat_id
            )

            title = (
                getattr(
                    entity,
                    "title",
                    None,
                )
                or "Unknown"
            )

            username = (
                getattr(
                    entity,
                    "username",
                    None,
                )
                or None
            )

            new_info[
                chat_id
            ] = {
                "title": title,
                "username": username,
            }

        old_count = len(
            GROUP_IDS
        )

        GROUP_IDS = new_ids

        GROUP_INFO = new_info

        new_count = len(
            GROUP_IDS
        )

        logger.warning(
            "🔎 Telegram groups detected: "
            f"{new_count}"
        )

        logger.warning(
            "👂 Monitoring all detected groups"
        )

        if new_count != old_count:

            logger.warning(
                "🔄 Group list updated: "
                f"{old_count} -> {new_count}"
            )

    except Exception as e:

        logger.exception(
            f"Group scan failed: {e}"
        )


# ============================================================
# GROUP REFRESH LOOP
# ============================================================

async def refresh_groups_loop(
    client,
):

    while True:

        try:

            await asyncio.sleep(
                GROUP_REFRESH_SECONDS
            )

            await scan_groups(
                client
            )

        except asyncio.CancelledError:

            raise

        except Exception as e:

            logger.exception(
                f"Group refresh error: {e}"
            )

            await asyncio.sleep(
                10
            )


# ============================================================
# PROCESS MESSAGE
# ============================================================

async def process_message(
    client,
    event,
):

    try:

        # ====================================================
        # CHAT ID
        # ====================================================

        chat_id = getattr(
            event,
            "chat_id",
            None,
        )

        if not chat_id:

            return

        try:

            chat_id = int(
                chat_id
            )

        except Exception:

            return

        # ====================================================
        # GROUP CHECK
        # ====================================================

        if not event.is_group:

            return

        # ====================================================
        # TARGET LOG CHAT
        # ====================================================

        if (
            TARGET_CHAT_ID
            and chat_id == TARGET_CHAT_ID
        ):

            return

        # ====================================================
        # GROUP LIST CHECK
        #
        # إذا لم تنتهِ عملية الفحص بعد، لا نسقط الرسالة.
        # أما بعد الفحص، نقبل فقط المجموعات المكتشفة.
        # ====================================================

        if GROUP_IDS:

            if chat_id not in GROUP_IDS:

                return

        # ====================================================
        # MESSAGE
        # ====================================================

        text = (
            getattr(
                event,
                "raw_text",
                None,
            )
            or ""
        ).strip()

        if not text:

            return

        # ====================================================
        # KEYWORDS
        # ====================================================

        matches = get_matches(
            text
        )

        if not matches:

            return

        # ====================================================
        # DUPLICATE CHECK
        # ====================================================

        if already_processed(
            event
        ):

            return

        # ====================================================
        # SENDER
        # ====================================================

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
        # IGNORE OUR OWN ACCOUNT
        #
        # مهم:
        # لا نعتمد على event.out فقط.
        # نتحقق من ID الحساب نفسه.
        # ====================================================

        sender_id = 0

        if sender:

            try:

                sender_id = int(
                    getattr(
                        sender,
                        "id",
                        0,
                    )
                    or 0
                )

            except Exception:

                sender_id = 0

        if (
            OWNER_ID
            and sender_id == OWNER_ID
        ):

            return

        # ====================================================
        # CHAT
        # ====================================================

        try:

            chat = await event.get_chat()

        except Exception:

            chat = GROUP_INFO.get(
                chat_id
            )

        # ====================================================
        # BUILD
        # ====================================================

        (
            final_message,
            user_id,
        ) = build_message(
            event,
            text,
            matches,
            sender,
            chat,
        )

        # ====================================================
        # SEND
        # ====================================================

        success = await send_result(
            client,
            final_message,
            user_id,
        )

        if success:

            logger.info(
                "✅ DELIVERY SENT | "
                f"chat={chat_id} | "
                f"user={user_id} | "
                f"keywords={matches}"
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
            "Telegram RPC error: "
            f"{type(e).__name__}: {e}"
        )

    except asyncio.CancelledError:

        raise

    except Exception as e:

        logger.exception(
            f"Delivery monitor error: {e}"
        )


# ============================================================
# EVENT HANDLER
# ============================================================

async def event_handler(
    event,
):

    if CLIENT is None:

        return

    # ========================================================
    # IMPORTANT
    #
    # لا نستخدم incoming=True هنا.
    #
    # نستخدم NewMessage() ثم نحدد الحساب المرسل بأنفسنا.
    # هذا يجعل الاستقبال يعتمد على نفس Telegram client
    # بدون تقييد event builder.
    # ========================================================

    asyncio.create_task(
        process_message(
            CLIENT,
            event,
        )
    )


# ============================================================
# INIT
# ============================================================

def init(client):

    global CLIENT
    global OWNER_ID
    global MONITOR_STARTED
    global REFRESH_TASK

    # --------------------------------------------------------
    # Prevent duplicate initialization
    # --------------------------------------------------------

    if MONITOR_STARTED:

        logger.warning(
            "Delivery Monitor already initialized."
        )

        return

    # --------------------------------------------------------
    # Target
    # --------------------------------------------------------

    if not TARGET_CHAT_ID:

        logger.error(
            "❌ LOG_CHAT_ID غير مضبوط."
        )

        return

    # --------------------------------------------------------
    # Save client
    # --------------------------------------------------------

    CLIENT = client

    # --------------------------------------------------------
    # Get account ID
    # --------------------------------------------------------

    async def initialize():

        global OWNER_ID
        global REFRESH_TASK

        try:

            me = await client.get_me()

            if me:

                try:

                    OWNER_ID = int(
                        me.id
                    )

                except Exception:

                    OWNER_ID = 0

            logger.warning(
                "👤 Account ID: "
                f"{OWNER_ID}"
            )

        except Exception as e:

            logger.warning(
                "Could not determine account ID: "
                f"{e}"
            )

        # ----------------------------------------------------
        # Scan groups
        # ----------------------------------------------------

        await scan_groups(
            client
        )

        # ----------------------------------------------------
        # Start refresh loop
        # ----------------------------------------------------

        if REFRESH_TASK is None:

            REFRESH_TASK = (
                asyncio.create_task(
                    refresh_groups_loop(
                        client
                    )
                )
            )

        logger.warning(
            "🚀 Delivery Monitor initialized"
        )

        logger.warning(
            "📡 Event handler: ACTIVE"
        )

        logger.warning(
            "👂 Listening for group messages"
        )

        logger.warning(
            "👤 User Profile Button: ENABLED"
        )

        logger.warning(
            "🧲 Keywords: "
            f"{len(KEYWORDS)}"
        )

        logger.warning(
            "⏱️ Group refresh: "
            f"{GROUP_REFRESH_SECONDS}s"
        )

    # --------------------------------------------------------
    # Register event handler
    #
    # مهم:
    # نسجل NewMessage بدون incoming=True
    # ثم process_message يتحقق من sender ID.
    # --------------------------------------------------------

    client.add_event_handler(
        event_handler,
        events.NewMessage(),
    )

    MONITOR_STARTED = True

    # --------------------------------------------------------
    # Initialize asynchronously
    # --------------------------------------------------------

    asyncio.create_task(
        initialize()
    )
