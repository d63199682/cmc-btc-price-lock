from __future__ import annotations

import csv
import io
import json
import os
import random
import re
import secrets
import smtplib
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
import httpx
import qrcode
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, EmailStr, Field, field_validator
from starlette.middleware.sessions import SessionMiddleware

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
load_dotenv(PROJECT_DIR / ".env")
DATA_DIR = PROJECT_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "app.db"
TZ = ZoneInfo("Atlantic/Bermuda")


def env(name: str, default: str) -> str:
    return os.environ.get(name, default)


DEFAULT_CONFIG: Dict[str, Any] = {
    "event_name": "CMC Markets Bermuda | BTC Price Lock",
    "event_date": "2026-04-11",
    "event_date_display": "Saturday, April 11, 2026",
    "event_series_name": "Bermuda Meets Ibiza",
    "event_partner_name": "Habitat for Humanity Bermuda",
    "event_support_copy": "Presented by CMC Markets Bermuda · Platinum Sponsor",
    "event_location": "The Loren Hotel · Bermuda",
    "timezone": "Atlantic/Bermuda",
    "entry_lock_local": "2026-04-11T22:00:00",
    "final_time_local": "2026-04-11T23:00:00",
    "public_base_url": env("CMC_PUBLIC_BASE_URL", ""),
    "qr_image_url": "",
    "lead_export_email": env("CMC_LEAD_EXPORT_EMAIL", "b.charbonneau@cmcmarkets.com"),
    "price_provider": "demo",  # demo | manual | coinbase | coingecko
    "manual_price": 66000.00,
    "final_reference_price": None,
    "final_reference_captured_at": None,
    "demo_step_max": 65.0,
    "units": 10,
    "margin_percent": 0.10,
    "spread_per_unit": 15.0,
    "holding_cost": 0.0,
    "edit_throttle_seconds": 0,
    "marketing_opt_in_enabled": True,
    "seed_demo_data": False,
    "rules": [
        "Open to Bermuda residents aged 18 or over.",
        "One active entry per person.",
        "One active prediction per participant.",
        "Duplicate predictions are not permitted.",
        "Entries and edits close at 10:00 PM Hamilton time.",
        "The most recent valid prediction before 10:00 PM becomes final.",
        "Closest eligible prediction to the official BTC/USD reference price at 11:00 PM wins.",
        "If two entries are equally close, the earliest final locked submission timestamp wins.",
        "Winner must complete identity and residency verification.",
        "CMC may disqualify false, duplicate or abusive entries.",
    ],
    "privacy_notice": (
        "CMC Markets Bermuda will use your information to administer this educational activation, "
        "contact you if you win, and, if you opt in, share information about future events, products, "
        "services, and insights."
    ),
    "hero_copy": (
        "This is a live educational CMC Markets Bermuda experience created for Bermuda Meets Ibiza by Habitat for Humanity Bermuda. "
        "We are using Bitcoin because the event takes place on a Saturday, when many traditional markets are closed while crypto is still open and moving."
    ),
    "education_copy": (
        "Leverage is a double-edged sword. A small move can help you or hurt you faster because you control a larger position with less cash. "
        "This simulation is designed to make that risk easy to see before anyone places a real trade."
    ),
    "example_copy": (
        "Think of leverage like buying a home. In Bermuda, you might put down 20% and the bank funds the other 80%. Here, 10 BTC at $66,000 creates $660,000 of exposure, and the minimum cash needed is 10%, or $66,000. Gold or USD/CAD can require as little as 0.5% cash because those markets are deeper and trade for longer hours. Daily interest is easy: close before the daily cut-off and there is no daily adjustment; hold past it and a daily charge or credit can apply."
    ),
    "dashboard_footer": (
        "Educational illustration only. Not investment advice. Leverage can increase gains and losses. Review the product overview, costs, and risks before trading."
    ),
    "prize_title": "Win the Black Yamaha RAY-ZR 125cc Hybrid",
    "qr_steps": ["Scan the QR", "Register", "Lock your price", "Watch the live board"],
    "status_badge_copy": "Live BTC/USD Price · updates every 10 seconds",
    "leaderboard_size": 5,
    "saturday_copy": (
        "It is Saturday. Most traditional financial markets are closed, while Bitcoin is still open, live, and moving."
    ),
}

APP = FastAPI(title="CMC Markets Bermuda | BTC Price Lock")
APP.add_middleware(
    SessionMiddleware,
    secret_key=env("CMC_SESSION_SECRET", "change-me-in-production"),
    same_site="lax",
    https_only=env("CMC_HTTPS_ONLY", "false").strip().lower() == "true",
)
APP.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
TEMPLATES = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def now_bermuda() -> datetime:
    return datetime.now(TZ)


@dataclass
class EventTimes:
    entry_lock: datetime
    final_time: datetime


def parse_local_dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=TZ)


def get_event_times(config: Dict[str, Any]) -> EventTimes:
    return EventTimes(
        entry_lock=parse_local_dt(config["entry_lock_local"]),
        final_time=parse_local_dt(config["final_time_local"]),
    )


def public_entry_url(request: Request, config: Dict[str, Any]) -> str:
    configured = (config.get("public_base_url") or "").strip()
    if configured:
        return configured if configured.endswith("/") else f"{configured}/"
    return str(request.base_url)


def iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    return dt.astimezone(TZ).isoformat()


