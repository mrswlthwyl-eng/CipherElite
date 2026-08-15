# ============================================================
# main.py
# Telegram Delivery Monitor - Elite Deployer
#
# حساب Telegram واحد
# مراقبة المجموعات
# فلترة طلبات التوصيل
# إرسال الكليشة إلى القناة
# اسم الطالب + ID قابلان للضغط
# رابط الرسالة الأصلية
# Auto Reconnect
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

    if value is None or not value.strip():
        raise RuntimeError(
            f"❌ متغير الاستضافة مفقود: {name}"
        )

    return value.strip()


def get_int(name):
    value = get_required(name)

    try:
        return int(value)

    except ValueError:
        raise RuntimeError(
            f"❌ المتغير {name} يجب أن يكون رقمًا صحيحًا"
        )


# ============================================================
# CONFIG
# ============================================================

API_ID = get_int("API_ID")

API_HASH = get_required(
    "API_HASH"
)

ELITE_SESSION = get_required(
    "ELITE_SESSION"
)

LOG_CHAT_ID = get_int(
    "LOG_CHAT_ID"
)


# ============================================================
# KEYWORDS
# ============================================================

KEYWORDS = [
    "توصيل",
    "مشوار",
    "من _الى",
    "احتاج سيارة",
    "احتاج سواق",
    "شهري",
    "مندوب",
    "سواق",
    "سواقه",
    "تاكسي",
    "سيارة",
    "باص",
    "نقل",
    "ابي توصيل",
    "تواصل",
    "من رايحة",
    "تعرفون باص",
    "سواقة",
    "تعرفون سواق",
    "ابغى باص",
    "توصيل طلب",
    "يوصلي",
    "يوديني مشوار",
]


# ============================================================
# TEXT NORMALIZATION
# ============================================================

def normalize_text(text):

    if not text:
        return ""

    text = str(text).lower()

    replacements = {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ة": "ه",
        "ى": "ي",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

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
    if original
]


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
        dict.fromkeys(matches)
    )


# ============================================================
# TELEGRAM CLIENT
# ============================================================

client = TelegramClient(

    StringSession(
        ELITE_SESSION
    ),

    API_ID,

    API_HASH,

    connection_retries=10,

    retry_delay=3,

    request_retries=5,

    auto_reconnect=True,

    sequential_updates=False,

    catch_up=True,

    flood_sleep_threshold=60,

    entity_cache_limit=10000,
)


# ============================================================
# SEND LOCK
# ============================================================

send_lock = asyncio.Lock()


# ============================================================
# BUILD USER INFORMATION
# ============================================================

def build_user_info(sender):

    if sender is None:

        return (
            "مستخدم",
            "غير معروف",
            "🔗 بدون username",
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
            f'{escape(full_name)}'
            f'</a>'
        )

        clickable_id = (
            f'<a href="tg://user?id={user_id}">'
            f'{user_id}'
            f'</a>'
        )

    else:

        clickable_name = escape(
            full_name
        )

        clickable_id = "غير معروف"


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
            f'{escape(username)}">'
            f'@{escape(username)}'
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
    )


# ============================================================
# SOURCE MESSAGE LINK
# ============================================================

def build_message_link(
    chat,
    chat_id,
    message_id,
):

    if not chat_id:
        return None


    # --------------------------------------------------------
    # Public username
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
    # Private supergroup
    # --------------------------------------------------------

    raw_chat_id = str(
        chat_id
    )


    if raw_chat_id.startswith("-100"):

        internal_id = raw_chat_id[4:]

        return (
            f"https://t.me/c/"
            f"{internal_id}/"
            f"{message_id}"
        )


    return None


# ============================================================
# BUILD FINAL MESSAGE
# ============================================================

