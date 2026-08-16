from vars import *


class Config:

    # ============================================================
    # Core Settings
    # ============================================================

    API_ID = API_ID
    API_HASH = API_HASH
    STRING_SESSION = ELITE_SESSION


    # ============================================================
    # Database
    # MongoDB disabled
    # CipherElite will use Local JSON storage
    # ============================================================

    MONGO_URI = ""


    # ============================================================
    # Bot Configuration
    # ============================================================

    BOT_PREFIX = ELITE_BOT_PREFIX
    BOT_NAME = "Cipher Elite"

    BOT_TOKEN = BOT_TOKEN
    TG_BOT_USERNAME = ELITE_BOT_USERNAME


    # ============================================================
    # Access Control
    # ============================================================

    SUDO_USERS = SUDO_USERS
    LOG_CHAT_ID = LOG_CHAT_ID


    # ============================================================
    # Alive / Pictures
    # ============================================================

    ALIVE_NAME = ALIVE_NAME

    DEFAULT_PING_PIC = PING_PIC
    DEFAULT_ALIVE_PIC = ALIVE_PIC
    DEFAULT_PMPERMIT_PIC = PMPERMIT_PIC


    # ============================================================
    # Version Information
    # ============================================================

    VERSION = "2.0.0"

    BRANCH = BRANCH

    UPSTREAM_REPO = (
        "https://github.com/rishabhops/CipherElite"
    )
