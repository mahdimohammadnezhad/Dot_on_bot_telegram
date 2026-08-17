import os
import sys
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# باید پیش از import شدن app.config اعمال شود تا تست‌ها هرگز به دیتابیس/توکن واقعی دست نزنند
os.environ["DB_PATH"] = str(ROOT / "tests" / "_test_powermatch.db")
os.environ["TELEGRAM_BOT_TOKEN"] = "123456:TEST-TOKEN-FOR-UNIT-TESTS-ONLY"
os.environ["COMPANY_NAME"] = "شرکت آزمایشی"
os.environ["ADMIN_CHAT_IDS"] = "999001,999002"
os.environ["ADMIN_USERNAMES"] = "Farbod_Papoli"
os.environ["ADMIN_SECRET"] = "unit-test-secret-value"
# تست‌ها هرگز نباید به گوگل‌شیت واقعی وصل شوند
os.environ["GOOGLE_CREDENTIALS_FILE"] = ""
os.environ["GOOGLE_SHEET_ID"] = ""
os.environ["ADMIN_BOT_TOKEN"] = ""

import pytest


@pytest.fixture
def fresh_db():
    from app.db import init_db
    p = pathlib.Path(os.environ["DB_PATH"])
    if p.exists():
        p.unlink()
    init_db()
    yield p
    if p.exists():
        p.unlink()
