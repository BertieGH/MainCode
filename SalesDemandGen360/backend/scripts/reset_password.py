"""Set a user's password from the command line.

The way back in when the super admin's password is lost: no other admin can
reset that account (`docs/17`), on purpose, so recovery needs access to the
server rather than to the app. Works for any account.

Signs the person out everywhere and clears a lockout. The password is asked
for twice and never echoed; `--password-stdin` reads it from standard input
instead. Never put it on the command line, where it lands in shell history.

    python scripts/reset_password.py --email you@example.com
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app  # noqa: E402,F401  — sets the Windows event-loop policy

from app.database import SessionLocal  # noqa: E402
from app.models.identity import AuditLog  # noqa: E402
from app.services import auth  # noqa: E402


def _read_password(from_stdin: bool) -> str:
    if from_stdin:
        return sys.stdin.readline().rstrip("\r\n")
    first = getpass.getpass("New password: ")
    if first != getpass.getpass("New password again: "):
        sys.exit("The two passwords differ. Nothing was changed.")
    return first


async def _main(args: argparse.Namespace) -> int:
    async with SessionLocal() as session:
        user = await auth.find_by_email(session, args.email)
        if user is None:
            print(f"No account for {args.email}.")
            return 1
        try:
            auth.set_password(user, _read_password(args.password_stdin))
        except ValueError as e:
            print(f"Not changed: {e}.")
            return 1
        # The fact, and that it came from the server rather than the app.
        session.add(AuditLog(
            actor_id=None, actor_label="command line", action="user.password_set",
            subject_type="app_user", subject_id=str(user.id),
        ))
        await session.commit()
        print(f"Password set for {user.email}. Their other sessions have ended.")
        return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--email", required=True)
    parser.add_argument("--password-stdin", action="store_true")
    sys.exit(asyncio.run(_main(parser.parse_args())))
