import os, hmac, hashlib, time, datetime as dt
from zoneinfo import ZoneInfo
import jwt
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.security import HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import select, delete, func
from .db import Session, Dept, User, Slot, Faculty, Room, Notice, UniNotice, Assignment, Syllabus, cached, bust, stamp, uni_notices, timetable, ftimetable, lookups, notices, fkey, skey, classwork, teacher_classes, teacher_posts
from . import chatbot, excel, dean

SECRET = os.getenv("SECRET_KEY", "dev-secret-change-me")
if os.getenv("ENV") == "prod" and SECRET == "dev-secret-change-me": raise RuntimeError("Set SECRET_KEY")
DEAN_USER = os.getenv("DEAN_USERNAME") or "dean"
DEAN_PASS = os.getenv("DEAN_PASSWORD") or "dean_admin123"
if os.getenv("ENV") == "prod" and DEAN_PASS == "dean_admin123": raise RuntimeError("Set DEAN_PASSWORD")
TZ = ZoneInfo(os.getenv("APP_TZ", "Asia/Kolkata"))
app = FastAPI(title="Campus Timetable", docs_url=None, redoc_url=None)
app.add_middleware(GZipMiddleware, minimum_size=800)

def hash_pw(p):
    s = os.urandom(16); return s.hex() + "$" + hashlib.pbkdf2_hmac("sha256", p.encode(), s, 200_000).hex()
def check_pw(p, h):
    s, d = h.split("$"); return hmac.compare_digest(hashlib.pbkdf2_hmac("sha256", p.encode(), bytes.fromhex(s), 200_000).hex(), d)

def get_db():
    with Session() as s: yield s
def _decode(cr):
    try: return jwt.decode(cr.credentials, SECRET, algorithms=["HS256"])
    except Exception: raise HTTPException(401, "Session expired. Please sign in again.")
def claims(cr=Depends(HTTPBearer(auto_error=False))):  # every department route (student / faculty / admin) -- the Dean has none of these
    c = _decode(cr)
    if c["role"] == "dean": raise HTTPException(403, "The Dean's portal cannot use department routes.")
    return c
def dean_only(cr=Depends(HTTPBearer(auto_error=False))):
    c = _decode(cr)
    if c["role"] != "dean": raise HTTPException(403, "This area is for the Dean's Office only.")
    return c
def admin(c=Depends(claims)):
    if c["role"] != "admin": raise HTTPException(403, "Admins only")
    return c

class Login(BaseModel): dept: str = ""; username: str; password: str
class Chat(BaseModel): message: str
class AsgIn(BaseModel): section: str; subject: str; title: str; details: str = ""; due: str
class SylIn(BaseModel): section: str; subject: str; topic: str; unit: str = ""; covered: str = ""
class PwIn(BaseModel): current: str; new: str
class NoticeIn(BaseModel): title: str; body: str = ""; audience: str = "all"; pinned: bool = False
class WhoIn(BaseModel): faculty: list[str]; day: str | None = None; start: str | None = None; end: str | None = None

@app.get("/api/health")
def health(db=Depends(get_db)): db.execute(select(1)); return {"ok": True}

@app.get("/api/departments")
def departments(db=Depends(get_db)):
    return cached("depts", 300, lambda: [{"code": d.code, "name": d.name} for d in db.scalars(select(Dept).order_by(Dept.id))])

