"""Dean's Office logic (read-only across every department; the endpoints live in main.py).

Everything is read live from the same tables the department admins upload into, so the Dean always sees what students and
faculty see. Results go through the same per-worker TTL cache as the rest of the app (cached()/bust()), so a dean refreshing
the page never turns into 12 departments' worth of queries.

Faculty are matched across departments by name (fkey: case-insensitive, "Dr."/"Prof." and punctuation ignored), so one
person teaching in two departments is a single person here and a class in either department counts as busy.
Times are compared as clock times, not period numbers, so departments may use their own period timings.
"""
import json, os, re
from fastapi import HTTPException
from sqlalchemy import select, func
from .db import Dept, User, Slot, Faculty, Sync, cached, fkey

DAYN = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
SHORT = {x["id"]: x["short"] for x in json.load(open(os.path.join(os.path.dirname(__file__), "departments.json")))}
TTL = 60  # same freshness window as lookups()/timetable() in db.py

def mins(t):
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", t or "")
    return int(m[1]) * 60 + int(m[2]) if m and int(m[1]) < 24 and int(m[2]) < 60 else None
hhmm = lambda m: f"{m // 60:02d}:{m % 60:02d}"

def depts(db):  # {dept pk: {id (code), name, short}}
    return cached(("dn", "depts"), 300, lambda: {d.id: dict(id=d.code, name=d.name, short=SHORT.get(d.code, d.code.upper())) for d in db.scalars(select(Dept).order_by(Dept.id))})

def directory(db):
    """(people list sorted by name, people by key): every faculty member of every department, merged by name."""
    def load():
        D, people = depts(db), {}
        def person(name):
            k = fkey(name)
            return people.setdefault(k, dict(key=k, name=name, departments={}, info=[], sessions=0)) if k else None
        for f in db.scalars(select(Faculty).order_by(Faculty.id)):  # the department's own faculty list first: it has the properly spelt name + contact details
            d, p = D.get(f.dept_id), person(f.name)
            if not d or not p: continue
            p["departments"][d["id"]] = d["short"]
            p["info"].append({k: v for k, v in dict(dept=d["short"], designation=f.designation, emp_id=f.emp_id, email=f.email, phone=f.phone, cabin=f.cabin).items() if v})
        for dept_id, name, n in db.execute(select(Slot.dept_id, Slot.faculty, func.count()).group_by(Slot.dept_id, Slot.faculty)):  # then anyone who only appears in a timetable
            d, p = D.get(dept_id), person(name)
            if not d or not p: continue
            p["departments"][d["id"]] = d["short"]; p["sessions"] += n
        rows = sorted(({**p, "departments": [dict(id=i, short=s) for i, s in sorted(p["departments"].items())]} for p in people.values()), key=lambda r: r["name"].lower())
        return rows, {r["key"]: r for r in rows}
    return cached(("dn", "dir"), TTL, load)

def overview(db):
    """One row per department (what it has published, and when) + university totals."""
    def load():
        D = depts(db)
        agg = {r[0]: r[1:] for r in db.execute(select(Slot.dept_id, func.count(), func.count(func.distinct(Slot.skey)), func.count(func.distinct(Slot.fkey)), func.count(func.distinct(Slot.room))).group_by(Slot.dept_id))}
        stu = {a: b for a, b in db.execute(select(User.dept_id, func.count()).where(User.role == "student").group_by(User.dept_id))}
        fac = {a: b for a, b in db.execute(select(Faculty.dept_id, func.count()).group_by(Faculty.dept_id))}
        syn = {}
        for x in db.scalars(select(Sync)): syn.setdefault(x.dept_id, {})[x.kind] = x.at
        rows = []
        for pk, d in D.items():
            sl, sec, tea, rm = agg.get(pk, (0, 0, 0, 0))
            rows.append(dict(d, has_timetable=sl > 0, periods=sl, sections=sec, teachers=tea, rooms=rm, students=stu.get(pk, 0), faculty=fac.get(pk, 0), synced=syn.get(pk, {})))
        return dict(departments=rows, totals=dict(departments=len(rows), with_timetable=sum(r["has_timetable"] for r in rows), faculty=len(directory(db)[0]),
                                                   students=sum(stu.values()), periods=sum(r["periods"] for r in rows)))
    return cached(("dn", "ov"), TTL, load)

def timetable(db, code):
    """A department's whole published timetable (one row per section/day/period). None if it has not published one."""
    d = next((x for x in depts(db).items() if x[1]["id"] == code), None)
    if not d: raise HTTPException(404, "Unknown department.")
    pk, info = d
    def load():
        rows = db.scalars(select(Slot).where(Slot.dept_id == pk).order_by(Slot.day, Slot.period)).all()
        if not rows: return None
        slots = [dict(day=s.day, period=s.period, start=s.start, end=s.end, code=s.code, subject=s.subject, kind=s.kind, section=s.section, group=s.group, faculty=s.faculty, room=s.room) for s in rows]
        return dict(department=info, slots=slots, stats=next(r for r in overview(db)["departments"] if r["id"] == code))
    r = cached(("dn", "tt", pk), TTL, load)
    if r is None: raise HTTPException(404, f"{info['name']} has not published a timetable yet.")
    return r