class SubmissionPayload(BaseModel):
    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=80)
    display_name: str = Field(default="", max_length=32)
    email: EmailStr
    phone: str = Field(min_length=7, max_length=32)
    country: str = Field(min_length=2, max_length=80)
    industry: str = Field(min_length=2, max_length=120)
    company: Optional[str] = Field(default="", max_length=120)
    job_title: Optional[str] = Field(default="", max_length=120)
    product_interest: List[str] = Field(default_factory=list)
    prediction: str
    confirm_resident_age: bool
    accept_rules: bool
    consent_admin: bool
    marketing_opt_in: bool = False
    edit_token: Optional[str] = Field(default="", max_length=128)

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str) -> str:
        cleaned = re.sub(r"\s+", " ", value).strip()
        return cleaned

    @field_validator("country")
    @classmethod
    def validate_country(cls, value: str) -> str:
        cleaned = value.strip()
        if cleaned.lower() not in {"bermuda", "bm", "bermuda islands"}:
            raise ValueError("This activation is limited to Bermuda residents.")
        return "Bermuda"

    @field_validator("prediction")
    @classmethod
    def validate_prediction(cls, value: str) -> str:
        try:
            parsed = Decimal(value.replace(",", "")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        except InvalidOperation as exc:
            raise ValueError("Enter a valid BTC/USD prediction to 2 decimal places.") from exc
        if parsed <= 0:
            raise ValueError("Prediction must be greater than zero.")
        return format(parsed, ".2f")


class AdminConfigPayload(BaseModel):
    public_base_url: str
    qr_image_url: Optional[str] = ""
    event_date_display: str
    event_series_name: str
    event_partner_name: str
    event_support_copy: str
    event_location: str
    entry_lock_local: str
    final_time_local: str
    lead_export_email: EmailStr
    price_provider: str
    manual_price: float
    final_reference_price: Optional[float] = None
    rules: List[str]
    hero_copy: str
    education_copy: str
    example_copy: str
    saturday_copy: str
    status_badge_copy: str
    privacy_notice: str
    dashboard_footer: str
    marketing_opt_in_enabled: bool
    leaderboard_size: int = Field(default=5, ge=3, le=20)


def normalize_email(value: str) -> str:
    return value.strip().lower()


def normalize_phone(value: str) -> str:
    digits = re.sub(r"[^0-9+]", "", value)
    digits = digits.replace("++", "+")
    if digits.startswith("+1"):
        return digits
    if digits.startswith("1") and len(digits) == 11:
        return f"+{digits}"
    if digits.startswith("+"):
        return digits
    return digits


def default_display_name(first_name: str, last_name: str) -> str:
    first = re.sub(r"\s+", " ", (first_name or "").strip())
    last = re.sub(r"\s+", " ", (last_name or "").strip())
    if first and last:
        return f"{first} {last[0].upper()}."
    return first or last


FIELD_LABELS: Dict[str, str] = {
    "first_name": "First name",
    "last_name": "Last name",
    "display_name": "Public display name",
    "email": "Email",
    "phone": "Mobile number",
    "country": "Country of residence",
    "industry": "Industry",
    "prediction": "Prediction",
    "confirm_resident_age": "Resident / age confirmation",
    "accept_rules": "Rules and Privacy Notice",
    "consent_admin": "Consent to administer the activation",
}


def validation_message_for(field: Optional[str], raw_message: str) -> str:
    message = raw_message or "Please review this field."
    lowered = message.lower()
    if field == "confirm_resident_age":
        return "Please confirm that you are a Bermuda resident aged 18 or over."
    if field == "accept_rules":
        return "Please agree to the Rules and Privacy Notice to continue."
    if field == "consent_admin":
        return "Please consent to CMC Markets Bermuda administering this activation."
    if "field required" in lowered or "missing" in lowered:
        label = FIELD_LABELS.get(field, "This field")
        return f"{label} is required."
    return message[0].upper() + message[1:] if message else "Please review this field."


PRODUCT_INTEREST_CHOICES = [
    "Private Markets",
    "Crypto",
    "FX",
    "Commodities",
    "Global Indices",
    "Shares",
    "ETFs",
    "Events & Insights",
]
INDUSTRY_CHOICES = sorted(
    [
        "Accounting",
        "Asset Management",
        "Aviation",
        "Banking",
        "Civil Service",
        "Construction & Real Estate",
        "Consulting",
        "Corporate Services",
        "Education",
        "Family Office",
        "Financial Services",
        "Government",
        "Healthcare",
        "Hospitality",
        "Insurance",
        "International Business",
        "Legal",
        "Media & Marketing",
        "Military",
        "Non-profit",
        "Other",
        "Police",
        "Regulatory",
        "Reinsurance",
        "Retail",
        "Shipping & Maritime",
        "Student",
        "Technology",
        "Tourism",
        "Transport",
        "Trust & Private Client",
        "Utilities & Telecom",
    ],
    key=str.casefold,
)

def column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row["name"] == column for row in rows)


def ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    if not column_exists(conn, table, column):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def ensure_participant_token(conn: sqlite3.Connection, participant_id: int) -> str:
    row = conn.execute("SELECT edit_token FROM participants WHERE id = ?", (participant_id,)).fetchone()
    existing = (row["edit_token"] or "").strip() if row else ""
    if existing:
        return existing
    token = secrets.token_urlsafe(24)
    conn.execute("UPDATE participants SET edit_token = ? WHERE id = ?", (token, participant_id))
    conn.commit()
    return token


def get_participant_by_token(conn: sqlite3.Connection, token: str) -> Optional[sqlite3.Row]:
    cleaned = (token or "").strip()
    if not cleaned:
        return None
    return conn.execute(
        "SELECT * FROM participants WHERE edit_token = ? AND is_disqualified = 0 LIMIT 1",
        (cleaned,),
    ).fetchone()


