#!/usr/bin/env python3
"""Rollcall — a dependency-free local prototype with a real SQLite/API boundary."""
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import smtplib
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from attendance import LABELS, STATUSES, entry_status, exit_status

ROOT = Path(__file__).resolve().parent
for line in (ROOT / ".env").read_text().splitlines() if (ROOT / ".env").exists() else []:
    if line.strip() and not line.lstrip().startswith("#") and "=" in line:
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

JST = timezone(timedelta(hours=9))  # fixed offset: no DST, and Windows lacks tzdata
DEMO = os.getenv("DEMO_MODE", "1") == "1"
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "3000"))
PUBLIC_URL = os.getenv("PUBLIC_URL", f"http://{HOST}:{PORT}").rstrip("/")  # base of the login link in the mail
DB_PATH = Path(os.getenv("DATABASE_PATH", str(ROOT / "data" / "rollcall.sqlite3")))
LOCK = threading.RLock()
RATE = {}


def now():
    return datetime.now(JST)


def stamp():
    return now().isoformat(timespec="seconds")


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(password):
    salt = secrets.token_hex(16)
    return salt + ":" + hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1).hex()


def password_ok(password, stored):
    salt, expected = stored.split(":")
    actual = hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1).hex()
    return hmac.compare_digest(actual, expected)


@contextmanager
def database():
    with LOCK:
        connection = sqlite3.connect(DB_PATH)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()


def rows(db, sql, args=()):
    return [dict(r) for r in db.execute(sql, args).fetchall()]


def one(db, sql, args=()):
    row = db.execute(sql, args).fetchone()
    return dict(row) if row else None


def audit(db, actor, action, detail):
    db.execute("INSERT INTO audit(actor,action,detail,created_at) VALUES(?,?,?,?)", (actor, action, detail, stamp()))