def build_message(
    event,
    text,
    matches,
    sender,
    chat,
):

    # --------------------------------------------------------
    # CHAT
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

        chat_title = "مجموعة غير معروفة"


    # --------------------------------------------------------
    # USER
    # --------------------------------------------------------

    (
        clickable_name,
        clickable_id,
        username_line,
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
            f'🔗 <a href="{escape(message_link)}">'
            "الضغط للذهاب للرسالة الأصلية"
            "</a>"
        )

    else:

        source_line = (
            "🔗 رابط الرسالة الأصلية غير متاح"
        )


    # --------------------------------------------------------
    # MATCHED KEYWORDS
    # --------------------------------------------------------

    keyword_text = ", ".join(
        matches
    )


    if not keyword_text:

        keyword_text = "مطابقة"


    # --------------------------------------------------------
    # FINAL
    # --------------------------------------------------------

    return (

        "╭━━━ 🚗 "
        "<b>طلب توصيل جديد</b> "
        "━━━╮\n\n"

        "📝 <b>نص الرسالة:</b>\n"

        f"{escape(text)}\n\n"

        "━━━━━━━━━━━━━━━━━━━━\n\n"

        f"👤 <b>الاسم:</b> "
        f"{clickable_name}\n"

        f"🆔 <b>الأيدي:</b> "
        f"{clickable_id}\n"

        f"{username_line}\n\n"

        f"📡 <b>المجموعة:</b> "
        f"{escape(chat_title)}\n"

        f"🆔 <b>أيدي المجموعة:</b> "
        f"<code>{event.chat_id}</code>\n\n"

        f"{source_line}\n\n"

        "━━━━━━━━━━━━━━━━━━━━\n\n"

        "🧲 <b>الكلمات المطابقة:</b>\n"

        f"{escape(keyword_text)}\n\n"

        "╰━━━━━━━━━━━━━━━━━━━━╯"

    )


# ============================================================
# PROCESS MESSAGE
# ============================================================

async def process_message(event):

    started = time.perf_counter()

    try:

        # ----------------------------------------------------
        # GROUPS ONLY
        # ----------------------------------------------------

        if not event.is_group:

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
        # FILTER
        # ----------------------------------------------------

        matches = matched_keywords(
            text
        )


        if not matches:

            return


        # ----------------------------------------------------
        # SENDER
        # ----------------------------------------------------

        sender = getattr(
            event,
            "sender",
            None,
        )


        if sender is None:

            try:

                sender = await event.get_sender()

            except Exception:

                sender = None


        # ----------------------------------------------------
        # IGNORE BOTS
        # ----------------------------------------------------

        if sender:

            if getattr(
                sender,
                "bot",
                False,
            ):

                return


        # ----------------------------------------------------
        # CHAT
        # ----------------------------------------------------

        chat = getattr(
            event,
            "chat",
            None,
        )


        if chat is None:

            try:

                chat = await event.get_chat()

            except Exception:

                chat = None


        # ----------------------------------------------------
        # BUILD
        # ----------------------------------------------------

        final_message = build_message(

            event,

            text,

            matches,

            sender,

            chat,

        )


        # ----------------------------------------------------
        # SEND
        # ----------------------------------------------------

        async with send_lock:

            await client.send_message(

                LOG_CHAT_ID,

                final_message,

                parse_mode="html",

                link_preview=False,

            )


        # ----------------------------------------------------
        # LOG
        # ----------------------------------------------------

        elapsed = (
            time.perf_counter()
            - started
        )


        logger.info(

            f"✅ SENT | "
            f"chat={event.chat_id} | "
            f"message={event.id} | "
            f"keywords={matches} | "
            f"{elapsed:.3f}s"

        )


    except FloodWaitError as e:

        seconds = max(
            int(e.seconds),
            1,
        )

        logger.warning(

            f"⏳ FloodWait: "
            f"{seconds}s"

        )

        await asyncio.sleep(
            seconds
        )


    except RPCError as e:

        logger.error(

            f"❌ Telegram RPC error | "
            f"{type(e).__name__}: {e}"

        )


    except asyncio.CancelledError:

        raise


    except Exception as e:

        logger.exception(

            f"❌ Message processing error | "
            f"{type(e).__name__}: {e}"

        )


