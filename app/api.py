import secrets

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .config import settings
from .db import connect, init_db, calendar_rules
from .calendar_utils import period_label, available_periods
from .export import build_workbook

app = FastAPI(title="PowerMatch MVP API")

WEAK_SECRETS = {"", "change-me", "changeme", "secret", "admin"}


@app.on_event("startup")
def startup():
    init_db()


def auth(secret):
    """احراز هویت ادمین: مقایسه‌ی زمان‌ثابت + رد کردن رازهای پیش‌فرض/خالی."""
    if settings.admin_secret.strip().lower() in WEAK_SECRETS:
        raise HTTPException(status_code=503,
                            detail="ADMIN_SECRET تنظیم نشده است؛ اندپوینت‌های مدیریتی غیرفعال‌اند.")
    if not secrets.compare_digest(secret or "", settings.admin_secret):
        raise HTTPException(status_code=401, detail="Unauthorized")


def _rows(query, args=()):
    conn = connect()
    rows = [dict(r) for r in conn.execute(query, args).fetchall()]
    conn.close()
    return rows


def _with_label(rows):
    for r in rows:
        r["delivery_period_label"] = period_label(r["delivery_period"], r.get("period_type"))
    return rows


@app.get("/health")
def health():
    return {"status": "ok", "service": "powermatch"}


# ---------- وب‌هوک تلگرام (جایگزین long polling) ----------

WEBHOOK_PATH = "/telegram/webhook"
ADMIN_WEBHOOK_PATH = "/telegram/webhook/admin"


async def _feed(which, request: Request, secret: str):
    """آپدیت تلگرام را می‌گیرد و به dispatcher می‌سپارد.

    هدر مخفی تلگرام بررسی می‌شود تا کسی نتواند آپدیت جعلی به ربات تزریق کند.
    """
    from aiogram.types import Update
    from . import bot as B

    if not settings.webhook_secret or not secrets.compare_digest(secret or "", settings.webhook_secret):
        raise HTTPException(status_code=401, detail="Unauthorized")
    dispatcher, target = ((B.dp, B.bot) if which == "user" else (B.admin_dp, B.admin_bot))
    await dispatcher.feed_webhook_update(target, Update.model_validate(await request.json()))
    return {"ok": True}


@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request,
                           x_telegram_bot_api_secret_token: str = Header(default="")):
    return await _feed("user", request, x_telegram_bot_api_secret_token)


@app.post(ADMIN_WEBHOOK_PATH)
async def telegram_admin_webhook(request: Request,
                                 x_telegram_bot_api_secret_token: str = Header(default="")):
    return await _feed("admin", request, x_telegram_bot_api_secret_token)


@app.get("/admin/organizations")
def organizations(x_admin_secret: str = Header(default="")):
    auth(x_admin_secret)
    return _rows("SELECT * FROM organizations ORDER BY id DESC")


@app.get("/admin/offers")
def offers(x_admin_secret: str = Header(default="")):
    auth(x_admin_secret)
    return _with_label(_rows("SELECT * FROM offers ORDER BY id DESC"))


@app.get("/admin/requests")
def requests(x_admin_secret: str = Header(default="")):
    auth(x_admin_secret)
    return _with_label(_rows("SELECT * FROM requests ORDER BY id DESC"))


@app.get("/admin/matches")
def matches(x_admin_secret: str = Header(default="")):
    """جدول تطبیق حفظ شده اما دیگر توسط بات پر نمی‌شود (تطبیق برای کاربران حذف شد)."""
    auth(x_admin_secret)
    return _rows("SELECT * FROM matches ORDER BY id DESC")


class RulesIn(BaseModel):
    weekly_cutoff_weekday: int | None = Field(default=None, ge=0, le=6)
    weekly_cutoff_hour: int | None = Field(default=None, ge=0, le=23)
    weekly_cutoff_minute: int | None = Field(default=None, ge=0, le=59)
    monthly_cutoff_weekday: int | None = Field(default=None, ge=0, le=6)
    monthly_cutoff_hour: int | None = Field(default=None, ge=0, le=23)
    monthly_cutoff_minute: int | None = Field(default=None, ge=0, le=59)
    future_periods_visible: int | None = Field(default=None, ge=1, le=24)


@app.get("/admin/calendar")
def calendar(x_admin_secret: str = Header(default="")):
    auth(x_admin_secret)
    rules = calendar_rules()
    return {
        "rules": rules.__dict__,
        "holidays": _rows("SELECT jalali_date,title FROM holidays ORDER BY jalali_date"),
        "weekly": [{"code": c, "label": l} for c, l, _ in available_periods("weekly", rules)],
        "monthly": [{"code": c, "label": l} for c, l, _ in available_periods("monthly", rules)],
    }


@app.put("/admin/calendar")
def update_calendar(body: RulesIn, x_admin_secret: str = Header(default="")):
    auth(x_admin_secret)
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if fields:  # کلیدها از مدل whitelist می‌آیند، نه از ورودی خام
        conn = connect()
        conn.execute(f"UPDATE market_calendar_rules SET {','.join(f'{k}=?' for k in fields)},"
                     "updated_at=CURRENT_TIMESTAMP WHERE id=1", list(fields.values()))
        conn.commit()
        conn.close()
    return calendar_rules().__dict__


@app.get("/admin/export")
def export(x_admin_secret: str = Header(default="")):
    auth(x_admin_secret)
    return Response(
        build_workbook(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="powermatch_report.xlsx"'})
