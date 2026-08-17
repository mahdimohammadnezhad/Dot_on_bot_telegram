"""همگام‌سازی لحظه‌ای داده‌ها با Google Sheets.

پس از هر ثبت/ویرایش/حذف، bot.push_sheet() این ماژول را در یک thread جداگانه اجرا می‌کند،
پس پاسخ به کاربر معطل شبکه نمی‌ماند. اگر تنظیم نشده باشد، بی‌صدا رد می‌شود و
دستور /sheet راهنمای گام‌به‌گام راه‌اندازی را نشان می‌دهد.
"""
import os

from .config import settings
from .export import sheet_data

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def missing_pieces():
    """فهرست دقیق چیزهایی که هنوز کم است — برای پیام خطای قابل‌فهم."""
    out = []
    if not settings.google_sheet_id:
        out.append("GOOGLE_SHEET_ID در فایل .env خالی است")
    if not settings.google_credentials_file:
        out.append("GOOGLE_CREDENTIALS_FILE در فایل .env خالی است")
    elif not os.path.exists(settings.google_credentials_file):
        out.append(f"فایل کلید «{settings.google_credentials_file}» در پوشه‌ی پروژه پیدا نشد")
    try:
        import gspread  # noqa: F401
        from google.oauth2.service_account import Credentials  # noqa: F401
    except ImportError:
        out.append("کتابخانه نصب نیست: pip install gspread google-auth")
    return out


def is_configured():
    return not missing_pieces()


def setup_help():
    problems = "\n".join(f"• {p}" for p in missing_pieces())
    return (
        "📄 <b>اتصال به Google Sheets آماده نیست</b>\n\n"
        f"<b>موارد باقی‌مانده:</b>\n{problems}\n\n"
        "<b>مراحل یک‌بارِ راه‌اندازی:</b>\n"
        "۱) در console.cloud.google.com پروژه بسازید و «Google Sheets API» را Enable کنید.\n"
        "۲) از بخش Credentials یک Service Account بسازید و کلید JSON آن را دانلود کنید.\n"
        "۳) فایل JSON را با نام google_credentials.json کنار پروژه بگذارید.\n"
        "۴) شیت را با ایمیل client_email داخل آن فایل، با دسترسی Editor به اشتراک بگذارید.\n"
        "۵) در .env مقادیر GOOGLE_CREDENTIALS_FILE و GOOGLE_SHEET_ID را پر کنید.\n"
        "۶) نصب کتابخانه: pip install gspread google-auth\n"
        "۷) ربات را ری‌استارت و دوباره /sheet را بزنید.\n\n"
        "تا آن زمان با /report همان داده‌ها را به‌صورت فایل اکسل دریافت می‌کنید."
    )


def client():
    import gspread
    from google.oauth2.service_account import Credentials
    creds = Credentials.from_service_account_file(settings.google_credentials_file, scopes=SCOPES)
    return gspread.authorize(creds)


def sync():
    """همه‌ی شیت‌ها را بازنویسی می‌کند و (لینک، تعداد سطر) را برمی‌گرداند."""
    import gspread
    book = client().open_by_key(settings.google_sheet_id)
    total = 0
    for name, (headers, rows) in sheet_data().items():
        try:
            ws = book.worksheet(name)
            ws.clear()
        except gspread.WorksheetNotFound:
            ws = book.add_worksheet(title=name, rows=max(len(rows) + 20, 100), cols=len(headers) + 2)
        values = [headers] + [["" if v is None else v for v in r] for r in rows]
        ws.update(values=values, range_name="A1")
        ws.freeze(rows=1)
        total += len(rows)
    return f"https://docs.google.com/spreadsheets/d/{settings.google_sheet_id}", total


def diagnose():
    """تشخیص علت خرابی اتصال — برای اجرا از خط فرمان."""
    problems = missing_pieces()
    if problems:
        return "تنظیم نشده:\n" + "\n".join(f"  - {p}" for p in problems)
    try:
        import json
        with open(settings.google_credentials_file, encoding="utf-8") as f:
            email = json.load(f).get("client_email", "?")
        book = client().open_by_key(settings.google_sheet_id)
        return (f"OK — شیت «{book.title}» باز شد.\n"
                f"سرویس‌اکانت: {email}\nشیت‌ها: {[w.title for w in book.worksheets()]}")
    except Exception as e:
        return (f"خطا: {type(e).__name__}: {e}\n"
                "اگر خطا PermissionDenied/APIError 403 است، شیت را با ایمیل سرویس‌اکانت "
                "(client_email داخل فایل JSON) با دسترسی Editor به اشتراک بگذارید.")


if __name__ == "__main__":
    print(diagnose())
