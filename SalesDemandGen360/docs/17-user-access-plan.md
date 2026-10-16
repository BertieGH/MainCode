# User access: login, admin-created accounts and role-based permissions

**Status: phases 1–2 built (2026-10-15); phases 3–4 to come.** Agreed in chat 2026-10-15. Screens are in
`mockups/user-access.html`. This is the brief, so the build does not have to re-derive it.

## Why

There is no authentication. All 163 routes are open, and the only lock is the
prompt-editor password in `services/admin_gate.py`, whose own docstring calls
real auth "the prerequisite before this app is hosted or shared". CGVAK is the
only organisation using it. Multi-tenancy was costed (about 6–9 extra weeks)
and **declined for now**. If outside clients come, give each one its own
installation before considering it.

## Accounts

- **Only admins create accounts.** Name, email, role and a password the
  admin sets (or generates). The admin tells the person their email and
  password themselves, since the app sends nothing. No forced change on first
  sign-in, but anyone can change their own password from the user menu.
- **No email service.** A forgotten password is replaced by an admin, which
  signs that person out everywhere.
- **The first admin** is created from the command line, so there is no open
  bootstrap route.
- **Users are deactivated, never deleted.** Approvals, sends and the audit log
  point at them. Deactivating someone ends every session at once.
- **At least one active Admin must always remain.** No admin can demote or
  deactivate themselves.
- One `organization` row is created now, with users belonging to it, so a
  later split costs a column rather than a redesign. No `tenant_id` goes
  anywhere else.

## Roles

Admin, AIOps, Marketing, DemandGen. Each module is **None / View / Edit**,
where Edit includes create, because config is versioned and "save" already
creates a new version. Risky actions get their own switch.

| Module | AIOps | Marketing | DemandGen |
|---|---|---|---|
| Dashboard, Cost & health | Edit | View | View |
| Account Lists & research | View | Edit | Edit |
| Campaign Queues | View | View | Edit |
| Outreach: strategy and drafts | View | Edit | Edit |
| Sales Prep | View | Edit | Edit |
| Learning | View | View | View |
| Model & Prompts config | Edit | View | View |
| Sources & signals | Edit | View | View |
| Services & proof, ICP, Writing samples | View | Edit | View |
| Weights & scoring | Edit | Edit | View |
| Sales rules & Cadences | View | View | Edit |
| API config, Users & Roles | – | – | – |

| Action | AIOps | Marketing | DemandGen |
|---|---|---|---|
| Approve and send to LGM | – | – | ✓ |
| Run paid research | ✓ | ✓ | ✓ |
| Delete a campaign | – | – | ✓ |

Admin has everything and cannot be edited. The grid is **admin-editable** on
Settings › Roles and **versioned**, with one `is_active` row, so "who could
send on 3 Oct?" stays answerable. The server enforces every cell; hiding
menu items and buttons is only for clarity.

The prompt-editor password retires: "Model & Prompts config: Edit" replaces it.

## Build phases

1. **Backend accounts (about 1 day).** `organization` and `user` tables with
   a migration. Login, logout, "who am I" and change own password. scrypt,
   as `admin_gate.py` already uses. HttpOnly session cookie signed with
   `SECRET_KEY`. Every route requires a login by default, with a public list
   (login, health). Login attempts are rate-limited.
   *Built.* `models/identity.py`, `services/auth.py`, `services/passwords.py`
   (scrypt lifted out of `admin_gate`), `api/auth.py`, migration `b6d2e8f41a07`,
   `scripts/create_admin.py`. Enforcement sits behind `AUTH_REQUIRED`, **off
   by default** until phase 3 gives the UI a sign-in page; with it off,
   requests still resolve their user when a cookie is present. The LGM inbox
   webhook moved to a public router, because LGM authenticates with the token
   in its path and cannot sign in.
2. **Roles and user management (about 1½ days).** The versioned role grid and
   a permission dependency per group of routes. Admin endpoints: create
   (with password), change role, deactivate or reactivate, set new password.
   Approvals and sends record the user instead of `"api"`.

   *Built.* `services/permissions.py` maps every route template to a module
   or a risky action (first match wins; an unmapped route is admin-only, and
   `test_permissions` lists any). `require_user` checks a signed-in caller
   against the active `role_grid` on every request; anonymous callers still
   pass while `AUTH_REQUIRED` is off. `/users` and `/roles` are the exception:
   they always need a signed-in admin, or an anonymous caller could create an
   admin that outlives phase 3. `audit_log` exists now and records user
   changes, grid saves, approvals, sample acceptance, execute, stop, campaign
   delete and credential saves and deletes (slot only, never the value).
   `approval.reviewer_id` is the user's id once someone is signed in, and
   stays `"bertie"` for anonymous approvals so the column keeps one meaning
   per era. The prompt password now guards anonymous callers only; a signed-in
   caller already passed the grid's Model & Prompts edit check.
   `/auth/me` returns `{user, permissions}` for phase 3 to hide by.
3. **Angular (1–1½ days).** A sign-in page and a change-password dialog. Guard, expired-session handling, user menu, Settings ›
   Users, Settings › Roles, and view-only screens with disabled inputs.
4. **Hardening (½–1 day).** CSRF protection, full test runs, a browser pass as
   each of the four roles, CLAUDE.md invariant 9 extended to sessions, and a
   `docs/13` entry.

About 4–5 working days in all.

## Deferred: self-registration

Dropped for this stage on 2026-10-15. If it returns: sign-up lands as
`pending`, an admin approves it and picks a role, and pending users cannot
sign in. The screens were drafted and removed from `mockups/user-access.html`.

## Next stage, not in this build: per-user overrides

Agreed in principle and deferred. A user starts from their role's grid, and an
admin may raise or lower any module or action **for that one person**
(e.g. one Marketing user who may also approve and send).

- **Override storage:** a `user_permission_override` table (user, permission,
  value). Effective rights = role grid, then overrides.
- **User screen:** a per-user grid on the user's page that marks which cells
  are overridden, with "Reset to role" per cell and for the whole user.
- **Badge:** a "has overrides" badge on the Users list, so exceptions stay visible.
- **Role change:** changing a user's role **clears** their overrides, after a warning.
- **Role edits:** editing a role still flows to its users, except where they
  have an override.
- **Audit:** every override change goes to `audit_log` (who changed what, for
  whom, when).
- **Admin:** Admin cannot be overridden.

Estimated at about 1 extra day. Build it only once a real exception comes up:
overrides are where permissions quietly sprawl.
