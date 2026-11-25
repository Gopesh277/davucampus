"""python -m app.manage init      create tables + all 12 departments, each with an `admin` login whose first password is
                                  DEFAULT_ADMIN_PASSWORD (required in production) and must be changed at first sign-in
   python -m app.manage add-dept CODE "Name" admin_user 'TempPass'   add a department admin, or reset one who forgot their password
                                  (TempPass is one-time: they must choose their own at the next sign-in)"""
import sys, os, json
from sqlalchemy import select
from .db import Base, engine, Session, Dept, User
from .main import hash_temp, check_pw

PROD = os.getenv("ENV") == "prod"

def seed():
    pw = os.getenv("DEFAULT_ADMIN_PASSWORD") or ("" if PROD else "admin123")
    if PROD and (len(pw) < 12 or pw.lower() == "admin123"):
        sys.exit("Set DEFAULT_ADMIN_PASSWORD (at least 12 characters, not admin123): it is each department admin's one-time first password.")
    deps = json.load(open(os.path.join(os.path.dirname(__file__), "departments.json")))
    created = upgraded = 0
    with Session() as s:
        for x in deps:
            d = s.scalar(select(Dept).where(Dept.code == x["id"]))
            if not d: d = Dept(code=x["id"], name=x["name"]); s.add(d); s.flush()
            u = s.scalar(select(User).where(User.dept_id == d.id, User.username == "admin"))
            if not u:
                s.add(User(dept_id=d.id, username="admin", role="admin", name=f"{x['short']} Admin", pw_hash=hash_temp(pw))); created += 1
            elif PROD and u.pw_hash and not u.pw_hash.startswith("!") and check_pw("admin123", u.pw_hash):
                u.pw_hash = hash_temp(pw); upgraded += 1  # an older install still on admin123: switch to the one-time password
        s.commit()
    shown = "DEFAULT_ADMIN_PASSWORD" if PROD else pw
    print(f"{len(deps)} departments ready; {created} admin logins created, {upgraded} moved off admin123 "
          f"(first sign-in: admin / {shown}, then each admin must choose their own password).")

def main(a):
    Base.metadata.create_all(engine)
    if a[:1] == ["add-dept"]:
        if len(a) < 5: sys.exit(__doc__)
        code, name, user, pw = a[1:5]
        if len(pw) < 8: sys.exit("Use a temporary password of at least 8 characters.")
        with Session() as s:
            d = s.scalar(select(Dept).where(Dept.code == code)) or Dept(code=code, name=name)
            s.add(d); s.flush()
            u = s.scalar(select(User).where(User.dept_id == d.id, User.username == user)) or User(dept_id=d.id, username=user, role="admin", name=f"{code} Admin")
            u.pw_hash = hash_temp(pw); s.add(u); s.commit()
        print(f"Department {code} ready. Admin login: {user} (one-time password; they choose their own at the next sign-in)")
    else: seed()
if __name__ == "__main__": main(sys.argv[1:])
