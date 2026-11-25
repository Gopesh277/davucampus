import os, re, time, datetime as dt
from sqlalchemy import create_engine, String, Integer, ForeignKey, UniqueConstraint, Index, select
from sqlalchemy.orm import sessionmaker, DeclarativeBase, Mapped, mapped_column

URL = os.getenv("DATABASE_URL", "sqlite:///./local.db")
if os.getenv("ENV") == "prod" and URL.startswith("sqlite"): raise RuntimeError("Set DATABASE_URL to PostgreSQL in production")
# per worker: 4 workers x (5 + 10) = 60 connections at most, under PostgreSQL's default max_connections of 100
kw = {"connect_args": {"check_same_thread": False}} if URL.startswith("sqlite") else {"pool_size": 5, "max_overflow": 10, "pool_pre_ping": True, "pool_recycle": 1800}
engine = create_engine(URL, **kw)
Session = sessionmaker(engine, expire_on_commit=False)

class Base(DeclarativeBase): pass
S = lambda n=120: String(n)

# Same period grid as the scheduler repo (9:30-4:30, 7 periods)
DEFAULT_PERIODS = {1: ("09:30", "10:30"), 2: ("10:30", "11:30"), 3: ("11:30", "12:30"), 4: ("12:30", "13:30"),
                   5: ("13:30", "14:30"), 6: ("14:30", "15:30"), 7: ("15:30", "16:30")}
def t12(t):
    h, m = t.split(":"); return f"{int(h) % 12 or 12}:{m}"
TITLES = {"dr", "prof", "mr", "mrs", "ms", "er", "sh", "smt"}
fkey = lambda n: "".join(w for w in re.findall(r"[a-z0-9]+", (n or "").lower()) if w not in TITLES)  # "Dr. A. Sharma" == "A Sharma"
skey = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())

class Dept(Base):
    __tablename__ = "dept"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(S(20), unique=True)
    name: Mapped[str] = mapped_column(S(200))

class User(Base):  # role: student | faculty | admin. pw_hash NULL => password == username (reg no / employee id)
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    dept_id: Mapped[int] = mapped_column(ForeignKey("dept.id"))
    username: Mapped[str] = mapped_column(S(40))
    name: Mapped[str] = mapped_column(S(), default="")
    role: Mapped[str] = mapped_column(S(10), default="student")
    section: Mapped[str] = mapped_column(S(80), default="")
    group: Mapped[str] = mapped_column(S(10), default="")
    pw_hash: Mapped[str | None] = mapped_column(S(200), nullable=True)
    __table_args__ = (UniqueConstraint("dept_id", "username"),)

class Slot(Base):  # one row per (section, day, period); 2-period labs become 2 rows
    __tablename__ = "slot"
    id: Mapped[int] = mapped_column(primary_key=True)
    dept_id: Mapped[int] = mapped_column(ForeignKey("dept.id"))
    section: Mapped[str] = mapped_column(S(80))
    skey: Mapped[str] = mapped_column(S(80))
    group: Mapped[str] = mapped_column(S(10), default="")
    day: Mapped[int] = mapped_column(Integer)
    period: Mapped[int] = mapped_column(Integer)
    start: Mapped[str] = mapped_column(S(8), default="")
    end: Mapped[str] = mapped_column(S(8), default="")
    code: Mapped[str] = mapped_column(S(40), default="")
    subject: Mapped[str] = mapped_column(S(200), default="")
    faculty: Mapped[str] = mapped_column(S(), default="")
    fkey: Mapped[str] = mapped_column(S(), default="")
    room: Mapped[str] = mapped_column(S(60), default="")
    kind: Mapped[str] = mapped_column(S(20), default="Theory")
    __table_args__ = (Index("ix_slot_sec", "dept_id", "skey"), Index("ix_slot_fac", "dept_id", "fkey"))

class Faculty(Base):
    __tablename__ = "faculty"
    id: Mapped[int] = mapped_column(primary_key=True)
    dept_id: Mapped[int] = mapped_column(ForeignKey("dept.id"), index=True)
    name: Mapped[str] = mapped_column(S())
    emp_id: Mapped[str] = mapped_column(S(40), default="")
    designation: Mapped[str] = mapped_column(S(), default="")
    email: Mapped[str] = mapped_column(S(), default="")
    phone: Mapped[str] = mapped_column(S(40), default="")
    cabin: Mapped[str] = mapped_column(S(), default="")

class Room(Base):
    __tablename__ = "room"
    id: Mapped[int] = mapped_column(primary_key=True)
    dept_id: Mapped[int] = mapped_column(ForeignKey("dept.id"), index=True)
    name: Mapped[str] = mapped_column(S(60))
    building: Mapped[str] = mapped_column(S(), default="")
    floor: Mapped[str] = mapped_column(S(40), default="")
    directions: Mapped[str] = mapped_column(S(400), default="")

