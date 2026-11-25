import io, re, zipfile, datetime as dt
from openpyxl import load_workbook, Workbook
from .db import DEFAULT_PERIODS, t12, fkey, skey

DAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
MASTER = ["Course Code", "Course Name", "Kind", "Duration (pd)", "Teacher", "Register", "Section", "Day", "Start Period", "Room", "Status"]
# Templates hold headers only: an example row left in by mistake would be uploaded as a real session / student / faculty login.
# The "How to fill" sheet is never read by the upload.
TEMPLATES = {
    "timetable": {"Master": [MASTER], "Rooms": [["Room", "Building", "Floor", "Directions"]], "How to fill": [
        ["Sheet 'Master': one row per session, as the scheduler exports it (same layout as its 'Master' sheet)."],
        ["Start Period: the time range of the first period, written like 9:30-10:30. Hours before 8 are afternoon (1:30 = 13:30)."],
        ["Day: Monday to Saturday. Duration (pd): number of consecutive periods, 1 to 8. Status: only Placed (or blank) rows are published."],
        ["Section: the class name, e.g. B.Tech CSE A; add (G1) for a lab group. Students must use exactly the same section text."],
        ["Sheet 'Rooms' (optional): building, floor and directions per room. Leave it empty to keep the room details already saved."],
        ["Uploading replaces the department's whole timetable."]]},
    "students": {"Students": [["Reg No", "Name", "Section", "Group"]], "How to fill": [
        ["One row per student. Reg No is their username; their first password is also the Reg No, and they must choose their own at first sign-in."],
        ["Section must be written exactly as in the timetable (e.g. B.Tech CSE A). Group is optional (G1, G2...)."]]},
    "faculty": {"Faculty": [["Faculty Name", "Employee ID", "Nature of Appointment", "Email", "Phone", "Cabin"]], "How to fill": [
        ["One row per faculty member. Faculty Name must match the Teacher column of the timetable (Dr./Prof. and punctuation are ignored)."],
        ["Employee ID is their username; their first password is also the Employee ID, and they must choose their own at first sign-in."]]}}

def template(kind):
    wb = Workbook(); wb.remove(wb.active)
    for name, rows in TEMPLATES[kind].items():
        ws = wb.create_sheet(name)
        for r in rows: ws.append(r)
    b = io.BytesIO(); wb.save(b); b.seek(0); return b

H = lambda h: re.sub(r"[^a-z0-9]+", "_", str(h or "").lower()).strip("_")
def _s(v):
    s = str(v).strip(); return s[:-2] if re.fullmatch(r"\d+\.0", s) else s

def open_wb(data):
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:  # refuse zip bombs before openpyxl unpacks anything
            if sum(i.file_size for i in z.infolist()) > 200_000_000: raise ValueError("The file is too large once unpacked")
    except zipfile.BadZipFile: raise ValueError("Not a valid .xlsx file")
    try: return load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception: raise ValueError("Not a valid .xlsx file")

def _rows(wb, name, required, first=True):
    if name not in wb.sheetnames:
        if not first: return []
        name = wb.sheetnames[0]
    it = wb[name].iter_rows(values_only=True)
    head = [H(h) for h in next(it, [])]
    miss = [c for c in required if c not in head]
    if miss: raise ValueError(f"Sheet '{name}' is missing column(s): {', '.join(miss)}")
    return [(i, {h: ("" if v is None else v) for h, v in zip(head, r)}) for i, r in enumerate(it, 2) if any(v not in (None, "") for v in r)]

HM = re.compile(r"(\d{1,2}):(\d{2})")
def _times(label):
    a, b = re.sub(r"[\s]", "", str(label)).replace("–", "-").replace("—", "-").split("-")
    def f(x):  # strictly H:MM -- anything else is rejected (these strings end up in every timetable page)
        m = HM.fullmatch(x)
        if not m or int(m[1]) > 23 or int(m[2]) > 59: raise ValueError(f"Invalid time {x!r}")
        h = int(m[1]); return f"{h + 12 if h < 8 else h:02d}:{m[2]}"
    return f(a), f(b)

GROUP = re.compile(r"^(.*?)[\s,:\-]*\(?\s*(G\d+)\s*\)?\s*$", re.I)
MULTI = re.compile(r"[\s,:\-]*\(?\s*G\d+(\s*[,&/]\s*G\d+)+\s*\)?\s*$", re.I)
def split_section(s):
    """'B.Tech CSE B(G1)' -> ('B.Tech CSE B','G1'); joint 'B(G1, G2)' -> ('B','')"""
    s = _s(s)
    if MULTI.search(s): return MULTI.sub("", s).strip(), ""
    m = GROUP.match(s)
    return (m.group(1).strip(), m.group(2).upper()) if m else (s, "")

