"""Database tables (SQLAlchemy 2). Tables are created on first start.

Works on MySQL / MariaDB (XAMPP - the default) and on PostgreSQL. Nothing here
uses features of only one of them: students' courses are searched through the
small student_units table (kept in step automatically), not with JSON operators."""
from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import (JSON, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer,
                        LargeBinary, String, Text, UniqueConstraint, create_engine, event, select)
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

import config

# One database per organisation. Nothing is ever written to the other one:
# every session opens the database of the organisation this request (or
# background job) works for - see orgs.current_org().
def _make_engine(url):
    url = make_url(url)
    opts = {"pool_pre_ping": True, "future": True}
    if url.get_backend_name() in ("mysql", "mariadb"):
        if "charset" not in url.query:          # names like "Python · 4–6 PM" need full Unicode
            url = url.update_query_dict({"charset": "utf8mb4"})
        opts["pool_recycle"] = 3600             # MySQL drops connections idle for 8 hours
    return create_engine(url, **opts)


engine = _make_engine(config.DATABASE_URL)               # college
ithub_engine = _make_engine(config.ITHUB_DATABASE_URL)   # Aakansha IT Hub
ENGINES = {"college": engine, "ithub": ithub_engine}
_SESSIONS = {org: sessionmaker(bind=e, expire_on_commit=False, future=True) for org, e in ENGINES.items()}
SessionLocal = _SESSIONS["college"]


def engine_for(org=None):
    from orgs import clean_org, current_org
    return ENGINES[clean_org(org or current_org())]


@contextmanager
def db(org=None):
    """with db() as s: ...   commits on success, rolls back on error.
    Opens this organisation's database (or the one named by org=)."""
    from orgs import clean_org, current_org
    s = _SESSIONS[clean_org(org or current_org())]()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def now():
    return datetime.now().replace(microsecond=0)


class Base(DeclarativeBase):
    pass


class Admin(Base):
    """A login. role 'admin' can do everything; role 'teacher' only sees the
    students of their branches (empty list = all branches)."""
    __tablename__ = "admins"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(60), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    role: Mapped[str] = mapped_column(String(10), default="admin")
    full_name: Mapped[str] = mapped_column(String(80), default="")
    branches: Mapped[list] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change: Mapped[bool] = mapped_column(Boolean, default=False)   # must set own password at next login
    token_version: Mapped[int] = mapped_column(Integer, default=0)      # +1 = every old login stops working
    org: Mapped[str] = mapped_column(String(10), default="college")     # college | ithub (see orgs.py)


class Student(Base):
    __tablename__ = "students"
    # Names and registration numbers are unique inside one organisation only:
    # the same person can study at the college and at the IT Hub.
    __table_args__ = (Index("uq_students_org_name", "org", "name", unique=True),
                      Index("uq_students_org_roll", "org", "roll_no", unique=True))
    id: Mapped[int] = mapped_column(primary_key=True)
    org: Mapped[str] = mapped_column(String(10), default="college", index=True)
    name: Mapped[str] = mapped_column(String(60))
    roll_no: Mapped[str | None] = mapped_column(String(30), nullable=True)
    branch: Mapped[str] = mapped_column(String(60), default="")               # college
    courses: Mapped[list] = mapped_column(JSON, default=list)                # IT Hub: ["Python", "Tally"]
    batches: Mapped[dict] = mapped_column(JSON, default=dict)                # IT Hub: {"Python": "4–6 PM"}
    # IT Hub classes the student is in: each course, and "Course · Batch" (courses.units_for).
    # Attendance, teacher access and reports go by these.
    units: Mapped[list] = mapped_column(JSON, default=list)
    unit_rows: Mapped[list["StudentUnit"]] = relationship(cascade="all, delete-orphan", passive_deletes=True)
    class_name: Mapped[str] = mapped_column(String(30), default="")
    student_email: Mapped[str] = mapped_column(String(120), default="")
    student_phone: Mapped[str] = mapped_column(String(20), default="")
    parent_name: Mapped[str] = mapped_column(String(80), default="")
    parent_relation: Mapped[str] = mapped_column(String(20), default="")
    parent_phone: Mapped[str] = mapped_column(String(20), default="")      # WhatsApp number
    parent_email: Mapped[str] = mapped_column(String(120), default="")
    alt_phone: Mapped[str] = mapped_column(String(20), default="")
    address: Mapped[str] = mapped_column(Text, default="")
    qualifications: Mapped[list] = mapped_column(JSON, default=list)
    achievements: Mapped[list] = mapped_column(JSON, default=list)
    consent: Mapped[bool] = mapped_column(Boolean, default=False)
    photo_file: Mapped[str] = mapped_column(String(120), default="")
    face_encoding: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    registered_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


