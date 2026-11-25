import os, hmac, hashlib, time, datetime as dt
from zoneinfo import ZoneInfo
import jwt
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.security import HTTPBearer
from fastapi.staticfiles import StaticFiles
from typing import Annotated
from pydantic import BaseModel, Field
from sqlalchemy import select, delete, func
from .db import Session, Dept, User, Slot, Faculty, Room, Notice, UniNotice, Assignment, Syllabus, cached, bust, forget, stamp, uni_notices, timetable, ftimetable, lookups, notices, fkey, skey, classwork, teacher_classes, teacher_posts
from . import chatbot, excel, dean

PROD = os.getenv("ENV") == "prod"
SECRET = os.getenv("SECRET_KEY", "dev-secret-change-me")
DEAN_USER = os.getenv("DEAN_USERNAME") or "dean"
DEAN_PASS = os.getenv("DEAN_PASSWORD") or "dean_admin123"
if PROD:  # refuse to start with development defaults
    if len(SECRET) < 32 or SECRET in ("dev-secret-change-me", "generate-with-openssl-rand-hex-32"): raise RuntimeError("Set SECRET_KEY (openssl rand -hex 32)")
    if len(DEAN_PASS) < 12 or DEAN_PASS == "dean_admin123": raise RuntimeError("Set DEAN_PASSWORD (at least 12 characters)")
TZ = ZoneInfo(os.getenv("APP_TZ", "Asia/Kolkata"))
_today = lambda: dt.datetime.now(TZ).date().isoformat()  # the campus's date, not the server's (containers run on UTC)
app = FastAPI(title="Campus Timetable", docs_url=None, redoc_url=None)
app.add_middleware(GZipMiddleware, minimum_size=800)

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; "
       "img-src 'self' data: blob:; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
@app.middleware("http")
async def security_headers(req, call_next):
    r = await call_next(req)
    for k, v in (("Content-Security-Policy", CSP), ("X-Content-Type-Options", "nosniff"), ("X-Frame-Options", "DENY"), ("Referrer-Policy", "same-origin")):
        r.headers.setdefault(k, v)
    return r

def hash_pw(p):
    s = os.urandom(16); return s.hex() + "$" + hashlib.pbkdf2_hmac("sha256", p.encode(), s, 200_000).hex()
def hash_temp(p): return "!" + hash_pw(p)  # "!" = one-time password (new or reset admin): must be changed at the next sign-in
def check_pw(p, h):
    s, d = h.lstrip("!").split("$"); return hmac.compare_digest(hashlib.pbkdf2_hmac("sha256", p.encode(), bytes.fromhex(s), 200_000).hex(), d)

def get_db():
    with Session() as s: yield s
def _decode(cr):
    try: return jwt.decode(cr.credentials, SECRET, algorithms=["HS256"])
    except Exception: raise HTTPException(401, "Session expired. Please sign in again.")
_pv = lambda h: hashlib.sha256((h or "").encode()).hexdigest()[:16]  # password fingerprint in the token: a password change ends every older session
def _user_state(uid):
    with Session() as s:
        u = s.get(User, uid)
        return (_pv(u.pw_hash), u.dept_id, u.role) if u else None
def session(cr=Depends(HTTPBearer(auto_error=False))):  # a department login that still exists, with the password and role it signed in with
    c = _decode(cr)
    if c["role"] == "dean": raise HTTPException(403, "The Dean's portal cannot use department routes.")
    if cached(("u", c["uid"]), 30, lambda: _user_state(c["uid"])) != (c.get("pv"), c["dept"], c["role"]):
        raise HTTPException(401, "Session expired. Please sign in again.")
    return c
def claims(c=Depends(session)):  # every department route (student / faculty / admin) -- the Dean has none of these
    if c.get("pwc"): raise HTTPException(403, "Set your own password first.")
    return c
def dean_only(cr=Depends(HTTPBearer(auto_error=False))):
    c = _decode(cr)
    if c["role"] != "dean": raise HTTPException(403, "This area is for the Dean's Office only.")
    return c
def admin(c=Depends(claims)):
    if c["role"] != "admin": raise HTTPException(403, "Admins only")
    return c

def Str(n): return Annotated[str, Field(max_length=n)]  # every request field is bounded
class Login(BaseModel): dept: Str(40) = ""; username: Str(100); password: Str(200)
class Chat(BaseModel): message: Str(1000)
class AsgIn(BaseModel): section: Str(200); subject: Str(300); title: Str(1000); details: Str(5000) = ""; due: Str(20)
class SylIn(BaseModel): section: Str(200); subject: Str(300); topic: Str(2000); unit: Str(200) = ""; covered: Str(20) = ""
class PwIn(BaseModel): current: Str(200); new: Str(200)
class ResetIn(BaseModel): username: Str(100)
class NoticeIn(BaseModel): title: Str(1000); body: Str(5000) = ""; audience: Str(20) = "all"; pinned: bool = False
class WhoIn(BaseModel): faculty: list[Str(200)]; day: Str(20) | None = None; start: Str(20) | None = None; end: Str(20) | None = None

@app.get("/api/health")
def health(db=Depends(get_db)): db.execute(select(1)); return {"ok": True}

@app.get("/api/departments")
def departments(db=Depends(get_db)):
    return cached("depts", 300, lambda: [{"code": d.code, "name": d.name} for d in db.scalars(select(Dept).order_by(Dept.id))])

