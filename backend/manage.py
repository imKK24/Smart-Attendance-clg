"""Admin tasks from the terminal.

  python manage.py reset-password <username>     set a new admin password
  python manage.py create-accounts                 make the ready-made Admin and Teacher logins
                                                   (+ the Aakansha IT Hub admin)
  python manage.py add-ithub-admin                 only the Aakansha IT Hub admin (existing installs)
  python manage.py move-ithub-data                 move IT Hub records out of the college database
                                                   (only needed once, after upgrading)
  python manage.py clean-deleted-students           remove leftovers of students deleted before v2.1
  python manage.py copy-from-postgres <postgres url>  copy all data from the old PostgreSQL into MySQL
  python manage.py import-old <old project folder> copy students, photos, attendance
                                                   CSVs, events and Gmail settings
                                                   from the old file-based app.py
"""
import csv
import getpass
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

from werkzeug.security import generate_password_hash

import config
from common import clean_name, normalize_phone, password_problem, update_settings
from models import Admin, AttendanceRecord, Event, Student, create_tables, db


def reset_password(username):
    pw = getpass.getpass("New password (8+ characters): ")
    if pw != getpass.getpass("Type it again: "):
        sys.exit("The two passwords didn't match.")
    problem = password_problem(pw, username)
    if problem:
        sys.exit(problem)
    org = "college"
    for o in ("college", "ithub"):        # the account is in one of the two databases
        with db(o) as s:
            if s.query(Admin).filter(Admin.username == username).first():
                org = o
                break
    with db(org) as s:
        admin = s.query(Admin).filter(Admin.username == username).first()
        if not admin:
            admin = Admin(username=username, password_hash="")
            s.add(admin)
            print("No such admin, so a new one was created.")
        admin.password_hash = generate_password_hash(pw)
        admin.must_change = False
        admin.token_version = (admin.token_version or 0) + 1   # logs out every old session
    print("Done.")


# Ready-made logins. Each gets a RANDOM first password, shown once, and must
# set its own password at the first login. (Fixed passwords used to be here;
# they were published, so they no longer work.)
DEFAULT_ACCOUNTS = [
    {"username": "admin@attendai.local", "role": "admin", "full_name": "Administrator", "org": "college"},
    {"username": "teacher@attendai.local", "role": "teacher", "full_name": "Class Teacher", "org": "college"},
    {"username": "admin@ithub.local", "role": "admin", "full_name": "IT Hub Administrator", "org": "ithub"},
]


def first_password():
    import secrets
    alphabet = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no 0/O/1/l mix-ups
    return "-".join("".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(3))


def create_accounts(passwords=None):
    passwords = passwords or {}
    made = {}
    for acc in DEFAULT_ACCOUNTS:
        with db(acc.get("org", "college")) as s:   # each in its own organisation's database
            if s.query(Admin).filter(Admin.username == acc["username"]).first():
                print(f"  {acc['username']:<26} already exists (password not changed)")
                continue
            pw = passwords.get(acc["username"]) or first_password()
            s.add(Admin(username=acc["username"], password_hash=generate_password_hash(pw), role=acc["role"],
                        full_name=acc["full_name"], branches=[], active=True, must_change=True,
                        org=acc.get("org", "college")))
            made[acc["username"]] = pw
            where = "  (IT Hub: log in at /it-hub)" if acc.get("org") == "ithub" else ""
            print(f"  {acc['role'].title():<8} {acc['username']:<26} first password: {pw}{where}")
    if made:
        print("Write these down now: they are not shown again. Each account must set its own")
        print("password at the first login.")
    return made


# ---------------------------------------------------------------------------
# One-time move: IT Hub records that were saved in the college database (the
# first IT Hub version kept both in one database) go to the IT Hub database.
# ---------------------------------------------------------------------------
_BY_ORG = ("admins", "students", "holidays", "events", "exams", "attendance", "messages", "inbox",
           "wa_incoming", "class_photos")
_BY_STUDENT = ("student_faces", "absence_alerts", "leaves", "fee_dues")