@app.post("/api/login")
def login(b: Login, db=Depends(get_db)):
    if hmac.compare_digest(b.username.strip().lower().encode(), DEAN_USER.lower().encode()): return dean_login(b)  # reserved username; no department needed
    if not b.dept: raise HTTPException(400, "Please select your department.")
    d = db.scalar(select(Dept).where(Dept.code == b.dept)); un = b.username.strip(); u = None
    if d:
        for name in (un.upper(), un):
            u = db.scalar(select(User).where(User.dept_id == d.id, User.username == name))
            if u: break
    ok = bool(u) and (check_pw(b.password, u.pw_hash) if u.pw_hash else hmac.compare_digest(b.password.strip().upper(), u.username.upper()))
    if not ok: raise HTTPException(401, "Wrong department, ID or password")
    tok = jwt.encode({"uid": u.id, "dept": d.id, "role": u.role, "section": u.section, "group": u.group, "name": u.name or u.username, "dname": d.name,
                      "exp": dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=12)}, SECRET, "HS256")
    return {"token": tok, "role": u.role, "name": u.name or u.username, "dept": d.name, "section": u.section}

_dean_fails = []  # recent failed Dean sign-ins (per worker). A campus shares one IP, so only this one privileged account is throttled, never students.
def dean_login(b):
    now = time.time(); _dean_fails[:] = [t for t in _dean_fails if t > now - 300]
    if len(_dean_fails) >= 10: raise HTTPException(429, "Too many failed Dean's Office sign-ins. Try again in a few minutes.")
    if not hmac.compare_digest(b.password.encode(), DEAN_PASS.encode()):
        _dean_fails.append(now); raise HTTPException(401, "Wrong department, ID or password")
    tok = jwt.encode({"uid": 0, "dept": None, "role": "dean", "section": "", "group": "", "name": "Dean's Office", "dname": "Dean's Office",
                      "exp": dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=12)}, SECRET, "HS256")
    return {"token": tok, "role": "dean", "name": "Dean's Office", "dept": "Dean's Office", "section": ""}

@app.get("/api/timetable")  # students: their class; faculty: every class they teach
def my_timetable(c=Depends(claims), db=Depends(get_db)):
    d, info = c["dept"], None
    if c["role"] == "faculty":
        slots = ftimetable(db, d, fkey(c["name"])); info = lookups(db, d)[0].get(fkey(c["name"]))
    else: slots = timetable(db, d, c["section"], c.get("group", ""))
    return JSONResponse({"name": c["name"], "dept": c["dname"], "role": c["role"], "section": c["section"], "info": info, "slots": slots,
                         "notices": notices(db, d, c["role"])}, headers={"Cache-Control": "private, max-age=30"})

@app.post("/api/chat")
def chat(b: Chat, c=Depends(claims), db=Depends(get_db)):
    return {"reply": chatbot.answer(db, c, b.message[:300], dt.datetime.now(TZ))}

# ---------------- assignments & syllabus ----------------
def teacher(c=Depends(claims)):
    if c["role"] != "faculty": raise HTTPException(403, "Teachers only")
    return c
def _date(v, default=None):
    try: return dt.date.fromisoformat(v or default).isoformat()
    except (ValueError, TypeError): raise HTTPException(400, "Enter a valid date")
def _mine(db, c, section, subject):  # a teacher may only post for a class + subject they really teach
    fk = fkey(c["name"])
    m = next((x for x in teacher_classes(db, c["dept"], fk) if x["skey"] == skey(section) and x["subject"] == subject), None)
    if not m: raise HTTPException(403, "You can only post for classes you teach")
    return fk, m

@app.get("/api/classwork")
def my_classwork(c=Depends(claims), db=Depends(get_db)):
    today = dt.datetime.now(TZ).date().isoformat()
    if c["role"] == "faculty":
        fk = fkey(c["name"]); a, y = teacher_posts(db, c["dept"], fk)
        return {"role": "faculty", "today": today, "classes": teacher_classes(db, c["dept"], fk), "assignments": a, "syllabus": y}
    a, y = classwork(db, c["dept"], skey(c["section"])) if c["role"] == "student" else ([], [])
    return JSONResponse({"role": c["role"], "today": today, "assignments": a, "syllabus": y}, headers={"Cache-Control": "private, max-age=20"})