# Failed sign-ins per (client IP, account), per worker: 10 in 5 minutes blocks that account from that IP only. A campus shares one IP,
# so this never locks out the whole campus, and nobody elsewhere can lock an account (e.g. the Dean) out for everyone.
_fails = {}
def _ip(req): return req.headers.get("x-forwarded-for", "").split(",")[0].strip() or (req.client.host if req.client else "")  # nginx overwrites this header
def _throttle(key):
    now = time.time(); xs = [t for t in _fails.get(key, ()) if t > now - 300]
    if xs: _fails[key] = xs
    else: _fails.pop(key, None)
    if len(xs) >= 10: raise HTTPException(429, "Too many failed sign-ins. Try again in a few minutes.")
def _failed(key):
    if len(_fails) > 50_000: _fails.clear()
    _fails.setdefault(key, []).append(time.time())
_DUMMY = hash_pw(os.urandom(8).hex())
def _same(a, b): return hmac.compare_digest(a.strip().upper().encode(), b.strip().upper().encode())
_temp = lambda h: h is None or h.startswith("!")  # no hash = first sign-in with their ID; "!" = one-time admin password
def _token(u, dname):  # pwc: still on a first-sign-in / one-time password, so only /api/password is allowed until they set their own
    tok = jwt.encode({"uid": u.id, "dept": u.dept_id, "role": u.role, "section": u.section, "group": u.group, "name": u.name or u.username, "dname": dname,
                      "pv": _pv(u.pw_hash), "pwc": _temp(u.pw_hash), "exp": dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=12)}, SECRET, "HS256")
    return {"token": tok, "role": u.role, "name": u.name or u.username, "dept": dname, "section": u.section, "must_change": _temp(u.pw_hash)}

@app.post("/api/login")
def login(b: Login, req: Request, db=Depends(get_db)):
    if hmac.compare_digest(b.username.strip().lower().encode(), DEAN_USER.lower().encode()): return dean_login(b, _ip(req))  # reserved username; no department needed
    if not b.dept: raise HTTPException(400, "Please select your department.")
    un = b.username.strip(); key = (_ip(req), b.dept[:40], un.upper()[:60]); _throttle(key)
    d = db.scalar(select(Dept).where(Dept.code == b.dept)); u = None
    if d:
        for name in (un.upper(), un):
            u = db.scalar(select(User).where(User.dept_id == d.id, User.username == name))
            if u: break
    if u and u.pw_hash: ok = check_pw(b.password, u.pw_hash)
    else:  # first sign-in: password = Reg No / Employee ID. Hash anyway, so an unknown ID takes as long as a real one.
        check_pw(b.password, _DUMMY); ok = bool(u) and _same(b.password, u.username)
    if not ok: _failed(key); raise HTTPException(401, "Wrong department, ID or password")
    return _token(u, d.name)

def dean_login(b, ip):
    key = (ip, "dean"); _throttle(key)
    if not hmac.compare_digest(b.password.encode(), DEAN_PASS.encode()):
        _failed(key); raise HTTPException(401, "Wrong department, ID or password")
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
                      details=b.details.strip()[:2000], due=_date(b.due), posted=_today(), fkey=fk, teacher=c["name"]))
    db.commit(); bust(); return {"ok": True}

@app.post("/api/teacher/syllabus")
def post_syllabus(b: SylIn, c=Depends(teacher), db=Depends(get_db)):
    fk, m = _mine(db, c, b.section, b.subject)
    if not b.topic.strip(): raise HTTPException(400, "Topic is required")
    db.add(Syllabus(dept_id=c["dept"], skey=m["skey"], section=m["section"], subject=m["subject"], code=m["code"], unit=b.unit.strip()[:80],
                    topic=b.topic.strip()[:500], covered=_date(b.covered, _today()), fkey=fk, teacher=c["name"]))
    db.commit(); bust(); return {"ok": True}

@app.delete("/api/teacher/{kind}/{rid}")
def delete_post(kind: str, rid: int, c=Depends(teacher), db=Depends(get_db)):
    M = {"assignment": Assignment, "syllabus": Syllabus}.get(kind)
    if not M: raise HTTPException(404)
    db.execute(delete(M).where(M.id == rid, M.dept_id == c["dept"], M.fkey == fkey(c["name"]))); db.commit(); bust(); return {"ok": True}

# ---------------- department admin (scoped to the admin's own department) ----------------
@app.post("/api/password")  # every student / faculty / admin login changes its own password (required at first sign-in); returns a fresh token
def change_password(b: PwIn, c=Depends(session), db=Depends(get_db)):
    u = db.get(User, c["uid"])
    if not u or not (check_pw(b.current, u.pw_hash) if u.pw_hash else _same(b.current, u.username)): raise HTTPException(400, "Current password is incorrect")
    if not 8 <= len(b.new) <= 128: raise HTTPException(400, "New password must be 8 to 128 characters")
    if b.new == b.current or b.new.lower() == "admin123" or _same(b.new, u.username): raise HTTPException(400, "Choose a different password (not your ID or a default)")
    u.pw_hash = hash_pw(b.new); db.commit(); forget(("u", u.id))
    return _token(u, c["dname"])

@app.post("/api/admin/reset-password")  # a student / faculty member who forgot theirs goes back to the first-sign-in password (their ID)
def reset_password(b: ResetIn, c=Depends(admin), db=Depends(get_db)):
    u = db.scalar(select(User).where(User.dept_id == c["dept"], User.username == b.username.strip().upper(), User.role.in_(("student", "faculty"))))
    if not u: raise HTTPException(404, "No student or faculty login with that ID in your department.")
    u.pw_hash = None; db.commit(); forget(("u", u.id)); return {"ok": True}

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
    db.add(Notice(dept_id=c["dept"], title=b.title.strip()[:200], body=b.body.strip()[:2000], audience=aud, pinned=int(b.pinned), posted=_today()))
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
    db.add(UniNotice(title=b.title.strip()[:200], body=b.body.strip()[:2000], audience=aud, pinned=int(b.pinned), posted=_today()))
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
