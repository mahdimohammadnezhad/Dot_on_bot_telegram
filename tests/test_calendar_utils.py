"""تست‌های منطق تقویم شمسی — کاملاً مستقل از بات و دیتابیس."""
import jdatetime
import pytest

from app.calendar_utils import (CalendarRules, week_start, week_code, month_code, week_label,
                                month_label, period_label, available_periods, weekly_cutoff,
                                monthly_cutoff, prev_working_day, is_holiday, add_months)

R = CalendarRules()  # سه‌شنبه ۱۸:۰۰، ۶ دوره


def dt(d, h=9, m=0):
    return jdatetime.datetime(d.year, d.month, d.day, h, m)


# ---------- کدها و لیبل‌ها ----------

def test_week_start_is_saturday():
    for i in range(14):
        d = jdatetime.date.today() + jdatetime.timedelta(days=i)
        s = week_start(d)
        assert s.weekday() == 0 and 0 <= (d - s).days <= 6


def test_week_code_format():
    d = jdatetime.date(1405, 6, 24)
    s = week_start(d)
    assert week_code(d) == f"{s.year:04d}{s.month:02d}{s.day:02d}" and len(week_code(d)) == 8


def test_month_code_format():
    assert month_code(jdatetime.date(1405, 6, 17)) == "14050601"


def test_month_label():
    assert month_label("14050601") == "شهریور ۱۴۰۵"


def test_week_label_same_month():
    # شنبه ۲۰ شهریور ۱۴۰۵ ... بررسی می‌کنیم که شنبه باشد وگرنه لیبل بازه‌ی درست را می‌سازد
    s = week_start(jdatetime.date(1405, 6, 20))
    assert week_label(week_code(s)).startswith("هفته ")
    assert " تا " in week_label(week_code(s))


def test_period_label_falls_back_for_legacy_values():
    assert period_label("2026-W34") == "2026-W34"


def test_period_label_respects_period_type():
    # کد ماهانه و کد هفته‌ای که شنبه‌اش اول ماه است هم‌شکل‌اند؛ period_type تفکیک می‌کند
    assert period_label("14050601", "monthly") == "شهریور ۱۴۰۵"
    assert period_label("14050601", "weekly").startswith("هفته ")


# ---------- مهلت ثبت ----------

def test_weekly_cutoff_is_tuesday_of_previous_week():
    s = week_start(jdatetime.date.today()) + jdatetime.timedelta(days=7)  # هفته‌ی پیش‌رو
    c = weekly_cutoff(s, R)
    assert c.weekday() == R.weekly_cutoff_weekday        # سه‌شنبه
    assert (s - jdatetime.date(c.year, c.month, c.day)).days == 4   # سه‌شنبه‌ی هفته‌ی جاری


def test_monthly_cutoff_is_before_month_start():
    first = add_months(jdatetime.date.today(), 1)
    c = monthly_cutoff(first, R)
    assert jdatetime.date(c.year, c.month, c.day) < first
    assert c.weekday() == R.monthly_cutoff_weekday


# ---------- قواعد لیست دوره‌ها ----------

def test_next_week_available_before_tuesday_cutoff():
    """۱) پیش از مهلت سه‌شنبه، هفته‌ی بعدی باید در لیست باشد."""
    sat = week_start(jdatetime.date.today())
    now = dt(sat, 10)  # شنبه‌ی هفته‌ی جاری، پیش از سه‌شنبه
    codes = [c for c, _, _ in available_periods("weekly", R, now)]
    assert codes[0] == week_code(sat + jdatetime.timedelta(days=7))


def test_next_week_hidden_after_tuesday_cutoff():
    """۲) پس از مهلت، هفته‌ی بلافاصله‌ی بعد حذف و هفته‌ی پس از آن اولین گزینه می‌شود."""
    sat = week_start(jdatetime.date.today())
    now = dt(sat + jdatetime.timedelta(days=R.weekly_cutoff_weekday), R.weekly_cutoff_hour + 1)
    codes = [c for c, _, _ in available_periods("weekly", R, now)]
    assert codes[0] == week_code(sat + jdatetime.timedelta(days=14))
    assert week_code(sat + jdatetime.timedelta(days=7)) not in codes


def test_exactly_at_cutoff_minute_is_still_open():
    sat = week_start(jdatetime.date.today())
    now = dt(sat + jdatetime.timedelta(days=R.weekly_cutoff_weekday),
             R.weekly_cutoff_hour, R.weekly_cutoff_minute)
    codes = [c for c, _, _ in available_periods("weekly", R, now)]
    assert codes[0] == week_code(sat + jdatetime.timedelta(days=7))


@pytest.mark.parametrize("ptype", ["weekly", "monthly"])
@pytest.mark.parametrize("n", [1, 4, 8])
def test_count_equals_future_periods_visible(ptype, n):
    """۳) تعداد گزینه‌ها دقیقاً برابر future_periods_visible است."""
    assert len(available_periods(ptype, CalendarRules(future_periods_visible=n))) == n


@pytest.mark.parametrize("ptype", ["weekly", "monthly"])
def test_no_past_period_is_ever_selectable(ptype):
    """۴) هیچ دوره‌ی گذشته یا جاری‌ای قابل انتخاب نیست."""
    today = jdatetime.date.today()
    for _, _, start in available_periods(ptype, R):
        assert start > today


def test_periods_are_strictly_increasing_and_unique():
    starts = [s for _, _, s in available_periods("weekly", R)]
    assert starts == sorted(starts) and len(set(starts)) == len(starts)


def test_monthly_next_month_available_well_before_cutoff():
    first = add_months(jdatetime.date.today(), 1)
    c = monthly_cutoff(first, R)
    now = c - jdatetime.timedelta(days=1)
    codes = [code for code, _, _ in available_periods("monthly", R, now)]
    assert codes[0] == month_code(first)


def test_monthly_next_month_hidden_after_cutoff():
    first = add_months(jdatetime.date.today(), 1)
    c = monthly_cutoff(first, R)
    now = c + jdatetime.timedelta(minutes=1)
    codes = [code for code, _, _ in available_periods("monthly", R, now)]
    assert month_code(first) not in codes
    assert codes[0] == month_code(add_months(first, 1))


def test_cutoff_hours_are_read_from_rules_not_hardcoded():
    sat = week_start(jdatetime.date.today())
    rules = CalendarRules(weekly_cutoff_weekday=0, weekly_cutoff_hour=8)
    now = dt(sat, 9)  # شنبه ۹ صبح؛ با cutoff شنبه ۸ صبح، هفته‌ی بعد باید بسته باشد
    codes = [c for c, _, _ in available_periods("weekly", rules, now)]
    assert codes[0] == week_code(sat + jdatetime.timedelta(days=14))


# ---------- تعطیلات ----------

def test_holidays_helpers():
    d = jdatetime.date(1405, 1, 5)
    assert is_holiday(d, {"14050105"})
    assert not is_holiday(d, set())
    p = prev_working_day(jdatetime.date(1405, 1, 8), {"14050107"})
    assert p.weekday() != 6 and not is_holiday(p, {"14050107"})
