# ============================================================
# CipherElite Delivery Monitor
# ============================================================

import asyncio
import logging
import re
from html import escape

from telethon import events, Button
from telethon.errors import FloodWaitError, RPCError

from config.config import Config


# ============================================================
# VERSION
# ============================================================

VERSION = "2.2.0"


# ============================================================
# LOGGER
# ============================================================

logger = logging.getLogger(
    "cipherelite.delivery_monitor"
)


# ============================================================
# TARGET
# ============================================================

TARGET_CHAT_ID = int(
    getattr(Config, "LOG_CHAT_ID", 0) or 0
)


# ============================================================
# KEYWORDS
# ============================================================

KEYWORDS = [
    "توصيل",
    "مشوار",
    "مشاوير",

    "احتاج",
    "احتاج سيارة",
    "احتاج سواق",
    "احتاج سائق",
    "احتاج توصيل",
    "احتاج مواصلات",

    "ابي توصيل",
    "أبي توصيل",

    "ابغى توصيل",
    "أبغى توصيل",

    "ابي سواق",
    "أبي سواق",

    "ابغى سواق",
    "أبغى سواق",

    "ابي سائق",
    "أبي سائق",

    "ابغى سائق",
    "أبغى سائق",

    "ابي باص",
    "أبي باص",

    "ابغى باص",
    "أبغى باص",

    "سواق",
    "سواقه",
    "سائق",
    "سائقه",

    "سيارة",
    "سياره",

    "باص",
    "تاكسي",

    "نقل",
    "مندوب",
    "موصلات",

    "شهري",

    "يوصلني",
    "يوصلي",
    "يوديني",

    "تعرفون سواق",
    "تعرفون سائق",
    "تعرفون باص",

    "من رايحة",
    "من رايحه",

]


# ============================================================
# NORMALIZE ARABIC
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
        text = text.replace(old, new)

    # إزالة التشكيل
    text = re.sub(
        r"[\u064B-\u065F\u0670]",
        "",
        text
    )

    # توحيد المسافات
    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


# ============================================================
# NORMALIZED KEYWORDS
# ============================================================

NORMALIZED_KEYWORDS = [
    (
        original,
        normalize_text(original)
    )
    for original in KEYWORDS
]


# ============================================================
# MATCH
# ============================================================

def get_matches(text):

    normalized = normalize_text(text)

    if not normalized:
        return []

    result = []

    for original, keyword in NORMALIZED_KEYWORDS:

        if keyword and keyword in normalized:

            result.append(original)

    return list(dict.fromkeys(result))


# ============================================================
# SAFE HTML
# ============================================================

def safe(value):

    if value is None:
        return ""

    return escape(str(value))


# ============================================================
# USER DATA
# ============================================================