def grid_meta(db):
    """(sorted unique period windows in minutes, working days) across all departments."""
    def load():
        w = sorted({(a, b) for a, b in ((mins(s), mins(e)) for s, e in db.execute(select(Slot.start, Slot.end).distinct())) if a is not None and b is not None and a < b})
        return w, sorted({d for (d,) in db.execute(select(Slot.day).distinct())} | {0, 1, 2, 3, 4, 5})
    return cached(("dn", "grid"), TTL, load)

def _blocks(db, keys):
    """{fkey: [class blocks]} -- consecutive periods of the same class are merged into one block (a 2-period lab is one block)."""
    out = {k: [] for k in keys}
    for s in db.scalars(select(Slot).where(Slot.fkey.in_(keys)).order_by(Slot.dept_id, Slot.day, Slot.start, Slot.period)):
        a, b = mins(s.start), mins(s.end)
        if a is None or b is None or b <= a: continue
        L = out[s.fkey]; p = L[-1] if L else None
        if p and p["dept_pk"] == s.dept_id and p["day"] == s.day and p["end"] == a and all(p[k] == getattr(s, k) for k in ("subject", "section", "group", "room")): p["end"] = b
        else: L.append(dict(dept_pk=s.dept_id, day=s.day, start=a, end=b, room=s.room, code=s.code, subject=s.subject, kind=s.kind, section=s.section, group=s.group))
    return out

def _j(b, D):
    d = D.get(b["dept_pk"], {})
    return dict(dept_id=d.get("id", ""), dept=d.get("short", ""), dept_display=d.get("name", ""), room=b["room"], course_code=b["code"], course_name=b["subject"], kind=b["kind"],
                section=b["section"] + (" " + b["group"] if b["group"] else ""), day=DAYN[b["day"]], start=hhmm(b["start"]), end=hhmm(b["end"]))
_hit = lambda b, s, e: b["start"] < e and b["end"] > s

def availability(db, keys, day=None, start=None, end=None):
    """Who is free when. `day`+`start` (+`end`) answer 'is everyone free then / where are they?'; the week grid answers 'when is everyone free together?'."""
    D, people = depts(db), directory(db)[1]
    chosen = []
    for k in dict.fromkeys(keys):  # de-dupe, keep order
        if k not in people: raise HTTPException(404, "Unknown faculty member (a department may have changed its lists). Reload the page.")
        chosen.append(people[k])
    blocks = _blocks(db, [p["key"] for p in chosen])
    windows, days = grid_meta(db)

    at_time = None
    if start:
        if not day or day.strip().capitalize() not in DAYN: raise HTTPException(400, "Choose a day as well as a time.")
        a = mins(start)
        if a is None: raise HTTPException(400, f"Invalid time {start!r}; use HH:MM (24-hour).")
        b = mins(end) if end else min(a + 1, 24 * 60)
        if b is None: raise HTTPException(400, f"Invalid time {end!r}; use HH:MM (24-hour).")
        if b <= a: raise HTTPException(400, "End time must be after the start time.")
        di, rows = DAYN.index(day.strip().capitalize()), []
        for p in chosen:
            today = sorted((x for x in blocks[p["key"]] if x["day"] == di), key=lambda x: x["start"])
            busy = [x for x in today if _hit(x, a, b)]
            row = dict(key=p["key"], name=p["name"], departments=p["departments"], info=p["info"][:1], free=not busy, busy=[_j(x, D) for x in busy])
            if busy:
                t, changed = max(x["end"] for x in busy), True
                while changed:  # chain back-to-back classes to find when they are truly free
                    changed = False
                    for x in today:
                        if x["start"] <= t < x["end"]: t, changed = x["end"], True
                row["free_from"] = hhmm(t)
            else:
                nxt = next((x for x in today if x["start"] >= b), None)
                row["next_class"] = _j(nxt, D) if nxt else None
            rows.append(row)
        at_time = dict(day=DAYN[di], start=hhmm(a), end=hhmm(b), all_free=all(r["free"] for r in rows), busy_count=sum(1 for r in rows if not r["free"]), people=rows)

    grid, suggested = {}, {}
    for di in days:
        cells, runs = [], []
        for s, e in windows:
            busy = []
            for p in chosen:
                hit = next((x for x in blocks[p["key"]] if x["day"] == di and _hit(x, s, e)), None)
                if hit: busy.append(dict(name=p["name"], **_j(hit, D)))
            cells.append(dict(start=hhmm(s), end=hhmm(e), all_free=not busy, busy=busy))
            if not busy:
                if runs and runs[-1][1] >= s: runs[-1][1] = e
                else: runs.append([s, e])
        grid[DAYN[di]] = cells; suggested[DAYN[di]] = [[hhmm(x), hhmm(y)] for x, y in runs]
    return dict(at_time=at_time, slots=[dict(start=hhmm(s), end=hhmm(e)) for s, e in windows], days=[DAYN[i] for i in days], grid=grid, suggested=suggested, has_data=bool(windows))