def init_db() -> None:
    with closing(db_connect()) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS app_config (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS participants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                first_name TEXT NOT NULL,
                last_name TEXT NOT NULL,
                display_name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                phone TEXT NOT NULL UNIQUE,
                country TEXT NOT NULL,
                industry TEXT NOT NULL,
                company TEXT,
                job_title TEXT,
                product_interest TEXT,
                marketing_opt_in INTEGER NOT NULL DEFAULT 0,
                confirm_resident_age INTEGER NOT NULL,
                accept_rules INTEGER NOT NULL,
                consent_admin INTEGER NOT NULL,
                prediction REAL NOT NULL,
                prediction_cents INTEGER NOT NULL,
                entry_price REAL NOT NULL,
                direction TEXT NOT NULL,
                margin_required REAL NOT NULL,
                cost_of_trade REAL NOT NULL,
                holding_cost REAL NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                ip_address TEXT,
                user_agent TEXT,
                is_disqualified INTEGER NOT NULL DEFAULT 0,
                disqualification_reason TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_participants_prediction_cents ON participants(prediction_cents);
            CREATE INDEX IF NOT EXISTS idx_participants_updated_at ON participants(updated_at DESC);

            CREATE TABLE IF NOT EXISTS price_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                captured_at TEXT NOT NULL,
                price REAL NOT NULL,
                source TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_price_snapshots_captured_at ON price_snapshots(captured_at DESC);

            CREATE TABLE IF NOT EXISTS activities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                participant_id INTEGER,
                display_name TEXT NOT NULL,
                prediction REAL,
                event_type TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (participant_id) REFERENCES participants(id)
            );
            CREATE INDEX IF NOT EXISTS idx_activities_created_at ON activities(created_at DESC);
            """
        )
        ensure_column(conn, "participants", "edit_token", "TEXT")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_participants_edit_token ON participants(edit_token)")

        existing = conn.execute("SELECT json FROM app_config WHERE id = 1").fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO app_config (id, json, updated_at) VALUES (1, ?, ?)",
                (json.dumps(DEFAULT_CONFIG), iso(now_bermuda())),
            )
        conn.commit()

    maybe_seed_demo_data()


def get_config(conn: sqlite3.Connection) -> Dict[str, Any]:
    row = conn.execute("SELECT json FROM app_config WHERE id = 1").fetchone()
    if not row:
        raise RuntimeError("Config not found")
    stored = json.loads(row["json"])
    config = DEFAULT_CONFIG | stored
    config["rules"] = list(config.get("rules", []))

    changed = set(config.keys()) != set(stored.keys())
    if config.get("edit_throttle_seconds") == 60:
        config["edit_throttle_seconds"] = 0
        changed = True
    if config.get("status_badge_copy") == "Live BTC/USD Price · updates every minute":
        config["status_badge_copy"] = "Live BTC/USD Price · updates every 10 seconds"
        changed = True
    config["leaderboard_size"] = max(3, min(20, int(config.get("leaderboard_size", 5) or 5)))
    if stored.get("leaderboard_size") != config["leaderboard_size"]:
        changed = True

    if changed:
        conn.execute(
            "UPDATE app_config SET json = ?, updated_at = ? WHERE id = 1",
            (json.dumps(config), iso(now_bermuda())),
        )
        conn.commit()
    return config


def save_config(conn: sqlite3.Connection, config: Dict[str, Any]) -> None:
    conn.execute(
        "UPDATE app_config SET json = ?, updated_at = ? WHERE id = 1",
        (json.dumps(config), iso(now_bermuda())),
    )
    conn.commit()


def maybe_seed_demo_data() -> None:
    with closing(db_connect()) as conn:
        config = get_config(conn)
        count = conn.execute("SELECT COUNT(*) AS c FROM participants").fetchone()["c"]
        if count or not config.get("seed_demo_data", False):
            return
        base_price = Decimal(str(config.get("manual_price", 66000.00)))
        entries = [
            {
                "first_name": "Ariel",
                "last_name": "Roberts",
                "display_name": "Ariel R.",
                "email": "demo1@example.com",
                "phone": "+14415550001",
                "country": "Bermuda",
                "industry": "Reinsurance",
                "company": "Atlantic Re",
                "job_title": "Portfolio Lead",
                "product_interest": "Crypto,FX",
                "marketing_opt_in": 1,
                "confirm_resident_age": 1,
                "accept_rules": 1,
                "consent_admin": 1,
                "prediction": float((base_price + Decimal("142.17")).quantize(Decimal("0.01"))),
                "prediction_cents": int((base_price + Decimal("142.17")) * 100),
                "entry_price": float(base_price),
                "direction": "LONG",
                "margin_required": float(base_price * Decimal(str(config["units"])) * Decimal(str(config["margin_percent"]))),
                "cost_of_trade": float(config["spread_per_unit"] * config["units"]),
                "holding_cost": 0.0,
                "created_at": iso(now_bermuda() - timedelta(minutes=14)),
                "updated_at": iso(now_bermuda() - timedelta(minutes=14)),
                "ip_address": "127.0.0.1",
                "user_agent": "demo",
            },
            {
                "first_name": "Mika",
                "last_name": "Thomas",
                "display_name": "Mika T.",
                "email": "demo2@example.com",
                "phone": "+14415550002",
                "country": "Bermuda",
                "industry": "Insurance",
                "company": "Harbour Risk",
                "job_title": "Analyst",
                "product_interest": "Crypto,Shares",
                "marketing_opt_in": 1,
                "confirm_resident_age": 1,
                "accept_rules": 1,
                "consent_admin": 1,
                "prediction": float((base_price - Decimal("88.43")).quantize(Decimal("0.01"))),
                "prediction_cents": int((base_price - Decimal("88.43")) * 100),
                "entry_price": float(base_price - Decimal("55.00")),
                "direction": "SHORT",
                "margin_required": float((base_price - Decimal("55.00")) * Decimal(str(config["units"])) * Decimal(str(config["margin_percent"]))),
                "cost_of_trade": float(config["spread_per_unit"] * config["units"]),
                "holding_cost": 0.0,
                "created_at": iso(now_bermuda() - timedelta(minutes=9)),
                "updated_at": iso(now_bermuda() - timedelta(minutes=9)),
                "ip_address": "127.0.0.1",
                "user_agent": "demo",
            },
            {
                "first_name": "Noah",
                "last_name": "Dill",
                "display_name": "Noah D.",
                "email": "demo3@example.com",
                "phone": "+14415550003",
                "country": "Bermuda",
                "industry": "Technology",
                "company": "Ocean Tech",
                "job_title": "Founder",
                "product_interest": "Crypto,Events & Insights",
                "marketing_opt_in": 1,
                "confirm_resident_age": 1,
                "accept_rules": 1,
                "consent_admin": 1,
                "prediction": float((base_price + Decimal("12.02")).quantize(Decimal("0.01"))),
                "prediction_cents": int((base_price + Decimal("12.02")) * 100),
                "entry_price": float(base_price + Decimal("22.00")),
                "direction": "SHORT",
                "margin_required": float((base_price + Decimal("22.00")) * Decimal(str(config["units"])) * Decimal(str(config["margin_percent"]))),
                "cost_of_trade": float(config["spread_per_unit"] * config["units"]),
                "holding_cost": 0.0,
                "created_at": iso(now_bermuda() - timedelta(minutes=3)),
                "updated_at": iso(now_bermuda() - timedelta(minutes=1)),
                "ip_address": "127.0.0.1",
                "user_agent": "demo",
            },
        ]
        for item in entries:
            cursor = conn.execute(
                """
                INSERT INTO participants (
                    first_name, last_name, display_name, edit_token, email, phone, country, industry, company, job_title,
                    product_interest, marketing_opt_in, confirm_resident_age, accept_rules, consent_admin,
                    prediction, prediction_cents, entry_price, direction, margin_required, cost_of_trade,
                    holding_cost, created_at, updated_at, ip_address, user_agent
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["first_name"],
                    item["last_name"],
                    item["display_name"],
                    secrets.token_urlsafe(12),
                    item["email"],
                    item["phone"],
                    item["country"],
                    item["industry"],
                    item["company"],
                    item["job_title"],
                    item["product_interest"],
                    item["marketing_opt_in"],
                    item["confirm_resident_age"],
                    item["accept_rules"],
                    item["consent_admin"],
                    item["prediction"],
                    item["prediction_cents"],
                    item["entry_price"],
                    item["direction"],
                    item["margin_required"],
                    item["cost_of_trade"],
                    item["holding_cost"],
                    item["created_at"],
                    item["updated_at"],
                    item["ip_address"],
                    item["user_agent"],
                ),
            )
            conn.execute(
                "INSERT INTO activities (participant_id, display_name, prediction, event_type, created_at) VALUES (?, ?, ?, ?, ?)",
                (cursor.lastrowid, item["display_name"], item["prediction"], "entered", item["updated_at"]),
            )
        conn.commit()