def get_user_data(sender):

    if sender is None:
        return (
            "مستخدم",
            0,
            None,
        )

    user_id = int(
        getattr(sender, "id", 0) or 0
    )

    first_name = (
        getattr(sender, "first_name", None)
        or ""
    )

    last_name = (
        getattr(sender, "last_name", None)
        or ""
    )

    full_name = (
        f"{first_name} {last_name}"
    ).strip()

    if not full_name:
        full_name = "مستخدم"

    username = getattr(
        sender,
        "username",
        None
    )

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
    message_id
):

    if not chat_id:
        return None

    username = getattr(
        chat,
        "username",
        None
    )

    # Public group
    if username:

        return (
            f"https://t.me/"
            f"{username}/"
            f"{message_id}"
        )

    # Private supergroup
    chat_id_string = str(chat_id)

    if chat_id_string.startswith("-100"):

        internal_id = chat_id_string[4:]

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
    chat
):

    # --------------------------------------------------------
    # USER
    # --------------------------------------------------------

    (
        full_name,
        user_id,
        username
    ) = get_user_data(sender)

    # --------------------------------------------------------
    # GROUP
    # --------------------------------------------------------

    chat_title = (
        getattr(
            chat,
            "title",
            None
        )
        or "مجموعة غير معروفة"
    )

    # --------------------------------------------------------
    # USERNAME
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
    # CLICKABLE USER NAME
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

        clickable_id = "غير معروف"

    # --------------------------------------------------------
    # ORIGINAL MESSAGE
    # --------------------------------------------------------

    message_link = get_message_link(
        chat,
        event.chat_id,
        event.id
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
    # KEYWORDS
    # --------------------------------------------------------

    keyword_text = ", ".join(
        matches
    )

    # --------------------------------------------------------
    # MESSAGE
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

    return message, user_id


# ============================================================
# PROCESS MESSAGE
# ============================================================

async def process_message(
    client,
    event
):

    try:

        # ----------------------------------------------------
        # رسائل الآخرين فقط
        # ----------------------------------------------------

        if event.out:
            return

        # ----------------------------------------------------
        # مجموعات فقط
        # ----------------------------------------------------

        if not event.is_group:
            return

        # ----------------------------------------------------
        # لا نلتقط رسائل قناة/مجموعة النتائج
        # ----------------------------------------------------

        if (
            TARGET_CHAT_ID
            and event.chat_id == TARGET_CHAT_ID
        ):
            return

        # ----------------------------------------------------
        # TEXT
        # ----------------------------------------------------

        text = (
            event.raw_text
            or ""
        ).strip()

        if not text:
            return

        # ----------------------------------------------------
        # KEYWORDS
        # ----------------------------------------------------

        matches = get_matches(text)

        if not matches:
            return

        # ----------------------------------------------------
        # SENDER
        # ----------------------------------------------------

        sender = None

        try:

            sender = await event.get_sender()

        except Exception as e:

            logger.debug(
                f"Could not get sender: {e}"
            )

        # ----------------------------------------------------
        # IGNORE BOTS
        # ----------------------------------------------------

        if sender and getattr(
            sender,
            "bot",
            False
        ):

            return

        # ----------------------------------------------------
        # CHAT
        # ----------------------------------------------------

        try:

            chat = await event.get_chat()

        except Exception:

            chat = None

        # ----------------------------------------------------
        # BUILD
        # ----------------------------------------------------

        (
            final_message,
            user_id
        ) = build_message(
            event,
            text,
            matches,
            sender,
            chat
        )

        # ====================================================
        # IMPORTANT
        #
        # زر فتح الخاص
        #
        # هذا ليس نصًا عاديًا.
        # هذا Inline URL Button.
        # ====================================================

        buttons = None

        if user_id:

            buttons = [
                [
                    Button.url(
                        "👤 فتح الخاص",
                        f"tg://user?id={user_id}"
                    )
                ]
            ]

        # ----------------------------------------------------
        # SEND
        # ----------------------------------------------------

        await client.send_message(
            TARGET_CHAT_ID,
            final_message,
            parse_mode="html",
            link_preview=False,
            buttons=buttons
        )

        logger.info(
            "✅ Delivery captured | "
            f"chat={event.chat_id} | "
            f"user={user_id} | "
            f"keywords={matches}"
        )

    except FloodWaitError as e:

        seconds = max(
            int(e.seconds),
            1
        )

        logger.warning(
            f"Telegram FloodWait: {seconds}s"
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
# EVENT HANDLER
# ============================================================

async def handle_new_message(
    client,
    event
):

    # إنشاء مهمة منفصلة حتى لا نوقف استقبال
    # الرسائل الجديدة أثناء إرسال رسالة سابقة.

    asyncio.create_task(
        process_message(
            client,
            event
        )
    )


# ============================================================
# GROUP SCANNER
# ============================================================

async def scan_groups(client):

    count = 0

    try:

        async for dialog in client.iter_dialogs():

            try:

                if not dialog.is_group:
                    continue

                count += 1

            except Exception:
                continue

        logger.info(
            f"📊 Groups available to account: {count}"
        )

    except Exception as e:

        logger.error(
            f"Group scan error: {e}"
        )


# ============================================================
# INIT
# ============================================================

def init(client):

    # --------------------------------------------------------
    # LOG CHAT
    # --------------------------------------------------------

    if not TARGET_CHAT_ID:

        logger.error(
            "❌ LOG_CHAT_ID غير مضبوط"
        )

        return

    # --------------------------------------------------------
    # REGISTER EVENT
    #
    # لا نضع chats=...
    #
    # لأننا نريد الرسائل الواردة من جميع المجموعات
    # التي يستطيع هذا الحساب استقبال تحديثاتها.
    # --------------------------------------------------------

    client.add_event_handler(
        lambda event:
            asyncio.create_task(
                handle_new_message(
                    client,
                    event
                )
            ),
        events.NewMessage(
            incoming=True
        )
    )

    # --------------------------------------------------------
    # STARTUP SCAN
    # --------------------------------------------------------

    async def startup():

        try:

            logger.warning(
                "🔎 Scanning Telegram groups..."
            )

            await scan_groups(
                client
            )

            logger.warning(
                "✅ Group scan completed"
            )

        except Exception as e:

            logger.exception(
                f"Startup scan error: {e}"
            )

    asyncio.create_task(
        startup()
    )

    # --------------------------------------------------------
    # LOG
    # --------------------------------------------------------

    logger.warning(
        "🚗 Delivery Monitor loaded"
    )

    logger.warning(
        "👂 Monitoring incoming messages from groups"
    )

    logger.warning(
        f"🧲 Keywords loaded: {len(KEYWORDS)}"
    )

    logger.warning(
        f"📢 Destination: {TARGET_CHAT_ID}"
    )

    logger.warning(
        "👤 Private contact button: ENABLED"
    )
