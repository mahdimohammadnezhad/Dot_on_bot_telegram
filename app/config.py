import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()

BOT_NAME = "بازار برق آزاد | DOT ON ⚡️"
TZ = "Asia/Tehran"


def _ids(key):
    raw = os.getenv(key, "")
    return [int(x) for x in (p.strip() for p in raw.replace(";", ",").split(",")) if x.lstrip("-").isdigit()]


def _names(key):
    raw = os.getenv(key, "")
    return [p.strip().lstrip("@").lower() for p in raw.replace(";", ",").split(",") if p.strip()]


@dataclass
class Settings:
    bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    bot_username: str = os.getenv("BOT_USERNAME", "").lstrip("@")
    # ربات دوم و اختصاصی برای پنل مدیریت؛ اگر خالی باشد پنل داخل همین ربات باز می‌شود
    admin_bot_token: str = os.getenv("ADMIN_BOT_TOKEN", "")
    admin_bot_username: str = os.getenv("ADMIN_BOT_USERNAME", "").lstrip("@")
    db_path: str = os.getenv("DB_PATH", "powermatch.db")
    admin_secret: str = os.getenv("ADMIN_SECRET", "")
    admin_chat_ids: list = field(default_factory=lambda: _ids("ADMIN_CHAT_IDS"))
    admin_usernames: list = field(default_factory=lambda: _names("ADMIN_USERNAMES"))
    # حالت وب‌هوک: برای اجرا پشت nginx یا روی سکوهای ابری (به‌جای long polling)
    use_webhook: bool = os.getenv("USE_WEBHOOK", "").strip().lower() in ("1", "true", "yes")
    webhook_base: str = os.getenv("WEBHOOK_BASE_URL", "").strip().rstrip("/")
    webhook_secret: str = os.getenv("WEBHOOK_SECRET", "").strip()
    google_sheet_id: str = os.getenv("GOOGLE_SHEET_ID", "").strip()
    google_credentials_file: str = os.getenv("GOOGLE_CREDENTIALS_FILE", "").strip()
    # اگر تنظیم شده باشد، دیتابیس روی Turso (libSQL) نگه‌داری می‌شود؛ برای اجرای بدون سرور
    # (مثل GitHub Actions) لازم است چون فایل SQLite محلی بین اجراهای runner ماندگار نیست.
    turso_database_url: str = os.getenv("TURSO_DATABASE_URL", "").strip()
    turso_auth_token: str = os.getenv("TURSO_AUTH_TOKEN", "").strip()

    def is_admin(self, user_id=None, username=None):
        return (user_id is not None and user_id in self.admin_chat_ids) or \
               (bool(username) and username.lstrip("@").lower() in self.admin_usernames)


settings = Settings()
