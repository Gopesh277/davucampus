# DAV University – Student & Faculty Timetable Portal

Companion to the DAVUNI-SCHEDULER repo: the scheduler *generates* timetables; this portal *publishes* them to students and faculty.

## Logins (all 12 departments from the scheduler's departments.json)
| Who | Department | Username | Password |
|---|---|---|---|
| Department admin | pick department | `admin` | one-time `DEFAULT_ADMIN_PASSWORD` (`admin123` in local development), then they must choose their own |
| Dean's Office | *no department needed* | `dean` | `DEAN_PASSWORD` (`dean_admin123` in local development); change it by editing `.env`, there is no in-app change |
| Student | pick department | Reg No | Reg No at first sign-in, then they must choose their own |
| Faculty | pick department | Employee ID | Employee ID at first sign-in, then they must choose their own |

Students, faculty and admins can change their own password at any time (**Change password**). A department admin can **Reset a password** for a student or faculty member who forgot theirs: it goes back to their ID and they choose a new one at the next sign-in. A department admin who forgot theirs is reset on the server: `docker compose exec app python -m app.manage add-dept CODE "Department name" admin 'TempPass'` (one-time password; they choose their own at the next sign-in). Changing, resetting or deleting a login ends that person's existing sessions (within 30 seconds).
Failed sign-ins are throttled per account and client IP (10 failures in 5 minutes per worker), so a campus sharing one IP is never locked out as a whole.

## Dean's Office portal (read-only, all departments)
Sign in as `dean` with no department. It reads the same live tables the department admins upload into, so it is always in sync with what students and faculty see (within the 60-second per-worker cache).
- **Timetables** – pick any department and view its published timetable teacher-wise, room-wise or class-wise, with when it last published its timetable / students / faculty.
- **Availability** – pick faculty from any department (matched by name across departments, so a teacher in two departments is one person) and check a day + time: who is free, who is busy and *where* (room, class, department), cabin/phone, when they are next free, plus a week grid and one-tap "everyone is free" windows. "Where are they right now?" uses the current day and time.
- **Notices** – post a university notice for everyone, students, faculty or department admins. It appears on every department's board marked *Dean's Office* (pinned ones first); department admins see it read-only above their panel. Only the Dean can delete it.
The Dean cannot use department routes and department logins cannot use `/api/dean/*`. Dean sign-in is throttled per client IP (10 failures / 5 min per worker), so nobody can lock the Dean out from elsewhere.

## Admin uploads (each department admin only touches their own department)
1. **Timetable** – the `.xlsx` the scheduler exports (sheet `Master`: Course Code, Course Name, Kind, Duration (pd), Teacher, Register, Section, Day, Start Period, Room, Status). UNPLACED rows are skipped. Optional sheet `Rooms` (Room, Building, Floor, Directions).
2. **Students** – Reg No, Name, Section, optional Group. *Section must be written the same as in the timetable* (e.g. `B.Tech CSE A`); `(G1)` group markers are understood.
3. **Faculty** – Faculty Name, Employee ID, Nature of Appointment, Email, Phone, Cabin (the scheduler's teaching-load register also works). Creates faculty logins. Teacher names are matched to the timetable ignoring Dr./Prof. and punctuation.
4. **Announcements** – posted and deleted directly in the admin panel (title, message, audience, pin).
Templates are downloadable in the admin panel. They contain column headers only, plus a *How to fill* sheet that the upload ignores.

## Assignments & syllabus
- **Teachers** (faculty login → *Teaching* tab) post assignments (title, details, due date) and log syllabus topics covered (unit, topic, date) for the classes and subjects they teach in the timetable. They can only post for their own subjects, and can delete only their own entries.
- **Students** (*Assignments* tab) see upcoming assignments with "due in N days" (due within 2 days is highlighted), past assignments, and syllabus covered per subject. They only see their own section's work.

## Chatbot
Students: next class, today/tomorrow/day, room location, faculty info, *"when is Dr. X free to meet?"*.
Faculty: next class, *"when am I free?"*, *"my info"*, plus all of the above.

## Run locally (development)
    pip install -r requirements.txt && python -m app.manage init && uvicorn app.main:app --reload     # http://localhost:8000
Uses `local.db` (SQLite) and the development passwords above. Never expose this setup to users.

## Production
1. **Secrets:** `cp .env.example .env` and fill in every value (`openssl rand -hex 32` for each). The app refuses to start with a missing, short or default `SECRET_KEY`, `DEAN_PASSWORD` or `DEFAULT_ADMIN_PASSWORD`, or without PostgreSQL.
2. **HTTPS certificate:** put `fullchain.pem` and `privkey.pem` in `./certs` (your university's certificate, or Let's Encrypt: `certbot certonly --standalone -d your.host`, then copy the two files). nginx serves HTTPS only and redirects port 80. Renew before expiry and run `docker compose restart nginx`.
3. **Start:** `docker compose --env-file .env up -d --build`. On start the app creates any missing tables and the 12 departments' `admin` logins; it never overwrites existing data. An older install whose admins still use `admin123` is moved to the one-time `DEFAULT_ADMIN_PASSWORD`.
4. **First sign-in:** give each department admin `admin` + the `DEFAULT_ADMIN_PASSWORD`; they must choose their own password straight away. Then they upload the timetable, faculty and students.
5. **Backups** (PostgreSQL holds everything):
   `docker compose exec -T db pg_dump -U tt -Fc tt > backup-$(date +%F).dump` (daily, e.g. from cron; keep copies off the server)
   Restore: `docker compose exec -T db pg_restore -U tt -d tt --clean < backup-YYYY-MM-DD.dump`
6. **Updates:** `git pull && docker compose --env-file .env up -d --build`. Users stay signed in unless `SECRET_KEY` changes.
7. **Health / logs:** `curl -k https://your.host/api/health`, `docker compose ps` (all *healthy*), `docker compose logs -f app` (rotated at 5 x 10 MB per service).

## Layout
    frontend/  index.html, styles.css, app.js, dean.css, dean.js, assets/logo.jpg
    app/       main.py (API) · dean.py (Dean's Office logic) · db.py (models, cache) · excel.py (parsers/templates) · chatbot.py · manage.py (CLI) · departments.json