def get_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    client = request.client
    return client.host if client else ""


async def fetch_live_price(conn: sqlite3.Connection, config: Dict[str, Any], force_refresh: bool = False) -> tuple[float, str]:
    latest = conn.execute(
        "SELECT price, source, captured_at FROM price_snapshots ORDER BY captured_at DESC LIMIT 1"
    ).fetchone()
    now = now_bermuda()
    if latest and not force_refresh:
        latest_at = datetime.fromisoformat(latest["captured_at"])
        if latest_at.tzinfo is None:
            latest_at = latest_at.replace(tzinfo=TZ)
        if now - latest_at < timedelta(seconds=9):
            return float(latest["price"]), latest["source"]

    price_provider = config.get("price_provider", "demo")
    price: Optional[float] = None
    source = price_provider

    if price_provider == "manual":
        price = float(config.get("manual_price", 66000.0))
    elif price_provider == "coinbase":
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                response = await client.get("https://api.coinbase.com/v2/prices/BTC-USD/spot")
                response.raise_for_status()
                payload = response.json()
                price = float(payload["data"]["amount"])
        except Exception:
            price = None
    elif price_provider == "coingecko":
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                response = await client.get(
                    "https://api.coingecko.com/api/v3/simple/price",
                    params={"ids": "bitcoin", "vs_currencies": "usd"},
                )
                response.raise_for_status()
                payload = response.json()
                price = float(payload["bitcoin"]["usd"])
        except Exception:
            price = None

    if price is None:
        source = "demo"
        base = float(config.get("manual_price", 66000.0))
        if latest:
            base = float(latest["price"])
        step = float(config.get("demo_step_max", 65.0))
        drift = random.uniform(-step, step)
        price = round(base + drift, 2)

    captured_at = iso(now)
    conn.execute(
        "INSERT INTO price_snapshots (captured_at, price, source) VALUES (?, ?, ?)",
        (captured_at, price, source),
    )
    conn.commit()
    return float(price), source


async def get_or_lock_final_reference_price(conn: sqlite3.Connection, config: Dict[str, Any]) -> Optional[float]:
    final_reference = config.get("final_reference_price")
    if final_reference is not None:
        return float(final_reference)
    times = get_event_times(config)
    if now_bermuda() < times.final_time:
        return None
    price, source = await fetch_live_price(conn, config, force_refresh=True)
    config["final_reference_price"] = price
    config["final_reference_captured_at"] = iso(now_bermuda())
    save_config(conn, config)
    conn.execute(
        "INSERT INTO activities (participant_id, display_name, prediction, event_type, created_at) VALUES (?, ?, ?, ?, ?)",
        (None, "SYSTEM", price, f"final-price:{source}", iso(now_bermuda())),
    )
    conn.commit()
    return float(price)


def prediction_to_cents(prediction: str | float | Decimal) -> int:
    if isinstance(prediction, Decimal):
        value = prediction
    else:
        value = Decimal(str(prediction))
    return int((value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)) * 100)


async def current_market_state(conn: sqlite3.Connection) -> Dict[str, Any]:
    config = get_config(conn)
    live_price, price_source = await fetch_live_price(conn, config)
    final_reference = await get_or_lock_final_reference_price(conn, config)
    times = get_event_times(config)
    now = now_bermuda()
    phase = "open"
    if now >= times.entry_lock and now < times.final_time:
        phase = "locked"
    elif now >= times.final_time:
        phase = "final"
    return {
        "config": config,
        "times": times,
        "now": now,
        "live_price": float(live_price),
        "price_source": price_source,
        "final_reference_price": float(final_reference) if final_reference is not None else None,
        "phase": phase,
        "entry_open": now < times.entry_lock,
    }



def calculate_row_metrics(participant: sqlite3.Row, live_price: float, reference_price: float) -> Dict[str, Any]:
    entry_price = float(participant["entry_price"])
    units = 10
    position_value = round(live_price * units, 2)
    cost_of_trade = float(participant["cost_of_trade"])
    holding_cost = float(participant["holding_cost"])
    direction = participant["direction"]

    if direction == "LONG":
        pnl = ((live_price - entry_price) * units) - cost_of_trade - holding_cost
    elif direction == "SHORT":
        pnl = ((entry_price - live_price) * units) - cost_of_trade - holding_cost
    else:
        pnl = -cost_of_trade - holding_cost

    margin_required = float(participant["margin_required"])
    roi = 0.0 if margin_required == 0 else (pnl / margin_required) * 100
    distance = abs(float(participant["prediction"]) - reference_price)
    return {
        "id": participant["id"],
        "display_name": participant["display_name"],
        "entry_price": round(float(participant["entry_price"]), 2),
        "prediction": round(float(participant["prediction"]), 2),
        "product": "Bitcoin",
        "units": units,
        "direction": direction,
        "position_value": position_value,
        "entry_margin_required": round(margin_required, 2),
        "cost_of_trade": round(cost_of_trade, 2),
        "holding_cost": round(holding_cost, 2),
        "pnl": round(pnl, 2),
        "roi": round(roi, 2),
        "distance": round(distance, 2),
        "updated_at": participant["updated_at"],
    }