@app.post("/api/teacher/assignment")
def post_assignment(b: AsgIn, c=Depends(teacher), db=Depends(get_db)):
    fk, m = _mine(db, c, b.section, b.subject)
    if not b.title.strip(): raise HTTPException(400, "Title is required")
    db.add(Assignment(dept_id=c["dept"], skey=m["skey"], section=m["section"], subject=m["subject"], code=m["code"], title=b.title.strip()[:200],
                      details=b.details.strip()[:2000], due=_date(b.due), posted=dt.date.today().isoformat(), fkey=fk, teacher=c["name"]))
    db.commit(); bust(); return {"ok": True}

@app.post("/api/teacher/syllabus")
def post_syllabus(b: SylIn, c=Depends(teacher), db=Depends(get_db)):
    fk, m = _mine(db, c, b.section, b.subject)
    if not b.topic.strip(): raise HTTPException(400, "Topic is required")
    db.add(Syllabus(dept_id=c["dept"], skey=m["skey"], section=m["section"], subject=m["subject"], code=m["code"], unit=b.unit.strip()[:80],
                    topic=b.topic.strip()[:500], covered=_date(b.covered, dt.date.today().isoformat()), fkey=fk, teacher=c["name"]))
    db.commit(); bust(); return {"ok": True}

@app.delete("/api/teacher/{kind}/{rid}")
def delete_post(kind: str, rid: int, c=Depends(teacher), db=Depends(get_db)):
    M = {"assignment": Assignment, "syllabus": Syllabus}.get(kind)
    if not M: raise HTTPException(404)
    db.execute(delete(M).where(M.id == rid, M.dept_id == c["dept"], M.fkey == fkey(c["name"]))); db.commit(); bust(); return {"ok": True}

# ---------------- department admin (scoped to the admin's own department) ----------------
@app.post("/api/admin/password")  # only department admins can change a password (their own)
def change_password(b: PwIn, c=Depends(admin), db=Depends(get_db)):
    u = db.get(User, c["uid"])
    if not u or not u.pw_hash or not check_pw(b.current, u.pw_hash): raise HTTPException(400, "Current password is incorrect")
    if len(b.new) < 8: raise HTTPException(400, "New password must be at least 8 characters")
    if b.new == b.current or b.new.lower() == "admin123": raise HTTPException(400, "Choose a different, non-default password")
    u.pw_hash = hash_pw(b.new); db.commit(); return {"ok": True}

@app.get("/api/admin/stats")
def stats(c=Depends(admin), db=Depends(get_db)):
    d = c["dept"]; n = lambda m, *w: db.scalar(select(func.count()).select_from(m).where(m.dept_id == d, *w))
    return {"students": n(User, User.role == "student"), "faculty": n(Faculty), "slots": n(Slot), "rooms": n(Room), "notices": n(Notice),
            "sections": db.scalar(select(func.count(func.distinct(Slot.skey))).where(Slot.dept_id == d))}

@app.get("/api/admin/template/{kind}")
def tpl(kind: str, c=Depends(admin)):
    if kind not in excel.TEMPLATES: raise HTTPException(404)
    return StreamingResponse(excel.template(kind), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f"attachment; filename={kind}_template.xlsx"})

def _read(f: UploadFile):
    data = f.file.read(10_000_001)
    if len(data) > 10_000_000: raise HTTPException(413, "File is over 10 MB")
    try: return excel.open_wb(data)
    except ValueError as e: raise HTTPException(400, str(e))
def _bad(errs): raise HTTPException(422, {"message": "Nothing was saved. Fix these and upload again.", "errors": errs[:25]})

