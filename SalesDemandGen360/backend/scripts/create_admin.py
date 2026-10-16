"""Create an admin account from the command line.

The only way to make the *first* account: there is no registration, and every
other account is created by an admin on Settings › Users (`docs/17`). A
command line rather than a seed in a migration, so the password never sits in
a file or in git.

The password is asked for twice and never echoed. `--password-stdin` reads it
from standard input instead, for a provisioning script — never put it on the
command line, where it lands in shell history and the process list.

    python scripts/create_admin.py --email bert@cgvak.com --name "Bert"
    python scripts/create_admin.py --email ... --name ... --another   # an admin exists already

Refuses when an active admin already exists unless `--another` is given, so a
second run of a setup script cannot quietly add an account nobody meant to.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app  # noqa: E402,F401  — sets the Windows event-loop policy
from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models.identity import User  # noqa: E402
from app.services import auth  # noqa: E402


def _read_password(from_stdin: bool) -> str:
    if from_stdin:
        return sys.stdin.readline().rstrip("\r\n")
    first = getpass.getpass("Password: ")
    if first != getpass.getpass("Password again: "):
        sys.exit("The two passwords differ. Nothing was created.")
    return first


async def _main(args: argparse.Namespace) -> int:
    async with SessionLocal() as session:
        existing = (
            await session.execute(
                select(User).where(User.role == "admin", User.status == "active").limit(1)
            )
        ).scalar_one_or_none()
        if existing is not None and not args.another:
            print(
                f"An active admin already exists ({existing.email}). "
                "Pass --another to add one more, or create users from Settings › Users."
            )
            return 1

        password = _read_password(args.password_stdin)
        try:
            user = await auth.create_user(
                session,
                email=args.email,
                full_name=args.name,
                role="admin",
                password=password,
            )
        except ValueError as e:
            print(f"Not created: {e}.")
            return 1
        await session.commit()
        print(f"Admin created: {user.full_name} <{user.email}>. Sign in with that email.")
        return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--password-stdin", action="store_true")
    parser.add_argument("--another", action="store_true", help="an active admin exists; add another")
    sys.exit(asyncio.run(_main(parser.parse_args())))