def load_active_participants(conn: sqlite3.Connection) -> List[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM participants WHERE is_disqualified = 0 ORDER BY updated_at DESC"
        ).fetchall()
    )


async def build_public_state(conn: sqlite3.Connection) -> Dict[str, Any]:
    market_state = await current_market_state(conn)
    config = market_state["config"]
    reference_price = (
        market_state["final_reference_price"]
        if market_state["phase"] == "final" and market_state["final_reference_price"] is not None
        else market_state["live_price"]
    )
    participants = load_active_participants(conn)
    rows = [calculate_row_metrics(p, market_state["live_price"], reference_price) for p in participants]
    rows.sort(key=lambda item: (item["distance"], item["updated_at"]))
    leaderboard_visible_rows = max(3, min(20, int(config.get("leaderboard_size", 5) or 5)))
    leaders = rows

    recent = list(
        conn.execute(
            "SELECT display_name, prediction, event_type, created_at FROM activities ORDER BY created_at DESC LIMIT 8"
        ).fetchall()
    )
    ticker = []
    for item in recent:
        event_type = item["event_type"]
        if event_type.startswith("final-price"):
            continue
        verb = "updated to" if event_type == "updated" else "locked"
        ticker.append(
            {
                "message": f"{item['display_name']} {verb} ${float(item['prediction']):,.2f}",
                "created_at": item["created_at"],
            }
        )

    times = market_state["times"]
    now = market_state["now"]
    return {
        "event_name": config["event_name"],
        "phase": market_state["phase"],
        "entry_open": market_state["entry_open"],
        "live_price": round(market_state["live_price"], 2),
        "price_source": market_state["price_source"],
        "final_reference_price": market_state["final_reference_price"],
        "leaders": leaders,
        "leaderboard_visible_rows": leaderboard_visible_rows,
        "ticker": ticker,
        "entry_lock_iso": iso(times.entry_lock),
        "final_time_iso": iso(times.final_time),
        "now_iso": iso(now),
        "seconds_to_lock": max(0, int((times.entry_lock - now).total_seconds())),
        "seconds_to_final": max(0, int((times.final_time - now).total_seconds())),
        "dashboard_footer": config["dashboard_footer"],
        "rules": config["rules"],
        "prize_title": config["prize_title"],
        "status_badge_copy": config["status_badge_copy"],
        "hero_copy": config["hero_copy"],
        "example_copy": config["example_copy"],
        "education_copy": config["education_copy"],
        "saturday_copy": config["saturday_copy"],
        "event_date_display": config["event_date_display"],
        "event_series_name": config["event_series_name"],
        "event_partner_name": config["event_partner_name"],
        "event_support_copy": config["event_support_copy"],
        "event_location": config["event_location"],
        "qr_image_url": "/api/qr.png",
        "public_base_url": config.get("public_base_url") or "",
    }



@APP.exception_handler(RequestValidationError)
async def request_validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    field_errors = []
    for error in exc.errors():
        loc = list(error.get("loc") or [])
        field = None
        if loc:
            field = str(loc[-1])
        if field == "body" or field == "__root__":
            field = None
        message = validation_message_for(field, str(error.get("msg", "Please review this field.")))
        field_errors.append({"field": field, "message": message})
    detail = field_errors[0]["message"] if field_errors else "Please review the highlighted fields."
    return JSONResponse(status_code=422, content={"detail": detail, "field_errors": field_errors})


def ensure_admin(request: Request) -> None:
    if not request.session.get("admin_authenticated"):
        raise HTTPException(status_code=401, detail="Admin login required")


@APP.on_event("startup")
async def startup_event() -> None:
    init_db()


@APP.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    with closing(db_connect()) as conn:
        state = await current_market_state(conn)
        config = state["config"]
        return TEMPLATES.TemplateResponse(
            "index.html",
            {
                "request": request,
                "config": config,
                "entry_open": state["entry_open"],
                "live_price": state["live_price"],
                "phase": state["phase"],
                "industry_choices": INDUSTRY_CHOICES,
                "product_interest_choices": PRODUCT_INTEREST_CHOICES,
                "entry_lock_iso": iso(state["times"].entry_lock),
                "final_time_iso": iso(state["times"].final_time),
                "now_iso": iso(state["now"]),
            },
        )


@APP.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    with closing(db_connect()) as conn:
        config = get_config(conn)
        return TEMPLATES.TemplateResponse(
            "dashboard.html",
            {"request": request, "config": config},
        )


@APP.get("/admin", response_class=HTMLResponse)
async def admin(request: Request) -> HTMLResponse:
    authenticated = request.session.get("admin_authenticated", False)
    with closing(db_connect()) as conn:
        config = get_config(conn)
        return TEMPLATES.TemplateResponse(
            "admin.html",
            {"request": request, "config": config, "authenticated": authenticated},
        )


@APP.post("/admin/login")
async def admin_login(request: Request, password: str = Form(...)) -> Response:
    if password != env("CMC_ADMIN_PASSWORD", "cmcmarkets"):
        request.session["admin_authenticated"] = False
        return RedirectResponse(url="/admin?error=1", status_code=303)
    request.session["admin_authenticated"] = True
    return RedirectResponse(url="/admin", status_code=303)


@APP.post("/admin/logout")
async def admin_logout(request: Request) -> Response:
    request.session.clear()
    return RedirectResponse(url="/admin", status_code=303)


@APP.get("/api/status")
async def api_status() -> JSONResponse:
    with closing(db_connect()) as conn:
        state = await current_market_state(conn)
        config = state["config"]
        return JSONResponse(
            {
                "entry_open": state["entry_open"],
                "phase": state["phase"],
                "live_price": round(state["live_price"], 2),
                "entry_lock_iso": iso(state["times"].entry_lock),
                "final_time_iso": iso(state["times"].final_time),
                "now_iso": iso(state["now"]),
                "hero_copy": config["hero_copy"],
                "education_copy": config["education_copy"],
                "example_copy": config["example_copy"],
                "saturday_copy": config["saturday_copy"],
                "status_badge_copy": config["status_badge_copy"],
                "event_date_display": config["event_date_display"],
                "event_series_name": config["event_series_name"],
                "event_partner_name": config["event_partner_name"],
                "event_support_copy": config["event_support_copy"],
                "event_location": config["event_location"],
            }
        )


