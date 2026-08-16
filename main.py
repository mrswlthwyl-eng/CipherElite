# ============================================================
# main.py
# CipherElite - Telegram Delivery Monitor
#
# يعتمد على vars.py الخاص بـ CipherElite
# حساب Telegram واحد
# مراقبة المجموعات
# فلترة طلبات التوصيل
# إرسال الطلبات إلى LOG_CHAT_ID
# اسم المستخدم + ID قابلان للضغط
# رابط الرسالة الأصلية
# Auto Reconnect
# ============================================================

import asyncio
import logging
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
# LOAD CIPHERELITE CONFIG
# ============================================================

from vars import (
    API_ID,
    API_HASH,
    ELITE_SESSION,
    LOG_CHAT_ID,
)


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger(
    "cipherelite-delivery-monitor"
)


# ============================================================
# VALIDATE CONFIG
# ============================================================

if not API_ID:
    raise RuntimeError(
        "❌ API_ID غير موجود في vars.py / Environment Variables"
    )

if not API_HASH:
    raise RuntimeError(
        "❌ API_HASH غير موجود في vars.py / Environment Variables"
    )

if not ELITE_SESSION:
    raise RuntimeError(
        "❌ ELITE_SESSION غير موجودة في vars.py / Environment Variables"
    )

if not LOG_CHAT_ID:
    raise RuntimeError(
        "❌ LOG_CHAT_ID غير موجود في vars.py / Environment Variables"
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
    "ابغى توصيل",
    "أبي توصيل",
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
    توحيد بعض الحروف العربية حتى يعمل الفلتر
    مع اختلافات الكتابة.
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
    if original
]


def matched_keywords(text):
    """
    إرجاع الكلمات التي تطابقت مع الرسالة.
    """

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
# USER INFORMATION
# ============================================================

def get_user_information(sender):

    if sender is None:

        return (
            "مستخدم",
            "غير معروف",
            "🔗 بدون username",
        )


    # --------------------------------------------------------
    # USER ID
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
    # CLICKABLE USER
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
    # PUBLIC GROUP / CHANNEL
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

def build_message(
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
    ) = get_user_information(
        sender
    )


    # --------------------------------------------------------
    # SOURCE LINK
    # --------------------------------------------------------

    message_link = get_message_link(
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
        # MESSAGE TEXT
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

                sender = (
                    await event.get_sender()
                )

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

                chat = (
                    await event.get_chat()
                )

            except Exception:

                chat = None


        # ----------------------------------------------------
        # BUILD
        # ----------------------------------------------------

        formatted = build_message(

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

                formatted,

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
            f"time={elapsed:.3f}s"

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

    # لا نعالج الرسالة داخل callback نفسه
    # حتى لا نوقف استقبال الرسائل الأخرى.

    asyncio.create_task(
        process_message(event)
    )


# ============================================================
# MAIN
# ============================================================

async def main():

    print("=" * 70)

    print(
        "🚗 CIPHERELITE DELIVERY MONITOR"
    )

    print(
        "👤 ONE TELEGRAM ACCOUNT"
    )

    print(
        "📡 GROUP MESSAGE MONITOR"
    )

    print(
        "🔗 CLICKABLE USER NAME / ID"
    )

    print(
        f"📢 TARGET: {LOG_CHAT_ID}"
    )

    print(
        f"🧲 KEYWORDS: {len(KEYWORDS)}"
    )

    print("=" * 70)


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

            authorized = (
                await client.is_user_authorized()
            )


            if not authorized:

                logger.critical(
                    "❌ ELITE_SESSION غير صالحة أو غير مصرح بها."
                )

                return


            # ------------------------------------------------
            # ACCOUNT
            # ------------------------------------------------

            me = await client.get_me()


            username = (

                f"@{me.username}"

                if me.username

                else "بدون username"

            )


            logger.info(

                f"✅ الحساب متصل | "
                f"name={me.first_name or ''} | "
                f"id={me.id} | "
                f"username={username}"

            )


            # ------------------------------------------------
            # CHECK TARGET
            # ------------------------------------------------

            try:

                target = (
                    await client.get_entity(
                        LOG_CHAT_ID
                    )
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

                    "⚠️ تعذر الوصول إلى "
                    f"القناة الهدف: {e}"

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
                "📡 ينتظر طلبات التوصيل..."
            )


            # ------------------------------------------------
            # RUN
            # ------------------------------------------------

            await client.run_until_disconnected()


        except AuthKeyDuplicatedError:

            logger.critical(

                "🚨 AuthKeyDuplicatedError\n"
                "هذه ELITE_SESSION مستخدمة في مكان آخر.\n"
                "لا تشغل نفس Session في أكثر من مكان."

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

                f"❌ Telegram RPC error | "
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
