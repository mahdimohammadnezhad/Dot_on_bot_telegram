import sqlite3
from .config import settings

ROLE_LABELS = {"generator": "⚡️ نیروگاه", "buyer": "🏭 خریدار نهایی / صنعت",
               "retailer": "🏬 خرده‌فروش", "broker": "🤝 کارگزاری"}
SUPPLY_ROLES = ("generator", "retailer", "broker")   # می‌توانند عرضه ثبت کنند
DEMAND_ROLES = ("buyer", "retailer", "broker")       # می‌توانند تقاضا ثبت کنند

# سقف‌های اعتبارسنجی ورودی کاربر (جلوگیری از داده‌ی بی‌معنا و سرریز)
MAX_TEXT = 120
MAX_KW = 5_000_000
MAX_RIAL = 1_000_000_000

_turso_client = None


class _Row(dict):
    """معادل sqlite3.Row روی نتیجه‌ی libsql: هم row["x"] و هم dict(row) کار می‌کند."""


class _TursoCursor:
    """معادل سبک sqlite3.Cursor برای نتیجه‌ی یک اجرای libsql."""

    def __init__(self, result):
        self.lastrowid = result.last_insert_rowid
        self.rowcount = result.rows_affected
        self._rows = [_Row(zip(result.columns, r)) for r in result.rows]

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows

    def __iter__(self):
        return iter(self._rows)


class _TursoConn:
    """پوششی روی کلاینت libsql که رفتار sqlite3.Connection مورد استفاده‌ی این پروژه
    (execute/executescript/commit/close) را روی دیتابیس Turso شبیه‌سازی می‌کند؛ چون فایل
    SQLite محلی بین اجراهای runner در GitHub Actions ماندگار نیست.

    کلاینت HTTP (که به‌خاطر شکست هندشیک وب‌ساکت روی GitHub Actions انتخاب شده) از
    تراکنش چندمرحله‌ای پشتیبانی نمی‌کند؛ هر execute مستقل و خودش atomically commit
    می‌شود. commit/close برای این پروژه فقط no-op هستند (سازگار با الگوی sqlite3 قبلی)."""

    def __init__(self, client):
        self._client = client

    def execute(self, sql, params=()):
        return _TursoCursor(self._client.execute(sql, list(params)))

    def executescript(self, script):
        for stmt in script.split(";"):
            stmt = stmt.strip()
            if stmt:
                self._client.execute(stmt)

    def commit(self):
        pass

    def close(self):
        pass


def _turso_client_singleton():
    global _turso_client
    if _turso_client is None:
        import libsql_client
        # libsql:// یعنی اتصال روی وب‌ساکت (wss)؛ روی runner های GitHub Actions هندشیک آن
        # با خطای ۴۰۰ شکست می‌خورد، پس آدرس را به https تبدیل می‌کنیم (کلاینت HTTP ساده،
        # بدون اتصال دائمی، برای این کاربرد کاملاً معادل و پایدارتر است).
        url = settings.turso_database_url
        if url.startswith("libsql://"):
            url = "https://" + url[len("libsql://"):]
        _turso_client = libsql_client.create_client_sync(url=url, auth_token=settings.turso_auth_token)
    return _turso_client


