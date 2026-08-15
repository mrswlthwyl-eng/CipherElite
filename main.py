# ============================================================
# main.py
# CipherElite - Telegram Delivery Monitor
#
# يعمل مع vars.py الخاص بـ CipherElite
# حساب Telegram واحد
# مراقبة المجموعات
# فلترة طلبات التوصيل
# إرسال الطلبات إلى LOG_CHAT_ID
# اسم الطالب + ID قابلان للضغط
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
    KEYWORDS,
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
        "❌ API_ID غير موجود."
    )

if not API_HASH:
    raise RuntimeError(
        "❌ API_HASH غير موجود."
    )

if (
    not ELITE_SESSION
    or ELITE_SESSION == "INVALID_SESSION"
):
    raise RuntimeError(
        "❌ ELITE_SESSION غير موجودة."
    )

if not LOG_CHAT_ID:
    raise RuntimeError(
        "❌ LOG_CHAT_ID غير موجود."
    )


# ============================================================
# KEYWORDS
# ============================================================

DELIVERY_KEYWORDS = [
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

# إذا أردت لاحقًا استخدام KEYWORDS من vars.py
# بدلاً من القائمة أعلاه، غيّر هذا إلى:
#
# DELIVERY_KEYWORDS = KEYWORDS


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

        text = text.replace(
            old,
            new,
        )

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

    for original in DELIVERY_KEYWORDS

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

    for (
        original,
        normalized_keyword,
    ) in NORMALIZED_KEYWORDS:

        if not normalized_keyword:
            continue

        if normalized_keyword in normalized:

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
# GET USER INFORMATION
# ============================================================

def get_user_information(sender):

    if sender is None:

        return (
            "مستخدم",
            "غير معروف",
            "🔗 بدون username",
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
    # CLICKABLE NAME + ID
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
        user_id,
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


    chat_username = getattr(
        chat,
        "username",
        None,
    )


    # --------------------------------------------------------
    # PUBLIC GROUP
    # --------------------------------------------------------

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
        user_id,
    ) = get_user_information(
        sender
    )


    # --------------------------------------------------------
    # MESSAGE LINK
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
        # GET SENDER
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

            except Exception as e:

                logger.warning(
                    "⚠️ تعذر جلب المرسل: %s",
                    e,
                )

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
        # GET CHAT
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

            except Exception as e:

                logger.warning(
                    "⚠️ تعذر جلب المجموعة: %s",
                    e,
                )

                chat = None


        # ====================================================
        # BUILD
        # ====================================================

        final_message = build_message(

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

                LOG_CHAT_ID,

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

            "✅ SENT | "
            "chat=%s | "
            "message=%s | "
            "keywords=%s | "
            "%.3fs",

            event.chat_id,

            event.id,

            matches,

            elapsed,

        )


    except FloodWaitError as e:

        seconds = max(
            int(e.seconds),
            1,
        )

        logger.warning(
            "⏳ FloodWait: %ss",
            seconds,
        )

        await asyncio.sleep(
            seconds
        )


    except RPCError as e:

        logger.error(

            "❌ Telegram RPC error | "
            "%s: %s",

            type(e).__name__,

            e,

        )


    except asyncio.CancelledError:

        raise


    except Exception as e:

        logger.exception(

            "❌ Message processing error: %s",

            e,

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

    print("=" * 70)

    print(
        "🚗 CIPHERELITE DELIVERY MONITOR"
    )

    print(
        "👤 ONE TELEGRAM ACCOUNT"
    )

    print(
        "⚡ DELIVERY KEYWORD FILTER"
    )

    print(
        "🔗 CLICKABLE USER NAME / ID"
    )

    print(
        f"📢 TARGET: {LOG_CHAT_ID}"
    )

    print(
        f"🧲 KEYWORDS: "
        f"{len(DELIVERY_KEYWORDS)}"
    )

    print("=" * 70)


    while True:

        try:

            # =================================================
            # CONNECT
            # =================================================

            logger.info(
                "🔌 جاري الاتصال بـ Telegram..."
            )

            await client.connect()


            # =================================================
            # AUTH
            # =================================================

            authorized = (
                await client.is_user_authorized()
            )


            if not authorized:

                logger.critical(

                    "❌ ELITE_SESSION غير صالحة "
                    "أو لم تعد مصرحًا بها."

                )

                return


            # =================================================
            # ACCOUNT
            # =================================================

            me = await client.get_me()


            username = (

                f"@{me.username}"

                if me.username

                else "بدون username"

            )


            logger.info(

                "✅ الحساب متصل | "
                "name=%s | "
                "id=%s | "
                "username=%s",

                me.first_name or "",

                me.id,

                username,

            )


            # =================================================
            # CHECK TARGET
            # =================================================

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

                    "📢 القناة الهدف: %s",

                    target_title,

                )


            except Exception as e:

                logger.error(

                    "❌ لا يستطيع الحساب الوصول "
                    "إلى القناة الهدف: %s",

                    e,

                )

                return


            # =================================================
            # CATCH UP
            # =================================================

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

                    "⚠️ catch_up error: %s",

                    e,

                )


            # =================================================
            # READY
            # =================================================

            logger.info(
                "👂 الحساب يراقب المجموعات الآن..."
            )

            logger.info(

                "🧲 عدد الكلمات المفتاحية: %s",

                len(
                    DELIVERY_KEYWORDS
                ),

            )

            logger.info(
                "📡 النظام جاهز لاستقبال الطلبات."
            )


            # =================================================
            # RUN
            # =================================================

            await client.run_until_disconnected()


        # =====================================================
        # AUTH KEY DUPLICATED
        # =====================================================

        except AuthKeyDuplicatedError:

            logger.critical(

                "🚨 AuthKeyDuplicatedError\n"
                "نفس ELITE_SESSION مستخدمة "
                "في مكان آخر.\n"
                "أوقف النسخة الأخرى."

            )

            return


        # =====================================================
        # FLOOD WAIT
        # =====================================================

        except FloodWaitError as e:

            seconds = max(
                int(e.seconds),
                1,
            )

            logger.warning(

                "⏳ Telegram طلب الانتظار %s ثانية.",

                seconds,

            )

            await asyncio.sleep(
                seconds
            )


        # =====================================================
        # RPC ERROR
        # =====================================================

        except RPCError as e:

            logger.error(

                "❌ RPC ERROR | %s: %s",

                type(e).__name__,

                e,

            )

            await asyncio.sleep(
                10
            )


        # =====================================================
        # CANCEL
        # =====================================================

        except asyncio.CancelledError:

            raise


        # =====================================================
        # OTHER ERROR
        # =====================================================

        except Exception as e:

            logger.exception(

                "❌ Connection error: %s",

                e,

            )

            await asyncio.sleep(
                10
            )


        # =====================================================
        # DISCONNECT
        # =====================================================

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