def parse_timetable(wb):
    """Reads the scheduler's exported workbook (sheet 'Master'); optional 'Rooms' sheet."""
    errs, raw, skipped = [], [], 0
    for i, r in _rows(wb, "Master", ["course_name", "teacher", "section", "day", "start_period"]):
        if str(r.get("status", "Placed")).strip().lower() not in ("placed", ""): skipped += 1; continue
        day = DAYS.get(str(r["day"]).strip()[:3].lower())
        try: lab = str(r["start_period"]); _times(lab)
        except Exception: lab = None
        if day is None or lab is None or not str(r["section"]).strip(): errs.append(f"Master row {i}: invalid Section / Day / Start Period"); continue
        raw.append((i, r, day, lab))
    known = {f"{t12(a)}-{t12(b)}": p for p, (a, b) in DEFAULT_PERIODS.items()}
    norm = lambda l: re.sub(r"[\s]", "", l).replace("–", "-")
    labels = sorted({norm(x[3]) for x in raw}, key=lambda l: _times(l)[0])
    pidx = known if all(l in known for l in labels) else {l: n for n, l in enumerate(labels, 1)}
    plabel = {p: l for l, p in pidx.items()}
    slots = []
    for i, r, day, lab in raw:
        base, grp = split_section(r["section"])
        try: dur = min(8, max(1, int(float(r.get("duration_pd") or 1))))  # no session is longer than a day's periods
        except (ValueError, OverflowError): dur = 1
        p0 = pidx[norm(lab)]
        for k in range(dur):
            p = p0 + k; a, b = _times(plabel.get(p, norm(lab)))
            slots.append(dict(section=base, skey=skey(base), group=grp, day=day, period=p, start=a, end=b, code=_s(r.get("course_code", "")),
                              subject=str(r["course_name"]).strip(), faculty=str(r["teacher"]).strip(), fkey=fkey(r["teacher"]),
                              room=_s(r.get("room", "")), kind=str(r.get("kind", "") or "Theory").strip()))
    rooms = None
    if "Rooms" in wb.sheetnames:
        rooms = [dict(name=_s(r["room"]), building=str(r.get("building", "")), floor=_s(r.get("floor", "")), directions=str(r.get("directions", "")))
                 for _, r in _rows(wb, "Rooms", ["room"], False) if r["room"] != ""] or None  # an empty sheet keeps the saved rooms
    return slots, rooms, errs, skipped

def parse_faculty(wb):
    """Accepts a plain faculty list or the repo's teaching-load register (merged cells are forward-filled)."""
    out, errs, last = {}, [], ("", "", "")
    rows = _rows(wb, "Faculty", [])
    for i, r in rows:
        name = str(r.get("faculty_name") or r.get("name") or "").strip()
        eid = _s(r.get("employee_id") or r.get("emp_id") or r.get("reg_no") or "")
        if not name: name, eid, _ = last[0], last[1], 0
        if not name: continue
        last = (name, eid or last[1] if name == last[0] else eid, 0)
        e = out.setdefault(fkey(name), dict(name=name, emp_id="", designation="", email="", phone="", cabin=""))
        for k, v in (("emp_id", eid), ("designation", r.get("designation") or r.get("nature_of_appointment") or r.get("register") or ""),
                     ("email", r.get("email", "")), ("phone", r.get("phone", "")), ("cabin", r.get("cabin", ""))):
            if v != "" and not e[k]: e[k] = _s(v)
    if not out: errs.append("No faculty rows found (need a 'Faculty Name' column)")
    return list(out.values()), errs

def parse_students(wb):
    out, errs = {}, []
    for i, r in _rows(wb, "Students", ["reg_no", "section"]):
        reg = _s(r["reg_no"]).upper()
        if not reg or not str(r["section"]).strip(): errs.append(f"Row {i}: reg_no / section missing"); continue
        base, g = split_section(r["section"])
        nm = r.get("name") or r.get("student_name") or r.get("full_name") or r.get("candidate_name") or ""
        out[reg] = dict(username=reg, name=re.sub(r"\s+", " ", str(nm)).strip(), section=base, group=_s(r.get("group", "")).upper() or g)
    return list(out.values()), errs
