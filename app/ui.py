"""قالب‌بندی پیام‌ها.

همه‌ی پیام‌ها با parse_mode=HTML ارسال می‌شوند، پس هر مقدارِ واردشده توسط کاربر
باید از esc() عبور کند. تنها همین ماژول اجازه‌ی تولید تگ HTML را دارد.
"""
import html

from .calendar_utils import fa

SEP = "━━━━━━━━━━━━━━"


def esc(v):
    return html.escape("" if v is None else str(v), quote=False)


def b(v):
    return f"<b>{esc(v)}</b>"


def field(label, value, unit=""):
    """«برچسب بولد: مقدار با فونت معمولی» — هر مورد در یک خط."""
    if value in (None, ""):
        return None
    return f"<b>{esc(label)}:</b> {esc(value)}{esc(unit)}"


def lines(*items):
    return "\n".join(i for i in items if i)


def card(title, *items, note=None):
    """کارت استاندارد: عنوان بولد، هر داده در یک خط، یادداشت اختیاری."""
    body = lines(*items)
    out = f"<b>{esc(title)}</b>\n{SEP}\n{body}"
    return f"{out}\n{SEP}\n<i>{esc(note)}</i>" if note else out


def pipe(*parts):
    """نمایش فشرده برای فهرست‌ها — هر داده با | جدا می‌شود."""
    return " | ".join(esc(p) for p in parts if p not in (None, ""))


def kw(v):
    return f"{fa(f'{float(v):,.0f}')} کیلووات"


def rial(v):
    return f"{fa(f'{float(v):,.0f}')} ریال"