@APP.get("/api/me")
async def api_me(token: str = "") -> JSONResponse:
    with closing(db_connect()) as conn:
        participant = get_participant_by_token(conn, token)
        if not participant:
            return JSONResponse({"found": False})
        state = await current_market_state(conn)
        return JSONResponse(
            {
                "found": True,
                "participant": {
                    "first_name": participant["first_name"],
                    "last_name": participant["last_name"],
                    "display_name": participant["display_name"],
                    "email": participant["email"],
                    "phone": participant["phone"],
                    "country": participant["country"],
                    "industry": participant["industry"],
                    "company": participant["company"] or "",
                    "job_title": participant["job_title"] or "",
                    "product_interest": [item for item in (participant["product_interest"] or "").split(",") if item],
                    "prediction": f"{float(participant['prediction']):.2f}",
                    "marketing_opt_in": bool(participant["marketing_opt_in"]),
                    "confirm_resident_age": bool(participant["confirm_resident_age"]),
                    "accept_rules": bool(participant["accept_rules"]),
                    "consent_admin": bool(participant["consent_admin"]),
                    "entry_price": round(float(participant["entry_price"]), 2),
                    "direction": participant["direction"],
                },
                "live_price": round(state["live_price"], 2),
                "entry_open": state["entry_open"],
            }
        )


@APP.get("/api/public-state")
async def api_public_state() -> JSONResponse:
    with closing(db_connect()) as conn:
        state = await build_public_state(conn)
        return JSONResponse(state)


@APP.get("/api/qr.png")
async def api_qr(request: Request) -> Response:
    with closing(db_connect()) as conn:
        config = get_config(conn)
        target = public_entry_url(request, config)
        qr = qrcode.QRCode(box_size=10, border=2)
        qr.add_data(target)
        qr.make(fit=True)
        image = qr.make_image(fill_color="black", back_color="white")
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        buffer.seek(0)
        return Response(content=buffer.getvalue(), media_type="image/png")


@APP.get("/healthz")
async def healthz() -> JSONResponse:
    return JSONResponse({"status": "ok"})



def suggest_available_predictions(conn: sqlite3.Connection, desired_cents: int, self_id: Optional[int] = None, count: int = 5) -> List[str]:
    params: List[Any] = []
    query = "SELECT prediction_cents FROM participants WHERE is_disqualified = 0"
    if self_id is not None:
        query += " AND id != ?"
        params.append(self_id)
    taken = {row["prediction_cents"] for row in conn.execute(query, params).fetchall()}
    suggestions: List[str] = []
    delta = 1
    while len(suggestions) < count and delta < 500:
        for candidate in (desired_cents + delta, desired_cents - delta):
            if candidate <= 0 or candidate in taken:
                continue
            suggestions.append(f"{candidate / 100:,.2f}")
            if len(suggestions) >= count:
                break
        delta += 1
    return suggestions


