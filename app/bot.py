import asyncio
import functools
import inspect
import re
import time
import unicodedata

from aiogram import Bot, Dispatcher, F, BaseMiddleware
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart, Command
from aiogram.types import (Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton,
                           InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from .config import settings, BOT_NAME
from .db import (connect, get_user, memberships_of, active_membership, set_active_membership,
                 calendar_rules, get_setting, set_setting, remember_admin_chat, admin_chat_ids,
                 next_seq, log_change, now_jalali, ROLE_LABELS, SUPPLY_ROLES, DEMAND_ROLES,
                 MAX_TEXT, MAX_KW, MAX_RIAL)
from . import calendar_utils as cal
from . import reminders as rem
from .calendar_utils import fa
from .ui import esc, b, field, lines, card, pipe, kw, rial, SEP

# parse_mode=HTML فعال است تا برچسب‌ها بولد شوند؛ در عوض هر مقدارِ کاربر
# پیش از نمایش از esc() عبور می‌کند (ماژول ui) تا تزریق HTML ممکن نباشد.
bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

ROLE_NAMES = {"⚡️ نیروگاه": "generator", "🏭 خریدار نهایی / صنعت": "buyer",
              "🏬 خرده‌فروش": "retailer", "🤝 کارگزاری": "broker"}
CAPACITY_ROLES = ("generator", "buyer")
BTN_OFFER, BTN_REQUEST = "⚡ ثبت عرضه (فروش)", "🔌 ثبت تقاضا (خرید)"
BTN_ORDERS, BTN_PROFILE = "🧾 سفارش‌های من", "👤 پروفایل من"
BTN_SWITCH, BTN_INVITE, BTN_ABOUT = "🔄 تغییر شرکت/نقش", "🤝 معرفی به همکاران", "ℹ️ درباره ما"
BTN_HELP, BTN_SHARE_PHONE = "❓ راهنما", "📱 ارسال شماره‌ی من"
ABOUT_KEY = "about_text"
CONTACT_ID = "@Farbod_Papoli"

BIDI_SPOOF = set("‪‫‬‭‮⁦⁧⁨⁩﻿")
BAD_CATS = {"Cc", "Cs", "Co", "Cn"}
DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
IR_MOBILE = re.compile(r"^(?:0098|\+98|98|0)?(9\d{9})$")

SHORT_DESCRIPTION = "سامانه تطبیق و تحلیل بازار برق"
BOT_DESCRIPTION = (
    "سامانه تطبیق و تحلیل بازار برق برای نیروگاه‌ها، صنایع، خرده‌فروشان و فعالان بازار.\n\n"
    "⚡️ ثبت و مدیریت عرضه و تقاضای برق\n"
    "🎯 شناسایی فرصت‌های مناسب خرید و فروش\n"
    "🔔 اطلاع‌رسانی فرصت‌های معاملاتی\n"
    "🤝 کمک به تطبیق عرضه و تقاضا\n\n"
    "پس از ثبت درخواست، کارشناسان ما با شما تماس می‌گیرند."
)

DEFAULT_ABOUT = (
    f"⚡️ <b>درباره {BOT_NAME}</b>\n"
    f"{SEP}\n"
    "سامانه تطبیق و تحلیل بازار برق برای نیروگاه‌ها، صنایع، خرده‌فروشان و فعالان بازار.\n\n"
    "⚡️ <b>ثبت و مدیریت</b> عرضه و تقاضای برق\n"
    "🎯 <b>شناسایی</b> فرصت‌های مناسب خرید و فروش\n"
    "🔔 <b>اطلاع‌رسانی</b> فرصت‌های معاملاتی\n"
    "🤝 <b>کمک به تطبیق</b> عرضه و تقاضا\n\n"
    "پس از ثبت درخواست خود، کارشناسان ما با شما تماس می‌گیرند.\n\n"
    "❌ اطلاعات کاربران و معاملات به‌صورت محرمانه مدیریت می‌شود و برای هیچ کاربر دیگری "
    "نمایش داده نمی‌شود.\n"
    f"{SEP}\n"
    "<b>ارتباط با ما</b> 👇\n"
    f"🆔 {CONTACT_ID}\n"
    "🏢 شرکت نیروگاهی داتیس آوان نیرو"
)

HELP_TEXT = (
    "📘 <b>راهنمای سریع</b>\n"
    f"{SEP}\n"
    "<b>۱) ثبت‌نام</b>\n"
    "▫️ نوع فعالیت خود را انتخاب کنید: نیروگاه، خریدار صنعتی، خرده‌فروش یا کارگزاری\n"
    "▫️ نام شرکت، شخص مسئول، سمت و شماره تماس را وارد کنید\n"
    "▫️ شماره را می‌توانید تایپ کنید یا با دکمه‌ی «📱 ارسال شماره‌ی من» بفرستید\n\n"
    "<b>۲) ثبت سفارش</b>\n"
    "▫️ «⚡ ثبت عرضه (فروش)» برای فروش برق\n"
    "▫️ «🔌 ثبت تقاضا (خرید)» برای خرید برق\n"
    "▫️ بازه را انتخاب کنید: <b>هفتگی</b> یا <b>ماهانه</b>\n"
    "▫️ دوره‌ی تحویل را از میان گزینه‌های آماده بزنید (تایپ لازم نیست)\n"
    "▫️ حجم بر حسب <b>کیلووات</b> و قیمت بر حسب <b>ریال</b> وارد می‌شود\n\n"
    "<b>۳) مدیریت سفارش‌ها</b>\n"
    "▫️ «🧾 سفارش‌های من» فهرست سفارش‌های شما را نشان می‌دهد\n"
    "▫️ کنار هر سفارش دکمه‌های ✏️ ویرایش حجم/قیمت/دوره و 🗑 حذف هست\n\n"
    "<b>۴) پروفایل و نقش‌ها</b>\n"
    "▫️ «👤 پروفایل من» برای دیدن و ویرایش هر مورد (مثلاً شماره تماس)\n"
    "▫️ می‌توانید چند نقش داشته باشید و با «🔄 تغییر شرکت/نقش» بین آن‌ها جابه‌جا شوید\n\n"
    "<b>۵) نکته‌های مهم</b>\n"
    "▫️ مهلت ثبت هر دوره محدود است؛ فقط دوره‌های مجاز نمایش داده می‌شوند\n"
    "🔔 اگر برای نزدیک‌ترین دوره چیزی ثبت نکنید، یادآوری دریافت می‌کنید\n"
    "🔒 اطلاعات شما محرمانه است و به هیچ کاربر دیگری نشان داده نمی‌شود\n"
    f"{SEP}\n"
    f"پشتیبانی: {CONTACT_ID}"
)

# فیلدهای قابل ویرایش پروفایل: کلید → (برچسب، ستون دیتابیس)
PROFILE_FIELDS = {"name": ("نام شرکت", "name"), "person": ("نام شخص مسئول", "contact_person"),
                  "position": ("سمت", "position"), "phone": ("شماره تلفن", "phone"),
                  "capacity": ("سقف مجاز (کیلووات)", "capacity_kw")}
ORDER_KINDS = {"o": ("offers", "min_price", "عرضه", "کف قیمت", "offer"),
               "r": ("requests", "max_price", "تقاضا", "سقف قیمت", "request")}


def about_text():
    return get_setting(ABOUT_KEY, DEFAULT_ABOUT)


class Registration(StatesGroup):
    role = State(); org_name = State(); contact_person = State()
    position = State(); phone = State(); capacity = State()


class TradeForm(StatesGroup):
    period_type = State(); period = State(); volume = State(); price = State()


class EditProfile(StatesGroup):
    value = State()


class EditOrder(StatesGroup):
    value = State(); period = State()


class AdminForm(StatesGroup):
    about = State(); rem_times = State(); rem_text = State()


# ---------- میان‌افزارها ----------

class AdminChatMiddleware(BaseMiddleware):
    """chat_id ادمین‌های تعریف‌شده با یوزرنیم را ثبت می‌کند تا نوتیف لحظه‌ای ممکن شود."""
    async def __call__(self, handler, event, data):
        u = data.get("event_from_user")
        if u and u.username and u.username.lower() in settings.admin_usernames:
            try:
                remember_admin_chat(u.username, u.id)
            except Exception:
                pass
        return await handler(event, data)


class ThrottleMiddleware(BaseMiddleware):
    """محدودسازی ساده‌ی نرخ درخواست برای جلوگیری از flood/سوءاستفاده."""
    LIMIT, WINDOW = 25, 10.0

    def __init__(self):
        self.hits = {}

    async def __call__(self, handler, event, data):
        u = data.get("event_from_user")
        if u:
            now = time.monotonic()
            q = [t for t in self.hits.get(u.id, []) if now - t < self.WINDOW]
            q.append(now)
            self.hits[u.id] = q
            if len(self.hits) > 10_000:
                self.hits = {u.id: q}
            if len(q) > self.LIMIT:
                return None
        return await handler(event, data)


for observer in (dp.message, dp.callback_query):
    observer.outer_middleware(ThrottleMiddleware())
    observer.outer_middleware(AdminChatMiddleware())


# ---------- کیبوردها ----------

def menu():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text=BTN_OFFER), KeyboardButton(text=BTN_REQUEST)],
        [KeyboardButton(text=BTN_ORDERS), KeyboardButton(text=BTN_PROFILE)],
        [KeyboardButton(text=BTN_SWITCH), KeyboardButton(text=BTN_INVITE)],
        [KeyboardButton(text=BTN_HELP), KeyboardButton(text=BTN_ABOUT)],
    ], resize_keyboard=True)