def connect():
    if settings.turso_database_url:
        return _TursoConn(_turso_client_singleton())
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _cols(conn, table):
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def _add_col(conn, table, col, decl):
    """افزودن ستون به‌صورت idempotent — قبل از ALTER وجود ستون چک می‌شود."""
    if col not in _cols(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")


def _flag(conn, name):
    return conn.execute("SELECT 1 FROM schema_meta WHERE key=?", (name,)).fetchone() is not None


def _set_flag(conn, name):
    conn.execute("INSERT OR REPLACE INTO schema_meta(key,value) VALUES(?,CURRENT_TIMESTAMP)", (name,))


def _migrate_v1(conn):
    """مهاجرت داده‌های نسخه‌ی اول (users.role تنها) به مدل سازمان/عضویت.

    هیچ داده‌ای حذف یا بازنویسی نمی‌شود؛ فقط رکوردهای متناظر ساخته و لینک می‌شوند.
    یک‌بار اجرا می‌شود (schema_meta) و در اجراهای بعدی no-op است.
    """
    if _flag(conn, "migrate_v1"):
        return
    for u in conn.execute("SELECT id,name,role FROM users WHERE role IS NOT NULL").fetchall():
        if conn.execute("SELECT 1 FROM memberships WHERE user_id=?", (u["id"],)).fetchone():
            continue
        org = conn.execute("INSERT INTO organizations(name,role,contact_person) VALUES(?,?,?)",
                           (u["name"] or "سازمان بدون نام", u["role"], u["name"])).lastrowid
        mid = conn.execute("INSERT INTO memberships(user_id,org_id,role) VALUES(?,?,?)",
                           (u["id"], org, u["role"])).lastrowid
        conn.execute("UPDATE users SET active_membership_id=? WHERE id=? AND active_membership_id IS NULL",
                     (mid, u["id"]))
        for t in ("offers", "requests"):
            conn.execute(f"UPDATE {t} SET org_id=?, membership_id=? WHERE user_id=? AND org_id IS NULL",
                         (org, mid, u["id"]))
    _set_flag(conn, "migrate_v1")


def _migrate_v2_units(conn):
    """تبدیل واحدها: حجم MW→kW (×۱۰۰۰) و قیمت تومان→ریال (×۱۰) و تغییر نام ستون‌ها.

    شرطِ اجرا وجودِ نامِ قدیمی ستون است، پس ذاتاً idempotent است.
    """
    if "volume_mw" in _cols(conn, "offers"):
        conn.execute("UPDATE offers SET volume_mw=volume_mw*1000, min_price=min_price*10")
        conn.execute("ALTER TABLE offers RENAME COLUMN volume_mw TO volume_kw")
    if "volume_mw" in _cols(conn, "requests"):
        conn.execute("UPDATE requests SET volume_mw=volume_mw*1000, max_price=max_price*10")
        conn.execute("ALTER TABLE requests RENAME COLUMN volume_mw TO volume_kw")
    if "matched_volume_mw" in _cols(conn, "matches"):
        conn.execute("UPDATE matches SET matched_volume_mw=matched_volume_mw*1000, "
                     "indicative_price=indicative_price*10")
        conn.execute("ALTER TABLE matches RENAME COLUMN matched_volume_mw TO matched_volume_kw")


def _migrate_v3_seq(conn):
    """شماره‌ی سفارش، مستقل و پیوسته برای هر پروفایل کاربر (نه شمارنده‌ی سراسری)."""
    if _flag(conn, "migrate_v3"):
        return
    for t in ("offers", "requests"):
        counters = {}
        for r in conn.execute(f"SELECT id,membership_id FROM {t} ORDER BY id").fetchall():
            k = r["membership_id"]
            counters[k] = counters.get(k, 0) + 1
            conn.execute(f"UPDATE {t} SET seq=? WHERE id=?", (counters[k], r["id"]))
    _set_flag(conn, "migrate_v3")


def init_db():
    conn = connect()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id INTEGER UNIQUE NOT NULL,
        name TEXT,
        username TEXT,
        role TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS organizations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        role TEXT NOT NULL,
        legal_id TEXT,                 -- در UI پرسیده نمی‌شود؛ nullable برای استفاده‌ی ادمین
        contact_person TEXT,
        position TEXT,
        phone TEXT,
        capacity_kw REAL,              -- سقف مجاز عرضه/خرید (kW)
        activity TEXT,                 -- منسوخ: دیگر پرسیده نمی‌شود (داده‌ی قدیمی حفظ می‌شود)
        broker_code TEXT,              -- منسوخ: دیگر پرسیده نمی‌شود
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS memberships (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        org_id INTEGER NOT NULL,
        role TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, org_id)
    );
    CREATE TABLE IF NOT EXISTS offers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        delivery_period TEXT NOT NULL,
        volume_kw REAL NOT NULL,
        min_price REAL NOT NULL,       -- ریال به ازای هر کیلووات‌ساعت
        status TEXT DEFAULT 'active',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        delivery_period TEXT NOT NULL,
        volume_kw REAL NOT NULL,
        max_price REAL NOT NULL,       -- ریال به ازای هر کیلووات‌ساعت
        status TEXT DEFAULT 'active',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS matches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        request_id INTEGER NOT NULL,
        offer_id INTEGER NOT NULL,
        matched_volume_kw REAL NOT NULL,
        indicative_price REAL NOT NULL,
        score REAL NOT NULL,
        status TEXT DEFAULT 'candidate',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS market_calendar_rules (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        weekly_cutoff_weekday INTEGER NOT NULL DEFAULT 3,
        weekly_cutoff_hour INTEGER NOT NULL DEFAULT 18,
        weekly_cutoff_minute INTEGER NOT NULL DEFAULT 0,
        monthly_cutoff_weekday INTEGER NOT NULL DEFAULT 3,
        monthly_cutoff_hour INTEGER NOT NULL DEFAULT 18,
        monthly_cutoff_minute INTEGER NOT NULL DEFAULT 0,
        future_periods_visible INTEGER NOT NULL DEFAULT 6,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS holidays (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        jalali_date TEXT UNIQUE NOT NULL,   -- YYYYMMDD
        title TEXT
    );
    CREATE TABLE IF NOT EXISTS admin_chats (
        username TEXT PRIMARY KEY,          -- lowercase، بدون @
        chat_id INTEGER NOT NULL,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    -- ردپای همه‌ی تغییرات؛ هیچ داده‌ای واقعاً حذف نمی‌شود
    CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        entity TEXT NOT NULL,               -- organization | offer | request
        entity_id INTEGER NOT NULL,
        action TEXT NOT NULL,               -- create | update | delete
        field TEXT,
        old_value TEXT,
        new_value TEXT,
        actor_user_id INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        created_at_jalali TEXT
    );
    CREATE TABLE IF NOT EXISTS reminder_log (
        key TEXT PRIMARY KEY,               -- YYYY-MM-DD|HH:MM|user_id
        sent_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_log(entity, entity_id);
    CREATE INDEX IF NOT EXISTS idx_memberships_user ON memberships(user_id);
    CREATE INDEX IF NOT EXISTS idx_offers_period ON offers(delivery_period, status);
    """)
    _migrate_v2_units(conn)
    _add_col(conn, "users", "active_membership_id", "INTEGER")
    for t in ("offers", "requests"):
        _add_col(conn, t, "org_id", "INTEGER")
        _add_col(conn, t, "membership_id", "INTEGER")
        _add_col(conn, t, "period_type", "TEXT")
        _add_col(conn, t, "seq", "INTEGER")
    _add_col(conn, "organizations", "legal_id", "TEXT")
    for t in ("organizations", "memberships", "offers", "requests"):
        _add_col(conn, t, "deleted_at", "TEXT")      # حذف نرم: رکورد در گزارش‌ها می‌ماند
        _add_col(conn, t, "updated_at", "TEXT")
    conn.execute("INSERT OR IGNORE INTO market_calendar_rules(id) VALUES(1)")
    _migrate_v1(conn)
    _migrate_v3_seq(conn)
    conn.commit()
    conn.close()


# ---------- تنظیمات قابل ویرایش از داخل تلگرام ----------

def get_setting(key, default=None, conn=None):
    own = conn is None
    conn = conn or connect()
    row = conn.execute("SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
    if own:
        conn.close()
    return row["value"] if row and row["value"] is not None else default


def set_setting(key, value, conn=None):
    own = conn is None
    conn = conn or connect()
    conn.execute("INSERT INTO app_settings(key,value,updated_at) VALUES(?,?,CURRENT_TIMESTAMP) "
                 "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP",
                 (key, value))
    if own:
        conn.commit()
        conn.close()


# ---------- ادمین‌ها ----------

def remember_admin_chat(username, chat_id):
    """chat_id ادمینی که با یوزرنیم شناخته می‌شود را نگه می‌دارد تا نوتیف لحظه‌ای ممکن شود."""
    conn = connect()
    conn.execute("INSERT INTO admin_chats(username,chat_id,updated_at) VALUES(?,?,CURRENT_TIMESTAMP) "
                 "ON CONFLICT(username) DO UPDATE SET chat_id=excluded.chat_id, "
                 "updated_at=CURRENT_TIMESTAMP", (username.lstrip("@").lower(), chat_id))
    conn.commit()
    conn.close()


def admin_chat_ids():
    """ادمین‌های عددیِ .env به‌علاوه‌ی ادمین‌های یوزرنیمی که ربات را استارت کرده‌اند."""
    ids = list(settings.admin_chat_ids)
    if settings.admin_usernames:
        conn = connect()
        q = f"SELECT chat_id FROM admin_chats WHERE username IN ({','.join('?' * len(settings.admin_usernames))})"
        ids += [r["chat_id"] for r in conn.execute(q, settings.admin_usernames)]
        conn.close()
    return list(dict.fromkeys(ids))


# ---------- دسترسی‌های پرکاربرد ----------

def calendar_rules(conn=None):
    from .calendar_utils import CalendarRules
    own = conn is None
    conn = conn or connect()
    row = conn.execute("SELECT * FROM market_calendar_rules WHERE id=1").fetchone()
    if own:
        conn.close()
    return CalendarRules.from_row(row)


def holiday_set(conn=None):
    own = conn is None
    conn = conn or connect()
    s = {r["jalali_date"] for r in conn.execute("SELECT jalali_date FROM holidays")}
    if own:
        conn.close()
    return s


def get_user(tg_id, conn=None):
    own = conn is None
    conn = conn or connect()
    row = conn.execute("SELECT * FROM users WHERE telegram_id=?", (tg_id,)).fetchone()
    if own:
        conn.close()
    return row


def memberships_of(user_id, conn=None, roles=None):
    """عضویت‌های *فعال* کاربر همراه اطلاعات سازمان؛ در صورت نیاز فیلترشده بر اساس نقش."""
    own = conn is None
    conn = conn or connect()
    q = ("SELECT m.id AS membership_id, m.role, o.id AS org_id, o.name, o.capacity_kw, "
         "o.contact_person, o.position, o.phone "
         "FROM memberships m JOIN organizations o ON o.id=m.org_id "
         "WHERE m.user_id=? AND m.deleted_at IS NULL AND o.deleted_at IS NULL")
    args = [user_id]
    if roles:
        q += f" AND m.role IN ({','.join('?' * len(roles))})"
        args += list(roles)
    rows = conn.execute(q + " ORDER BY m.id", args).fetchall()
    if own:
        conn.close()
    return rows


def active_membership(user_id, conn=None):
    own = conn is None
    conn = conn or connect()
    row = conn.execute(
        "SELECT m.id AS membership_id, m.role, o.id AS org_id, o.name, o.capacity_kw, "
        "o.contact_person, o.position, o.phone "
        "FROM users u JOIN memberships m ON m.id=u.active_membership_id "
        "JOIN organizations o ON o.id=m.org_id WHERE u.id=? "
        "AND m.deleted_at IS NULL AND o.deleted_at IS NULL", (user_id,)).fetchone()
    if own:
        conn.close()
    return row


def set_active_membership(user_id, membership_id, conn=None):
    own = conn is None
    conn = conn or connect()
    conn.execute("UPDATE users SET active_membership_id=? WHERE id=?", (membership_id, user_id))
    if own:
        conn.commit()
        conn.close()


def now_jalali():
    """زمان جاری تهران به تقویم شمسی — برای ردپای تغییرات."""
    from datetime import datetime
    import jdatetime
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo(settings_tz()))
    except Exception:
        from datetime import timedelta, timezone
        now = datetime.now(timezone(timedelta(hours=3, minutes=30)))
    j = jdatetime.datetime.fromgregorian(datetime=now.replace(tzinfo=None))
    return j.strftime("%Y/%m/%d %H:%M")


def settings_tz():
    from .config import TZ
    return TZ


def log_change(conn, entity, entity_id, action, field=None, old=None, new=None, actor=None):
    """ثبت ردپای تغییر. هیچ داده‌ای بازنویسی نمی‌شود؛ تاریخچه در گزارش‌ها می‌ماند."""
    conn.execute(
        "INSERT INTO audit_log(entity,entity_id,action,field,old_value,new_value,actor_user_id,"
        "created_at_jalali) VALUES(?,?,?,?,?,?,?,?)",
        (entity, entity_id, action, field,
         None if old is None else str(old), None if new is None else str(new),
         actor, now_jalali()))


def audit_trail(conn, entity, entity_id):
    """خلاصه‌ی خوانای تاریخچه‌ی یک رکورد برای ستون گزارش اکسل."""
    rows = conn.execute(
        "SELECT action,field,old_value,new_value,created_at_jalali FROM audit_log "
        "WHERE entity=? AND entity_id=? ORDER BY id", (entity, entity_id)).fetchall()
    out = []
    for r in rows:
        when = r["created_at_jalali"] or ""
        if r["action"] == "create":
            out.append(f"[{when}] ایجاد")
        elif r["action"] == "delete":
            out.append(f"[{when}] حذف")
        else:
            out.append(f"[{when}] {r['field']}: «{r['old_value']}» ← «{r['new_value']}»")
    return " ؛ ".join(out)


def next_seq(table, membership_id, conn):
    row = conn.execute(f"SELECT COALESCE(MAX(seq),0)+1 AS n FROM {table} WHERE membership_id=?",
                       (membership_id,)).fetchone()
    return row["n"]
