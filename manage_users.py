"""Manage student accounts from the server's terminal (the /admin/users page does the same).

    python manage_users.py list
    python manage_users.py code                         # show the cohort code (makes one if none exists)
    python manage_users.py newcode                      # replace the code; the old one stops working
    python manage_users.py closecode                    # close signup
    python manage_users.py invite name@example.com      # one-time sign-up link, valid 24 hours
    python manage_users.py reset name@example.com       # one-time password reset link, valid 24 hours
    python manage_users.py disable name@example.com
    python manage_users.py enable name@example.com
    python manage_users.py delete name@example.com
    python manage_users.py owner name@example.com       # make an admin (and owner) of this student account
    python manage_users.py unowner name@example.com     # take the owner flag away (stays an admin)
"""
import sys

from archive import accounts, admins, config

NO_ARG = {"list", "code", "newcode", "closecode"}
WITH_EMAIL = {"invite", "reset", "disable", "enable", "delete", "owner", "unowner"}


def link(token: str) -> str:
    return f"{config.PUBLIC_URL or 'http://localhost:8000'}/verify?token={token}"


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in NO_ARG | WITH_EMAIL:
        print(__doc__)
        return 1
    command = argv[0]
    if (command in NO_ARG and len(argv) != 1) or (command in WITH_EMAIL and len(argv) != 2):
        print(__doc__)
        return 1
    if command == "list":
        rows = accounts.list_accounts()
        if not rows:
            print("No student accounts yet.")
        for a in rows:
            print(f"{a.id:4}  {a.email:40} {'DISABLED' if a.disabled else 'active':9} joined {a.created_at[:10]}  last sign-in {(a.last_login_at or '-')[:10]}")
        return 0
    if command == "code":
        print(accounts.get_signup_code() or accounts.new_signup_code())
        return 0
    if command == "newcode":
        print(accounts.new_signup_code())
        return 0
    if command == "closecode":
        accounts.clear_signup_code()
        print("Signup is closed. Existing accounts keep working.")
        return 0
    email = accounts.normalize_email(argv[1])
    if not email:
        print("That does not look like an email address.")
        return 1
    account = accounts.get_account_by_email(email)
    if command == "invite":
        if account:
            print("That email already has an account. Use: reset", email)
            return 1
        print(f"One-time sign-up link for {email} (works once, valid 24 hours):\n{link(accounts.issue_token(email, 'signup'))}")
        return 0
    if not account:
        print("No account with that email.")
        return 1
    if command == "reset":
        print(f"One-time reset link for {email} (works once, valid 24 hours):\n{link(accounts.issue_token(email, 'reset'))}")
    elif command in ("owner", "unowner"):
        try:
            if not admins.get_admin(account.id):
                admins.make_admin(account.id)
            member = admins.set_owner(account.id, command == "owner")
        except ValueError as problem:
            print(problem)
            return 1
        print(f"{member.email} is now {'an owner' if member.is_owner else 'an admin (not an owner)'}.")
    elif command == "delete":
        accounts.delete_account(account.id)
        print("Done.")
    else:
        accounts.set_disabled(account.id, command == "disable")
        print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
