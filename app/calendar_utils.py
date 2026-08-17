"""منطق تقویم شمسی PowerMatch.

این ماژول عمداً هیچ وابستگی‌ای به بات/دیتابیس ندارد تا مستقل تست شود.
همه‌ی محاسبات با jdatetime و بر اساس تاریخ واقعی روز انجام می‌شود (هیچ تاریخی hardcode نیست).
"""
from dataclasses import dataclass
import jdatetime

MONTHS = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
          "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]
WEEKDAYS = ["شنبه", "یک‌شنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنج‌شنبه", "جمعه"]
_FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")

WEEKLY, MONTHLY = "weekly", "monthly"
MAX_SCAN = 120  # سقف پویش برای جلوگیری از حلقه‌ی بی‌پایان


def fa(x):
    """تبدیل ارقام لاتین به فارسی."""
    return str(x).translate(_FA)


@dataclass
class CalendarRules:
    """قوانین تقویم بازار؛ مقادیر از جدول market_calendar_rules می‌آیند نه از کد."""
    weekly_cutoff_weekday: int = 3      # ۰=شنبه ... ۳=سه‌شنبه
    weekly_cutoff_hour: int = 18
    weekly_cutoff_minute: int = 0
    monthly_cutoff_weekday: int = 3
    monthly_cutoff_hour: int = 18
    monthly_cutoff_minute: int = 0
    future_periods_visible: int = 6

    @classmethod
    def from_row(cls, row):
        if row is None:
            return cls()
        d = dict(row)
        return cls(**{f: d[f] for f in cls.__dataclass_fields__ if d.get(f) is not None})


# ---------- کدها ----------

def week_start(d):
    """شنبه‌ی هفته‌ای که تاریخ d در آن قرار دارد (weekday در jdatetime: شنبه=۰)."""
    return d - jdatetime.timedelta(days=d.weekday())


def week_code(d):
    """کد هفته: تاریخ شمسی شنبه‌ی همان هفته به فرمت YYYYMMDD."""
    s = week_start(d)
    return f"{s.year:04d}{s.month:02d}{s.day:02d}"


def month_code(d):
    """کد ماه: YYYYMM01 یعنی «کل آن ماه»."""
    return f"{d.year:04d}{d.month:02d}01"


def parse_code(code):
    """کد ۸ رقمی را به تاریخ شمسی تبدیل می‌کند."""
    c = str(code).strip()
    if len(c) != 8 or not c.isdigit():
        raise ValueError(f"کد دوره نامعتبر است: {code}")
    return jdatetime.date(int(c[:4]), int(c[4:6]), int(c[6:8]))


# ---------- لیبل‌های خوانا ----------

def month_label(code):
    d = parse_code(code)
    return f"{MONTHS[d.month - 1]} {fa(d.year)}"


def week_label(code):
    s = parse_code(code)
    e = s + jdatetime.timedelta(days=6)
    if s.year != e.year:
        return f"هفته {fa(s.day)} {MONTHS[s.month-1]} {fa(s.year)} تا {fa(e.day)} {MONTHS[e.month-1]} {fa(e.year)}"
    if s.month != e.month:
        return f"هفته {fa(s.day)} {MONTHS[s.month-1]} تا {fa(e.day)} {MONTHS[e.month-1]} {fa(e.year)}"
    return f"هفته {fa(s.day)} تا {fa(e.day)} {MONTHS[s.month-1]} {fa(s.year)}"


def period_label(code, period_type=None):
    """لیبل خوانا برای هر کد دوره.

    نکته: کد ماهانه (YYYYMM01) با کد هفته‌ای که شنبه‌اش روز اول ماه است هم‌شکل است،
    پس هرجا period_type در دسترس است باید پاس داده شود. در نبود آن، روزِ ۰۱ ماهانه فرض می‌شود
    (رفتار سازگار با رکوردهای قدیمی).
    """
    try:
        if period_type == WEEKLY:
            return week_label(code)
        if period_type == MONTHLY:
            return month_label(code)
        return month_label(code) if str(code).endswith("01") else week_label(code)
    except (ValueError, IndexError):
        return str(code)  # رکوردهای قدیمی مثل «2026-W34» دست‌نخورده نمایش داده شوند


