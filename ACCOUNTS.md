# Student accounts

Classmates create their own account with a cohort code. Nobody shares a password, and no email is ever sent.

## How it works

1. The admin opens `/admin/users`, makes a **cohort code** and shares it in the class group.
2. A student opens `/signup` and enters their email, the cohort code and a password they choose.
3. They sign in at `/login` with email and password. A signed cookie keeps them signed in for 14 days.
4. Forgot a password? The student messages the admin, who clicks **Reset link** next to their name and sends the one-time link (valid 24 hours). Opening it lets the student choose a new password and signs out their other devices.
5. With `ARCHIVE_REQUIRE_LOGIN=1`, every page except login, signup and the admin area needs a student (or admin) login.

The administrator never needs a student account. The admin password and `/admin` work exactly as before.

## Settings (in `.env` on the server)

| Setting | Meaning |
|---|---|
| `ARCHIVE_REQUIRE_LOGIN=1` | Lock the whole site behind student login. Off by default so local development stays open. |
| `ARCHIVE_ALLOWED_EMAIL_DOMAINS=school.edu.ng` | Optional. Only these email domains may sign up (comma separated, subdomains included). Empty means any email, so the cohort code is the only gate. |
| `ARCHIVE_PUBLIC_URL=https://study.example.com` | Used to build one-time links. Always set this on a public server. |

## Managing accounts

- Browser: `/admin/users` while signed in as admin. Make a new code (the old one stops at once), close signup, make a one-time sign-up link for a classmate who cannot use the code, make reset links, disable, enable and delete accounts.
- Terminal: `python manage_users.py list | code | newcode | closecode | invite EMAIL | reset EMAIL | disable EMAIL | enable EMAIL | delete EMAIL`.
- Disabling an account signs that person out immediately.
- If the code leaks, make a new one. Existing accounts are not affected. Disable or delete any account you do not recognise.

## Security notes

- Passwords are stored as salted PBKDF2 hashes. One-time link tokens are stored only as hashes and work once.
- Wrong cohort codes are limited per network address (10 per hour); correct signups do not count, so a whole classroom can sign up from one Wi-Fi. Wrong passwords are limited per account and per address.
- Sign-in never reveals whether an email has an account.
- Run behind HTTPS (the session cookie is marked secure automatically on HTTPS) and with a single server process: the rate limits live in memory.
- Back up the whole `data/` folder. `accounts.sqlite` holds the student accounts, the cohort code and the key that signs sessions.
