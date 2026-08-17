"""تضمین می‌کند مهاجرت روی دیتابیس نسخه‌ی قدیمی هیچ داده‌ای را از دست نمی‌دهد و idempotent است."""
import sqlite3

import pytest

from app import db as D

LEGACY = """
CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, telegram_id INTEGER UNIQUE NOT NULL,
    name TEXT, username TEXT, role TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE offers (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
    delivery_period TEXT NOT NULL, volume_mw REAL NOT NULL, min_price REAL NOT NULL,
    status TEXT DEFAULT 'active', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE requests (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
    delivery_period TEXT NOT NULL, volume_mw REAL NOT NULL, max_price REAL NOT NULL,
    status TEXT DEFAULT 'active', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE matches (id INTEGER PRIMARY KEY AUTOINCREMENT, request_id INTEGER NOT NULL,
    offer_id INTEGER NOT NULL, matched_volume_mw REAL NOT NULL, indicative_price REAL NOT NULL,
    score REAL NOT NULL, status TEXT DEFAULT 'candidate', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
INSERT INTO users(telegram_id,name,username,role) VALUES(4242,'شرکت قدیمی','old','generator');
INSERT INTO offers(user_id,delivery_period,volume_mw,min_price) VALUES(1,'2026-W34',5,8000);
INSERT INTO offers(user_id,delivery_period,volume_mw,min_price) VALUES(1,'2026-W35',7,8200);
"""


@pytest.fixture
def legacy_db(tmp_path, monkeypatch):
    p = tmp_path / "legacy.db"
    conn = sqlite3.connect(p)
    conn.executescript(LEGACY)
    conn.commit()
    conn.close()
    monkeypatch.setattr(D.settings, "db_path", str(p))
    return p


def test_legacy_data_survives_and_is_linked(legacy_db):
    D.init_db()
    conn = D.connect()
    assert conn.execute("SELECT COUNT(*) c FROM offers").fetchone()["c"] == 2
    assert conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"] == 1
    orgs = conn.execute("SELECT * FROM organizations").fetchall()
    assert len(orgs) == 1 and orgs[0]["name"] == "شرکت قدیمی" and orgs[0]["role"] == "generator"
    u = conn.execute("SELECT * FROM users").fetchone()
    assert u["active_membership_id"] is not None
    assert all(o["org_id"] == orgs[0]["id"] for o in conn.execute("SELECT * FROM offers"))
    # کدهای قدیمی دست‌نخورده می‌مانند
    assert {o["delivery_period"] for o in conn.execute("SELECT * FROM offers")} == {"2026-W34", "2026-W35"}
    conn.close()


def test_units_are_converted_to_kw_and_rial_exactly_once(legacy_db):
    for _ in range(3):                       # اجرای مکرر نباید دوباره ضرب کند
        D.init_db()
    conn = D.connect()
    rows = conn.execute("SELECT volume_kw,min_price FROM offers ORDER BY id").fetchall()
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(offers)")}
    conn.close()
    assert "volume_mw" not in cols and "volume_kw" in cols
    assert [(r["volume_kw"], r["min_price"]) for r in rows] == [(5000, 80000), (7000, 82000)]


def test_seq_is_assigned_per_membership(legacy_db):
    D.init_db()
    conn = D.connect()
    assert [r["seq"] for r in conn.execute("SELECT seq FROM offers ORDER BY id")] == [1, 2]
    conn.close()


def test_init_db_is_idempotent(legacy_db):
    for _ in range(3):
        D.init_db()
    conn = D.connect()
    assert conn.execute("SELECT COUNT(*) c FROM organizations").fetchone()["c"] == 1
    assert conn.execute("SELECT COUNT(*) c FROM memberships").fetchone()["c"] == 1
    assert conn.execute("SELECT COUNT(*) c FROM offers").fetchone()["c"] == 2
    assert conn.execute("SELECT COUNT(*) c FROM market_calendar_rules").fetchone()["c"] == 1
    conn.close()


def test_calendar_rules_seeded_from_table_not_code(legacy_db):
    D.init_db()
    conn = D.connect()
    conn.execute("UPDATE market_calendar_rules SET future_periods_visible=3, weekly_cutoff_weekday=1 WHERE id=1")
    conn.commit()
    conn.close()
    r = D.calendar_rules()
    assert r.future_periods_visible == 3 and r.weekly_cutoff_weekday == 1

    from app.calendar_utils import available_periods
    assert len(available_periods("weekly", r)) == 3