class Notice(Base):
    __tablename__ = "notice"
    id: Mapped[int] = mapped_column(primary_key=True)
    dept_id: Mapped[int] = mapped_column(ForeignKey("dept.id"), index=True)
    title: Mapped[str] = mapped_column(S(200))
    body: Mapped[str] = mapped_column(S(2000), default="")
    audience: Mapped[str] = mapped_column(S(10), default="all")  # all | students | faculty
    posted: Mapped[str] = mapped_column(S(10), default="")
    pinned: Mapped[int] = mapped_column(Integer, default=0)

class UniNotice(Base):  # posted by the Dean's Office; shown to every department. audience: all | students | faculty | admins
    __tablename__ = "uni_notice"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(S(200))
    body: Mapped[str] = mapped_column(S(2000), default="")
    audience: Mapped[str] = mapped_column(S(10), default="all")
    posted: Mapped[str] = mapped_column(S(10), default="")
    pinned: Mapped[int] = mapped_column(Integer, default=0)

class Sync(Base):  # when each department last published a timetable / student list / faculty list (shown to the Dean)
    __tablename__ = "sync"
    id: Mapped[int] = mapped_column(primary_key=True)
    dept_id: Mapped[int] = mapped_column(ForeignKey("dept.id"))
    kind: Mapped[str] = mapped_column(S(20))  # timetable | students | faculty
    at: Mapped[str] = mapped_column(S(25), default="")
    __table_args__ = (UniqueConstraint("dept_id", "kind"),)

def stamp(db, d, kind):  # call inside the upload's transaction, before commit
    row = db.scalar(select(Sync).where(Sync.dept_id == d, Sync.kind == kind))
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    if row: row.at = now
    else: db.add(Sync(dept_id=d, kind=kind, at=now))

# Small per-worker TTL cache: thousands of users read the same few sections, so this absorbs most DB load.
_c = {}
def cached(key, ttl, fn):
    v = _c.get(key)
    if v and time.time() - v[0] < ttl: return v[1]
    r = fn(); _c[key] = (time.time(), r); return r
def bust(): _c.clear()
def forget(key): _c.pop(key, None)

def _row(x): return {c.name: getattr(x, c.name) for c in x.__table__.columns if c.name not in ("id", "dept_id")}

def lookups(db, d):
    """(faculty by fkey, rooms by lowercase name). Names that only appear in the timetable are included too."""
    def load():
        f = {fkey(x.name): _row(x) for x in db.scalars(select(Faculty).where(Faculty.dept_id == d))}
        for n in db.scalars(select(Slot.faculty).where(Slot.dept_id == d).distinct()):
            if n and fkey(n) not in f: f[fkey(n)] = {"name": n}
        r = {x.name.lower(): _row(x) for x in db.scalars(select(Room).where(Room.dept_id == d))}
        for n in db.scalars(select(Slot.room).where(Slot.dept_id == d).distinct()):
            if n and n.lower() not in r: r[n.lower()] = {"name": n}
        return f, r
    return cached(("lk", d), 60, load)

def _slot(s, f, r):
    return dict(day=s.day, period=s.period, start=s.start, end=s.end, code=s.code, subject=s.subject, kind=s.kind, section=s.section,
                group=s.group, faculty=f.get(s.fkey) or {"name": s.faculty}, room=r.get(s.room.lower()) or {"name": s.room})

def timetable(db, d, sec, grp=""):
    def load():
        f, r = lookups(db, d)
        q = select(Slot).where(Slot.dept_id == d, Slot.skey == skey(sec)).order_by(Slot.day, Slot.period)
        return [_slot(s, f, r) for s in db.scalars(q) if not grp or s.group in ("", grp)]
    return cached(("tt", d, skey(sec), grp), 60, load)

def ftimetable(db, d, fk):
    def load():
        f, r = lookups(db, d)
        q = select(Slot).where(Slot.dept_id == d, Slot.fkey == fk).order_by(Slot.day, Slot.period)
        return [_slot(s, f, r) for s in db.scalars(q)]
    return cached(("ft", d, fk), 60, load)

def periods(db, d):
    def load():
        m = {p: (s, e) for p, s, e in db.execute(select(Slot.period, Slot.start, Slot.end).where(Slot.dept_id == d).distinct()).all()}
        return {**DEFAULT_PERIODS, **m} if set(m.values()) <= set(DEFAULT_PERIODS.values()) else m
    return cached(("pm", d), 60, load)

AUD = {"student": "students", "faculty": "faculty", "admin": "admins"}  # login role -> audience value