def move_ithub_data(dry_run=False):
    from sqlalchemy import select, text
    from models import ENGINES, Base
    src, dst = ENGINES["college"], ENGINES["ithub"]
    T = Base.metadata.tables
    with src.connect() as c:
        sids = [r[0] for r in c.execute(select(T["students"].c.id).where(T["students"].c.org == "ithub"))]
        eids = [r[0] for r in c.execute(select(T["exams"].c.id).where(T["exams"].c.org == "ithub"))]
        inbox_ids = {r[0] for r in c.execute(select(T["inbox"].c.id).where(T["inbox"].c.org == "ithub"))}
        plan = []
        for name in ("admins", "students", "student_faces", "holidays", "events", "exams", "exam_results",
                     "absence_alerts", "attendance", "messages", "inbox", "leaves", "wa_incoming", "fee_dues",
                     "class_photos"):
            tb = T[name]
            if name in _BY_ORG:
                cond = tb.c.org == "ithub"
            elif name in _BY_STUDENT:
                cond = tb.c.student_id.in_(sids or [-1])
            else:   # exam_results
                cond = tb.c.exam_id.in_(eids or [-1])
            rows = [dict(r._mapping) for r in c.execute(select(tb).where(cond))]
            plan.append((name, cond, rows))
        settings = [dict(r._mapping) for r in c.execute(select(T["settings"]).where(T["settings"].c.key.like("ithub:%")))]
    total = sum(len(rows) for _, _, rows in plan)
    print(f"IT Hub records found in the college database: {total} (+ {len(settings)} settings)")
    for name, _, rows in plan:
        if rows:
            print(f"  {name:<15} {len(rows)}")
    if not total and not settings:
        print("Nothing to move.")
        return 0
    if dry_run:
        return total
    with dst.connect() as c:
        busy = [n for n, _, rows in plan if rows and c.execute(select(T[n].c.id).limit(1)).first()]
    if busy:
        sys.exit("The IT Hub database already has records in: " + ", ".join(busy)
                 + ". Nothing was moved, so nothing is mixed up. Ask for help before going on.")
    with dst.begin() as c:
        for name, _, rows in plan:
            if not rows:
                continue
            if name == "leaves":
                for r in rows:
                    if r.get("inbox_id") not in inbox_ids:
                        r["inbox_id"] = None
            if name == "class_photos":
                for r in rows:
                    r["files"] = [f"ithub/{f}" if not str(f).startswith("ithub/") else f for f in r["files"] or []]
            if name == "student_faces":
                for r in rows:
                    if r["photo_file"].startswith("extra/") and not r["photo_file"].startswith("extra/ithub/"):
                        r["photo_file"] = "extra/ithub/" + r["photo_file"][len("extra/"):]
            c.execute(T[name].insert(), rows)
            _fix_sequence(c, name)
        for st in settings:
            key = st["key"].split(":", 1)[1]
            c.execute(T["settings"].delete().where(T["settings"].c.key == key))
            c.execute(T["settings"].insert(), [{"key": key, "value": st["value"]}])
    with src.begin() as c:   # only after the copy succeeded
        for name, cond, rows in reversed(plan):
            if rows:
                c.execute(T[name].delete().where(cond))
        for st in settings:
            c.execute(T["settings"].delete().where(T["settings"].c.key == st["key"]))
    # photo folders: their numbers belong to the IT Hub database now
    photos = config.BASE_DIR / "class_photos"
    for name, _, rows in plan:
        for r in rows:
            if name == "class_photos" and (photos / str(r["id"])).is_dir():
                (photos / "ithub").mkdir(parents=True, exist_ok=True)
                shutil.move(str(photos / str(r["id"])), str(photos / "ithub" / str(r["id"])))
    for sid in sids:
        old = config.KNOWN_FACES_DIR / "extra" / str(sid)
        if old.is_dir():
            (config.KNOWN_FACES_DIR / "extra" / "ithub").mkdir(parents=True, exist_ok=True)
            shutil.move(str(old), str(config.KNOWN_FACES_DIR / "extra" / "ithub" / str(sid)))
    print("Moved. The college database now holds only college records.")
    return total


