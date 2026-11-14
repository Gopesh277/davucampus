import re
from difflib import SequenceMatcher
from .db import lookups, timetable, ftimetable, periods, fkey, t12

DAYN = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
STOP = {"dr", "prof", "mr", "mrs", "ms", "the", "and", "lab", "room", "sir", "madam", "who", "where", "teaches", "when", "free", "meet", "class", "next"}
norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
toks = lambda s: [w for w in re.findall(r"[a-z0-9]+", s.lower()) if len(w) > 2 and w not in STOP]
rng = lambda s: f"{t12(s['start'])}-{t12(s['end'])}"

def _score(words, text):
    t = toks(text)
    if not t: return 0
    return sum(any(w == x or (len(w) > 3 and SequenceMatcher(None, w, x).ratio() >= .85) for w in words) for x in t) / len(t)

def _best(words, names, need):
    sc = [x for x in ((_score(words, n), n) for n in names) if x[0] >= need]
    return max(sc)[1] if sc else None

def merge(slots):  # a 2-period lab appears as one class
    out = []
    for s in sorted(slots, key=lambda x: (x["day"], x["period"])):
        p = out[-1] if out else None
        same = p and p["day"] == s["day"] and p["period"] + p["span"] == s["period"] and all(p[k] == s[k] for k in ("subject", "section", "group")) and p["room"].get("name") == s["room"].get("name")
        if same: p["span"] += 1; p["end"] = s["end"]
        else: out.append({**s, "span": 1})
    return out

def _line(s, isf):
    who = f"{s['section']}{' ' + s['group'] if s['group'] else ''}" if isf else s["faculty"].get("name", "TBA")
    return f"{rng(s)}  {s['subject']} ({who}, Room {s['room'].get('name', '?')})"

def _day(ms, d, label, isf):
    xs = [s for s in ms if s["day"] == d]
    return f"{label}: " + ("no classes." if not xs else "\n" + "\n".join(_line(s, isf) for s in xs))

def _fac(f, slots, you):
    mine = sorted({s["subject"] for s in slots if fkey(s["faculty"].get("name")) == fkey(f["name"])})
    o = [f["name"] + (f" — {f['designation']}" if f.get("designation") else "")]
    for k, l in (("emp_id", "Employee ID"), ("cabin", "Cabin"), ("email", "Email"), ("phone", "Phone")):
        if f.get(k): o.append(f"{l}: {f[k]}")
    if mine: o.append(("Teaches you: " if you else "Teaches: ") + ", ".join(mine))
    return "\n".join(o)

def _room(r, slots):
    o = [f"Room {r['name']}"]
    for k, l in (("building", "Building"), ("floor", "Floor"), ("directions", "How to reach")):
        if r.get(k): o.append(f"{l}: {r[k]}")
    if len(o) == 1: o.append("No building/floor details have been added for this room yet.")
    mine = [s for s in merge(slots) if s["room"].get("name") == r["name"]]
    if mine: o.append("Classes here: " + "; ".join(f"{DAYN[s['day']][:3]} {t12(s['start'])} {s['subject']}" for s in mine[:6]))
    return "\n".join(o)

def _runs(tslots, pm, day):
    occ = {s["period"] for s in tslots if s["day"] == day}; runs = []
    for p in sorted(pm):
        if p in occ: continue
        if runs and runs[-1]["last"] == p - 1: runs[-1].update(last=p, end=pm[p][1])
        else: runs.append(dict(first=p, last=p, start=pm[p][0], end=pm[p][1]))
    return runs