# ---------- مهلت ثبت (cutoff) ----------

def _dt(d, hour, minute):
    return jdatetime.datetime(d.year, d.month, d.day, int(hour), int(minute))


def weekly_cutoff(start, rules):
    """مهلت ثبت برای هفته‌ای که از `start` (شنبه) آغاز می‌شود.

    مهلت، روزِ cutoff در هفته‌ی *قبل* از آن هفته است؛ یعنی برای «هفته‌ی پیش‌رو»
    تا سه‌شنبه‌ی هفته‌ی جاری فرصت ثبت هست.
    """
    prev = start - jdatetime.timedelta(days=7)
    return _dt(prev + jdatetime.timedelta(days=int(rules.weekly_cutoff_weekday)),
               rules.weekly_cutoff_hour, rules.weekly_cutoff_minute)


def monthly_cutoff(first, rules):
    """مهلت ثبت برای ماهی که از `first` (روز اول ماه) آغاز می‌شود:
    آخرین روزِ cutoff_weekday پیش از شروع ماه."""
    d = first - jdatetime.timedelta(days=1)
    while d.weekday() != int(rules.monthly_cutoff_weekday):
        d -= jdatetime.timedelta(days=1)
    return _dt(d, rules.monthly_cutoff_hour, rules.monthly_cutoff_minute)


def add_months(d, n):
    m = d.month - 1 + n
    y, m = d.year + m // 12, m % 12 + 1
    return jdatetime.date(y, m, 1)


def cutoff_for(period_type, code, rules):
    d = parse_code(code)
    return weekly_cutoff(d, rules) if period_type == WEEKLY else monthly_cutoff(d, rules)


# ---------- دوره‌های قابل انتخاب ----------

def available_periods(period_type, rules, now=None):
    """لیست دوره‌های آینده‌ی قابل ثبت: [(code, label, start_date), ...]

    قواعد:
      • هیچ دوره‌ای که شروع شده یا گذشته باشد نمایش داده نمی‌شود.
      • دوره‌ای که از مهلت ثبتش گذشته‌ایم حذف می‌شود (و دوره‌های بعدی جایگزین می‌شوند).
      • تعداد خروجی دقیقاً برابر rules.future_periods_visible است.
    """
    now = now or jdatetime.datetime.now()
    today = jdatetime.date(now.year, now.month, now.day)
    weekly = period_type == WEEKLY
    start = week_start(today) if weekly else jdatetime.date(today.year, today.month, 1)
    out = []
    for i in range(MAX_SCAN):
        s = start + jdatetime.timedelta(days=7 * i) if weekly else add_months(start, i)
        if s <= today:
            continue  # دوره‌ی جاری/گذشته هرگز قابل انتخاب نیست
        if now > (weekly_cutoff(s, rules) if weekly else monthly_cutoff(s, rules)):
            continue  # مهلت ثبت این دوره گذشته است
        out.append((week_code(s) if weekly else month_code(s),
                    week_label(week_code(s)) if weekly else month_label(month_code(s)), s))
        if len(out) >= int(rules.future_periods_visible):
            break
    return out


# ---------- تعطیلات ----------

def is_holiday(d, holidays):
    """holidays: مجموعه‌ای از کدهای YYYYMMDD یا رشته‌های YYYY-MM-DD."""
    return f"{d.year:04d}{d.month:02d}{d.day:02d}" in holidays or \
           f"{d.year:04d}-{d.month:02d}-{d.day:02d}" in holidays


def prev_working_day(d, holidays):
    """آخرین روز کاری پیش از d (جمعه و روزهای جدول holidays کاری نیستند)."""
    d -= jdatetime.timedelta(days=1)
    while d.weekday() == 6 or is_holiday(d, holidays):
        d -= jdatetime.timedelta(days=1)
    return d


def next_working_day(d, holidays):
    d += jdatetime.timedelta(days=1)
    while d.weekday() == 6 or is_holiday(d, holidays):
        d += jdatetime.timedelta(days=1)
    return d