@app.post("/api/admin/timetable")
def up_timetable(file: UploadFile = File(...), c=Depends(admin), db=Depends(get_db)):
    try: slots, rooms, errs, skipped = excel.parse_timetable(_read(file))
    except ValueError as e: raise HTTPException(400, str(e))
    if errs or not slots: _bad(errs or ["No placed sessions found in the 'Master' sheet"])
    d = c["dept"]
    db.execute(delete(Slot).where(Slot.dept_id == d))  # replaced atomically in one transaction
    db.bulk_insert_mappings(Slot, [{**s, "dept_id": d} for s in slots])
    if rooms is not None:
        db.execute(delete(Room).where(Room.dept_id == d)); db.bulk_insert_mappings(Room, [{**x, "dept_id": d} for x in rooms])
    stamp(db, d, "timetable"); db.commit(); bust()
    return {"periods_saved": len(slots), "sections": len({s["skey"] for s in slots}), "teachers": len({s["fkey"] for s in slots}), "unplaced_skipped": skipped}

@app.post("/api/admin/students")
def up_students(file: UploadFile = File(...), replace: bool = Form(False), c=Depends(admin), db=Depends(get_db)):
    try: rows, errs = excel.parse_students(_read(file))
    except ValueError as e: raise HTTPException(400, str(e))
    if errs or not rows: _bad(errs or ["No students found"])
    d = c["dept"]
    have = {u.username: u.id for u in db.scalars(select(User).where(User.dept_id == d, User.role == "student"))}
    taken = set(db.scalars(select(User.username).where(User.dept_id == d, User.role != "student")))
    rows = [r for r in rows if r["username"] not in taken]
    new = [{**r, "dept_id": d, "role": "student"} for r in rows if r["username"] not in have]
    upd = [{"id": have[r["username"]], "section": r["section"], "group": r["group"], **({"name": r["name"]} if r["name"] else {})} for r in rows if r["username"] in have]  # a blank name never wipes a stored one
    if new: db.bulk_insert_mappings(User, new)
    if upd: db.bulk_update_mappings(User, upd)
    gone = 0
    if replace:
        keep = {r["username"] for r in rows}; ids = [i for u, i in have.items() if u not in keep]; gone = len(ids)
        for i in range(0, len(ids), 500): db.execute(delete(User).where(User.id.in_(ids[i:i + 500])))
    stamp(db, d, "students"); db.commit(); bust()
    return {"added": len(new), "updated": len(upd), "removed": gone}

@app.post("/api/admin/faculty")
def up_faculty(file: UploadFile = File(...), replace: bool = Form(False), c=Depends(admin), db=Depends(get_db)):
    try: rows, errs = excel.parse_faculty(_read(file))
    except ValueError as e: raise HTTPException(400, str(e))
    if errs: _bad(errs)
    d = c["dept"]
    db.execute(delete(Faculty).where(Faculty.dept_id == d)); db.bulk_insert_mappings(Faculty, [{**r, "dept_id": d} for r in rows])
    have = {u.username: u.id for u in db.scalars(select(User).where(User.dept_id == d, User.role == "faculty"))}
    taken = set(db.scalars(select(User.username).where(User.dept_id == d, User.role != "faculty")))
    login_rows = {r["emp_id"].upper(): r["name"] for r in rows if r["emp_id"] and r["emp_id"].upper() not in taken}
    new = [{"dept_id": d, "username": u, "name": n, "role": "faculty"} for u, n in login_rows.items() if u not in have]
    upd = [{"id": have[u], "name": n} for u, n in login_rows.items() if u in have]
    if new: db.bulk_insert_mappings(User, new)
    if upd: db.bulk_update_mappings(User, upd)
    gone = 0
    if replace:
        ids = [i for u, i in have.items() if u not in login_rows]; gone = len(ids)
        if ids: db.execute(delete(User).where(User.id.in_(ids)))
    stamp(db, d, "faculty"); db.commit(); bust()
    return {"faculty_saved": len(rows), "logins_created": len(new), "logins_updated": len(upd), "logins_removed": gone, "without_employee_id": sum(1 for r in rows if not r["emp_id"])}