def _meet(f, tslots, pm, now, me):
    today, hh = now.weekday(), now.strftime("%H:%M")
    o = ["You are free at:" if me else f"{f['name']} is free at:"]
    cur = next((s for s in tslots if s["day"] == today and s["start"] <= hh < s["end"]), None)
    if cur: o.insert(0, f"Right now: in class ({cur['section']}, Room {cur['room'].get('name', '?')}) until {t12(cur['end'])}.")
    for k in range(3):
        d = (today + k) % 7
        label = "Today" if k == 0 else DAYN[d]
        if d == 6: o.append(("Today (Sunday)" if k == 0 else "Sunday") + ": no classes."); continue
        runs = [r for r in _runs(tslots, pm, d) if k or r["end"] > hh]
        o.append(f"{label}: " + (", ".join(f"{t12(r['start'])}-{t12(r['end'])}" for r in runs) or "no free slots"))
    for key, l in (("cabin", "Cabin"), ("email", "Email"), ("phone", "Phone")):
        if f.get(key) and not me: o.append(f"{l}: {f[key]}")
    return "\n".join(o)

def answer(db, c, msg, now):
    d, isf = c["dept"], c["role"] == "faculty"
    fac, rooms = lookups(db, d); pm = periods(db, d)
    mk = fkey(c["name"]) if isf else None
    slots = ftimetable(db, d, mk) if isf else timetable(db, d, c["section"], c.get("group", ""))
    ms = merge(slots)
    q = msg.lower().strip(); words = toks(q); qn = norm(q)
    today, hhmm = now.weekday(), now.strftime("%H:%M")
    named = lambda: (lambda n: fac[fkey(n)] if n else None)(_best(words, [x["name"] for x in fac.values()], .5))
    if re.search(r"\b(free|available|availability|meet|meeting|appointment|vacant)\b", q):
        f = named()
        if f: return _meet(f, ftimetable(db, d, fkey(f["name"])), pm, now, False)
        if isf: return _meet(fac.get(mk) or {"name": c["name"]}, slots, pm, now, True)
        return "Tell me which faculty member, for example: “When is Dr. Sharma free to meet?”"
    if re.search(r"\b(next|upcoming)\b.*\b(class|lecture|lab)|what'?s next", q):
        nxt = [s for s in ms if (s["day"], s["start"]) > (today, hhmm)] or ms[:1]
        return f"Your next class: {DAYN[nxt[0]['day']]} {_line(nxt[0], isf)}" if nxt else "I couldn't find any classes on your timetable yet."
    if isf and re.search(r"\bmy (info|details|cabin|profile|email|phone)\b|who am i", q): return _fac(fac.get(mk) or {"name": c["name"]}, slots, False)
    if "tomorrow" in q: return _day(ms, (today + 1) % 7, "Tomorrow", isf)
    if re.search(r"\b(today|now)\b", q): return _day(ms, today, "Today", isf)
    for i, n in enumerate(DAYN):
        if re.search(rf"\b{n.lower()}\b|\b{n[:3].lower()}\b", q): return _day(ms, i, n, isf)
    for r in rooms.values():
        n = norm(r["name"])
        if len(n) >= 3 and n in qn: return _room(r, slots)
    f = named()
    if f: return _fac(f, slots, not isf)
    subs = {s["subject"]: s for s in slots}; subs.update({s["code"]: s for s in slots if s["code"]})
    subs.update({"".join(w[0] for w in re.findall(r"[A-Za-z]+", s["subject"])).lower(): s for s in slots})  # abbreviations: IoT, BDA
    sub = _best(words, list(subs), .6) or next((k for k in subs if len(norm(k)) >= 4 and norm(k) in qn), None)
    if sub:
        s = subs[sub]; mine = [x for x in ms if x["subject"] == s["subject"]]
        return f"{s['subject']} is taught by {s['faculty'].get('name', 'TBA')}.\n" + "\n".join(f"{DAYN[x['day']][:3]} {rng(x)} in Room {x['room'].get('name', '?')}" for x in mine)
    return ("I can help with:\n• Next class · today · tomorrow · Friday\n• When is Dr. Sharma free to meet?\n• Who is Dr. Sharma? (cabin, email, phone)\n• Where is room 216?\n"
            + ("• When am I free? · my info" if isf else "• Who teaches Operating Systems?"))
