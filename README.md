# DAV University – Student & Faculty Timetable Portal

Companion to the DAVUNI-SCHEDULER repo: the scheduler *generates* timetables; this portal *publishes* them to students and faculty.

## Logins (all 12 departments from the scheduler's departments.json)
| Who | Department | Username | Password |
|---|---|---|---|
| Department admin | pick department | `admin` | `admin123` (after signing in, use **Change password** in the top-right; only admins can change passwords) |
| Student | pick department | Reg No | same as Reg No |
| Faculty | pick department | Employee ID | same as Employee ID |

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
If you ran an earlier version, delete `local.db` (or `docker compose down -v`) first – the tables changed.

## Layout
    frontend/  index.html, styles.css, app.js, assets/logo.jpg
    app/       main.py (API) · db.py (models, cache) · excel.py (parsers/templates) · chatbot.py · manage.py (CLI) · departments.json
