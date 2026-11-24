"""Administrative CLI (run where the backend's environment / DATABASE_URL is configured).

    python -m app.manage create-admin --email admin@example.com [--name "Ada Admin"]
    python -m app.manage promote --email user@example.com
    python -m app.manage demote --email user@example.com

The password for create-admin is read interactively, or from the ADMIN_PASSWORD environment
variable for automation; it is never accepted as a command-line argument (shell history).
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys

from app.core.security import BCRYPT_MAX_BYTES, hash_password, password_too_long
from app.database.models import Role
from app.database.repositories import CollectionRepository, UserRepository
from app.database.session import session_scope


def _password() -> str:
    pw = os.environ.get("ADMIN_PASSWORD") or getpass.getpass("New admin password: ")
    if len(pw) < 12 or password_too_long(pw):
        sys.exit(f"Password must be 12 to {BCRYPT_MAX_BYTES} bytes long")
    return pw


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m app.manage", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create-admin")
    c.add_argument("--email", required=True)
    c.add_argument("--name", default="Administrator")
    for name in ("promote", "demote"):
        sub.add_parser(name).add_argument("--email", required=True)
    a = p.parse_args(argv)

    with session_scope() as db:
        repo = UserRepository(db)
        user = repo.get_by_email(a.email)
        if a.cmd == "create-admin":
            if user is not None:
                sys.exit(f"{a.email} already exists; use `promote` instead")
            user = repo.create(a.email, hash_password(_password()), a.name, Role.admin.value)
            CollectionRepository(db).get_or_create_default(user)
            print(f"Created administrator {a.email}")
            return 0
        if user is None:
            sys.exit(f"No user {a.email}")
        user.role = Role.admin.value if a.cmd == "promote" else Role.user.value
        print(f"{a.email} is now {user.role}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
