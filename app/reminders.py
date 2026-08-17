"""یادآوری روزانه‌ی ثبت عرضه/تقاضا.

هر روز در ساعت‌های تعیین‌شده توسط ادمین، به کاربرانی که برای *نزدیک‌ترین* دوره‌ی
هفتگی و ماهانه هنوز حجم و قیمت ثبت نکرده‌اند پیام یادآوری ارسال می‌شود.
متن پیام، ساعت‌ها و دسته‌ی مخاطبان همگی از پنل ادمین قابل تنظیم‌اند (app_settings).
"""
import asyncio
from datetime import datetime, timedelta, timezone

from .config import TZ
from .db import (connect, calendar_rules, get_setting, set_setting, ROLE_LABELS,
                 SUPPLY_ROLES, DEMAND_ROLES)
from . import calendar_utils as cal

K_ENABLED, K_TIMES, K_ROLES, K_TEXT = ("reminder_enabled", "reminder_times",
                                       "reminder_roles", "reminder_text")
DEFAULT_TIMES = "09:30,11:00"
DEFAULT_ROLES = "all"
DEFAULT_TEXT = (
    "⏰ <b>یادآوری ثبت سفارش</b>\n"
    "{name} گرامی، برای دوره‌های زیر هنوز حجم و قیمتی ثبت نکرده‌اید:\n"
    "{periods}\n"
    "لطفاً با دکمه‌های «ثبت عرضه» یا «ثبت تقاضا» اطلاعات خود را وارد کنید."
)
ALL_ROLES = ("generator", "buyer", "retailer", "broker")


def tehran_now():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(TZ)).replace(tzinfo=None)
    except Exception:                     # نبود پایگاه‌داده‌ی مناطق زمانی روی سیستم میزبان
        return datetime.now(timezone(timedelta(hours=3, minutes=30))).replace(tzinfo=None)


# ---------- تنظیمات ----------

def get_config():
    roles = get_setting(K_ROLES, DEFAULT_ROLES)
    return {
        "enabled": get_setting(K_ENABLED, "1") == "1",
        "times": [t for t in (get_setting(K_TIMES, DEFAULT_TIMES) or "").split(",") if t],
        "roles": list(ALL_ROLES) if roles == "all" else [r for r in roles.split(",") if r in ALL_ROLES],
        "all_roles": roles == "all",
        "text": get_setting(K_TEXT, DEFAULT_TEXT),
    }


def parse_times(raw):
    """«09:30, 11:00» → ['09:30','11:00'] با اعتبارسنجی کامل؛ خطا → ValueError."""
    out = []
    for part in str(raw).replace("،", ",").replace(" ", "").split(","):
        if not part:
            continue
        h, _, m = part.partition(":")
        if not (h.isdigit() and m.isdigit() and 0 <= int(h) <= 23 and 0 <= int(m) <= 59):
            raise ValueError(part)
        out.append(f"{int(h):02d}:{int(m):02d}")
    if not out:
        raise ValueError("empty")
    return sorted(dict.fromkeys(out))


def set_times(raw):
    set_setting(K_TIMES, ",".join(parse_times(raw)))


def set_roles(roles):
    set_setting(K_ROLES, "all" if not roles or set(roles) == set(ALL_ROLES) else ",".join(roles))


def describe():
    c = get_config()
    who = "همه‌ی نقش‌ها" if c["all_roles"] else "، ".join(ROLE_LABELS.get(r, r) for r in c["roles"])
    return c, who


# ---------- تشخیص کاربرانِ نیازمند یادآوری ----------

def missing_periods(conn, membership, rules):
    """نزدیک‌ترین دوره‌ی هفتگی و ماهانه‌ای که این پروفایل برایشان چیزی ثبت نکرده است."""
    out = []
    for ptype in (cal.WEEKLY, cal.MONTHLY):
        options = cal.available_periods(ptype, rules)
        if not options:
            continue
        code, label, _ = options[0]
        tables = []
        if membership["role"] in SUPPLY_ROLES:
            tables.append("offers")
        if membership["role"] in DEMAND_ROLES:
            tables.append("requests")
        found = any(conn.execute(
            f"SELECT 1 FROM {t} WHERE membership_id=? AND delivery_period=? AND period_type=? "
            "AND deleted_at IS NULL LIMIT 1",
            (membership["membership_id"], code, ptype)).fetchone() for t in tables)
        if not found:
            out.append(("هفتگی" if ptype == cal.WEEKLY else "ماهانه", label))
    return out


def pending_reminders(config=None):
    """[(telegram_id, نام شرکت, نقش, [(نوع, لیبل دوره)])] برای همه‌ی پروفایل‌های مشمول."""
    c = config or get_config()
    rules = calendar_rules()
    conn = connect()
    rows = conn.execute(
        "SELECT m.id AS membership_id, m.role, o.name, u.telegram_id FROM memberships m "
        "JOIN organizations o ON o.id=m.org_id JOIN users u ON u.id=m.user_id "
        "WHERE m.deleted_at IS NULL AND o.deleted_at IS NULL "
        f"AND m.role IN ({','.join('?' * len(c['roles']))})", c["roles"]).fetchall() if c["roles"] else []
    out = []
    for r in rows:
        miss = missing_periods(conn, r, rules)
        if miss:
            out.append((r["telegram_id"], r["name"], r["role"], miss))
    conn.close()
    return out


def render(text, name, role, missing):
    periods = "\n".join(f"• {kind}: {label}" for kind, label in missing)
    return (text.replace("{name}", name).replace("{periods}", periods)
                .replace("{role}", ROLE_LABELS.get(role, role)))


def _already_sent(conn, key):
    return conn.execute("SELECT 1 FROM reminder_log WHERE key=?", (key,)).fetchone() is not None


async def send_due(bot, now=None, slot=None, force=False):
    """ارسال یادآوری‌های سررسیدشده. خروجی: تعداد پیام‌های ارسال‌شده.

    force=True برای «ارسال آزمایشی» از پنل ادمین (بدون بررسی ساعت و بدون ثبت در لاگ).
    """
    c = get_config()
    if not c["enabled"] and not force:
        return 0
    now = now or tehran_now()
    slot = slot or now.strftime("%H:%M")
    if not force and slot not in c["times"]:
        return 0

    conn = connect()
    sent = 0
    for tg_id, name, role, missing in pending_reminders(c):
        key = f"{now:%Y-%m-%d}|{slot}|{tg_id}"
        if not force and _already_sent(conn, key):
            continue
        try:
            await bot.send_message(tg_id, render(c["text"], name, role, missing), parse_mode="HTML")
            sent += 1
        except Exception:
            pass          # کاربری که ربات را بلاک کرده نباید بقیه‌ی ارسال‌ها را متوقف کند
        if not force:
            conn.execute("INSERT OR IGNORE INTO reminder_log(key) VALUES(?)", (key,))
    conn.commit()
    conn.close()
    return sent


async def scheduler(bot, tick=30):
    """حلقه‌ی پس‌زمینه؛ هر نیم‌دقیقه ساعت تهران را با ساعت‌های تنظیم‌شده مقایسه می‌کند."""
    while True:
        try:
            await send_due(bot)
        except Exception:
            pass
        await asyncio.sleep(tick)
