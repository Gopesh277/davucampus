"""python -m app.manage init      create tables + all 12 departments, each with admin / admin123 (never overwrites existing admins)
   python -m app.manage add-dept CODE "Name" admin_user 'Pass'   add/replace one department admin"""
import sys, os, json
from sqlalchemy import select
from .db import Base, engine, Session, Dept, User
from .main import hash_pw

def seed():
    pw = os.getenv("DEFAULT_ADMIN_PASSWORD", "admin123")
    deps = json.load(open(os.path.join(os.path.dirname(__file__), "departments.json")))
    with Session() as s:
        for x in deps:
            d = s.scalar(select(Dept).where(Dept.code == x["id"]))
            if not d: d = Dept(code=x["id"], name=x["name"]); s.add(d); s.flush()
            if not s.scalar(select(User).where(User.dept_id == d.id, User.username == "admin")):
                s.add(User(dept_id=d.id, username="admin", role="admin", name=f"{x['short']} Admin", pw_hash=hash_pw(pw)))
        s.commit()
    print(f"{len(deps)} departments ready (admin login: admin / {pw}) - change these before going live.")

def main(a):
    Base.metadata.create_all(engine)
    if a[:1] == ["add-dept"]:
        code, name, user, pw = a[1:5]
        with Session() as s:
            d = s.scalar(select(Dept).where(Dept.code == code)) or Dept(code=code, name=name)
            s.add(d); s.flush()
            u = s.scalar(select(User).where(User.dept_id == d.id, User.username == user)) or User(dept_id=d.id, username=user, role="admin", name=f"{code} Admin")
            u.pw_hash = hash_pw(pw); s.add(u); s.commit()
        print(f"Department {code} ready. Admin login: {user}")
    else: seed()
if __name__ == "__main__": main(sys.argv[1:])