def roles_kb():
    keys = list(ROLE_NAMES)
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=keys[0]), KeyboardButton(text=keys[1])],
                  [KeyboardButton(text=keys[2]), KeyboardButton(text=keys[3])]],
        resize_keyboard=True, one_time_keyboard=True)


def phone_kb():
    """گزینه‌ی اختیاری اشتراک شماره — بدون افزودن یک سؤال جداگانه به فرم."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_SHARE_PHONE, request_contact=True)]],
        resize_keyboard=True, one_time_keyboard=True)


def inline(rows):
    return InlineKeyboardMarkup(inline_keyboard=rows)


def period_type_kb(prefix):
    return inline([[InlineKeyboardButton(text="🗓 هفتگی", callback_data=f"{prefix}:weekly"),
                    InlineKeyboardButton(text="📆 ماهانه", callback_data=f"{prefix}:monthly")]])


def periods_kb(prefix, options):
    return inline([[InlineKeyboardButton(text=lbl, callback_data=f"{prefix}:{i}")]
                   for i, (code, lbl, _) in enumerate(options)])


def profiles_kb(rows, prefix, suffix=""):
    return inline([[InlineKeyboardButton(
        text=f"{r['name']} — {ROLE_LABELS.get(r['role'], r['role'])}",
        callback_data=f"{prefix}:{r['membership_id']}" + (f":{suffix}" if suffix else ""))]
        for r in rows])


# ---------- اعتبارسنجی ورودی ----------

def clean(text, max_len=MAX_TEXT):
    """حذف کاراکترهای کنترلی و جهت‌دهنده‌های جعلی (spoofing) و محدودسازی طول.

    نیم‌فاصله (ZWNJ) و ZWJ عمداً حفظ می‌شوند چون بخشی از املای فارسی‌اند.
    """
    t = "".join(c for c in (text or "")
                if c not in BIDI_SPOOF and (c == " " or unicodedata.category(c) not in BAD_CATS))
    return t.strip()[:max_len]


def number(text, hi):
    v = float(clean(text, 32).translate(DIGITS).replace(",", "").replace("،", ""))
    if not (0 < v <= hi) or v != v:
        raise ValueError
    return v


def normalize_phone(raw):
    """شماره‌ی همراه ایران را به فرمت 09xxxxxxxxx تبدیل می‌کند؛ در غیر این صورت None."""
    digits = re.sub(r"[^\d+]", "", clean(raw, 30).translate(DIGITS))
    m = IR_MOBILE.match(digits)
    return "0" + m.group(1) if m else None


def is_admin(user):
    return settings.is_admin(user.id, user.username)


# ---------- خروجی لحظه‌ای ----------

async def notify_admins(text):
    """گزارش‌ها همیشه از مسیر ربات مدیریت می‌روند تا با چت کاربران قاطی نشوند."""
    for chat_id in admin_chat_ids():
        try:
            await admin_bot.send_message(chat_id, text)
        except Exception:
            pass  # نبود دسترسی به یک ادمین نباید جریان کاربر را بشکند


def push_sheet():
    """همگام‌سازی لحظه‌ای گوگل‌شیت، بدون بلاک‌کردن پاسخ به کاربر."""
    from . import gsheet
    if not gsheet.is_configured():
        return
    async def _run():
        try:
            await asyncio.to_thread(gsheet.sync)
        except Exception:
            pass
    try:
        asyncio.get_running_loop().create_task(_run())
    except RuntimeError:
        pass


async def after_change(admin_text=None):
    if admin_text:
        await notify_admins(admin_text)
    push_sheet()


# ---------- /start و درباره ما ----------

@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    if not SEPARATE_ADMIN_BOT and is_admin(message.from_user):
        set_admin_mode(message.from_user.id, False)   # بازگشت از پنل به فضای کاربری
    u = get_user(message.from_user.id)
    rows = memberships_of(u["id"]) if u else []
    if rows:
        act = active_membership(u["id"])
        await message.answer(card(
            f"👋 خوش آمدید به {BOT_NAME}",
            *[field(f"پروفایل {fa(i)}", f"{r['name']} — {ROLE_LABELS.get(r['role'], r['role'])}")
              for i, r in enumerate(rows, 1)],
            field("✅ پروفایل فعال", f"{act['name']} — {ROLE_LABELS.get(act['role'], act['role'])}")
            if act else None), reply_markup=menu())
        await message.answer("می‌توانید پروفایل تازه‌ای اضافه کنید:", reply_markup=inline(
            [[InlineKeyboardButton(text="➕ افزودن پروفایل/نقش جدید", callback_data="reg:new")]]))
        return
    await state.set_state(Registration.role)
    await message.answer(about_text())
    await message.answer(HELP_TEXT)          # راهنمای کوتاه برای کاربر تازه‌وارد
    await message.answer("برای شروع، <b>نوع فعالیت</b> خود را انتخاب کنید:", reply_markup=roles_kb())


@dp.message(Command("about"))
@dp.message(F.text == BTN_ABOUT)
async def about(message: Message):
    await message.answer(about_text(), reply_markup=menu())


@dp.message(Command("help"))
@dp.message(F.text == BTN_HELP)
async def help_cmd(message: Message):
    await message.answer(HELP_TEXT, reply_markup=menu())


def phone_intl(p):
    """۰۹۱۲… → +۹۸۹۱۲… تا کلاینت تلگرام آن را قابل‌کلیک (تماس) کند."""
    d = re.sub(r"\D", "", str(p or ""))
    if d.startswith("0"):
        d = "98" + d[1:]
    elif len(d) == 10 and d.startswith("9"):
        d = "98" + d
    return f"+{d}" if d else ""


def phone_field(p, label="شماره تلفن"):
    return field(label, phone_intl(p) or p)


@dp.message(Command("invite"))
@dp.message(F.text == BTN_INVITE)
async def invite(message: Message):
    link = await bot_link()
    text = card("🤝 معرفی به همکاران",
                f"{BOT_NAME} را به همکارانتان معرفی کنید:",
                field("لینک ربات", link),
                note="با اشتراک این لینک، همکارانتان می‌توانند عرضه یا تقاضای خود را ثبت کنند.")
    await message.answer(text, reply_markup=inline([[InlineKeyboardButton(
        text="📤 ارسال به یک گفتگو", switch_inline_query=f"\n{BOT_NAME}\n{link}")]]))


_link_cache = {}


async def bot_link():
    if not _link_cache.get("url"):
        username = settings.bot_username
        if not username:
            try:
                username = (await bot.get_me()).username
            except Exception:
                username = ""
        _link_cache["url"] = f"https://t.me/{username}" if username else "لینک ربات در دسترس نیست"
    return _link_cache["url"]


@dp.callback_query(F.data == "reg:new")
async def add_profile(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(Registration.role)
    await cb.message.answer("نوع فعالیت پروفایل جدید را انتخاب کنید:", reply_markup=roles_kb())
    await cb.answer()


# ---------- ثبت‌نام ----------

@dp.message(Registration.role)
async def reg_role(message: Message, state: FSMContext):
    role = ROLE_NAMES.get(clean(message.text, 40))
    if not role:
        await message.answer("لطفاً یکی از گزینه‌های منو را انتخاب کنید.")
        return
    await state.update_data(role=role)
    await state.set_state(Registration.org_name)
    await message.answer("🏢 <b>نام شرکت</b> را وارد کنید:")


@dp.message(Registration.org_name)
async def reg_org_name(message: Message, state: FSMContext):
    name = clean(message.text)
    if len(name) < 2:
        await message.answer("نام شرکت نامعتبر است؛ دوباره وارد کنید.")
        return
    await state.update_data(org_name=name)
    await state.set_state(Registration.contact_person)
    await message.answer("👤 <b>نام شخص مسئول</b> را وارد کنید:")


@dp.message(Registration.contact_person)
async def reg_person(message: Message, state: FSMContext):
    name = clean(message.text)
    if len(name) < 2:
        await message.answer("نام نامعتبر است؛ دوباره وارد کنید.")
        return
    await state.update_data(contact_person=name)
    await state.set_state(Registration.position)
    await message.answer("💼 <b>سمت</b> ایشان را وارد کنید:")


@dp.message(Registration.position)
async def reg_position(message: Message, state: FSMContext):
    await state.update_data(position=clean(message.text))
    await state.set_state(Registration.phone)
    await message.answer(
        "📞 <b>شماره تماس</b> را وارد کنید (نمونه: 09121234567)\n"
        "یا با دکمه‌ی زیر شماره‌ی حساب تلگرام خود را به اشتراک بگذارید.",
        reply_markup=phone_kb())


@dp.message(Registration.phone, F.contact)
async def reg_phone_contact(message: Message, state: FSMContext):
    if message.contact.user_id and message.contact.user_id != message.from_user.id:
        await message.answer("فقط شماره‌ی حساب خودتان قابل قبول است؛ شماره را وارد کنید.")
        return
    phone = normalize_phone(message.contact.phone_number)
    if not phone:
        await message.answer("شماره‌ی حساب شما ایرانی نیست؛ لطفاً یک شماره‌ی همراه ایران وارد کنید.")
        return
    await _phone_done(message, state, phone)


@dp.message(Registration.phone)
async def reg_phone(message: Message, state: FSMContext):
    phone = normalize_phone(message.text)
    if not phone:
        await message.answer(
            "⚠️ شماره‌ی همراه نامعتبر است.\n"
            "شماره باید ۱۱ رقم و ایرانی باشد و با <b>09</b> شروع شود؛ نمونه: <b>09121234567</b>\n"
            "لطفاً دوباره وارد کنید یا از دکمه‌ی ارسال شماره استفاده کنید.", reply_markup=phone_kb())
        return
    await _phone_done(message, state, phone)


async def _phone_done(message, state, phone):
    d = await state.update_data(phone=phone)
    if d["role"] in CAPACITY_ROLES:
        await state.set_state(Registration.capacity)
        label = "سقف مجاز عرضه در بورس نیروگاه" if d["role"] == "generator" else "سقف مجاز خرید"
        await message.answer(f"⚡ <b>{esc(label)}</b> «{esc(d['org_name'])}» را بر حسب "
                             "<b>کیلووات (kW)</b> وارد کنید:")
        return
    await finish_registration(message, state, d, None)


@dp.message(Registration.capacity)
async def reg_capacity(message: Message, state: FSMContext):
    d = await state.get_data()
    try:
        cap = number(message.text, MAX_KW)
    except ValueError:
        await message.answer("مقدار نامعتبر است؛ یک عدد بر حسب کیلووات وارد کنید.")
        return
    await finish_registration(message, state, d, cap)


async def finish_registration(message, state, d, cap):
    conn = connect()
    conn.execute("INSERT OR IGNORE INTO users(telegram_id,name,username,role) VALUES(?,?,?,?)",
                 (message.from_user.id, clean(message.from_user.full_name),
                  clean(message.from_user.username, 40), d["role"]))
    user = get_user(message.from_user.id, conn)
    org_id = conn.execute(
        "INSERT INTO organizations(name,role,contact_person,position,phone,capacity_kw) "
        "VALUES(?,?,?,?,?,?)",
        (d["org_name"], d["role"], d.get("contact_person"), d.get("position"),
         d.get("phone"), cap)).lastrowid
    mid = conn.execute("INSERT INTO memberships(user_id,org_id,role) VALUES(?,?,?)",
                       (user["id"], org_id, d["role"])).lastrowid
    log_change(conn, "organization", org_id, "create", actor=user["id"])
    set_active_membership(user["id"], mid, conn)
    conn.commit()
    conn.close()
    await state.clear()

    role_label = ROLE_LABELS.get(d["role"], d["role"])
    await message.answer(card(
        "✅ پروفایل شما ثبت شد",
        field("نام شرکت", d["org_name"]), field("نقش", role_label),
        field("نام شخص", d.get("contact_person")), field("سمت", d.get("position")),
        field("شماره تلفن", d.get("phone")),
        field("سقف مجاز", kw(cap)) if cap else None,
        note="این پروفایل اکنون فعال است."), reply_markup=menu())
    await after_change(card(
        "🆕 پروفایل جدید",
        field("نام شرکت", d["org_name"]), field("نقش", role_label),
        field("نام شخص", d.get("contact_person")), field("سمت", d.get("position")),
        phone_field(d.get("phone")),
        field("سقف مجاز", kw(cap)) if cap else None,
        field("کاربر تلگرام", f"@{message.from_user.username}" if message.from_user.username
              else message.from_user.id),
        field("زمان ثبت", now_jalali())))


# ---------- پروفایل من ----------

def profile_card(row):
    return card(
        f"👤 {row['name']}",
        field("نقش", ROLE_LABELS.get(row["role"], row["role"])),
        field("نام شخص مسئول", row["contact_person"]),
        field("سمت", row["position"]),
        field("شماره تلفن", row["phone"]),
        field("سقف مجاز", kw(row["capacity_kw"])) if row["capacity_kw"] else None)


def profile_actions_kb(mid, role):
    rows = [[InlineKeyboardButton(text=f"✏️ {lbl}", callback_data=f"pedit:{mid}:{key}")]
            for key, (lbl, _) in PROFILE_FIELDS.items()
            if key != "capacity" or role in CAPACITY_ROLES]
    rows.append([InlineKeyboardButton(text="🗑 حذف کامل این پروفایل", callback_data=f"pdel:{mid}")])
    return inline(rows)


@dp.message(F.text == BTN_PROFILE)
async def profile(message: Message):
    u = get_user(message.from_user.id)
    rows = memberships_of(u["id"]) if u else []
    if not rows:
        await message.answer("ابتدا /start را بزنید.")
        return
    act = active_membership(u["id"])
    for r in rows:
        star = " ✅ (فعال)" if act and act["membership_id"] == r["membership_id"] else ""
        await message.answer(profile_card(r) + (f"\n{b(star.strip())}" if star else ""),
                             reply_markup=profile_actions_kb(r["membership_id"], r["role"]))


def _owned_membership(tg_id, mid, roles=None):
    """پروفایل را فقط در صورتی برمی‌گرداند که متعلق به همین کاربر باشد."""
    u = get_user(tg_id)
    if not u:
        return None, None
    row = next((r for r in memberships_of(u["id"], roles=roles) if str(r["membership_id"]) == str(mid)), None)
    return u, row


@dp.callback_query(F.data.startswith("pedit:"))
async def profile_edit_start(cb: CallbackQuery, state: FSMContext):
    _, mid, key = cb.data.split(":")
    u, row = _owned_membership(cb.from_user.id, mid)
    if not row or key not in PROFILE_FIELDS:
        await cb.answer("پروفایل یافت نشد.", show_alert=True)
        return
    label, _col = PROFILE_FIELDS[key]
    await state.set_state(EditProfile.value)
    await state.update_data(mid=int(mid), org_id=row["org_id"], key=key)
    hint = ("نمونه: 09121234567" if key == "phone" else
            "یک عدد بر حسب کیلووات" if key == "capacity" else "مقدار تازه را بنویسید")
    await cb.message.answer(f"✏️ <b>{esc(label)}</b> را ویرایش می‌کنید.\n{esc(hint)}:")
    await cb.answer()


@dp.message(EditProfile.value)
async def profile_edit_save(message: Message, state: FSMContext):
    d = await state.get_data()
    key = d["key"]
    label, col = PROFILE_FIELDS[key]
    if key == "phone":
        value = normalize_phone(message.text)
        if not value:
            await message.answer("⚠️ شماره‌ی همراه نامعتبر است؛ نمونه: <b>09121234567</b>")
            return
    elif key == "capacity":
        try:
            value = number(message.text, MAX_KW)
        except ValueError:
            await message.answer("مقدار نامعتبر است؛ یک عدد بر حسب کیلووات وارد کنید.")
            return
    else:
        value = clean(message.text)
        if len(value) < 2:
            await message.answer("مقدار نامعتبر است؛ دوباره وارد کنید.")
            return

    u, row = _owned_membership(message.from_user.id, d["mid"])
    if not row:
        await state.clear()
        await message.answer("پروفایل یافت نشد.")
        return
    conn = connect()
    old = conn.execute(f"SELECT {col} AS v FROM organizations WHERE id=?", (row["org_id"],)).fetchone()["v"]
    conn.execute(f"UPDATE organizations SET {col}=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                 (value, row["org_id"]))
    log_change(conn, "organization", row["org_id"], "update", label, old, value, u["id"])
    conn.commit()
    conn.close()
    await state.clear()

    _, fresh = _owned_membership(message.from_user.id, d["mid"])
    await message.answer("✅ اطلاعات به‌روزرسانی شد.\n\n" + profile_card(fresh), reply_markup=menu())
    await after_change(card(
        "✏️ ویرایش پروفایل",
        field("نام شرکت", fresh["name"]), field("مورد", label),
        field("مقدار قبلی", old), field("مقدار جدید", value),
        field("زمان", now_jalali())))


@dp.callback_query(F.data.startswith("pdel:"))
async def profile_delete_confirm(cb: CallbackQuery):
    mid = cb.data.split(":")[1]
    _, row = _owned_membership(cb.from_user.id, mid)
    if not row:
        await cb.answer("پروفایل یافت نشد.", show_alert=True)
        return
    await cb.message.answer(
        card("🗑 حذف پروفایل", field("نام شرکت", row["name"]),
             note="سفارش‌های این پروفایل هم غیرفعال می‌شوند. سوابق در گزارش ادمین محفوظ می‌ماند."),
        reply_markup=inline([[InlineKeyboardButton(text="✅ بله، حذف کن", callback_data=f"pdelok:{mid}"),
                              InlineKeyboardButton(text="انصراف", callback_data="cancel")]]))
    await cb.answer()


@dp.callback_query(F.data == "cancel")
async def cancel_cb(cb: CallbackQuery):
    await cb.message.answer("انصراف داده شد.", reply_markup=menu())
    await cb.answer()


@dp.callback_query(F.data.startswith("pdelok:"))
async def profile_delete(cb: CallbackQuery):
    mid = cb.data.split(":")[1]
    u, row = _owned_membership(cb.from_user.id, mid)
    if not row:
        await cb.answer("پروفایل یافت نشد.", show_alert=True)
        return
    conn = connect()
    conn.execute("UPDATE memberships SET deleted_at=CURRENT_TIMESTAMP WHERE id=?", (row["membership_id"],))
    conn.execute("UPDATE organizations SET deleted_at=CURRENT_TIMESTAMP WHERE id=?", (row["org_id"],))
    for t in ("offers", "requests"):
        for r in conn.execute(f"SELECT id FROM {t} WHERE membership_id=? AND deleted_at IS NULL",
                              (row["membership_id"],)).fetchall():
            log_change(conn, "offer" if t == "offers" else "request", r["id"], "delete",
                       "حذف به‌همراه پروفایل", actor=u["id"])
        conn.execute(f"UPDATE {t} SET deleted_at=CURRENT_TIMESTAMP, status='deleted' "
                     "WHERE membership_id=? AND deleted_at IS NULL", (row["membership_id"],))
    log_change(conn, "organization", row["org_id"], "delete", actor=u["id"])
    conn.commit()
    conn.close()
    remaining = memberships_of(u["id"])
    set_active_membership(u["id"], remaining[0]["membership_id"] if remaining else None)
    await cb.message.answer(f"🗑 پروفایل «{esc(row['name'])}» حذف شد.", reply_markup=menu())
    await after_change(card("🗑 حذف پروفایل توسط کاربر",
                            field("نام شرکت", row["name"]),
                            field("نقش", ROLE_LABELS.get(row["role"], row["role"])),
                            field("زمان", now_jalali()),
                            note="رکورد در گزارش‌ها با ردپای تغییرات باقی است."))
    await cb.answer()


# ---------- سوییچ پروفایل ----------

@dp.message(F.text == BTN_SWITCH)
async def switch(message: Message):
    u = get_user(message.from_user.id)
    rows = memberships_of(u["id"]) if u else []
    if not rows:
        await message.answer("ابتدا /start را بزنید.")
        return
    await message.answer("پروفایل موردنظر را انتخاب کنید:", reply_markup=profiles_kb(rows, "sw"))


@dp.callback_query(F.data.startswith("sw:"))
async def do_switch(cb: CallbackQuery):
    u, row = _owned_membership(cb.from_user.id, cb.data.split(":")[1])
    if not row:
        await cb.answer("پروفایل یافت نشد.", show_alert=True)
        return
    set_active_membership(u["id"], row["membership_id"])
    await cb.message.answer(
        f"✅ اکنون به‌عنوان {b(row['name'])} — {esc(ROLE_LABELS.get(row['role'], row['role']))} فعالید.",
        reply_markup=menu())
    await cb.answer()


# ---------- ثبت عرضه/تقاضا ----------

FLOWS = {"offer": ("عرضه", SUPPLY_ROLES, "کف قیمت"), "request": ("تقاضا", DEMAND_ROLES, "سقف قیمت")}


async def begin_trade(flow, message: Message, state: FSMContext, membership):
    await state.set_state(TradeForm.period_type)
    await state.update_data(flow=flow, membership_id=membership["membership_id"],
                            org_id=membership["org_id"], org_name=membership["name"])
    await message.answer(
        f"ثبت <b>{esc(FLOWS[flow][0])}</b> برای «{esc(membership['name'])}»\n"
        "نوع بازه‌ی تحویل را انتخاب کنید:", reply_markup=period_type_kb(f"pt:{flow}"))


async def start_trade(flow, message: Message, state: FSMContext):
    u = get_user(message.from_user.id)
    if not u:
        await message.answer("ابتدا /start را بزنید.")
        return
    title, roles, _ = FLOWS[flow]
    rows = memberships_of(u["id"], roles=roles)
    if not rows:
        await message.answer(f"هیچ پروفایلی با نقش مجاز برای ثبت {esc(title)} ندارید.\n"
                             "با /start می‌توانید پروفایل جدید اضافه کنید.")
        return
    act = active_membership(u["id"])
    if act and act["role"] in roles:
        await begin_trade(flow, message, state, act)
    elif len(rows) == 1:
        await begin_trade(flow, message, state, rows[0])
    else:
        await message.answer(f"با کدام پروفایل {esc(title)} را ثبت می‌کنید؟",
                             reply_markup=profiles_kb(rows, "pk", flow))


@dp.message(F.text == BTN_OFFER)
async def offer_start(message: Message, state: FSMContext):
    await start_trade("offer", message, state)


@dp.message(F.text == BTN_REQUEST)
async def request_start(message: Message, state: FSMContext):
    await start_trade("request", message, state)


@dp.callback_query(F.data.startswith("pk:"))
async def pick_profile(cb: CallbackQuery, state: FSMContext):
    _, mid, flow = cb.data.split(":")
    if flow not in FLOWS:
        await cb.answer()
        return
    u, row = _owned_membership(cb.from_user.id, mid, roles=FLOWS[flow][1])
    if not row:
        await cb.answer("پروفایل یافت نشد.", show_alert=True)
        return
    set_active_membership(u["id"], row["membership_id"])
    await begin_trade(flow, cb.message, state, row)
    await cb.answer()


@dp.callback_query(TradeForm.period_type, F.data.startswith("pt:"))
async def choose_period_type(cb: CallbackQuery, state: FSMContext):
    _, flow, ptype = cb.data.split(":")
    options = await _period_options(cb, state, ptype)
    if options is None:
        return
    await state.set_state(TradeForm.period)
    await cb.message.answer("دوره‌ی تحویل را انتخاب کنید:", reply_markup=periods_kb(f"pd:{flow}", options))
    await cb.answer()


async def _period_options(cb, state, ptype):
    """دوره‌های معتبر را می‌سازد و در state ذخیره می‌کند؛ None یعنی خطا اعلام شد."""
    if ptype not in (cal.WEEKLY, cal.MONTHLY):
        await cb.answer("نوع بازه نامعتبر است.", show_alert=True)
        return None
    options = cal.available_periods(ptype, calendar_rules())
    if not options:
        await cb.message.answer("در حال حاضر دوره‌ی قابل ثبتی وجود ندارد.")
        await cb.answer()
        return None
    await state.update_data(period_type=ptype, options=[(c, l) for c, l, _ in options])
    return options


@dp.callback_query(TradeForm.period, F.data.startswith("pd:"))
async def choose_period(cb: CallbackQuery, state: FSMContext):
    _, flow, idx = cb.data.split(":")
    d = await state.get_data()
    options = d.get("options") or []
    if not idx.isdigit() or int(idx) >= len(options):
        await cb.answer("این گزینه دیگر معتبر نیست؛ دوباره تلاش کنید.", show_alert=True)
        return
    code, label = options[int(idx)]
    await state.update_data(period=code, period_label=label)
    await state.set_state(TradeForm.volume)
    what = "عرضه" if flow == "offer" else "موردنیاز"
    await cb.message.answer(f"دوره‌ی انتخابی: {b(label)}\n"
                            f"⚡ حجم {esc(what)} را بر حسب <b>کیلووات (kW)</b> وارد کنید؛ نمونه: 5000")
    await cb.answer()


@dp.message(TradeForm.volume)
async def trade_volume(message: Message, state: FSMContext):
    try:
        v = number(message.text, MAX_KW)
    except ValueError:
        await message.answer("حجم نامعتبر است؛ عدد بر حسب کیلووات وارد کنید.")
        return
    d = await state.update_data(volume=v)
    await state.set_state(TradeForm.price)
    label = FLOWS[d["flow"]][2]
    await message.answer(f"💰 <b>{esc(label)}</b> را بر حسب <b>ریال</b> به ازای هر کیلووات‌ساعت "
                         "وارد کنید؛ نمونه: 80000")


@dp.message(TradeForm.price)
async def trade_price(message: Message, state: FSMContext):
    try:
        p = number(message.text, MAX_RIAL)
    except ValueError:
        await message.answer("قیمت نامعتبر است؛ عدد بر حسب ریال وارد کنید.")
        return
    d = await state.get_data()
    await state.clear()
    await save_trade(message, d, p)


async def save_trade(message, d, price):
    """ثبت عرضه/تقاضا. هیچ اطلاعاتی از سایر کاربران محاسبه یا نمایش داده نمی‌شود."""
    offer = d["flow"] == "offer"
    table, price_col = ("offers", "min_price") if offer else ("requests", "max_price")
    title, _, price_label = FLOWS[d["flow"]]
    user = get_user(message.from_user.id)
    conn = connect()
    seq = next_seq(table, d["membership_id"], conn)
    row_id = conn.execute(
        f"INSERT INTO {table}(user_id,org_id,membership_id,seq,delivery_period,period_type,"
        f"volume_kw,{price_col}) VALUES(?,?,?,?,?,?,?,?)",
        (user["id"], d["org_id"], d["membership_id"], seq, d["period"], d["period_type"],
         d["volume"], price)).lastrowid
    org = conn.execute("SELECT * FROM organizations WHERE id=?", (d["org_id"],)).fetchone()
    log_change(conn, "offer" if offer else "request", row_id, "create", actor=user["id"])
    conn.commit()
    conn.close()

    await message.answer(card(
        f"✅ {title} شما ثبت شد",
        field("شماره سفارش", fa(seq)),
        field("شرکت", org["name"]),
        field("دوره تحویل", d["period_label"]),
        field("حجم", kw(d["volume"])),
        field(price_label, rial(price)),
        note="می‌توانید از «سفارش‌های من» آن را ویرایش یا حذف کنید."), reply_markup=menu())

    await after_change(card(
        f"📥 اطلاعات {title}",
        field("نام شرکت", org["name"]),
        field("نام شخص", org["contact_person"]),
        phone_field(org["phone"]),
        field("تاریخ", d["period_label"]),
        field("حجم", kw(d["volume"])),
        field(price_label, rial(price)),
        field("نقش", ROLE_LABELS.get(org["role"], org["role"])),
        field("شماره سفارش", fa(seq)),
        field("زمان ثبت", now_jalali())))


# ---------- سفارش‌های من: نمایش، ویرایش، حذف ----------

def order_line(kind, r):
    _t, _c, title, price_label, _f = ORDER_KINDS[kind]
    return pipe(f"{title} #{fa(r['seq'] or 0)}",
                cal.period_label(r["delivery_period"], r["period_type"]),
                kw(r["volume_kw"]), f"{price_label}: {rial(r['price'])}")


def order_kb(kind, row_id):
    return inline([
        [InlineKeyboardButton(text="✏️ حجم", callback_data=f"oedit:{kind}:{row_id}:volume"),
         InlineKeyboardButton(text="✏️ قیمت", callback_data=f"oedit:{kind}:{row_id}:price"),
         InlineKeyboardButton(text="✏️ دوره", callback_data=f"oedit:{kind}:{row_id}:period")],
        [InlineKeyboardButton(text="🗑 حذف سفارش", callback_data=f"odel:{kind}:{row_id}")]])


@dp.message(F.text == BTN_ORDERS)
async def my_orders(message: Message):
    """فقط سفارش‌های خودِ کاربر؛ شماره‌ها مستقل برای هر پروفایل."""
    u = get_user(message.from_user.id)
    if not u:
        await message.answer("ابتدا /start را بزنید.")
        return
    conn = connect()
    found = False
    for m in memberships_of(u["id"], conn):
        header = False
        for kind, (table, col, title, _pl, _f) in ORDER_KINDS.items():
            rows = conn.execute(
                f"SELECT id,seq,delivery_period,period_type,volume_kw,{col} AS price FROM {table} "
                "WHERE membership_id=? AND user_id=? AND deleted_at IS NULL ORDER BY seq DESC LIMIT 10",
                (m["membership_id"], u["id"])).fetchall()
            for r in rows:
                if not header:
                    await message.answer(f"🏢 {b(m['name'])} — "
                                         f"{esc(ROLE_LABELS.get(m['role'], m['role']))}")
                    header = found = True
                await message.answer(order_line(kind, r), reply_markup=order_kb(kind, r["id"]))
    conn.close()
    if not found:
        await message.answer("هنوز سفارشی ثبت نکرده‌اید.", reply_markup=menu())


def _owned_order(tg_id, kind, row_id, conn):
    """سفارش را فقط در صورت تعلق به همین کاربر برمی‌گرداند (جلوگیری از IDOR)."""
    if kind not in ORDER_KINDS:
        return None, None
    u = get_user(tg_id, conn)
    if not u:
        return None, None
    table = ORDER_KINDS[kind][0]
    row = conn.execute(f"SELECT * FROM {table} WHERE id=? AND user_id=? AND deleted_at IS NULL",
                       (row_id, u["id"])).fetchone()
    return u, row


@dp.callback_query(F.data.startswith("oedit:"))
async def order_edit_start(cb: CallbackQuery, state: FSMContext):
    _, kind, row_id, what = cb.data.split(":")
    conn = connect()
    u, row = _owned_order(cb.from_user.id, kind, row_id, conn)
    conn.close()
    if not row or what not in ("volume", "price", "period"):
        await cb.answer("سفارش یافت نشد.", show_alert=True)
        return
    await state.update_data(kind=kind, row_id=int(row_id), what=what)
    if what == "period":
        await state.set_state(EditOrder.period)
        await cb.message.answer("نوع بازه‌ی جدید را انتخاب کنید:",
                                reply_markup=period_type_kb(f"opt:{kind}:{row_id}"))
        await cb.answer()
        return
    await state.set_state(EditOrder.value)
    prompt = ("⚡ حجم جدید را بر حسب <b>کیلووات</b> وارد کنید:" if what == "volume"
              else "💰 قیمت جدید را بر حسب <b>ریال</b> وارد کنید:")
    await cb.message.answer(prompt)
    await cb.answer()


@dp.callback_query(EditOrder.period, F.data.startswith("opt:"))
async def order_edit_period_type(cb: CallbackQuery, state: FSMContext):
    _, kind, row_id, ptype = cb.data.split(":")
    options = await _period_options(cb, state, ptype)
    if options is None:
        return
    await cb.message.answer("دوره‌ی تحویل جدید را انتخاب کنید:",
                            reply_markup=periods_kb(f"opd:{kind}:{row_id}", options))
    await cb.answer()


@dp.callback_query(EditOrder.period, F.data.startswith("opd:"))
async def order_edit_period_save(cb: CallbackQuery, state: FSMContext):
    _, kind, row_id, idx = cb.data.split(":")
    d = await state.get_data()
    options = d.get("options") or []
    if not idx.isdigit() or int(idx) >= len(options):
        await cb.answer("این گزینه دیگر معتبر نیست.", show_alert=True)
        return
    code, label = options[int(idx)]
    await _apply_order_update(cb.message, cb.from_user, state, kind, int(row_id),
                              "period", (code, d["period_type"], label))
    await cb.answer()


@dp.message(EditOrder.value)
async def order_edit_save(message: Message, state: FSMContext):
    d = await state.get_data()
    what = d["what"]
    try:
        value = number(message.text, MAX_KW if what == "volume" else MAX_RIAL)
    except ValueError:
        await message.answer("مقدار نامعتبر است؛ دوباره وارد کنید.")
        return
    await _apply_order_update(message, message.from_user, state, d["kind"], d["row_id"], what, value)


async def _apply_order_update(message, from_user, state, kind, row_id, what, value):
    table, price_col, title, price_label, _f = ORDER_KINDS[kind]
    conn = connect()
    u, row = _owned_order(from_user.id, kind, row_id, conn)
    if not row:
        conn.close()
        await state.clear()
        await message.answer("سفارش یافت نشد.")
        return
    org = conn.execute("SELECT * FROM organizations WHERE id=?", (row["org_id"],)).fetchone()

    if what == "period":
        code, ptype, label = value
        old = cal.period_label(row["delivery_period"], row["period_type"])
        conn.execute(f"UPDATE {table} SET delivery_period=?,period_type=?,"
                     "updated_at=CURRENT_TIMESTAMP WHERE id=?", (code, ptype, row_id))
        new_show, fld = label, "دوره تحویل"
    else:
        col = "volume_kw" if what == "volume" else price_col
        fld = "حجم" if what == "volume" else price_label
        old_raw = row[col]
        old = kw(old_raw) if what == "volume" else rial(old_raw)
        conn.execute(f"UPDATE {table} SET {col}=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                     (value, row_id))
        new_show = kw(value) if what == "volume" else rial(value)

    log_change(conn, ORDER_KINDS[kind][4], row_id, "update", fld, old, new_show, u["id"])
    conn.commit()
    fresh = conn.execute(f"SELECT id,seq,delivery_period,period_type,volume_kw,{price_col} AS price "
                         f"FROM {table} WHERE id=?", (row_id,)).fetchone()
    conn.close()
    await state.clear()

    await message.answer("✅ سفارش به‌روزرسانی شد.\n" + order_line(kind, fresh), reply_markup=menu())
    await after_change(card(
        f"✏️ ویرایش {title}",
        field("نام شرکت", org["name"]), field("نام شخص", org["contact_person"]),
        phone_field(org["phone"]), field("شماره سفارش", fa(row["seq"] or 0)),
        field("مورد", fld), field("مقدار قبلی", old), field("مقدار جدید", new_show),
        field("زمان", now_jalali())))


@dp.callback_query(F.data.startswith("odel:"))
async def order_delete_confirm(cb: CallbackQuery):
    _, kind, row_id = cb.data.split(":")
    conn = connect()
    u, row = _owned_order(cb.from_user.id, kind, row_id, conn)
    conn.close()
    if not row:
        await cb.answer("سفارش یافت نشد.", show_alert=True)
        return
    await cb.message.answer(
        card(f"🗑 حذف {ORDER_KINDS[kind][2]} #{fa(row['seq'] or 0)}",
             field("دوره تحویل", cal.period_label(row["delivery_period"], row["period_type"])),
             note="سوابق در گزارش ادمین محفوظ می‌ماند."),
        reply_markup=inline([[InlineKeyboardButton(text="✅ بله، حذف کن",
                                                   callback_data=f"odelok:{kind}:{row_id}"),
                              InlineKeyboardButton(text="انصراف", callback_data="cancel")]]))
    await cb.answer()


@dp.callback_query(F.data.startswith("odelok:"))
async def order_delete(cb: CallbackQuery):
    _, kind, row_id = cb.data.split(":")
    table, price_col, title, price_label, entity = ORDER_KINDS[kind]
    conn = connect()
    u, row = _owned_order(cb.from_user.id, kind, row_id, conn)
    if not row:
        conn.close()
        await cb.answer("سفارش یافت نشد.", show_alert=True)
        return
    org = conn.execute("SELECT * FROM organizations WHERE id=?", (row["org_id"],)).fetchone()
    conn.execute(f"UPDATE {table} SET deleted_at=CURRENT_TIMESTAMP, status='deleted' WHERE id=?",
                 (row_id,))
    log_change(conn, entity, row_id, "delete", actor=u["id"])
    conn.commit()
    conn.close()
    await cb.message.answer(f"🗑 {esc(title)} #{fa(row['seq'] or 0)} حذف شد.", reply_markup=menu())
    await after_change(card(
        f"🗑 حذف {title}",
        field("نام شرکت", org["name"]), field("نام شخص", org["contact_person"]),
        phone_field(org["phone"]), field("شماره سفارش", fa(row["seq"] or 0)),
        field("دوره تحویل", cal.period_label(row["delivery_period"], row["period_type"])),
        field("حجم", kw(row["volume_kw"])), field(price_label, rial(row[price_col])),
        field("زمان", now_jalali())))
    await cb.answer()


# ---------- فضای اختصاصی مدیریت ----------
# اگر ADMIN_BOT_TOKEN تنظیم شده باشد، پنل مدیریت در یک ربات جداگانه باز می‌شود و
# هیچ‌گاه با چت کاربران قاطی نمی‌شود. در نبود آن، همان پنل داخل ربات اصلی در
# «حالت مدیریت» با کیبورد اختصاصی خودش باز می‌شود.
admin_bot = (Bot(settings.admin_bot_token, default=DefaultBotProperties(parse_mode="HTML"))
             if settings.admin_bot_token else bot)
admin_dp = Dispatcher()
SEPARATE_ADMIN_BOT = admin_bot is not bot

BTN_A_REPORT, BTN_A_SHEET = "📊 گزارش اکسل", "📄 گوگل‌شیت"
BTN_A_REMIND, BTN_A_ABOUT = "🔔 تنظیم یادآوری‌ها", "ℹ️ متن «درباره ما»"
BTN_A_STATS, BTN_A_ORDERS = "📈 آمار", "🗂 آخرین سفارش‌ها"
BTN_A_EXIT = "🚪 خروج از پنل"
ADMIN_MODE_KEY = "adminmode:"


def admin_menu():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text=BTN_A_REPORT), KeyboardButton(text=BTN_A_SHEET)],
        [KeyboardButton(text=BTN_A_ORDERS), KeyboardButton(text=BTN_A_STATS)],
        [KeyboardButton(text=BTN_A_REMIND), KeyboardButton(text=BTN_A_ABOUT)],
    ] + ([] if SEPARATE_ADMIN_BOT else [[KeyboardButton(text=BTN_A_EXIT)]]), resize_keyboard=True)


def in_admin_mode(user_id):
    return SEPARATE_ADMIN_BOT or get_setting(f"{ADMIN_MODE_KEY}{user_id}") == "1"


def set_admin_mode(user_id, on):
    set_setting(f"{ADMIN_MODE_KEY}{user_id}", "1" if on else "0")


def admin_only(handler):
    """اجازه‌ی دسترسی فقط برای ادمین‌ها.

    نکته‌ی مهم: aiogram امضای هندلر را بازرسی می‌کند و هر وابستگی‌ای که در امضا باشد
    (dispatcher, bot, event_update, …) را تزریق می‌کند. پس باید هم امضای اصلی را با
    functools.wraps حفظ کنیم و هم آرگومان‌های اضافی را قبل از فراخوانی فیلتر کنیم؛
    وگرنه خطای «unexpected keyword argument 'dispatcher'» رخ می‌دهد.
    """
    accepted = set(inspect.signature(handler).parameters)

    @functools.wraps(handler)
    async def wrapper(message: Message, *a, **kw_):
        if not is_admin(message.from_user):
            await message.answer("این بخش فقط برای مدیران است.")
            return
        return await handler(message, *a, **{k: v for k, v in kw_.items() if k in accepted})
    return wrapper


def reminders_kb():
    c, _ = rem.describe()
    return inline([
        [InlineKeyboardButton(text=("🔔 یادآوری روشن است — خاموش کن" if c["enabled"]
                                    else "🔕 یادآوری خاموش است — روشن کن"), callback_data="ar:toggle")],
        [InlineKeyboardButton(text="⏰ ساعت‌های ارسال", callback_data="ar:times"),
         InlineKeyboardButton(text="✍️ متن پیام", callback_data="ar:text")],
        [InlineKeyboardButton(text="👥 مخاطبان", callback_data="ar:roles")],
        [InlineKeyboardButton(text="🚀 ارسال آزمایشی", callback_data="ar:test")]])


def _sheet_ready():
    from . import gsheet
    return gsheet.is_configured()


def admin_summary():
    c, who = rem.describe()
    return card(
        "🛠 پنل مدیریت",
        field("سامانه", BOT_NAME),
        field("یادآوری روزانه", "روشن ✅" if c["enabled"] else "خاموش ⛔️"),
        field("ساعت‌های ارسال", "، ".join(fa(t) for t in c["times"]) or "—"),
        field("مخاطبان یادآوری", who or "—"),
        field("گوگل‌شیت", "متصل ✅" if _sheet_ready() else "تنظیم نشده ⛔️"),
        note="از دکمه‌های پایین صفحه استفاده کنید.")


async def admin_panel(message: Message):
    if not is_admin(message.from_user):
        await message.answer("این بخش فقط برای مدیران است.")
        return
    if not SEPARATE_ADMIN_BOT:
        set_admin_mode(message.from_user.id, True)
    await message.answer(admin_summary(), reply_markup=admin_menu())


async def admin_exit(message: Message):
    if not is_admin(message.from_user):
        return
    set_admin_mode(message.from_user.id, False)
    await message.answer("از پنل مدیریت خارج شدید.", reply_markup=menu())


@admin_only
async def stats(message: Message):
    conn = connect()
    n = {t: conn.execute(f"SELECT COUNT(*) c FROM {t}").fetchone()["c"]
         for t in ("users", "organizations", "offers", "requests")}
    active = conn.execute("SELECT COUNT(*) c FROM memberships WHERE deleted_at IS NULL").fetchone()["c"]
    by_role = conn.execute("SELECT role, COUNT(*) c FROM memberships WHERE deleted_at IS NULL "
                           "GROUP BY role").fetchall()
    conn.close()
    await message.answer(card(
        "📈 آمار کلی",
        field("کاربران", fa(n["users"])),
        field("پروفایل‌های فعال", fa(active)),
        field("عرضه‌ها", fa(n["offers"])),
        field("تقاضاها", fa(n["requests"])),
        *[field(ROLE_LABELS.get(r["role"], r["role"]), fa(r["c"])) for r in by_role]))


@admin_only
async def latest_orders(message: Message):
    """آخرین سفارش‌های ثبت‌شده، همراه اطلاعات تماس و شماره‌ی قابل تماس."""
    conn = connect()
    rows = []
    for table, price_col, title, price_label in (("offers", "min_price", "عرضه", "کف قیمت"),
                                                 ("requests", "max_price", "تقاضا", "سقف قیمت")):
        rows += [(title, price_label, r) for r in conn.execute(
            f"SELECT t.*, t.{price_col} AS price, g.name AS org, g.contact_person, g.phone "
            f"FROM {table} t LEFT JOIN organizations g ON g.id=t.org_id "
            "WHERE t.deleted_at IS NULL ORDER BY t.id DESC LIMIT 5").fetchall()]
    conn.close()
    if not rows:
        await message.answer("هنوز سفارشی ثبت نشده است.", reply_markup=admin_menu())
        return
    for title, price_label, r in rows:
        await message.answer(card(
            f"🗂 {title} #{fa(r['seq'] or 0)}",
            field("نام شرکت", r["org"]), field("نام شخص", r["contact_person"]),
            phone_field(r["phone"]),
            field("تاریخ", cal.period_label(r["delivery_period"], r["period_type"])),
            field("حجم", kw(r["volume_kw"])), field(price_label, rial(r["price"]))))


@admin_only
async def report(message: Message):
    from .export import build_workbook
    await message.answer_document(
        BufferedInputFile(build_workbook(), filename="powermatch_report.xlsx"),
        caption="📊 گزارش کامل " + BOT_NAME)


@admin_only
async def sheet(message: Message):
    from . import gsheet
    if not gsheet.is_configured():
        await message.answer(gsheet.setup_help())
        return
    try:
        url, rows = await asyncio.to_thread(gsheet.sync)
        await message.answer(card("✅ گوگل‌شیت به‌روزرسانی شد",
                                  field("تعداد سطر", fa(rows)), field("لینک", url)))
    except Exception as e:
        await message.answer(f"⛔️ همگام‌سازی ناموفق بود:\n<code>{esc(type(e).__name__)}: {esc(e)}</code>")


@admin_only
async def reminders_panel(message: Message):
    c, who = rem.describe()
    await message.answer(card(
        "🔔 یادآوری روزانه",
        field("وضعیت", "روشن ✅" if c["enabled"] else "خاموش ⛔️"),
        field("ساعت‌های ارسال", "، ".join(fa(t) for t in c["times"]) or "—"),
        field("مخاطبان", who or "—"),
        note="یادآوری فقط برای کسانی می‌رود که نزدیک‌ترین دوره را ثبت نکرده‌اند."),
        reply_markup=reminders_kb())


@admin_only
async def set_about_start(message: Message, state: FSMContext):
    await state.set_state(AdminForm.about)
    await message.answer("متن جدید «درباره ما» را ارسال کنید.\n"
                         "برای بازگرداندن متن پیش‌فرض عبارت «پیش‌فرض» را بفرستید.\n\nمتن فعلی:")
    await message.answer(about_text())


async def set_about_save(message: Message, state: FSMContext):
    if not is_admin(message.from_user):
        await state.clear()
        return
    text = (message.text or "").strip()[:4000]
    if not text:
        await message.answer("متن خالی است؛ دوباره ارسال کنید.")
        return
    set_setting(ABOUT_KEY, DEFAULT_ABOUT if text == "پیش‌فرض" else text)
    await state.clear()
    await message.answer("✅ متن «درباره ما» به‌روزرسانی شد:", reply_markup=admin_menu())
    await message.answer(about_text())


def roles_kb_admin():
    c = rem.get_config()
    rows = [[InlineKeyboardButton(
        text=("✅ " if r in c["roles"] else "▫️ ") + ROLE_LABELS[r], callback_data=f"ar:role:{r}")]
        for r in rem.ALL_ROLES]
    rows.append([InlineKeyboardButton(text="👥 همه‌ی نقش‌ها", callback_data="ar:role:all")])
    return inline(rows)


async def admin_reminders(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user):
        await cb.answer("فقط برای مدیران.", show_alert=True)
        return
    parts = cb.data.split(":")
    what = parts[1]
    if what == "toggle":
        c = rem.get_config()
        set_setting(rem.K_ENABLED, "0" if c["enabled"] else "1")
        await cb.message.answer(admin_summary(), reply_markup=reminders_kb())
    elif what == "times":
        await state.set_state(AdminForm.rem_times)
        c = rem.get_config()
        await cb.message.answer(
            "⏰ ساعت‌های ارسال یادآوری را با کاما وارد کنید (۲۴ساعته، به‌وقت تهران).\n"
            f"مقدار فعلی: <b>{esc(', '.join(c['times']))}</b>\nنمونه: <b>09:30,11:00</b>")
    elif what == "text":
        await state.set_state(AdminForm.rem_text)
        await cb.message.answer(
            "✍️ متن یادآوری را بفرستید.\nمتغیرهای مجاز: "
            "<code>{name}</code> نام شرکت، <code>{role}</code> نقش، <code>{periods}</code> دوره‌های ناقص\n"
            "برای بازگشت به متن پیش‌فرض «پیش‌فرض» را بفرستید.\n\nمتن فعلی:")
        await cb.message.answer(rem.get_config()["text"])
    elif what == "roles":
        await cb.message.answer("مخاطبان یادآوری را انتخاب کنید:", reply_markup=roles_kb_admin())
    elif what == "role":
        c = rem.get_config()
        if parts[2] == "all":
            rem.set_roles(list(rem.ALL_ROLES))
        else:
            rem.set_roles(sorted(set(c["roles"]) ^ {parts[2]}))
        await cb.message.answer("مخاطبان به‌روزرسانی شد:", reply_markup=roles_kb_admin())
    elif what == "test":
        sent = await rem.send_due(bot, force=True)
        await cb.message.answer(f"🚀 ارسال آزمایشی انجام شد؛ {fa(sent)} پیام ارسال شد.")
    await cb.answer()


async def save_rem_times(message: Message, state: FSMContext):
    if not is_admin(message.from_user):
        await state.clear()
        return
    try:
        rem.set_times(message.text)
    except ValueError:
        await message.answer("⚠️ قالب نامعتبر است؛ نمونه‌ی درست: <b>09:30,11:00</b>")
        return
    await state.clear()
    await message.answer(admin_summary(), reply_markup=admin_menu())


async def save_rem_text(message: Message, state: FSMContext):
    if not is_admin(message.from_user):
        await state.clear()
        return
    text = (message.text or "").strip()[:2000]
    if not text:
        await message.answer("متن خالی است؛ دوباره ارسال کنید.")
        return
    set_setting(rem.K_TEXT, rem.DEFAULT_TEXT if text == "پیش‌فرض" else text)
    await state.clear()
    await message.answer("✅ متن یادآوری ذخیره شد.", reply_markup=admin_menu())


def register_admin(d, with_start=False):
    """ثبت هندلرهای مدیریتی روی یک Dispatcher (هم ربات اصلی، هم ربات اختصاصی ادمین)."""
    if with_start:
        d.message.register(admin_panel, CommandStart())
    d.message.register(admin_panel, Command("admin"))
    d.message.register(report, Command("report"))
    d.message.register(sheet, Command("sheet"))
    d.message.register(stats, Command("stats"))
    d.message.register(set_about_start, Command("setabout"))
    d.message.register(admin_exit, F.text == BTN_A_EXIT)
    d.message.register(report, F.text == BTN_A_REPORT)
    d.message.register(sheet, F.text == BTN_A_SHEET)
    d.message.register(stats, F.text == BTN_A_STATS)
    d.message.register(latest_orders, F.text == BTN_A_ORDERS)
    d.message.register(reminders_panel, F.text == BTN_A_REMIND)
    d.message.register(set_about_start, F.text == BTN_A_ABOUT)
    d.message.register(set_about_save, AdminForm.about)
    d.message.register(save_rem_times, AdminForm.rem_times)
    d.message.register(save_rem_text, AdminForm.rem_text)
    d.callback_query.register(admin_reminders, F.data.startswith("ar:"))


for _obs in (admin_dp.message, admin_dp.callback_query):
    _obs.outer_middleware(ThrottleMiddleware())
    _obs.outer_middleware(AdminChatMiddleware())

register_admin(admin_dp, with_start=True)
register_admin(dp)


# ---------- اجرا ----------

async def set_branding():
    try:
        await bot.set_my_name(BOT_NAME)
        await bot.set_my_short_description(SHORT_DESCRIPTION)
        await bot.set_my_description(BOT_DESCRIPTION)
    except Exception:
        pass          # تلگرام تغییر نام را محدود می‌کند؛ شکستش نباید مانع اجرا شود
    if SEPARATE_ADMIN_BOT:
        try:
            await admin_bot.set_my_name(f"{BOT_NAME} — پنل مدیریت")
        except Exception:
            pass


async def run_bot():
    """حالت long polling — ساده‌ترین حالت و پیش‌فرض."""
    if not settings.bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN تنظیم نشده است.")
    await set_branding()
    asyncio.create_task(rem.scheduler(bot))
    if SEPARATE_ADMIN_BOT:
        await asyncio.gather(dp.start_polling(bot), admin_dp.start_polling(admin_bot))
        return
    await dp.start_polling(bot)


async def setup_webhooks():
    """حالت وب‌هوک — برای اجرا پشت nginx/سکوهای ابری. آدرس‌ها را در تلگرام ثبت می‌کند."""
    from .api import WEBHOOK_PATH, ADMIN_WEBHOOK_PATH
    if not settings.webhook_base or not settings.webhook_secret:
        raise RuntimeError("برای USE_WEBHOOK باید WEBHOOK_BASE_URL و WEBHOOK_SECRET تنظیم شوند.")
    await set_branding()
    await bot.set_webhook(settings.webhook_base + WEBHOOK_PATH,
                          secret_token=settings.webhook_secret, drop_pending_updates=False)
    if SEPARATE_ADMIN_BOT:
        await admin_bot.set_webhook(settings.webhook_base + ADMIN_WEBHOOK_PATH,
                                    secret_token=settings.webhook_secret, drop_pending_updates=False)
    asyncio.create_task(rem.scheduler(bot))