def initialize():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with database() as db:
        db.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS students(id TEXT PRIMARY KEY,name TEXT NOT NULL,email TEXT NOT NULL UNIQUE,
          card_id TEXT NOT NULL UNIQUE,year INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS admins(id TEXT PRIMARY KEY,name TEXT NOT NULL,password_hash TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS courses(id INTEGER PRIMARY KEY,name TEXT NOT NULL,code TEXT NOT NULL UNIQUE,
          teacher TEXT NOT NULL,room TEXT NOT NULL,year INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS enrollments(student_id TEXT REFERENCES students(id) ON DELETE CASCADE,
          course_id INTEGER REFERENCES courses(id) ON DELETE CASCADE,PRIMARY KEY(student_id,course_id));
        CREATE TABLE IF NOT EXISTS lessons(id INTEGER PRIMARY KEY,course_id INTEGER REFERENCES courses(id) ON DELETE CASCADE,
          day TEXT NOT NULL,first_start TEXT NOT NULL,first_end TEXT NOT NULL,second_start TEXT NOT NULL,
          second_end TEXT NOT NULL,UNIQUE(course_id,day));
        CREATE TABLE IF NOT EXISTS records(id INTEGER PRIMARY KEY,student_id TEXT REFERENCES students(id) ON DELETE CASCADE,
          lesson_id INTEGER REFERENCES lessons(id) ON DELETE CASCADE,entry_at TEXT,exit_at TEXT,
          first_auto TEXT NOT NULL,second_auto TEXT NOT NULL,first_override TEXT,second_override TEXT,
          reason TEXT NOT NULL DEFAULT '',confirmed INTEGER NOT NULL DEFAULT 0,updated_at TEXT NOT NULL,
          UNIQUE(student_id,lesson_id));
        CREATE TABLE IF NOT EXISTS challenges(id INTEGER PRIMARY KEY,student_id TEXT REFERENCES students(id) ON DELETE CASCADE,
          record_id INTEGER REFERENCES records(id) ON DELETE CASCADE,code_hash TEXT NOT NULL,
          expires_at REAL NOT NULL,used INTEGER NOT NULL DEFAULT 0);
        CREATE INDEX IF NOT EXISTS challenge_code ON challenges(code_hash);
        CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY,role TEXT NOT NULL,user_id TEXT NOT NULL,
          record_id INTEGER,csrf TEXT NOT NULL,expires_at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS mail(id INTEGER PRIMARY KEY,student_id TEXT REFERENCES students(id) ON DELETE CASCADE,
          recipient TEXT NOT NULL,subject TEXT NOT NULL,body TEXT NOT NULL,kind TEXT NOT NULL,created_at TEXT NOT NULL,
          delivery TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,next_attempt REAL NOT NULL DEFAULT 0,error TEXT);
        CREATE TABLE IF NOT EXISTS card_events(event_id TEXT PRIMARY KEY,result TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,actor TEXT NOT NULL,action TEXT NOT NULL,
          detail TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS usage_log(id INTEGER PRIMARY KEY,student_id TEXT REFERENCES students(id) ON DELETE CASCADE,
          action TEXT NOT NULL,detail TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS warnings(student_id TEXT REFERENCES students(id) ON DELETE CASCADE,
          course_id INTEGER REFERENCES courses(id) ON DELETE CASCADE,remaining INTEGER NOT NULL,PRIMARY KEY(student_id,course_id));
        """)
        # Older databases predate the exit-by-login flow.
        for table, column, declaration in (("records", "pending_exit_at", "TEXT"),
                                           ("challenges", "purpose", "TEXT NOT NULL DEFAULT 'entry'"),
                                           ("sessions", "purpose", "TEXT NOT NULL DEFAULT 'entry'")):
            if column not in {r["name"] for r in db.execute(f"PRAGMA table_info({table})")}:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")
        if not one(db, "SELECT * FROM settings WHERE key='otp_secret'"):
            db.execute("INSERT INTO settings VALUES('otp_secret',?)", (secrets.token_hex(32),))
        if not one(db, "SELECT * FROM settings WHERE key='initialized'"):
            initial_password = os.getenv("ADMIN_PASSWORD") or ("teacher123" if DEMO else "")
            if not initial_password:
                raise RuntimeError("本番の初回起動には ADMIN_PASSWORD を設定してください。")
            db.execute("INSERT INTO admins VALUES(?,?,?)", (os.getenv("ADMIN_ID", "teacher"),
                       os.getenv("ADMIN_NAME", "山田 太郎"), password_hash(initial_password)))
            if DEMO:
                seed(db)
            db.execute("INSERT INTO settings VALUES('initialized','1')")
        # Never carry over demo credentials or data silently into a server deployment.
        if DEMO:
            db.execute("INSERT OR IGNORE INTO settings VALUES('demo_database','1')")
        elif one(db, "SELECT * FROM settings WHERE key='demo_database'"):
            raise RuntimeError("デモDBは本番で使えません。DATABASE_PATH に新しいDBのパスを指定してください。")


def seed(db):
    people = [("24C1001", "佐藤 花", "hana.sato@example.edu", "CARD-001", 2026),
              ("24C1002", "鈴木 蓮", "ren.suzuki@example.edu", "CARD-002", 2026),
              ("24C1003", "高橋 凛", "rin.takahashi@example.edu", "CARD-003", 2026),
              ("24C1004", "田中 陽", "haru.tanaka@example.edu", "CARD-004", 2026),
              ("24C1005", "伊藤 葵", "aoi.ito@example.edu", "CARD-005", 2026)]
    db.executemany("INSERT INTO students VALUES(?,?,?,?,?)", people)
    today = now().date()
    for index, (name, code, room, offset, times) in enumerate([
        ("ソフトウェア工学", "CS301", "A棟 302", 0, ("09:00", "09:45", "09:45", "10:30")),
        ("データベース", "CS204", "B棟 201", 0, ("13:00", "13:45", "13:45", "14:30")),
        ("情報ネットワーク", "CS302", "A棟 405", 1, ("09:00", "09:45", "09:45", "10:30"))], 1):
        db.execute("INSERT INTO courses VALUES(?,?,?,?,?,?)", (index, name, code, "山田 太郎", room, today.year))
        for person in people:
            db.execute("INSERT INTO enrollments VALUES(?,?)", (person[0], index))
        for week in range(-7, 7):
            day = (today + timedelta(days=offset + week * 7)).isoformat()
            lesson = db.execute("INSERT INTO lessons(course_id,day,first_start,first_end,second_start,second_end) VALUES(?,?,?,?,?,?)",
                                (index, day, *times)).lastrowid
            if week < 0:
                for person_index, person in enumerate(people):
                    first = "present"
                    second = "present"
                    if (week + person_index + index) % 11 == 0:
                        first = second = "absent"
                    elif (week + person_index + index) % 7 == 0:
                        first = "late"
                    elif (week + person_index + index) % 13 == 0:
                        second = "early"
                    entry = f"{day}T{times[0]}:00+09:00" if first != "absent" else None
                    db.execute("INSERT INTO records(student_id,lesson_id,entry_at,first_auto,second_auto,confirmed,updated_at) VALUES(?,?,?,?,?,1,?)",
                               (person[0], lesson, entry, first, second, stamp()))


def effective(record):
    record = dict(record)
    record["first_status"] = record.get("first_override") or record["first_auto"]
    record["second_status"] = record.get("second_override") or record["second_auto"]
    return record


RECORD_QUERY = """SELECT r.*,l.day,l.first_start,l.first_end,l.second_start,l.second_end,
 c.name course_name,c.code course_code,c.id course_id,c.room,s.name student_name,s.email,s.card_id
 FROM records r JOIN lessons l ON l.id=r.lesson_id JOIN courses c ON c.id=l.course_id
 JOIN students s ON s.id=r.student_id """


def get_record(db, record_id):
    result = one(db, RECORD_QUERY + "WHERE r.id=?", (record_id,))
    return effective(result) if result else None


def enqueue(db, student_id, subject, body, kind):
    student = one(db, "SELECT * FROM students WHERE id=?", (student_id,))
    db.execute("INSERT INTO mail(student_id,recipient,subject,body,kind,created_at,delivery) VALUES(?,?,?,?,?,?,?)",
               (student_id, student["email"], subject, body, kind, stamp(), "local" if DEMO else "queued"))


LINK_SECONDS = 600  # how long a login link works; it is random and single use
LINK_FAILURES = 10  # bad links per minute per IP before login is paused
SESSION_MIN = 600  # seconds a login lasts at least, even when the scan is within 15 minutes of the lesson's end
WARN_REMAINING = 2  # warn when this many absent periods (or fewer) are left before the limit
LIMIT_DIVISOR = 3   # absence limit = one third of the course's periods (assumed; adjust to the school's rule)


def clock(value):
    return datetime.fromisoformat(value).astimezone(JST).strftime("%Y/%m/%d %H:%M:%S") if value else "記録なし"


def usage(db, student_id, action, detail=""):
    db.execute("INSERT INTO usage_log(student_id,action,detail,created_at) VALUES(?,?,?,?)", (student_id, action, detail, stamp()))


def history_rows(db, student_id, course_id=None):
    """The student's records, plus an implied absence for every ended lesson with no record."""
    extra, args = (" AND c.id=?", (student_id, course_id)) if course_id else ("", (student_id,))
    records = [effective(r) for r in rows(db, RECORD_QUERY + "WHERE r.student_id=?" + extra, args)]
    lessons = rows(db, "SELECT l.*,c.name course_name,c.room,c.code course_code FROM lessons l JOIN courses c ON c.id=l.course_id JOIN enrollments e ON e.course_id=c.id WHERE e.student_id=?" + extra + " ORDER BY l.day,l.first_start", args)
    existing = {r["lesson_id"] for r in records}
    for lesson in lessons:
        if lesson["id"] not in existing and f"{lesson['day']}T{lesson['second_end']}" < now().strftime("%Y-%m-%dT%H:%M"):
            records.append({**lesson, "id": None, "lesson_id": lesson["id"], "student_id": student_id,
                            "entry_at": None, "exit_at": None, "first_status": "absent", "second_status": "absent",
                            "first_auto": "absent", "second_auto": "absent", "confirmed": 1, "reason": ""})
    ended = now().strftime("%Y-%m-%dT%H:%M")
    for r in records:  # scanned but never confirmed by the end of the lesson: absent, unless a teacher set a status
        if not r["confirmed"] and f"{r['day']}T{r['second_end']}" < ended:
            r["first_status"], r["second_status"] = r.get("first_override") or "absent", r.get("second_override") or "absent"
            r["confirmed"] = 1
    records.sort(key=lambda r: (r["day"], r["first_start"]), reverse=True)
    return records, lessons


def absence_summary(db, student_id, course_id):
    records, lessons = history_rows(db, student_id, course_id)
    absent = sum(r[key] == "absent" for r in records if r["confirmed"] for key in ("first_status", "second_status"))
    limit = len(lessons) * 2 // LIMIT_DIVISOR  # lessons have two periods each; only absences count, not late/early
    return {"course_id": course_id, "absent": absent, "limit": limit, "remaining": limit - absent}


def warn_absences(db, student_id, course_id):
    """Mail once per change in the remaining allowance when it is close to (or past) the limit."""
    s = absence_summary(db, student_id, course_id)
    if s["limit"] < 1 or s["remaining"] > WARN_REMAINING:
        db.execute("DELETE FROM warnings WHERE student_id=? AND course_id=?", (student_id, course_id))
        return
    last = one(db, "SELECT remaining FROM warnings WHERE student_id=? AND course_id=?", (student_id, course_id))
    if last and last["remaining"] == s["remaining"]:
        return
    db.execute("INSERT OR REPLACE INTO warnings VALUES(?,?,?)", (student_id, course_id, s["remaining"]))
    student = one(db, "SELECT name FROM students WHERE id=?", (student_id,))
    course = one(db, "SELECT name FROM courses WHERE id=?", (course_id,))
    reached = s["remaining"] <= 0
    state = "欠席が上限に達しています。" if reached else f"あと {s['remaining']} コマ欠席すると上限に達します。"
    enqueue(db, student_id, f"{course['name']}：欠席が上限に達しました" if reached else f"{course['name']}：欠席が上限に近づいています",
            f"{student['name']} さん\n\n{course['name']} の欠席が上限{'に達しました' if reached else 'に近づいています'}。\n\n"
            f"欠席：{s['absent']} コマ / 上限：{s['limit']} コマ\n{state}\n※遅刻・早退は欠席に数えません。\n\nRollcall 出席管理", "warning")


def notify_record(db, record_id, subject, kind):
    record = get_record(db, record_id)
    content = (f"{record['student_name']} さん\n\n{subject}\n\n"
               f"{record['day']}  {record['course_name']}\n"
               f"1コマ目：{LABELS[record['first_status']]}\n2コマ目：{LABELS[record['second_status']]}\n"
               f"入室：{clock(record['entry_at'])}\n退室：{clock(record['exit_at'])}\n")
    if record["reason"]:
        content += f"変更理由：{record['reason']}\n"
    if kind == "confirmation":  # entry-confirmation mail also lists this course's attendance so far
        past, _ = history_rows(db, record["student_id"], record["course_id"])
        content += f"\n--- {record['course_name']} のここまでの出席状況 ---\n" + "".join(
            f"{r['day']}  1コマ目：{LABELS[r['first_status']]} / 2コマ目：{LABELS[r['second_status']]}\n"
            for r in reversed(past) if r["confirmed"])
    enqueue(db, record["student_id"], subject, content + "\nRollcall 出席管理", kind)


def token_hash(db, code):
    key = one(db, "SELECT value FROM settings WHERE key='otp_secret'")["value"]
    return hmac.new(key.encode(), code.encode(), hashlib.sha256).hexdigest()


def school_networks():
    return [ipaddress.ip_network(n.strip(), strict=False) for n in os.getenv("ALLOWED_NETWORKS", "").split(",") if n.strip()]


def on_school_network(ip):
    """True when ip is inside ALLOWED_NETWORKS. Without that setting only the local demo is open to everyone."""
    networks = school_networks()
    if not networks:
        return DEMO
    address = ipaddress.ip_address(ip.split("%")[0])
    address = getattr(address, "ipv4_mapped", None) or address
    return any(address in network for network in networks)


class APIError(Exception):
    def __init__(self, message, status=400):
        self.message, self.status = message, status


def require(value, message):
    if not value:
        raise APIError(message)


def text_field(data, key, limit=120):
    value = data.get(key, "")
    require(isinstance(value, str) and 0 < len(value.strip()) <= limit, f"{key} を正しく入力してください。")
    return value.strip()


def issue_link(db, student_id, record_id, purpose, occurred):
    """One random link per card scan: it logs the student in for exactly this lesson record and purpose."""
    token = secrets.token_urlsafe(32)  # 43 characters, 256 bits: cannot be guessed
    db.execute("UPDATE challenges SET used=1 WHERE student_id=? AND used=0", (student_id,))
    db.execute("INSERT INTO challenges(student_id,record_id,code_hash,expires_at,purpose) VALUES(?,?,?,?,?)",
               (student_id, record_id, token_hash(db, token), time.time() + LINK_SECONDS, purpose))
    record = get_record(db, record_id)
    what = "出席手続き" if purpose == "entry" else "退室（早退）の手続き"
    # The token is in the URL fragment, so it never reaches server logs or Referer headers, and mail scanners that only fetch the page cannot use it up.
    enqueue(db, student_id, "出席確認のログインリンク" if purpose == "entry" else "退室手続きのログインリンク",
            f"{record['course_name']} の{what}用のログインリンクです。\n学内ネットワークで、次のリンクを開いてください。\n\n"
            f"{PUBLIC_URL}/#login={token}\n\n有効期限は{LINK_SECONDS // 60}分で、1回しか使えません。他の人に送らないでください。\n"
            f"カード読取：{occurred.strftime('%Y/%m/%d %H:%M:%S')}\n\nRollcall 出席管理", "login")


def event(db, data):
    event_id = text_field(data, "event_id")
    existing = one(db, "SELECT * FROM card_events WHERE event_id=?", (event_id,))
    if existing:
        return json.loads(existing["result"])
    if data.get("card_id"):
        card_owner = one(db, "SELECT id FROM students WHERE card_id=?", (text_field(data, "card_id", 80),))
        require(card_owner, "未登録のカードです。")
        student_id = card_owner["id"]
        require(not data.get("student_id") or data["student_id"] == student_id, "カードと学生の紐付けが一致しません。")
    else:
        student_id = text_field(data, "student_id")
    lesson = one(db, "SELECT * FROM lessons WHERE id=?", (data.get("lesson_id"),))
    require(lesson, "授業が見つかりません。")
    require(one(db, "SELECT * FROM enrollments WHERE student_id=? AND course_id=?", (student_id, lesson["course_id"])),
            "この学生は授業に登録されていません。")
    try:
        occurred = datetime.fromisoformat(data["occurred_at"])
        require(occurred.tzinfo is not None, "時刻にはタイムゾーンが必要です。")
        occurred = occurred.astimezone(JST)
    except (ValueError, KeyError, TypeError):
        raise APIError("カード読取時刻を ISO 8601 形式で指定してください。")
    require(occurred.date().isoformat() == lesson["day"], "授業日とカード読取日が一致しません。")
    if not DEMO:
        require(-60 <= (now() - occurred).total_seconds() <= 300, "カード読取時刻が受付範囲外です。")
    record = one(db, "SELECT * FROM records WHERE student_id=? AND lesson_id=?", (student_id, lesson["id"]))
    mode = data.get("mode")
    if mode == "entry":
        repeated_entry = bool(record and record["entry_at"])
        if repeated_entry:
            record_id = record["id"]
        elif record:
            first, second = entry_status(lesson, occurred)
            record_id = record["id"]
            db.execute("UPDATE records SET entry_at=?,first_auto=?,second_auto=?,updated_at=? WHERE id=?",
                       (occurred.isoformat(), first, second, stamp(), record_id))
        else:
            first, second = entry_status(lesson, occurred)
            record_id = db.execute("INSERT INTO records(student_id,lesson_id,entry_at,first_auto,second_auto,updated_at) VALUES(?,?,?,?,?,?)",
                                   (student_id, lesson["id"], occurred.isoformat(), first, second, stamp())).lastrowid
        issue_link(db, student_id, record_id, "entry", occurred)
        result = {"record_id": record_id, "message": "入室時刻を維持し、ログインリンクを再送しました。" if repeated_entry else "入室を記録し、ログインリンクを送りました。"}
    elif mode == "exit":
        require(record and record["entry_at"], "先に入室カードを読み取ってください。")
        require(record["confirmed"], "先に出席手続きを完了してください。")
        require(not record["exit_at"], "この授業の退室はすでに記録されています。")
        pending = record["pending_exit_at"] or occurred.isoformat()  # the first exit scan fixes the time
        exit_status(lesson, datetime.fromisoformat(record["entry_at"]), datetime.fromisoformat(pending))  # validates order
        record_id = record["id"]
        db.execute("UPDATE records SET pending_exit_at=?,updated_at=? WHERE id=?", (pending, stamp(), record_id))
        issue_link(db, student_id, record_id, "exit", occurred)
        result = {"record_id": record_id, "message": "退室を記録しました。メールのログインリンクを開き、退室を提出してください。"}
    else:
        raise APIError("mode は entry または exit にしてください。")
    course = one(db, "SELECT name FROM courses WHERE id=?", (lesson["course_id"],))["name"]
    usage(db, student_id, "カード読取（入室）" if mode == "entry" else "カード読取（退室）", f"{course} / {occurred.strftime('%Y/%m/%d %H:%M:%S')}")
    audit(db, "card-reader", "入室" if mode == "entry" else "退室", f"{student_id} / 授業 {lesson['id']} / {occurred.isoformat()}")
    # Never put login links in the replay log or return them from integration APIs.
    db.execute("INSERT INTO card_events VALUES(?,?)", (event_id, json.dumps(result)))
    return result


def student_data(db, student_id):
    records, lessons = history_rows(db, student_id)
    courses = rows(db, "SELECT c.* FROM courses c JOIN enrollments e ON e.course_id=c.id WHERE e.student_id=? ORDER BY c.id", (student_id,))
    for r in records:  # what the pending exit scan will become once submitted
        if r.get("pending_exit_at") and not r["exit_at"]:
            r["exit_preview"] = exit_status(r, datetime.fromisoformat(r["entry_at"]), datetime.fromisoformat(r["pending_exit_at"]))
    return {"courses": courses, "lessons": lessons, "records": records,
            "absences": [absence_summary(db, student_id, c["id"]) for c in courses],
            "usage": rows(db, "SELECT * FROM usage_log WHERE student_id=? ORDER BY id DESC LIMIT 200", (student_id,)),
            "mail": rows(db, "SELECT * FROM mail WHERE student_id=? ORDER BY id DESC LIMIT 100", (student_id,))}


def mail_worker():
    while True:
        try:
            with database() as db:
                message = one(db, "SELECT * FROM mail WHERE delivery='queued' AND next_attempt<=? ORDER BY id LIMIT 1", (time.time(),))
            if message:
                email = EmailMessage()
                email["Subject"], email["From"], email["To"] = message["subject"], os.getenv("SMTP_FROM"), message["recipient"]
                email.set_content(message["body"])
                try:
                    with smtplib.SMTP(os.getenv("SMTP_HOST"), int(os.getenv("SMTP_PORT", "587")), timeout=10) as smtp:
                        if os.getenv("SMTP_STARTTLS", "1") == "1":
                            smtp.starttls()
                        if os.getenv("SMTP_USERNAME"):
                            smtp.login(os.getenv("SMTP_USERNAME"), os.getenv("SMTP_PASSWORD", ""))
                        smtp.send_message(email)
                    with database() as db:
                        db.execute("UPDATE mail SET delivery='sent',error=NULL WHERE id=?", (message["id"],))
                except Exception as error:
                    attempts = message["attempts"] + 1
                    with database() as db:
                        db.execute("UPDATE mail SET delivery=?,attempts=?,next_attempt=?,error=? WHERE id=?",
                                   ("failed" if attempts >= 3 else "queued", attempts, time.time()+60*attempts,
                                    type(error).__name__, message["id"]))
        except Exception as error:
            print("Mail worker:", type(error).__name__)
        time.sleep(2)


class Handler(SimpleHTTPRequestHandler):
    server_version = "Rollcall/1.0"

    def log_message(self, fmt, *args):
        # Paths only: never log authentication codes, cookies or request bodies.
        if args:
            print(f"[{stamp()}] {self.command} {self.path.split('?')[0]} {args[1] if len(args)>1 else ''}")

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
        super().end_headers()

    def send_json(self, value, status=200, cookie=None):
        body = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def cookie_token(self):
        try:
            cookies = SimpleCookie(self.headers.get("Cookie", ""))
            return cookies["rollcall_session"].value if "rollcall_session" in cookies else ""
        except Exception:
            return ""

    def auth(self, db, role=None):
        token = self.cookie_token()
        session = one(db, "SELECT * FROM sessions WHERE token_hash=? AND expires_at>?", (digest(token), time.time())) if token else None
        if not session:
            raise APIError("ログインしてください。", 401)
        if role and session["role"] != role:
            raise APIError("この操作は許可されていません。", 403)
        if session["role"] == "student" and not on_school_network(self.client_address[0]):
            raise APIError("学内ネットワークからのみ利用できます。", 403)
        table = "students" if session["role"] == "student" else "admins"
        user = one(db, f"SELECT id,name FROM {table} WHERE id=?", (session["user_id"],))
        if not user:
            raise APIError("このアカウントは利用できません。", 401)
        if self.command != "GET" and not hmac.compare_digest(self.headers.get("X-CSRF-Token", ""), session["csrf"]):
            raise APIError("画面を再読み込みしてやり直してください。", 403)
        return {**session, "name": user["name"]}

    def new_session(self, db, role, user_id, record_id=None, purpose="entry", lifetime=8*3600):
        old = self.cookie_token()
        if old:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (digest(old),))
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(24)
        db.execute("INSERT INTO sessions(token_hash,role,user_id,record_id,csrf,expires_at,purpose) VALUES(?,?,?,?,?,?,?)",
                   (digest(token), role, user_id, record_id, csrf, time.time() + lifetime, purpose))
        secure = "; Secure" if os.getenv("SECURE_COOKIE", "0") == "1" else ""
        return f"rollcall_session={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={int(lifetime)}{secure}"

    def rate_limit(self, kind, limit=8, record=True):
        """Per-IP limit. record=False only checks; call rate_hit() for each failure (students share the reader PC's IP)."""
        key = (self.client_address[0], kind)
        recent = [t for t in RATE.get(key, []) if t > time.time()-60]
        if len(recent) >= limit:
            raise APIError("試行回数が多いため、1分ほど待ってからお試しください。", 429)
        if record:
            self.rate_hit(kind)

    def rate_hit(self, kind):
        if len(RATE) > 1000:  # drop IPs with no attempt in the last minute
            for stale in [k for k, v in RATE.items() if not v or v[-1] <= time.time()-60]:
                del RATE[stale]
        RATE.setdefault((self.client_address[0], kind), []).append(time.time())

    def do_GET(self):
        path = urlparse(self.path).path
        if path.startswith("/api/"):
            self.dispatch(path)
            return
        filenames = {"/": "index.html", "/index.html": "index.html", "/app.js": "app.js", "/style.css": "style.css", "/favicon.svg": "favicon.svg"}
        if path not in filenames:
            self.send_error(404)
            return
        file = ROOT / "public" / filenames[path]
        body = file.read_bytes()
        self.send_response(200)
        content_type = {".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml"}[file.suffix]
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        self.dispatch(urlparse(self.path).path)

    def do_PUT(self):
        self.dispatch(urlparse(self.path).path)

    def do_DELETE(self):
        self.dispatch(urlparse(self.path).path)

    def dispatch(self, path):
        try:
            data = {}
            if self.command != "GET":
                origin = self.headers.get("Origin")
                if origin:
                    parsed = urlparse(origin)
                    require(parsed.scheme in ("http", "https") and parsed.netloc == self.headers.get("Host"), "この送信元からは操作できません。")
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 <= length <= 65536:
                    raise APIError("送信データが大きすぎます。", 413)
                data = json.loads(self.rfile.read(length)) if length else {}
                require(isinstance(data, dict), "JSONオブジェクトを送信してください。")
            with database() as db:
                result, cookie = self.route(db, path, data)
            self.send_json(result, cookie=cookie)
        except APIError as error:
            self.send_json({"error": error.message}, error.status)
        except (ValueError, TypeError, KeyError) as error:
            # Only our own Japanese messages (e.g. from attendance.py) go to the client, not Python's English ones.
            shown = isinstance(error, ValueError) and not isinstance(error, json.JSONDecodeError) and re.search(r"[^\x00-\x7f]", str(error))
            self.send_json({"error": str(error) if shown else "入力内容を確認してください。"}, 400)
        except sqlite3.IntegrityError:
            self.send_json({"error": "ID・メールアドレス・カードID・科目コードがすでに登録されています。"}, 409)
        except Exception as error:
            print("API error:", type(error).__name__)
            self.send_json({"error": "処理に失敗しました。再度お試しください。"}, 500)

    def route(self, db, path, data):
        method = self.command
        if path == "/api/bootstrap" and method == "GET":
            try:
                session = self.auth(db)
                user = {"id": session["user_id"], "name": session["name"], "role": session["role"], "csrf": session["csrf"],
                        "record_id": session["record_id"], "purpose": session["purpose"], "expires_at": session["expires_at"]}
            except APIError:
                user = None
            return {"user": user, "demo": DEMO, "today": now().date().isoformat(), "now": stamp()}, None
        if path == "/api/auth/link" and method == "POST":
            if not on_school_network(self.client_address[0]):
                raise APIError("学内ネットワークからのみ利用できます。", 403)
            self.rate_limit("link", LINK_FAILURES, record=False)  # only bad links count; many students log in from one PC
            token = str(data.get("token", ""))
            require(re.fullmatch(r"[A-Za-z0-9_-]{43}", token), "ログインリンクが正しくありません。")
            challenge = one(db, "SELECT * FROM challenges WHERE code_hash=? AND used=0 AND expires_at>?", (token_hash(db, token), time.time()))
            if not challenge:
                self.rate_hit("link")
                raise APIError("ログインリンクが無効か、有効期限が切れています。カードをもう一度かざしてください。", 401)
            db.execute("UPDATE challenges SET used=1 WHERE id=?", (challenge["id"],))
            db.execute("DELETE FROM sessions WHERE expires_at<?", (time.time(),))
            record = get_record(db, challenge["record_id"])
            # The session ends 15 minutes before the lesson does, so the next class needs a fresh card scan.
            end = datetime.fromisoformat(f"{record['day']}T{record['second_end']}+09:00") - timedelta(minutes=15)
            lifetime = min(max(end.timestamp() - time.time(), SESSION_MIN), 8 * 3600)
            usage(db, challenge["student_id"], "ログイン", f"{record['course_name']} / {'退室' if challenge['purpose'] == 'exit' else '入室'}")
            return {"ok": True}, self.new_session(db, "student", challenge["student_id"], challenge["record_id"], challenge["purpose"], lifetime)
        if path == "/api/auth/admin" and method == "POST":
            self.rate_limit("admin")
            admin = one(db, "SELECT * FROM admins WHERE id=?", (str(data.get("id", "")),))
            valid = password_ok(str(data.get("password", "")), admin["password_hash"] if admin else DUMMY_HASH)
            if not admin or not valid:
                raise APIError("ユーザーIDまたはパスワードが正しくありません。", 401)
            return {"ok": True}, self.new_session(db, "admin", admin["id"])
        if path == "/api/auth/logout" and method == "POST":
            session = self.auth(db)
            if session["role"] == "student":
                usage(db, session["user_id"], "ログアウト")
            db.execute("DELETE FROM sessions WHERE token_hash=?", (digest(self.cookie_token()),))
            return {"ok": True}, "rollcall_session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0"
        if path == "/api/integrations/card-events" and method == "POST":
            token = os.getenv("INTEGRATION_TOKEN", "")
            if not token or not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + token):
                raise APIError("連携キーが正しくありません。", 401)
            return event(db, data), None
        if path.startswith("/api/demo/"):
            if not DEMO:
                raise APIError("この機能はデモ環境でのみ利用できます。", 404)
            if path == "/api/demo/data" and method == "GET":
                students = rows(db, "SELECT * FROM students ORDER BY id")
                lessons = rows(db, "SELECT l.*,c.name course_name FROM lessons l JOIN courses c ON c.id=l.course_id WHERE l.day>=? ORDER BY l.day,l.first_start LIMIT 30", (now().date().isoformat(),))
                return {"students": students, "lessons": lessons, "enrollments": rows(db, "SELECT * FROM enrollments"),
                        "mail": rows(db, "SELECT * FROM mail ORDER BY id DESC LIMIT 100")}, None
            if path == "/api/demo/event" and method == "POST":
                self.rate_limit("demo", 30)
                data["event_id"] = "demo-" + secrets.token_hex(12)
                return event(db, data), None
        if path == "/api/student/data" and method == "GET":
            session = self.auth(db, "student")
            return student_data(db, session["user_id"]), None
        if path == "/api/student/confirm" and method == "POST":
            session = self.auth(db, "student")
            record = get_record(db, session["record_id"])
            require(record and record["student_id"] == session["user_id"] and session["purpose"] == "entry", "認証済みのカード読取記録がありません。")
            if not record["confirmed"]:
                db.execute("UPDATE records SET confirmed=1,updated_at=? WHERE id=?", (stamp(), record["id"]))
                notify_record(db, record["id"], "出席手続きが完了しました", "confirmation")
                warn_absences(db, record["student_id"], record["course_id"])
                usage(db, record["student_id"], "出席手続き", record["course_name"])
                audit(db, session["user_id"], "出席手続き", f"記録 {record['id']}")
            return {"ok": True, "message": "出席手続きが完了しました。"}, None
        if path == "/api/student/submit-exit" and method == "POST":
            session = self.auth(db, "student")
            record = get_record(db, session["record_id"])
            require(record and record["student_id"] == session["user_id"] and session["purpose"] == "exit"
                    and record["pending_exit_at"] and not record["exit_at"], "提出できる退室の記録がありません。退室カードを読み取り、新しいコードでログインしてください。")
            first, second = exit_status(record, datetime.fromisoformat(record["entry_at"]), datetime.fromisoformat(record["pending_exit_at"]))
            db.execute("UPDATE records SET exit_at=pending_exit_at,pending_exit_at=NULL,first_auto=?,second_auto=?,updated_at=? WHERE id=?",
                       (first, second, stamp(), record["id"]))
            notify_record(db, record["id"], "退室の手続きが完了しました", "exit")
            warn_absences(db, record["student_id"], record["course_id"])
            usage(db, record["student_id"], "退室を提出", record["course_name"])
            audit(db, session["user_id"], "退室提出", f"記録 {record['id']}")
            return {"ok": True, "message": "退室の手続きが完了しました。"}, None
        if path.startswith("/api/admin/"):
            session = self.auth(db, "admin")
            actor = session["name"]
            if path == "/api/admin/data" and method == "GET":
                people = rows(db, "SELECT * FROM students ORDER BY id")
                all_records = []
                for student in people:
                    for record in student_data(db, student["id"])["records"]:
                        all_records.append({**record, "student_name": student["name"], "email": student["email"]})
                return {"students": people, "courses": rows(db, "SELECT * FROM courses ORDER BY id"),
                        "enrollments": rows(db, "SELECT * FROM enrollments"),
                        "lessons": rows(db, "SELECT l.*,c.name course_name,c.room FROM lessons l JOIN courses c ON c.id=l.course_id ORDER BY day,first_start"),
                        "records": all_records, "admins": rows(db, "SELECT id,name FROM admins ORDER BY id"),
                        "audit": rows(db, "SELECT * FROM audit ORDER BY id DESC LIMIT 100"),
                        "mail": rows(db, "SELECT * FROM mail ORDER BY id DESC LIMIT 100")}, None
            if path == "/api/admin/records" and method == "PUT":
                student_id = text_field(data, "student_id")
                lesson_id = data.get("lesson_id")
                require(data.get("first_status") in STATUSES and data.get("second_status") in STATUSES, "出席区分を選択してください。")
                reason = text_field(data, "reason", 500)
                require(one(db, "SELECT e.* FROM enrollments e JOIN lessons l ON l.course_id=e.course_id WHERE e.student_id=? AND l.id=?", (student_id, lesson_id)), "受講登録が見つかりません。")
                existing = one(db, "SELECT * FROM records WHERE student_id=? AND lesson_id=?", (student_id, lesson_id))
                if not existing:
                    record_id = db.execute("INSERT INTO records(student_id,lesson_id,first_auto,second_auto,confirmed,updated_at) VALUES(?,?,'absent','absent',1,?)", (student_id, lesson_id, stamp())).lastrowid
                else:
                    record_id = existing["id"]
                before = get_record(db, record_id)
                db.execute("UPDATE records SET first_override=?,second_override=?,reason=?,updated_at=? WHERE id=?",
                           (data["first_status"], data["second_status"], reason, stamp(), record_id))
                notify_record(db, record_id, "教員が出席状況を変更しました", "correction")
                warn_absences(db, student_id, before["course_id"])
                audit(db, actor, "出席記録の変更", f"{student_id} / {before['day']} {before['course_name']} / {LABELS[before['first_status']]}・{LABELS[before['second_status']]} → {LABELS[data['first_status']]}・{LABELS[data['second_status']]} / {reason}")
                return {"ok": True, "message": "出席記録を変更し、学生に通知しました。"}, None
            if path == "/api/admin/students" and method in ("POST", "PUT"):
                student_id = text_field(data, "id", 30)
                name = text_field(data, "name", 60)
                email = text_field(data, "email", 200)
                card_id = text_field(data, "card_id", 80)
                require(re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", email), "メールアドレスを確認してください。")
                year = int(data.get("year", now().year))
                require(2000 <= year <= 2100, "年度を確認してください。")
                course_ids = data.get("course_ids", [])
                require(isinstance(course_ids, list) and len(course_ids) <= 100, "科目を確認してください。")
                for cid in course_ids:
                    require(one(db, "SELECT id FROM courses WHERE id=?", (cid,)), "科目が見つかりません。")
                if method == "POST":
                    db.execute("INSERT INTO students VALUES(?,?,?,?,?)", (student_id, name, email, card_id, year))
                else:
                    require(one(db, "SELECT id FROM students WHERE id=?", (student_id,)), "学生が見つかりません。")
                    db.execute("UPDATE students SET name=?,email=?,card_id=?,year=? WHERE id=?", (name, email, card_id, year, student_id))
                    db.execute("DELETE FROM enrollments WHERE student_id=?", (student_id,))
                for cid in set(course_ids):
                    db.execute("INSERT INTO enrollments VALUES(?,?)", (student_id, cid))
                audit(db, actor, "学生の登録" if method == "POST" else "学生情報の変更", student_id + " " + name)
                return {"ok": True}, None
            if path == "/api/admin/students" and method == "DELETE":
                sid = text_field(data, "id")
                require(one(db, "SELECT id FROM students WHERE id=?", (sid,)), "学生が見つかりません。")
                db.execute("DELETE FROM sessions WHERE role='student' AND user_id=?", (sid,))
                db.execute("DELETE FROM students WHERE id=?", (sid,))
                audit(db, actor, "学生の削除", sid)
                return {"ok": True}, None
            if path == "/api/admin/courses" and method == "POST":
                name = text_field(data, "name")
                code = text_field(data, "code", 30)
                teacher = text_field(data, "teacher", 60)
                room = text_field(data, "room", 60)
                year = int(data.get("year", now().year))
                require(2000 <= year <= 2100, "年度を確認してください。")
                times = [text_field(data, k, 5) for k in ("first_start", "first_end", "second_start", "second_end")]
                require(all(re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", t) for t in times) and times[0] < times[1] <= times[2] < times[3], "2コマの開始・終了時刻を順番に設定してください（1コマ目の終了と2コマ目の開始は同じ時刻でも構いません）。")
                require(all(datetime.strptime(times[i+1], "%H:%M")-datetime.strptime(times[i], "%H:%M") >= timedelta(minutes=30) for i in (0, 2)), "各コマは30分以上にしてください。")
                day = datetime.strptime(text_field(data, "start_date", 10), "%Y-%m-%d").date()
                count = int(data.get("weeks", 15))
                require(1 <= count <= 30, "授業回数は1〜30回にしてください。")
                students = data.get("student_ids", [])
                require(isinstance(students, list), "受講者を確認してください。")
                for sid in students:
                    require(one(db, "SELECT id FROM students WHERE id=?", (sid,)), "学生が見つかりません。")
                cid = db.execute("INSERT INTO courses(name,code,teacher,room,year) VALUES(?,?,?,?,?)", (name, code, teacher, room, year)).lastrowid
                for week in range(count):
                    db.execute("INSERT INTO lessons(course_id,day,first_start,first_end,second_start,second_end) VALUES(?,?,?,?,?,?)", (cid, (day+timedelta(weeks=week)).isoformat(), *times))
                for sid in set(students):
                    db.execute("INSERT INTO enrollments VALUES(?,?)", (sid, cid))
                audit(db, actor, "科目の登録", f"{name} / {count}回 / {len(students)}人")
                return {"ok": True}, None
            if path == "/api/admin/enrollments" and method == "PUT":
                cid = data.get("course_id")
                require(one(db, "SELECT id FROM courses WHERE id=?", (cid,)), "科目が見つかりません。")
                student_ids = data.get("student_ids", [])
                require(isinstance(student_ids, list), "受講者を確認してください。")
                for sid in student_ids:
                    require(one(db, "SELECT id FROM students WHERE id=?", (sid,)), "学生が見つかりません。")
                db.execute("DELETE FROM enrollments WHERE course_id=?", (cid,))
                for sid in set(student_ids):
                    db.execute("INSERT INTO enrollments VALUES(?,?)", (sid, cid))
                audit(db, actor, "受講名簿の変更", f"科目 {cid} / {len(student_ids)}人")
                return {"ok": True}, None
            if path == "/api/admin/admins" and method == "POST":
                admin_id, name = text_field(data, "id", 40), text_field(data, "name", 60)
                password = text_field(data, "password", 200)
                require(len(password) >= 10, "パスワードは10文字以上にしてください。")
                db.execute("INSERT INTO admins VALUES(?,?,?)", (admin_id, name, password_hash(password)))
                audit(db, actor, "管理者の追加", admin_id + " " + name)
                return {"ok": True}, None
            if path == "/api/admin/admins" and method == "DELETE":
                aid = text_field(data, "id")
                require(aid != session["user_id"], "ログイン中の管理者は削除できません。")
                require(db.execute("SELECT COUNT(*) FROM admins").fetchone()[0] > 1, "最後の管理者は削除できません。")
                require(one(db, "SELECT id FROM admins WHERE id=?", (aid,)), "管理者が見つかりません。")
                db.execute("DELETE FROM admins WHERE id=?", (aid,))
                db.execute("DELETE FROM sessions WHERE role='admin' AND user_id=?", (aid,))
                audit(db, actor, "管理者の削除", aid)
                return {"ok": True}, None
        raise APIError("ページが見つかりません。", 404)


DUMMY_HASH = password_hash("invalid-user-placeholder")


def main():
    if DEMO and HOST not in ("127.0.0.1", "localhost", "::1"):
        raise RuntimeError("デモはローカル限定です。HOST=127.0.0.1 を使用してください。")
    if not DEMO:
        if len(os.getenv("INTEGRATION_TOKEN", "")) < 32:
            raise RuntimeError("本番には32文字以上の INTEGRATION_TOKEN が必要です。")
        if not os.getenv("SMTP_HOST") or not os.getenv("SMTP_FROM"):
            raise RuntimeError("本番には SMTP_HOST と SMTP_FROM が必要です。")
        if not school_networks():
            raise RuntimeError("本番には学内ネットワークの ALLOWED_NETWORKS（例：192.168.0.0/16）が必要です。")
        if not os.getenv("PUBLIC_URL"):
            raise RuntimeError("本番にはメールのリンクに使う PUBLIC_URL（https://...）が必要です。")
        if os.getenv("SECURE_COOKIE") != "1":
            raise RuntimeError("本番ではHTTPSを使用し SECURE_COOKIE=1 を設定してください。")
    initialize()
    if not DEMO:
        threading.Thread(target=mail_worker, daemon=True).start()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"\n  Rollcall  →  http://{HOST}:{server.server_port}\n  {'デモモード / メールはローカルに保存' if DEMO else 'サーバーモード'}\n", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nRollcall を終了しました。")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
