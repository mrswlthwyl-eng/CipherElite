# ============================================================
# plugins/delivery_monitor.py
# ============================================================

import asyncio
import logging
import re
from html import escape

from telethon import events
from telethon.tl.types import (
    InputKeyboardButtonUserProfile,
)

from config.config import Config


# ============================================================
# VERSION
# ============================================================

VERSION = "3.0.0"


# ============================================================
# LOGGER
# ============================================================

logger = logging.getLogger(
    "cipherelite.delivery_monitor"
)


# ============================================================
# TARGET CHAT
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
]


# ============================================================
# NORMALIZE
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

    text = re.sub(
        r"[\u064B-\u065F\u0670]",
        "",
        text,
    )

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

def get_matches(text):

    normalized = normalize_text(text)

    if not normalized:
        return []

    result = []

    for original, keyword in NORMALIZED_KEYWORDS:

        if keyword and keyword in normalized:

            result.append(original)

    return list(
        dict.fromkeys(result)
    )


# ============================================================
# HTML ESCAPE
# ============================================================

def safe(value):

    if value is None:
        return ""

    return escape(str(value))


# ============================================================
# USER INFORMATION
# ============================================================

def get_user_info(sender):

    if sender is None:

        return (
            "مستخدم",
            0,
            None,
        )

    user_id = int(
        getattr(
            sender,
            "id",
            0,
        ) or 0
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

    username = getattr(
        sender,
        "username",
        None,
    )

    return (
        full_name,
        user_id,
        username,
    )


# ============================================================
# SOURCE MESSAGE LINK
# ============================================================

def get_message_link(
    chat,
    chat_id,
    message_id,
):

    if not chat_id:

        return None

    username = getattr(
        chat,
        "username",
        None,
    )

    # Public group
    if username:

        return (
            f"https://t.me/"
            f"{username}/"
            f"{message_id}"
        )

    # Private supergroup
    raw_id = str(chat_id)

    if raw_id.startswith("-100"):

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
    ) = get_user_info(sender)

    chat_title = (
        getattr(
            chat,
            "title",
            None,
        )
        or "مجموعة غير معروفة"
    )

    # --------------------------------------------------------
    # Name
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
    # Final
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
# SEND RESULT
# ============================================================

async def send_result(
    client,
    message,
    user_id,
):

    # ========================================================
    # IMPORTANT
    #
    # Telegram User Profile Button
    #
    # ليس Button.url
    # وليس tg:// URL كنص.
    #
    # ========================================================

    if user_id:

        try:

            # الحصول على InputUser الكامل
            input_user = await client.get_input_entity(
                user_id
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

            logger.exception(
                "UserProfile button failed: "
                f"{e}"
            )

            # ------------------------------------------------
            # Fallback
            # ------------------------------------------------
            #
            # إذا Telegram/الإصدار لا يسمح بالزر الجديد،
            # نرسل رابط tg:// داخل زر URL.
            #
            # ------------------------------------------------

            try:

                from telethon import Button

                fallback = [
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
                    buttons=fallback,
                )

                return True

            except Exception as fallback_error:

                logger.exception(
                    "Fallback button failed: "
                    f"{fallback_error}"
                )

                return False

    # --------------------------------------------------------
    # No user ID
    # --------------------------------------------------------

    await client.send_message(
        TARGET_CHAT_ID,
        message,
        parse_mode="html",
        link_preview=False,
    )

    return True


# ============================================================
# PROCESS MESSAGE
# ============================================================

async def process_message(
    client,
    event,
):

    try:

        # ----------------------------------------------------
        # Incoming only
        # ----------------------------------------------------

        if event.out:

            return

        # ----------------------------------------------------
        # Groups only
        # ----------------------------------------------------

        if not event.is_group:

            return

        # ----------------------------------------------------
        # Ignore target group
        # ----------------------------------------------------

        if (
            TARGET_CHAT_ID
            and event.chat_id
            == TARGET_CHAT_ID
        ):

            return

        # ----------------------------------------------------
        # Text
        # ----------------------------------------------------

        text = (
            event.raw_text
            or ""
        ).strip()

        if not text:

            return

        # ----------------------------------------------------
        # Keywords
        # ----------------------------------------------------

        matches = get_matches(
            text
        )

        if not matches:

            return

        # ----------------------------------------------------
        # Sender
        # ----------------------------------------------------

        try:

            sender = await event.get_sender()

        except Exception:

            sender = None

        # ----------------------------------------------------
        # Ignore bots
        # ----------------------------------------------------

        if sender:

            if getattr(
                sender,
                "bot",
                False,
            ):

                return

        # ----------------------------------------------------
        # Chat
        # ----------------------------------------------------

        try:

            chat = await event.get_chat()

        except Exception:

            chat = None

        # ----------------------------------------------------
        # Build
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # Send
        # ----------------------------------------------------

        success = await send_result(
            client,
            final_message,
            user_id,
        )

        if success:

            logger.info(
                "✅ DELIVERY SENT | "
                f"chat={event.chat_id} | "
                f"user={user_id} | "
                f"keywords={matches}"
            )

    except FloodWaitError as e:

        seconds = max(
            int(e.seconds),
            1,
        )

        logger.warning(
            f"⏳ FloodWait {seconds}s"
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
            f"Delivery error: {e}"
        )


# ============================================================
# EVENT
# ============================================================

async def handler(
    client,
    event,
):

    asyncio.create_task(
        process_message(
            client,
            event,
        )
    )


# ============================================================
# INIT
# ============================================================

def init(client):

    if not TARGET_CHAT_ID:

        logger.error(
            "❌ LOG_CHAT_ID غير مضبوط"
        )

        return

    # --------------------------------------------------------
    # جميع الرسائل الواردة
    # --------------------------------------------------------

    client.add_event_handler(
        lambda event:
            asyncio.create_task(
                handler(
                    client,
                    event,
                )
            ),
        events.NewMessage(
            incoming=True
        ),
    )

    # --------------------------------------------------------
    # Startup
    # --------------------------------------------------------

    async def startup():

        try:

            dialogs = 0

            async for dialog in client.iter_dialogs():

                if dialog.is_group:

                    dialogs += 1

            logger.warning(
                "🔎 Telegram groups detected: "
                f"{dialogs}"
            )

            logger.warning(
                "👂 Monitoring all incoming groups"
            )

            logger.warning(
                "👤 User Profile Button: ENABLED"
            )

        except Exception as e:

            logger.exception(
                f"Startup scan error: {e}"
            )

    asyncio.create_task(
        startup()
    )

    logger.warning(
        "🚗 Delivery Monitor loaded"
    )

    logger.warning(
        f"📢 Target: {TARGET_CHAT_ID}"
    )

    logger.warning(
        f"🧲 Keywords: {len(KEYWORDS)}"
    )