def clean_deleted_students():
    """Remove what students deleted before Delete erased everything left behind: attendance rows
    no longer linked to anyone, their names in the CSV registers, and orphaned face photos."""
    import shutil
    from attendance import write_csv
    from models import AttendanceRecord, Student, StudentFace, db
    from orgs import ORGS, as_org
    for org in ORGS:
        with as_org(org):
            with db() as s:
                names = {n for (n,) in s.query(Student.name)}
                ids = {i for (i,) in s.query(Student.id)}
                q = s.query(AttendanceRecord).filter(AttendanceRecord.org == org, AttendanceRecord.student_id.is_(None))
                gone = [r for r in q if r.student_name not in names]
                registers = {(r.day, r.course or "") for r in gone}
                for r in gone:
                    s.delete(r)
                used = {p for (p,) in s.query(Student.photo_file) if p} | {p for (p,) in s.query(StudentFace.photo_file) if p}
            for day, course in registers:
                try:
                    write_csv(day, course)
                except OSError as exc:
                    print(f"  could not rewrite the register for {day}: {exc}")
            # photos that no student uses any more are moved (not deleted) to known_faces/_removed/
            removed = config.KNOWN_FACES_DIR / "_removed" / org
            extra = config.KNOWN_FACES_DIR / ("extra" if org == "college" else f"extra/{org}")
            folders = 0
            if extra.is_dir():
                for d in extra.iterdir():
                    if d.is_dir() and d.name.isdigit() and int(d.name) not in ids:
                        removed.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(d), str(removed / f"extra-{d.name}")); folders += 1
            prefix = "" if org == "college" else f"{org}__"
            photos = 0
            for f in list(config.KNOWN_FACES_DIR.glob("*.jpg")):
                mine = f.name.startswith(prefix) if prefix else "__" not in f.name
                if mine and f.name not in used:
                    removed.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(f), str(removed / f.name)); photos += 1
            print(f"{'Aakansha IT Hub' if org == 'ithub' else 'College'}: removed {len(gone)} attendance rows of deleted students "
                  f"(registers rewritten for {len(registers)} days); moved {folders} extra-photo folders and {photos} unused photos "
                  f"to known_faces/_removed/{org} (delete that folder once you have checked it).")


def _fix_sequence(conn, name):
    """PostgreSQL: the next new id must come after the copied ones. (MySQL does this itself.)"""
    from sqlalchemy import text
    if conn.dialect.name == "postgresql":
        conn.execute(text(f"SELECT setval(pg_get_serial_sequence('{name}', 'id'), "
                          f"COALESCE((SELECT MAX(id) FROM {name}), 1))"))


def copy_from_postgres(pg_url):
    """Copy everything from the old PostgreSQL databases into the (new, empty) MySQL ones.
    pg_url is the college database, e.g. postgresql://attendai:PASS@localhost:5432/attendai ;
    the IT Hub one is the same with _ithub (or set ITHUB_PG_URL). Nothing in PostgreSQL changes."""
    from sqlalchemy import create_engine, func, select
    from models import ENGINES, Base
    if pg_url.startswith("postgresql://"):
        pg_url = "postgresql+psycopg2://" + pg_url[len("postgresql://"):]
    sources = {"college": pg_url, "ithub": os.environ.get("ITHUB_PG_URL") or config._sibling_db(pg_url, "_ithub")}
    tables = Base.metadata.sorted_tables          # parents before children (foreign keys)
    for org, url in sources.items():
        src, dst = create_engine(url), ENGINES[org]
        print(f"\n{'Aakansha IT Hub' if org == 'ithub' else 'College'}: {src.url.database} -> {dst.url.database}")
        try:
            src.connect().close()
        except Exception as exc:     # noqa: BLE001 - e.g. the IT Hub database never existed
            print(f"  skipped: can't open {src.url.database} ({type(exc).__name__})")
            continue
        with dst.connect() as c:
            busy = [t.name for t in tables if t.name not in ("settings", "student_units")
                    and c.execute(select(func.count()).select_from(t)).scalar()]
        if busy:
            sys.exit(f"  The MySQL database {dst.url.database} already has records in: {', '.join(busy)}.\n"
                     "  Nothing was copied. Copy into a fresh, empty database.")
        with src.connect() as s, dst.begin() as d:
            have = set(src.dialect.get_table_names(s))
            for t in tables:
                if t.name not in have:
                    continue
                cols = [c.name for c in t.columns if c.name in {x["name"] for x in src.dialect.get_columns(s, t.name)}]
                rows = [dict(r._mapping) for r in s.execute(select(*[t.c[n] for n in cols]))]
                if t.name == "settings":
                    d.execute(t.delete())
                if rows:
                    for i in range(0, len(rows), 500):
                        d.execute(t.insert(), rows[i:i + 500])
                print(f"  {t.name:<16} {len(rows)}")
        src.dispose()
    from models import create_tables
    create_tables()            # fills student_units for the copied students
    print("\nDone. Log in as before; the PostgreSQL databases were not changed.")


