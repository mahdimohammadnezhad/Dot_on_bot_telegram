"""تست در سطح Dispatcher: یک Update واقعی از مسیر کامل aiogram عبور می‌کند.

این لایه چیزی را می‌گیرد که تست‌های مستقیمِ هندلر نمی‌گیرند: تزریق وابستگی‌ها
(dispatcher/bot/…) بر اساس امضای هندلر، فیلترها، میان‌افزارها و ترتیب ثبت هندلرها.
"""
from datetime import datetime

import pytest
from aiogram.methods import SendMessage, SendDocument
from aiogram.types import Chat, Message, Update, User

from app import bot as B
from app.config import settings

ADMIN_ID = settings.admin_chat_ids[0]


class FakeSession:
    """جایگزین جلسه‌ی شبکه‌ای؛ هیچ درخواستی به تلگرام نمی‌رود."""
    def __init__(self):
        self.sent = []

    async def __call__(self, bot, method, timeout=None):
        self.sent.append(method)
        return Message(message_id=len(self.sent), date=datetime.now(),
                       chat=Chat(id=1, type="private"), text=getattr(method, "text", None))

    async def close(self):
        pass


@pytest.fixture
def session(monkeypatch):
    s = FakeSession()
    monkeypatch.setattr(B.bot, "session", s)
    return s


def update(text, uid=ADMIN_ID, username=None, n=[0]):
    """یوزرنیم ادمین فقط به ADMIN_ID داده می‌شود؛ بقیه کاربر عادی‌اند."""
    n[0] += 1
    if username is None:
        username = "Farbod_Papoli" if uid == ADMIN_ID else f"user{uid}"
    return Update(update_id=n[0], message=Message(
        message_id=n[0], date=datetime.now(), text=text,
        chat=Chat(id=uid, type="private"),
        from_user=User(id=uid, is_bot=False, first_name="کاربر", username=username)))


def texts(session):
    return "\n".join(m.text for m in session.sent if isinstance(m, SendMessage))


async def feed(dp, upd):
    """یک Update را از مسیر کامل dispatcher عبور می‌دهد و خطاها را بالا می‌آورد."""
    return await dp.feed_update(B.bot, upd)


# ---------- رگرسیون خطای «unexpected keyword argument 'dispatcher'» ----------

@pytest.mark.parametrize("button", [
    B.BTN_A_REPORT, B.BTN_A_STATS, B.BTN_A_ORDERS, B.BTN_A_REMIND, B.BTN_A_ABOUT, B.BTN_A_SHEET])
async def test_every_admin_button_works_through_the_dispatcher(fresh_db, session, button):
    await feed(B.dp, update("/admin"))
    session.sent.clear()
    await feed(B.dp, update(button))
    assert session.sent, f"دکمه‌ی «{button}» هیچ پاسخی تولید نکرد"
    assert all(isinstance(m, (SendMessage, SendDocument)) for m in session.sent)


@pytest.mark.parametrize("cmd", ["/admin", "/report", "/stats", "/sheet", "/setabout"])
async def test_admin_commands_work_through_the_dispatcher(fresh_db, session, cmd):
    await feed(B.dp, update(cmd))
    assert session.sent


async def test_admin_buttons_also_work_on_the_dedicated_admin_dispatcher(fresh_db, session):
    for button in (B.BTN_A_STATS, B.BTN_A_REMIND):
        session.sent.clear()
        await feed(B.admin_dp, update(button))
        assert session.sent, f"«{button}» روی admin_dp کار نکرد"


async def test_admin_panel_opens_and_exits(fresh_db, session):
    await feed(B.dp, update("/admin"))
    assert "پنل مدیریت" in texts(session)
    assert B.in_admin_mode(ADMIN_ID)
    await feed(B.dp, update(B.BTN_A_EXIT))
    assert not B.in_admin_mode(ADMIN_ID)


# ---------- مسیرهای کاربری ----------

async def test_regular_user_flow_through_the_dispatcher(fresh_db, session):
    uid = 6001
    await feed(B.dp, update("/start", uid))
    out = texts(session)
    assert "سامانه تطبیق و تحلیل بازار برق" in out and "راهنمای سریع" in out

    session.sent.clear()
    await feed(B.dp, update("⚡️ نیروگاه", uid))
    await feed(B.dp, update("شرکت نمونه", uid))
    await feed(B.dp, update("علی رضایی", uid))
    await feed(B.dp, update("مدیرعامل", uid))
    await feed(B.dp, update("09121234567", uid))
    await feed(B.dp, update("5000", uid))
    assert "پروفایل شما ثبت شد" in texts(session)


async def test_user_buttons_do_not_hit_admin_handlers(fresh_db, session):
    uid = 6002
    await feed(B.dp, update("/start", uid))
    for button in (B.BTN_HELP, B.BTN_ABOUT):
        session.sent.clear()
        await feed(B.dp, update(button, uid))
        assert session.sent and "پنل مدیریت" not in texts(session)


async def test_non_admin_cannot_use_admin_buttons(fresh_db, session):
    await feed(B.dp, update(B.BTN_A_REPORT, 6003))
    assert "فقط برای مدیران" in texts(session)
    assert not any(isinstance(m, SendDocument) for m in session.sent)


# ---------- وب‌هوک ----------

def _webhook_client(monkeypatch, secret="webhook-test-secret"):
    from fastapi.testclient import TestClient
    from app import api
    monkeypatch.setattr(api.settings, "webhook_secret", secret)
    return TestClient(api.app), secret


def _raw_update(text, uid=ADMIN_ID):
    u = update(text, uid)
    return u.model_dump(mode="json", exclude_none=True)


async def test_webhook_rejects_wrong_or_missing_secret(fresh_db, session, monkeypatch):
    client, secret = _webhook_client(monkeypatch)
    body = _raw_update("/admin")
    assert client.post(api_path(), json=body).status_code == 401
    assert client.post(api_path(), json=body,
                       headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"}).status_code == 401
    assert not session.sent


async def test_webhook_delivers_updates_to_the_dispatcher(fresh_db, session, monkeypatch):
    client, secret = _webhook_client(monkeypatch)
    r = client.post(api_path(), json=_raw_update("/admin"),
                    headers={"X-Telegram-Bot-Api-Secret-Token": secret})
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert "پنل مدیریت" in texts(session)


def api_path():
    from app.api import WEBHOOK_PATH
    return WEBHOOK_PATH
