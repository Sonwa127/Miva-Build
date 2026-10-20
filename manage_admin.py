"""Create or reset the local administrator password without exposing it in logs."""
from getpass import getpass

from api.auth import configure_admin


if __name__ == "__main__":
    password = getpass("New administrator password (at least 12 characters): ")
    if password != getpass("Confirm password: "):
        raise SystemExit("Passwords do not match; nothing was changed.")
    try:
        configure_admin(password)
    except ValueError as error:
        raise SystemExit(str(error))
    print("Administrator configured. Sign in at /admin/login. Previous sessions have been revoked.")