def _json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def import_old(folder):
    old = Path(folder).resolve()
    faces = old / "known_faces"
    if not faces.is_dir():
        sys.exit(f"No known_faces folder in {old}")
    metas = _json(old / "data" / "students.json", {})
    n_students = n_rows = n_events = 0
    with db() as s:
        for f in sorted(faces.iterdir()):
            if f.suffix.lower() not in (".jpg", ".jpeg", ".png") or f.name.startswith("."):
                continue
            name = clean_name(f.stem)
            if not name or s.query(Student).filter(Student.name == name).first():
                continue
            meta = metas.get(f.stem, {})
            shutil.copy2(f, config.KNOWN_FACES_DIR / f.name)
            try:
                phone = normalize_phone(meta.get("parent_phone", ""))
            except ValueError:
                phone = ""
            reg = meta.get("registered_at")
            s.add(Student(name=name, photo_file=f.name, class_name=meta.get("class_name", ""),
                          student_email=meta.get("student_email", ""), parent_name=meta.get("parent_name", ""),
                          parent_phone=phone, parent_email=meta.get("parent_email", ""), consent=True,
                          registered_at=datetime.strptime(reg, "%Y-%m-%d %H:%M:%S") if reg else datetime.now()))
            n_students += 1
        s.flush()
        ids = {st.name: st.id for st in s.query(Student)}
        for f in sorted((old / "attendance_records").glob("*.csv")):
            try:
                day = datetime.strptime(f.stem, "%Y-%m-%d").date()
            except ValueError:
                continue
            with open(f, newline="", encoding="utf-8-sig", errors="replace") as fh:
                for row in csv.DictReader(fh):
                    name = (row.get("Name") or "").strip()
                    status = "Present" if (row.get("Status") or "").strip() == "Present" else "Absent"
                    if not name:
                        continue
                    rec = s.query(AttendanceRecord).filter_by(day=day, student_name=name).first()
                    if rec:
                        if status == "Present":
                            rec.status, rec.time = "Present", row.get("Time") or "-"
                        continue
                    s.add(AttendanceRecord(day=day, student_name=name, student_id=ids.get(name), status=status,
                                           time=(row.get("Time") or "-").replace("—", "-")))
                    n_rows += 1
                    s.flush()
        for e in _json(old / "data" / "events.json", []):
            try:
                s.add(Event(title=e["title"], date=datetime.strptime(e["date"], "%Y-%m-%d").date(),
                            time=e.get("time", ""), venue=e.get("venue", ""), description=e.get("description", "")))
                n_events += 1
            except (KeyError, ValueError):
                pass
    st = _json(old / "data" / "settings.json", {})
    keep = {k: st[k] for k in ("gmail", "app_password", "sender_name", "threshold", "auto_send") if k in st}
    if keep:
        update_settings(**keep)
    import attendance
    for day in attendance.saved_days():
        attendance.write_csv(day)
    print(f"Imported {n_students} students, {n_rows} attendance rows, {n_events} events"
          + (", Gmail settings" if keep else "") + ".")
    print("Face encodings are worked out the first time you start the camera.")


if __name__ == "__main__":
    create_tables()
    if len(sys.argv) == 2 and sys.argv[1] == "create-accounts":
        create_accounts()
    elif len(sys.argv) == 3 and sys.argv[1] == "reset-password":
        reset_password(sys.argv[2])
    elif len(sys.argv) == 2 and sys.argv[1] == "add-ithub-admin":
        # Existing installs: just the Aakansha IT Hub admin (the others are left alone).
        DEFAULT_ACCOUNTS[:] = [a for a in DEFAULT_ACCOUNTS if a["org"] == "ithub"]
        create_accounts()
    elif len(sys.argv) == 2 and sys.argv[1] == "move-ithub-data":
        move_ithub_data()
    elif len(sys.argv) == 2 and sys.argv[1] == "clean-deleted-students":
        clean_deleted_students()
    elif len(sys.argv) == 3 and sys.argv[1] == "copy-from-postgres":
        copy_from_postgres(sys.argv[2])
    elif len(sys.argv) == 3 and sys.argv[1] == "import-old":
        import_old(sys.argv[2])
    else:
        print(__doc__)