@APP.post("/api/submit")
async def api_submit(request: Request, payload: SubmissionPayload) -> JSONResponse:
    with closing(db_connect()) as conn:
        config = get_config(conn)
        times = get_event_times(config)
        now = now_bermuda()
        if now >= times.entry_lock:
            raise HTTPException(status_code=400, detail="Entries are now closed.")

        normalized_email = normalize_email(payload.email)
        normalized_phone = normalize_phone(payload.phone)
        prediction_decimal = Decimal(payload.prediction)
        prediction_cents = prediction_to_cents(prediction_decimal)
        live_price, _ = await fetch_live_price(conn, config)

        token_existing = get_participant_by_token(conn, payload.edit_token or "")
        email_match = conn.execute(
            "SELECT * FROM participants WHERE email = ? LIMIT 1", (normalized_email,)
        ).fetchone()
        phone_match = conn.execute(
            "SELECT * FROM participants WHERE phone = ? LIMIT 1", (normalized_phone,)
        ).fetchone()

        existing = None
        if token_existing:
            existing = token_existing
            if email_match and email_match["id"] != existing["id"]:
                raise HTTPException(status_code=400, detail="That email address is already in use by another entry.")
            if phone_match and phone_match["id"] != existing["id"]:
                raise HTTPException(status_code=400, detail="That phone number is already in use by another entry.")
        elif email_match and phone_match:
            if email_match["id"] != phone_match["id"]:
                raise HTTPException(status_code=400, detail="We found conflicting contact details. Please see CMC staff for assistance.")
            existing = email_match
        elif email_match:
            existing = email_match
        elif phone_match:
            existing = phone_match

        existing_id = existing["id"] if existing else None
        duplicate_price = conn.execute(
            "SELECT id FROM participants WHERE prediction_cents = ? AND is_disqualified = 0 AND (? IS NULL OR id != ?)",
            (prediction_cents, existing_id, existing_id),
        ).fetchone()
        if duplicate_price:
            suggestions = suggest_available_predictions(conn, prediction_cents, self_id=existing_id)
            raise HTTPException(
                status_code=409,
                detail=f"That prediction is already taken. Try one of these nearby prices: {', '.join(suggestions)}",
            )

        if existing:
            last_updated = datetime.fromisoformat(existing["updated_at"])
            if last_updated.tzinfo is None:
                last_updated = last_updated.replace(tzinfo=TZ)
            throttle_seconds = int(config.get("edit_throttle_seconds", 0) or 0)
            if throttle_seconds > 0 and now - last_updated < timedelta(seconds=throttle_seconds):
                wait_for = throttle_seconds - int((now - last_updated).total_seconds())
                raise HTTPException(
                    status_code=429,
                    detail=f"Please wait {wait_for} more seconds before updating your prediction.",
                )

        direction = "FLAT"
        if prediction_decimal > Decimal(str(live_price)):
            direction = "LONG"
        elif prediction_decimal < Decimal(str(live_price)):
            direction = "SHORT"

        units = Decimal(str(config["units"]))
        margin_percent = Decimal(str(config["margin_percent"]))
        spread_cost = Decimal(str(config["spread_per_unit"])) * units
        margin_required = Decimal(str(live_price)) * units * margin_percent
        now_iso = iso(now)

        first_name = payload.first_name.strip()
        last_name = payload.last_name.strip()
        display_name = payload.display_name.strip() or default_display_name(first_name, last_name)
        if len(display_name) < 2:
            raise HTTPException(status_code=422, detail="Public display name is required.")

        values = {
            "first_name": first_name,
            "last_name": last_name,
            "display_name": display_name,
            "edit_token": (existing["edit_token"] if existing and existing["edit_token"] else secrets.token_urlsafe(24)),
            "email": normalized_email,
            "phone": normalized_phone,
            "country": payload.country,
            "industry": payload.industry.strip(),
            "company": payload.company.strip(),
            "job_title": payload.job_title.strip(),
            "product_interest": ",".join([item for item in payload.product_interest if item in PRODUCT_INTEREST_CHOICES]),
            "marketing_opt_in": 1 if payload.marketing_opt_in else 0,
            "confirm_resident_age": 1 if payload.confirm_resident_age else 0,
            "accept_rules": 1 if payload.accept_rules else 0,
            "consent_admin": 1 if payload.consent_admin else 0,
            "prediction": float(prediction_decimal),
            "prediction_cents": prediction_cents,
            "entry_price": float(live_price),
            "direction": direction,
            "margin_required": float(margin_required),
            "cost_of_trade": float(spread_cost),
            "holding_cost": float(config.get("holding_cost", 0.0)),
            "created_at": existing["created_at"] if existing else now_iso,
            "updated_at": now_iso,
            "ip_address": get_ip(request),
            "user_agent": request.headers.get("user-agent", ""),
        }

        if existing:
            conn.execute(
                """
                UPDATE participants SET
                    first_name = :first_name,
                    last_name = :last_name,
                    display_name = :display_name,
                    edit_token = :edit_token,
                    email = :email,
                    phone = :phone,
                    country = :country,
                    industry = :industry,
                    company = :company,
                    job_title = :job_title,
                    product_interest = :product_interest,
                    marketing_opt_in = :marketing_opt_in,
                    confirm_resident_age = :confirm_resident_age,
                    accept_rules = :accept_rules,
                    consent_admin = :consent_admin,
                    prediction = :prediction,
                    prediction_cents = :prediction_cents,
                    entry_price = :entry_price,
                    direction = :direction,
                    margin_required = :margin_required,
                    cost_of_trade = :cost_of_trade,
                    holding_cost = :holding_cost,
                    updated_at = :updated_at,
                    ip_address = :ip_address,
                    user_agent = :user_agent
                WHERE id = :id
                """,
                values | {"id": existing["id"]},
            )
            participant_id = existing["id"]
            activity_type = "updated"
        else:
            cursor = conn.execute(
                """
                INSERT INTO participants (
                    first_name, last_name, display_name, edit_token, email, phone, country, industry, company, job_title,
                    product_interest, marketing_opt_in, confirm_resident_age, accept_rules, consent_admin,
                    prediction, prediction_cents, entry_price, direction, margin_required, cost_of_trade,
                    holding_cost, created_at, updated_at, ip_address, user_agent
                ) VALUES (
                    :first_name, :last_name, :display_name, :edit_token, :email, :phone, :country, :industry, :company, :job_title,
                    :product_interest, :marketing_opt_in, :confirm_resident_age, :accept_rules, :consent_admin,
                    :prediction, :prediction_cents, :entry_price, :direction, :margin_required, :cost_of_trade,
                    :holding_cost, :created_at, :updated_at, :ip_address, :user_agent
                )
                """,
                values,
            )
            participant_id = cursor.lastrowid
            activity_type = "entered"

        conn.execute(
            "INSERT INTO activities (participant_id, display_name, prediction, event_type, created_at) VALUES (?, ?, ?, ?, ?)",
            (participant_id, values["display_name"], values["prediction"], activity_type, now_iso),
        )
        conn.commit()

        return JSONResponse(
            {
                "status": "updated" if existing else "created",
                "message": "Your prediction has been updated." if existing else "Your prediction is locked.",
                "participant": {
                    "id": participant_id,
                    "display_name": values["display_name"],
                    "edit_token": values["edit_token"],
                    "prediction": f"${values['prediction']:,.2f}",
                    "entry_price": f"${values['entry_price']:,.2f}",
                    "current_price": f"${live_price:,.2f}",
                    "direction": values["direction"],
                    "margin_required": f"${values['margin_required']:,.2f}",
                    "cost_of_trade": f"${values['cost_of_trade']:,.2f}",
                    "cost_of_trade_negative": f"-${values['cost_of_trade']:,.2f}",
                    "notional_value": f"${values['entry_price'] * float(units):,.2f}",
                    "spread_per_unit": f"${float(config['spread_per_unit']):,.2f}",
                    "margin_percent": float(config["margin_percent"]) * 100,
                },
            }
        )


@APP.get("/api/admin/state")
async def api_admin_state(request: Request) -> JSONResponse:
    ensure_admin(request)
    with closing(db_connect()) as conn:
        config = get_config(conn)
        state = await current_market_state(conn)
        participants = list(
            conn.execute(
                "SELECT * FROM participants ORDER BY is_disqualified ASC, updated_at DESC"
            ).fetchall()
        )
        participant_rows = []
        reference_price = state["final_reference_price"] or state["live_price"]
        for participant in participants:
            metrics = calculate_row_metrics(participant, state["live_price"], reference_price)
            metrics.update(
                {
                    "email": participant["email"],
                    "phone": participant["phone"],
                    "country": participant["country"],
                    "industry": participant["industry"],
                    "company": participant["company"],
                    "job_title": participant["job_title"],
                    "product_interest": participant["product_interest"],
                    "marketing_opt_in": bool(participant["marketing_opt_in"]),
                    "updated_at": participant["updated_at"],
                    "is_disqualified": bool(participant["is_disqualified"]),
                    "disqualification_reason": participant["disqualification_reason"],
                }
            )
            participant_rows.append(metrics)
        return JSONResponse(
            {
                "config": config,
                "state": {
                    "phase": state["phase"],
                    "entry_open": state["entry_open"],
                    "live_price": state["live_price"],
                    "price_source": state["price_source"],
                    "final_reference_price": state["final_reference_price"],
                    "entry_lock_iso": iso(state["times"].entry_lock),
                    "final_time_iso": iso(state["times"].final_time),
                    "now_iso": iso(state["now"]),
                },
                "participants": participant_rows,
            }
        )