def uni_notices(db, role):  # the Dean's notices for this kind of login (cached: every login of a role shares it)
    def load():
        q = select(UniNotice).where(UniNotice.audience.in_(["all", AUD.get(role, "all")])).order_by(UniNotice.pinned.desc(), UniNotice.id.desc()).limit(20)
        return [dict(id=n.id, title=n.title, body=n.body, posted=n.posted, pinned=n.pinned, uni=True) for n in db.scalars(q)]
    return cached(("un", role), 60, load)

def notices(db, d, role):
    def load():
        q = select(Notice).where(Notice.dept_id == d, Notice.audience.in_(["all", AUD.get(role, "all")])).order_by(Notice.pinned.desc(), Notice.id.desc()).limit(20)
        xs = uni_notices(db, role) + [dict(id=n.id, title=n.title, body=n.body, posted=n.posted, pinned=n.pinned, uni=False) for n in db.scalars(q)]
        xs.sort(key=lambda n: (n["posted"], n["id"]), reverse=True)
        xs.sort(key=lambda n: (-n["pinned"], not n["uni"]))  # pinned first, the Dean's notices ahead of the department's
        return xs[:20]
    return cached(("nt", d, role), 60, load)

# ---------------- classwork: assignments + syllabus covered (posted by the teacher for a section & subject) ----------------
class Assignment(Base):
    __tablename__ = "assignment"
    id: Mapped[int] = mapped_column(primary_key=True)
    dept_id: Mapped[int] = mapped_column(ForeignKey("dept.id"))
    skey: Mapped[str] = mapped_column(S(80))
    section: Mapped[str] = mapped_column(S(80))
    subject: Mapped[str] = mapped_column(S(200))
    code: Mapped[str] = mapped_column(S(40), default="")
    title: Mapped[str] = mapped_column(S(200))
    details: Mapped[str] = mapped_column(S(2000), default="")
    due: Mapped[str] = mapped_column(S(10))
    posted: Mapped[str] = mapped_column(S(10), default="")
    fkey: Mapped[str] = mapped_column(S(120))
    teacher: Mapped[str] = mapped_column(S(120), default="")
    __table_args__ = (Index("ix_asg_sec", "dept_id", "skey"), Index("ix_asg_fac", "dept_id", "fkey"))

class Syllabus(Base):
    __tablename__ = "syllabus"
    id: Mapped[int] = mapped_column(primary_key=True)
    dept_id: Mapped[int] = mapped_column(ForeignKey("dept.id"))
    skey: Mapped[str] = mapped_column(S(80))
    section: Mapped[str] = mapped_column(S(80))
    subject: Mapped[str] = mapped_column(S(200))
    code: Mapped[str] = mapped_column(S(40), default="")
    unit: Mapped[str] = mapped_column(S(80), default="")
    topic: Mapped[str] = mapped_column(S(500))
    covered: Mapped[str] = mapped_column(S(10))
    fkey: Mapped[str] = mapped_column(S(120))
    teacher: Mapped[str] = mapped_column(S(120), default="")
    __table_args__ = (Index("ix_syl_sec", "dept_id", "skey"), Index("ix_syl_fac", "dept_id", "fkey"))

_A = ("id", "section", "subject", "code", "title", "details", "due", "posted", "teacher")
_Y = ("id", "section", "subject", "code", "unit", "topic", "covered", "teacher")
_d = lambda o, cols: {c: getattr(o, c) for c in cols}

def classwork(db, d, sk):  # what a student of this section sees (cached: everyone in a section shares it)
    def load():
        a = db.scalars(select(Assignment).where(Assignment.dept_id == d, Assignment.skey == sk).order_by(Assignment.due, Assignment.id)).all()
        y = db.scalars(select(Syllabus).where(Syllabus.dept_id == d, Syllabus.skey == sk).order_by(Syllabus.covered.desc(), Syllabus.id.desc())).all()
        return [_d(x, _A) for x in a], [_d(x, _Y) for x in y]
    return cached(("cw", d, sk), 30, load)

def teacher_classes(db, d, fk):  # the (section, subject) pairs a teacher actually teaches, from the timetable
    def load():
        q = select(Slot.section, Slot.skey, Slot.subject, Slot.code).where(Slot.dept_id == d, Slot.fkey == fk).distinct().order_by(Slot.subject, Slot.section)
        return [dict(section=a, skey=b, subject=c, code=e) for a, b, c, e in db.execute(q)]
    return cached(("tc", d, fk), 60, load)

def teacher_posts(db, d, fk):
    a = db.scalars(select(Assignment).where(Assignment.dept_id == d, Assignment.fkey == fk).order_by(Assignment.due.desc()).limit(200)).all()
    y = db.scalars(select(Syllabus).where(Syllabus.dept_id == d, Syllabus.fkey == fk).order_by(Syllabus.covered.desc(), Syllabus.id.desc()).limit(300)).all()
    return [_d(x, _A) for x in a], [_d(x, _Y) for x in y]