class AttendanceRecord(Base):
    __tablename__ = "attendance"
    # One row per student per day (college), or per student per day per course (IT Hub).
    __table_args__ = (Index("uq_attendance_org_day_name_course", "org", "day", "student_name", "course", unique=True),)
    id: Mapped[int] = mapped_column(primary_key=True)
    org: Mapped[str] = mapped_column(String(10), default="college", index=True)
    course: Mapped[str] = mapped_column(String(60), default="")     # IT Hub course; "" for the college
    day: Mapped[datetime] = mapped_column(Date, index=True)
    # name is kept so old records survive when a student is deleted
    student_name: Mapped[str] = mapped_column(String(60))
    student_id: Mapped[int | None] = mapped_column(ForeignKey("students.id", ondelete="SET NULL"), nullable=True)
    time: Mapped[str] = mapped_column(String(20), default="-")
    status: Mapped[str] = mapped_column(String(10), default="Absent")
    source: Mapped[str] = mapped_column(String(10), default="camera")   # camera | photo


class StudentUnit(Base):
    """One row per entry of Student.units, so "students in Python · 4–6 PM" is a plain
    indexed lookup on MySQL and PostgreSQL alike. Filled automatically (see _sync_units)."""
    __tablename__ = "student_units"
    __table_args__ = (UniqueConstraint("student_id", "unit"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    unit: Mapped[str] = mapped_column(String(130), index=True)


@event.listens_for(Session, "before_flush")
def _sync_units(session, _ctx, _instances):
    for obj in list(session.new) + list(session.dirty):
        if isinstance(obj, Student):
            want = list(dict.fromkeys(obj.units or []))
            if [r.unit for r in obj.unit_rows] != want:
                obj.unit_rows = [StudentUnit(unit=u) for u in want]


def in_units(units):
    """Filter: students in any of these units (IT Hub course, or "Course · Batch")."""
    return Student.id.in_(select(StudentUnit.student_id).where(StudentUnit.unit.in_(list(units))))


class Device(Base):
    """A browser approved for taking attendance (guard.py). Only a hash of its key is kept."""
    __tablename__ = "devices"
    id: Mapped[int] = mapped_column(primary_key=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    username: Mapped[str] = mapped_column(String(60), index=True)
    label: Mapped[str] = mapped_column(String(80), default="")
    status: Mapped[str] = mapped_column(String(10), default="pending")    # pending | approved
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_ip: Mapped[str] = mapped_column(String(45), default="")


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)


class Holiday(Base):
    __tablename__ = "holidays"
    org: Mapped[str] = mapped_column(String(10), default="college", index=True)
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(80))
    start_date: Mapped[datetime] = mapped_column(Date)
    end_date: Mapped[datetime] = mapped_column(Date)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    last_notified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_recipients: Mapped[int] = mapped_column(Integer, default=0)


class Event(Base):
    __tablename__ = "events"
    org: Mapped[str] = mapped_column(String(10), default="college", index=True)
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(80))
    date: Mapped[datetime] = mapped_column(Date)
    time: Mapped[str] = mapped_column(String(5), default="")
    venue: Mapped[str] = mapped_column(String(80), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    last_notified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_recipients: Mapped[int] = mapped_column(Integer, default=0)


class Exam(Base):
    __tablename__ = "exams"
    org: Mapped[str] = mapped_column(String(10), default="college", index=True)
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    exam_date: Mapped[datetime | None] = mapped_column(Date, nullable=True)
    subjects: Mapped[list] = mapped_column(JSON, default=list)   # [{"name": "Maths", "max": 100}]
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    course: Mapped[str] = mapped_column(String(60), default="")   # IT Hub: the course this test is for
    last_recipients: Mapped[int] = mapped_column(Integer, default=0)


class ExamResult(Base):
    __tablename__ = "exam_results"
    __table_args__ = (UniqueConstraint("exam_id", "student_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id", ondelete="CASCADE"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"))
    marks: Mapped[dict] = mapped_column(JSON, default=dict)      # {"Maths": 78, "Physics": "AB"}
    total: Mapped[float] = mapped_column(Float, default=0)
    max_total: Mapped[float] = mapped_column(Float, default=0)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AbsenceAlert(Base):
    """One row per absence streak that parents were told about."""
    __tablename__ = "absence_alerts"
    __table_args__ = (UniqueConstraint("student_id", "streak_start"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"))
    streak_start: Mapped[datetime] = mapped_column(Date)
    days: Mapped[int] = mapped_column(Integer)
    channels: Mapped[list] = mapped_column(JSON, default=list)
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Message(Base):
    """Every outgoing email or WhatsApp message: queued -> sent / failed."""
    __tablename__ = "messages"
    org: Mapped[str] = mapped_column(String(10), default="college", index=True)
    id: Mapped[int] = mapped_column(primary_key=True)
    batch: Mapped[str] = mapped_column(String(16), index=True)
    channel: Mapped[str] = mapped_column(String(10))            # email | whatsapp
    kind: Mapped[str] = mapped_column(String(12))               # absence | holiday | result | event | reply | test
    student_id: Mapped[int | None] = mapped_column(ForeignKey("students.id", ondelete="SET NULL"), nullable=True)
    who: Mapped[str] = mapped_column(String(80), default="")
    to: Mapped[str] = mapped_column(String(160))
    subject: Mapped[str] = mapped_column(String(200), default="")
    body: Mapped[str] = mapped_column(Text)
    html: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(10), default="queued", index=True)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class InboxMail(Base):
    """Emails from parents, copied from Gmail (IMAP)."""
    __tablename__ = "inbox"
    org: Mapped[str] = mapped_column(String(10), default="college", index=True)
    id: Mapped[int] = mapped_column(primary_key=True)
    msg_id: Mapped[str] = mapped_column(String(300), unique=True)
    from_email: Mapped[str] = mapped_column(String(160), index=True)
    from_name: Mapped[str] = mapped_column(String(160), default="")
    subject: Mapped[str] = mapped_column(String(300), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    references: Mapped[str] = mapped_column(Text, default="")
    received_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    student_id: Mapped[int | None] = mapped_column(ForeignKey("students.id", ondelete="SET NULL"), nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    replied_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)



# ---------------- Batch 1: extra face photos, leave applications ----------------
class StudentFace(Base):
    """Extra photos of a student (other angles, glasses, light). Each adds one encoding."""
    __tablename__ = "student_faces"
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    encoding: Mapped[bytes] = mapped_column(LargeBinary)
    photo_file: Mapped[str] = mapped_column(String(160))
    label: Mapped[str] = mapped_column(String(30), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class LeaveRequest(Base):
    """A leave: pending -> approved / rejected. Approved days show as 'Leave', not 'Absent'."""
    __tablename__ = "leaves"
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    start_date: Mapped[datetime] = mapped_column(Date)
    end_date: Mapped[datetime] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(20), default="admin")     # admin | email
    inbox_id: Mapped[int | None] = mapped_column(ForeignKey("inbox.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="pending", index=True)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


# ---------------- Batch 3: WhatsApp replies from parents, fees ----------------
class WaIncoming(Base):
    """A WhatsApp message a parent sent to the school number (forwarded by the bridge)."""
    __tablename__ = "wa_incoming"
    org: Mapped[str] = mapped_column(String(10), default="college", index=True)
    id: Mapped[int] = mapped_column(primary_key=True)
    wa_id: Mapped[str] = mapped_column(String(120), unique=True)
    phone: Mapped[str] = mapped_column(String(20), index=True)          # +919876543210
    name: Mapped[str] = mapped_column(String(120), default="")          # their WhatsApp display name
    text: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(12), default="text")       # text | photo | voice | document | other
    received_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)


class FeeDue(Base):
    """One fee one student has to pay, e.g. 'Semester 6 tuition', 45000, due 30 Nov."""
    __tablename__ = "fee_dues"
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(80), index=True)
    amount: Mapped[float] = mapped_column(Float)
    due_date: Mapped[datetime] = mapped_column(Date)
    paid_amount: Mapped[float] = mapped_column(Float, default=0)
    paid_on: Mapped[datetime | None] = mapped_column(Date, nullable=True)
    note: Mapped[str] = mapped_column(String(200), default="")
    course: Mapped[str] = mapped_column(String(60), default="")     # IT Hub: the course this fee is for
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    last_reminded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reminders_sent: Mapped[int] = mapped_column(Integer, default=0)


class ClassPhoto(Base):
    """Class photos a teacher took on their phone: attendance and its evidence."""
    __tablename__ = "class_photos"
    org: Mapped[str] = mapped_column(String(10), default="college", index=True)
    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[datetime] = mapped_column(Date, index=True)
    branch: Mapped[str] = mapped_column(String(60), default="")      # college branch or IT Hub course
    files: Mapped[list] = mapped_column(JSON, default=list)           # ["class_photos/12/1.jpg", ...]
    faces: Mapped[list] = mapped_column(JSON, default=list)           # what was found in each photo
    status: Mapped[str] = mapped_column(String(10), default="draft")  # draft | saved
    present_ids: Mapped[list] = mapped_column(JSON, default=list)
    taken_by: Mapped[str] = mapped_column(String(60), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    saved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Course(Base):
    """Aakansha IT Hub course: shown as a card with its picture, price and description."""
    __tablename__ = "courses"
    id: Mapped[int] = mapped_column(primary_key=True)
    org: Mapped[str] = mapped_column(String(10), default="ithub")
    name: Mapped[str] = mapped_column(String(60), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    price: Mapped[float] = mapped_column(Float, default=0)             # rupees, for the whole course
    duration: Mapped[str] = mapped_column(String(40), default="")      # e.g. "3 months"
    image_file: Mapped[str] = mapped_column(String(160), default="")   # in course_images/
    active: Mapped[bool] = mapped_column(Boolean, default=True)        # off = hidden from new registrations
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


# Columns added after the first release. create_all() makes new tables but
# never changes old ones, so these are added here (safe to run every start).
UPGRADES = [
    "ALTER TABLE admins ADD COLUMN IF NOT EXISTS role VARCHAR(10) NOT NULL DEFAULT 'admin'",
    "ALTER TABLE admins ADD COLUMN IF NOT EXISTS full_name VARCHAR(80) NOT NULL DEFAULT ''",
    "ALTER TABLE admins ADD COLUMN IF NOT EXISTS branches JSON NOT NULL DEFAULT '[]'",
    "ALTER TABLE admins ADD COLUMN IF NOT EXISTS active BOOLEAN NOT NULL DEFAULT TRUE",
    "ALTER TABLE attendance ADD COLUMN IF NOT EXISTS source VARCHAR(10) NOT NULL DEFAULT 'camera'",
    "ALTER TABLE admins ADD COLUMN IF NOT EXISTS must_change BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE admins ADD COLUMN IF NOT EXISTS token_version INTEGER NOT NULL DEFAULT 0",
    # Aakansha IT Hub (orgs.py): everything that belongs to one organisation gets an org.
    *[f"ALTER TABLE {t} ADD COLUMN IF NOT EXISTS org VARCHAR(10) NOT NULL DEFAULT 'college'"
      for t in ("admins", "students", "attendance", "holidays", "events", "exams", "class_photos",
                "messages", "inbox", "wa_incoming")],
    *[f"CREATE INDEX IF NOT EXISTS ix_{t}_org ON {t} (org)"
      for t in ("students", "attendance", "holidays", "events", "exams", "class_photos", "messages", "inbox", "wa_incoming")],
    "ALTER TABLE students ADD COLUMN IF NOT EXISTS courses JSONB NOT NULL DEFAULT '[]'",
    "ALTER TABLE students ADD COLUMN IF NOT EXISTS batches JSONB NOT NULL DEFAULT '{}'",
    "ALTER TABLE students ADD COLUMN IF NOT EXISTS units JSONB NOT NULL DEFAULT '[]'",
    "UPDATE students SET units = courses WHERE units::text = '[]' AND courses::text <> '[]'",
    "ALTER TABLE attendance ADD COLUMN IF NOT EXISTS course VARCHAR(60) NOT NULL DEFAULT ''",
    "ALTER TABLE exams ADD COLUMN IF NOT EXISTS course VARCHAR(60) NOT NULL DEFAULT ''",
    "ALTER TABLE fee_dues ADD COLUMN IF NOT EXISTS course VARCHAR(60) NOT NULL DEFAULT ''",
    # names / registration numbers / attendance rows: unique per organisation (and course)
    "ALTER TABLE students DROP CONSTRAINT IF EXISTS students_name_key",
    "ALTER TABLE students DROP CONSTRAINT IF EXISTS students_roll_no_key",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_students_org_name ON students (org, name)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_students_org_roll ON students (org, roll_no)",
    "ALTER TABLE attendance DROP CONSTRAINT IF EXISTS attendance_day_student_name_key",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_attendance_org_day_name_course ON attendance (org, day, student_name, course)",
]


class DatabaseMissing(RuntimeError):
    pass


def ensure_database(org):
    """Create the organisation's database if it doesn't exist yet (needs the right to
    create databases; otherwise say exactly what to run)."""
    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError, ProgrammingError
    eng = ENGINES[org]
    mysql = eng.dialect.name in ("mysql", "mariadb")
    try:
        with eng.connect():
            return
    except OperationalError as exc:
        msg = str(exc)
        if mysql and ("Can't connect" in msg or "2003" in msg):
            raise DatabaseMissing(
                "Can't reach MySQL. Open the XAMPP Control Panel and press Start next to MySQL,\n"
                "  then start AttendAI again.") from exc
        if "does not exist" not in msg and "Unknown database" not in msg:
            raise
    name = eng.url.database
    server = eng.url.set(database="" if mysql else "postgres")
    try:
        admin = create_engine(server, isolation_level="AUTOCOMMIT")
        with admin.connect() as conn:
            if mysql:
                conn.execute(text(f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"))
            else:
                conn.execute(text(f'CREATE DATABASE "{name}"'))
        admin.dispose()
        print(f"Created the database {name} for {'Aakansha IT Hub' if org == 'ithub' else 'the college'}.")
    except (OperationalError, ProgrammingError) as exc:
        how = (f"  Open phpMyAdmin (http://localhost/phpmyadmin) > SQL and run:\n"
               f"      CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;\n") if mysql else (
               f"  Open 'SQL Shell (psql)' (or pgAdmin's Query Tool) as the postgres user and run:\n"
               f"      CREATE DATABASE {name} OWNER {eng.url.username};\n")
        raise DatabaseMissing(
            f"The database '{name}' doesn't exist and AttendAI isn't allowed to create it.\n"
            f"{how}  then start AttendAI again.") from exc


def create_tables():
    from sqlalchemy import text
    for org, eng in ENGINES.items():
        ensure_database(org)
        Base.metadata.create_all(eng)
        if eng.dialect.name == "postgresql":
            with eng.begin() as conn:
                for sql in UPGRADES:
                    conn.execute(text(sql))
        _backfill_units(org)


def _backfill_units(org):
    """Databases made before student_units existed: fill it once."""
    with db(org) as s:
        if s.query(StudentUnit.id).first() is not None:
            return
        for st in s.query(Student).all():
            if st.units:
                st.unit_rows = [StudentUnit(unit=u) for u in dict.fromkeys(st.units)]