@app.get("/api/admin/announcements")
def list_notices(c=Depends(admin), db=Depends(get_db)):
    q = select(Notice).where(Notice.dept_id == c["dept"]).order_by(Notice.pinned.desc(), Notice.id.desc())
    return [dict(id=n.id, title=n.title, body=n.body, audience=n.audience, posted=n.posted, pinned=n.pinned) for n in db.scalars(q)]

@app.get("/api/admin/university-notices")  # posted by the Dean's Office; read-only here
def uni_for_admin(c=Depends(admin), db=Depends(get_db)): return uni_notices(db, "admin")

@app.post("/api/admin/announcement")  # quick single post
def add_notice(b: NoticeIn, c=Depends(admin), db=Depends(get_db)):
    if not b.title.strip(): raise HTTPException(400, "Title is required")
    aud = b.audience if b.audience in ("all", "students", "faculty") else "all"
    db.add(Notice(dept_id=c["dept"], title=b.title.strip()[:200], body=b.body.strip()[:2000], audience=aud, pinned=int(b.pinned), posted=dt.date.today().isoformat()))
    db.commit(); bust(); return {"ok": True}

@app.delete("/api/admin/announcement/{nid}")
def del_notice(nid: int, c=Depends(admin), db=Depends(get_db)):
    db.execute(delete(Notice).where(Notice.id == nid, Notice.dept_id == c["dept"])); db.commit(); bust(); return {"ok": True}

# ---------------- Dean's Office: read-only view of every department + university-wide notices ----------------
@app.get("/api/dean/overview")
def dean_overview(c=Depends(dean_only), db=Depends(get_db)): return dean.overview(db)

@app.get("/api/dean/faculty")
def dean_faculty(c=Depends(dean_only), db=Depends(get_db)):
    return {"faculty": [{k: f[k] for k in ("key", "name", "departments", "sessions")} for f in dean.directory(db)[0]]}

@app.get("/api/dean/timetable/{code}")
def dean_timetable(code: str, c=Depends(dean_only), db=Depends(get_db)):
    return JSONResponse(dean.timetable(db, code), headers={"Cache-Control": "private, max-age=30"})

@app.post("/api/dean/availability")
def dean_availability(b: WhoIn, c=Depends(dean_only), db=Depends(get_db)):
    if not 1 <= len(b.faculty) <= 60: raise HTTPException(400, "Pick between 1 and 60 faculty.")
    return dean.availability(db, b.faculty, b.day, b.start, b.end)

@app.get("/api/dean/notices")
def dean_notices(c=Depends(dean_only), db=Depends(get_db)):
    q = select(UniNotice).order_by(UniNotice.pinned.desc(), UniNotice.id.desc())
    return [dict(id=n.id, title=n.title, body=n.body, audience=n.audience, posted=n.posted, pinned=n.pinned) for n in db.scalars(q)]

@app.post("/api/dean/notice")
def dean_add_notice(b: NoticeIn, c=Depends(dean_only), db=Depends(get_db)):
    if not b.title.strip(): raise HTTPException(400, "Title is required")
    aud = b.audience if b.audience in ("all", "students", "faculty", "admins") else "all"
    db.add(UniNotice(title=b.title.strip()[:200], body=b.body.strip()[:2000], audience=aud, pinned=int(b.pinned), posted=dt.date.today().isoformat()))
    db.commit(); bust(); return {"ok": True}

@app.delete("/api/dean/notice/{nid}")
def dean_del_notice(nid: int, c=Depends(dean_only), db=Depends(get_db)):
    db.execute(delete(UniNotice).where(UniNotice.id == nid)); db.commit(); bust(); return {"ok": True}

class Static(StaticFiles):  # html/css/js are always revalidated, so a new release never runs against stale cached styles
    async def get_response(self, path, scope):
        r = await super().get_response(path, scope)
        r.headers["Cache-Control"] = "public, max-age=86400" if path.startswith("assets/") else "no-cache"
        return r

app.mount("/", Static(directory=os.path.join(os.path.dirname(__file__), "..", "frontend"), html=True))