@APP.post("/api/admin/config")
async def api_admin_config(request: Request, payload: AdminConfigPayload) -> JSONResponse:
    ensure_admin(request)
    with closing(db_connect()) as conn:
        config = get_config(conn)
        updates = payload.model_dump()
        public_url = (updates.get("public_base_url") or "").strip()
        if public_url:
            updates["public_base_url"] = public_url if public_url.endswith("/") else f"{public_url}/"
        config.update(updates)
        save_config(conn, config)
        return JSONResponse({"status": "ok", "message": "Settings updated."})


@APP.post("/api/admin/disqualify/{participant_id}")
async def api_admin_disqualify(participant_id: int, request: Request, reason: str = Form("Manual review")) -> JSONResponse:
    ensure_admin(request)
    with closing(db_connect()) as conn:
        participant = conn.execute("SELECT * FROM participants WHERE id = ?", (participant_id,)).fetchone()
        if not participant:
            raise HTTPException(status_code=404, detail="Participant not found.")
        conn.execute(
            "UPDATE participants SET is_disqualified = 1, disqualification_reason = ? WHERE id = ?",
            (reason, participant_id),
        )
        conn.execute(
            "INSERT INTO activities (participant_id, display_name, prediction, event_type, created_at) VALUES (?, ?, ?, ?, ?)",
            (participant_id, participant["display_name"], participant["prediction"], "disqualified", iso(now_bermuda())),
        )
        conn.commit()
        return JSONResponse({"status": "ok"})


@APP.post("/api/admin/reinstate/{participant_id}")
async def api_admin_reinstate(participant_id: int, request: Request) -> JSONResponse:
    ensure_admin(request)
    with closing(db_connect()) as conn:
        participant = conn.execute("SELECT * FROM participants WHERE id = ?", (participant_id,)).fetchone()
        if not participant:
            raise HTTPException(status_code=404, detail="Participant not found.")
        conn.execute(
            "UPDATE participants SET is_disqualified = 0, disqualification_reason = NULL WHERE id = ?",
            (participant_id,),
        )
        conn.execute(
            "INSERT INTO activities (participant_id, display_name, prediction, event_type, created_at) VALUES (?, ?, ?, ?, ?)",
            (participant_id, participant["display_name"], participant["prediction"], "reinstated", iso(now_bermuda())),
        )
        conn.commit()
        return JSONResponse({"status": "ok"})


@APP.post("/api/admin/final-reference")
async def api_admin_final_reference(request: Request, price: float = Form(...)) -> JSONResponse:
    ensure_admin(request)
    if price <= 0:
        raise HTTPException(status_code=400, detail="Final reference price must be positive.")
    with closing(db_connect()) as conn:
        config = get_config(conn)
        config["final_reference_price"] = round(float(price), 2)
        config["final_reference_captured_at"] = iso(now_bermuda())
        save_config(conn, config)
        return JSONResponse({"status": "ok", "message": "Final reference price locked."})


@APP.get("/admin/export.csv")
async def admin_export_csv(request: Request) -> StreamingResponse:
    ensure_admin(request)
    with closing(db_connect()) as conn:
        participants = list(conn.execute("SELECT * FROM participants ORDER BY updated_at DESC").fetchall())
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "first_name",
                "last_name",
                "display_name",
                "email",
                "phone",
                "country",
                "industry",
                "company",
                "job_title",
                "product_interest",
                "prediction",
                "entry_price",
                "direction",
                "margin_required",
                "cost_of_trade",
                "holding_cost",
                "marketing_opt_in",
                "created_at",
                "updated_at",
                "is_disqualified",
                "disqualification_reason",
            ]
        )
        for item in participants:
            writer.writerow(
                [
                    item["first_name"],
                    item["last_name"],
                    item["display_name"],
                    item["email"],
                    item["phone"],
                    item["country"],
                    item["industry"],
                    item["company"],
                    item["job_title"],
                    item["product_interest"],
                    item["prediction"],
                    item["entry_price"],
                    item["direction"],
                    item["margin_required"],
                    item["cost_of_trade"],
                    item["holding_cost"],
                    item["marketing_opt_in"],
                    item["created_at"],
                    item["updated_at"],
                    item["is_disqualified"],
                    item["disqualification_reason"],
                ]
            )
        output.seek(0)
        filename = f"cmc-btc-price-lock-leads-{now_bermuda().strftime('%Y%m%d-%H%M%S')}.csv"
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )


@APP.post("/api/admin/send-summary")
async def api_admin_send_summary(request: Request) -> JSONResponse:
    ensure_admin(request)
    smtp_host = os.environ.get("SMTP_HOST")
    smtp_user = os.environ.get("SMTP_USER")
    smtp_pass = os.environ.get("SMTP_PASS")
    smtp_from = os.environ.get("SMTP_FROM")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))

    if not all([smtp_host, smtp_user, smtp_pass, smtp_from]):
        raise HTTPException(status_code=400, detail="SMTP is not configured. Use CSV export or set SMTP env vars.")

    with closing(db_connect()) as conn:
        config = get_config(conn)
        participants = list(conn.execute("SELECT * FROM participants ORDER BY updated_at DESC").fetchall())
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["display_name", "email", "phone", "industry", "prediction", "updated_at", "marketing_opt_in"])
        for item in participants:
            writer.writerow(
                [
                    item["display_name"],
                    item["email"],
                    item["phone"],
                    item["industry"],
                    item["prediction"],
                    item["updated_at"],
                    item["marketing_opt_in"],
                ]
            )
        msg = EmailMessage()
        msg["Subject"] = f"CMC BTC Price Lock leads - {now_bermuda().strftime('%Y-%m-%d %H:%M %Z')}"
        msg["From"] = smtp_from
        msg["To"] = config["lead_export_email"]
        msg.set_content("Attached is the current lead export from the BTC Price Lock activation.")
        msg.add_attachment(output.getvalue().encode("utf-8"), maintype="text", subtype="csv", filename="leads.csv")
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        return JSONResponse({"status": "ok", "message": f"Summary sent to {config['lead_export_email']}"})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:APP", host="0.0.0.0", port=8000, reload=True)
