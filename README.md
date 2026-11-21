# DAV University – Student & Faculty Timetable Portal

Companion to the DAVUNI-SCHEDULER repo: the scheduler *generates* timetables; this portal *publishes* them to students and faculty.

## Logins (all 12 departments from the scheduler's departments.json)
| Who | Department | Username | Password |
|---|---|---|---|
| Department admin | pick department | `admin` | `admin123` (after signing in, use **Change password** in the top-right; only admins can change passwords) |
| Dean's Office | *no department needed* | `dean` | `dean_admin123` locally; **set `DEAN_PASSWORD` in production** (the app refuses to start in prod without it; change it by editing the environment, there is no in-app change) |
| Student | pick department | Reg No | same as Reg No |
| Faculty | pick department | Employee ID | same as Employee ID |

## Dean's Office portal (read-only, all departments)
Sign in as `dean` with no department. It reads the same live tables the department admins upload into, so it is always in sync with what students and faculty see (within the 60-second per-worker cache).
- **Timetables** – pick any department and view its published timetable teacher-wise, room-wise or class-wise, with when it last published its timetable / students / faculty.
- **Availability** – pick faculty from any department (matched by name across departments, so a teacher in two departments is one person) and check a day + time: who is free, who is busy and *where* (room, class, department), cabin/phone, when they are next free, plus a week grid and one-tap "everyone is free" windows. "Where are they right now?" uses the current day and time.
- **Notices** – post a university notice for everyone, students, faculty or department admins. It appears on every department's board marked *Dean's Office* (pinned ones first); department admins see it read-only above their panel. Only the Dean can delete it.
The Dean cannot use department routes and department logins cannot use `/api/dean/*`. Dean sign-in is throttled separately (10 failures / 5 min per worker) so one wrong guess never locks out a campus sharing one IP.

## Admin uploads (each department admin only touches their own department)
1. **Timetable** – the `.xlsx` the scheduler exports (sheet `Master`: Course Code, Course Name, Kind, Duration (pd), Teacher, Register, Section, Day, Start Period, Room, Status). UNPLACED rows are skipped. Optional sheet `Rooms` (Room, Building, Floor, Directions).
2. **Students** – Reg No, Name, Section, optional Group. *Section must be written the same as in the timetable* (e.g. `B.Tech CSE A`); `(G1)` group markers are understood.
3. **Faculty** – Faculty Name, Employee ID, Nature of Appointment, Email, Phone, Cabin (the scheduler's teaching-load register also works). Creates faculty logins. Teacher names are matched to the timetable ignoring Dr./Prof. and punctuation.
4. **Announcements** – posted and deleted directly in the admin panel (title, message, audience, pin).
Templates are downloadable in the admin panel; `demo_data/` has a full B.Tech CSE example (timetable, faculty, students).

## Assignments & syllabus
- **Teachers** (faculty login → *Teaching* tab) post assignments (title, details, due date) and log syllabus topics covered (unit, topic, date) for the classes and subjects they teach in the timetable. They can only post for their own subjects, and can delete only their own entries.
- **Students** (*Assignments* tab) see upcoming assignments with "due in N days" (due within 2 days is highlighted), past assignments, and syllabus covered per subject. They only see their own section's work.

## Chatbot
Students: next class, today/tomorrow/day, room location, faculty info, *"when is Dr. X free to meet?"*.
Faculty: next class, *"when am I free?"*, *"my info"*, plus all of the above.

## Run
    pip install -r requirements.txt && python -m app.manage init && uvicorn app.main:app --reload     # http://localhost:8000
    # production: cp .env.example .env ; docker compose --env-file .env up -d --build   (HTTPS in front)
Upgrading from the version without the Dean's portal: run `python -m app.manage init` once (the Docker image does this on start). It only adds two new tables (`uni_notice`, `sync`); existing data is kept. A department's *last published* dates start empty and fill in at its next upload.
If you ran a much earlier version, delete `local.db` (or `docker compose down -v`) first – the tables changed.

## Layout
    frontend/  index.html, styles.css, app.js, dean.css, dean.js, assets/logo.jpg
    app/       main.py (API) · dean.py (Dean's Office logic) · db.py (models, cache) · excel.py (parsers/templates) · chatbot.py · manage.py (CLI) · departments.json