# ============================================================
# EVENT HANDLER
# ============================================================

@client.on(
    events.NewMessage()
)
async def new_message(event):

    asyncio.create_task(
        process_message(event)
    )


# ============================================================
# MAIN
# ============================================================

async def main():

    print("=" * 65)

    print(
        "🚗 TELEGRAM DELIVERY MONITOR"
    )

    print(
        "👤 ONE TELEGRAM ACCOUNT"
    )

    print(
        "🔗 CLICKABLE USER ID / NAME"
    )

    print(
        f"📢 TARGET: {LOG_CHAT_ID}"
    )

    print("=" * 65)


    while True:

        try:

            # ------------------------------------------------
            # CONNECT
            # ------------------------------------------------

            logger.info(
                "🔌 جاري الاتصال بـ Telegram..."
            )

            await client.connect()


            # ------------------------------------------------
            # AUTH
            # ------------------------------------------------

            if not await client.is_user_authorized():

                logger.critical(
                    "❌ ELITE_SESSION غير صالحة أو منتهية."
                )

                return


            # ------------------------------------------------
            # ACCOUNT
            # ------------------------------------------------

            me = await client.get_me()


            account_username = (

                f"@{me.username}"

                if me.username

                else "بدون username"

            )


            logger.info(

                f"✅ الحساب متصل | "
                f"name={me.first_name or ''} | "
                f"id={me.id} | "
                f"username={account_username}"

            )


            # ------------------------------------------------
            # TARGET CHECK
            # ------------------------------------------------

            try:

                target = await client.get_entity(
                    LOG_CHAT_ID
                )

                target_title = (
                    getattr(
                        target,
                        "title",
                        None,
                    )
                    or str(
                        LOG_CHAT_ID
                    )
                )

                logger.info(

                    f"📢 القناة الهدف: "
                    f"{target_title}"

                )

            except Exception as e:

                logger.warning(

                    f"⚠️ تعذر التحقق من القناة الهدف: "
                    f"{e}"

                )


            # ------------------------------------------------
            # CATCH UP
            # ------------------------------------------------

            try:

                logger.info(
                    "🔄 تشغيل catch_up..."
                )

                await client.catch_up()

                logger.info(
                    "✅ catch_up اكتمل."
                )

            except Exception as e:

                logger.warning(

                    f"⚠️ catch_up error: {e}"

                )


            # ------------------------------------------------
            # LISTEN
            # ------------------------------------------------

            logger.info(
                "👂 الحساب يراقب المجموعات الآن..."
            )

            logger.info(
                f"📡 عدد الكلمات: {len(KEYWORDS)}"
            )


            # ------------------------------------------------
            # RUN
            # ------------------------------------------------

            await client.run_until_disconnected()


        except AuthKeyDuplicatedError:

            logger.critical(

                "🚨 AuthKeyDuplicatedError\n"
                "نفس ELITE_SESSION مستخدمة في مكان آخر.\n"
                "أوقف النسخة الأخرى."

            )

            return


        except FloodWaitError as e:

            seconds = max(
                int(e.seconds),
                1,
            )

            logger.warning(

                f"⏳ Telegram طلب الانتظار "
                f"{seconds} ثانية."

            )

            await asyncio.sleep(
                seconds
            )


        except RPCError as e:

            logger.error(

                f"❌ RPC ERROR | "
                f"{type(e).__name__}: {e}"

            )

            await asyncio.sleep(
                5
            )


        except asyncio.CancelledError:

            raise


        except Exception as e:

            logger.exception(

                f"❌ Connection error | "
                f"{type(e).__name__}: {e}"

            )

            await asyncio.sleep(
                5
            )


        finally:

            if client.is_connected():

                with suppress(
                    Exception
                ):

                    await client.disconnect()


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    try:

        asyncio.run(
            main()
        )

    except KeyboardInterrupt:

        print(
            "\n🛑 تم إيقاف البرنامج."
        )
