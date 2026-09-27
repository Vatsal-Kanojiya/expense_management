# Handover — carrying on without an assistant

> Written in session 29 (September 2026) so that the owner can keep working alone for a while. It
> says where everything stands, how to run and check it, and what is left, in the order to do it.

---

## 1. Where things stand

### Branches

Three branches are stacked, each on the one before. **None is merged into `master` yet**, and
`master` is untouched at `9371cc5`.

| Order | Branch | What it adds | Status |
|---|---|---|---|
| 1 | `project-dockerization` | Docker for daily use: two modes, volumes, `Makefile` (phase 19) | Done, verified |
| 2 | `frontend-api` | A full API for React or mobile, and the frontend pack in `docs/frontend/` (phases 20–21) | Done, verified |
| 3 | `security-hardening` | Security passes 1–6 and this file | Passes 1–5 done, with tests; pass 6 in progress |

**To merge**, merge them in that order. On GitHub, open a pull request into `master` for each
branch in turn: after the first is merged, the next one's pull request shows only its own commits.
Or, from the command line:

```bash
git checkout master && git pull
git merge --no-ff origin/project-dockerization
git merge --no-ff origin/frontend-api
git merge --no-ff origin/security-hardening
git push origin master
```

CI (`.github/workflows/ci.yml`) runs on every pull request: lint, format, the migration check,
Django's checks, the tests with a 95% coverage floor, and the deploy check.

### Where to read what

| Want | Read |
|---|---|
| What happened, session by session, and the open issues | `docs/BUILD_LOG.md` (the "Resume here" box, and §6) |
| Why things are the way they are | `docs/DECISIONS.md` |
| The phase plans and their checklists | `docs/COMMIT_PLAN.md` |
| Running the Docker stack | `docs/DOCKER.md` |
| The frontend developer's pack | `docs/frontend/README.md` |
| What to do next | This file |

---

## 2. Daily commands

```bash
make up          # production-like stack at http://127.0.0.1:8765
make dev         # the same stack, with your checkout mounted live
make logs        # follow the logs (SERVICE=web|worker|beat|db|redis)
make test        # the whole suite, in Docker, on Postgres
make lint        # ruff check, and the format check
make api-docs    # regenerate docs/frontend's generated files after an API change
make down        # stop; your data is kept
make help        # everything else
```

Without Docker, which is faster for running tests:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
export SECRET_KEY=local-dev-key-at-least-fifty-characters-long-0123456789 DEBUG=True
python manage.py test
coverage run manage.py test && coverage report
ruff check . && ruff format --check .
python manage.py makemigrations --check --dry-run
```

### Before every commit

1. The tests pass, and coverage stays at 95% or more.
2. `ruff check .` and `ruff format --check .` are clean.
3. If you changed anything under `expenses/api/` or `accounts/api.py`, run `make api-docs` and
   commit the regenerated `docs/frontend/` files in the same commit. A test fails if you forget.
4. The commit message says what changed and why, as the existing ones do.

---

## 3. What is left, in order

Tick each task here as you finish it, and commit after each one.

- [x] **Task 1 — Tests for security pass 1.** (Done in session 30: `accounts/tests/test_security_pass1.py`.) Commit `ea732e4` changed the code in
      `accounts/ratelimit.py`, `accounts/views.py`, `accounts/api.py` and `accounts/admin.py`,
      and its message lists each change. Write a test for each item in that list, in a new file
      `accounts/tests/test_security_pass1.py`. Copy the patterns from
      `accounts/tests/test_api_auth.py` and `accounts/tests/test_hardening.py`. They show how to
      turn the cache on for rate-limit tests, since the test runner turns it off, and how to post
      to the web and API endpoints. The new limits are constants at the top of
      `accounts/ratelimit.py`; lower them in a test with `unittest.mock.patch.object` to keep the
      test short. **Done when** `python manage.py test accounts` passes and coverage is 95% or
      more.

- [x] **Task 2 — Bring the docs in line with pass 1.** (Done in session 30.) The rate-limit table in
      `docs/frontend/API_GUIDE.md` §11, and business rules BR-24 to BR-27 in
      `docs/frontend/BRD.md`, should list every limit that `accounts/ratelimit.py` now defines.
      (The configuration half is already done: `TRUSTED_PROXY_COUNT`, `ADMIN_URL` and
      `USE_X_FORWARDED_PROTO` are in `.env.example` and `docs/DOCKER.md` §6, and `compose.yaml`
      passes them to the containers.)

- [x] **Task 3 — Record session 29.** (Done in the handover commit series.) Add a session 29 entry to `docs/BUILD_LOG.md`, copying the
      shape of session 28. Then add a phase 22 section, "Security passes", to
      `docs/COMMIT_PLAN.md`.

- [ ] **Task 4 — Merge** the three branches, in the order in section 1, once CI is green on each.

- [ ] **Task 5 — Host it.** See section 4.

- [ ] **Task 6 — Hand the frontend pack over.** Send the React developer `docs/frontend/README.md`.
      She needs the hosted URL, an account (a normal one, not a superuser), and her development
      origin (`http://localhost:5173` for Vite) added to `CORS_ALLOWED_ORIGINS`.

- [x] **Security pass 2 — files in and out of the app.** Each item: a fix, a test, one commit.
  - [x] Bill photos: check the file's actual contents, not only the type the browser declares,
        and store and serve it with the verified type (`BillScanForm`, `bill_upload_path`,
        the scan `image` endpoint).
  - [x] Upload size: refuse oversized uploads as early as Django allows, and add a body-size
        limit for the reverse proxy to the hosting checklist in section 4.
  - [x] A per-user limit on creating scans and exports, shared by the web pages and the API, in
        `accounts/ratelimit.py`'s style. Scans and exports each occupy a background worker,
        and scans can cost money with a real provider.
  - [x] CSV exports: make cells that start with `=`, `+`, `-` or `@` safe to open in
        spreadsheet programs (`_write_csv` in `expenses/tasks.py`).

- [x] **Security pass 3 — each account sees and changes only its own records.** Each item: a
      fix (if needed), a test, one commit. All four items were already correctly implemented
      (`OwnerScopedMixin`/`OwnerScopedViewSet`/`OwnerJobViewSet` and `ScopedPrimaryKeyRelatedField`
      cover every route); `expenses/tests/test_security_pass3.py` adds the tests that confirm it,
      with no application code changes needed.
  - [x] Reading: every list, detail and download (web pages and API: expenses, categories,
        people, balances, splits, exports, scans, budgets) returns only the signed-in account's
        records, and another account's id answers 404, not 403 or the record.
  - [x] Linking: every id sent in a request body or form (a category, a person, a split's
        people, a bill scan, a settlement) must belong to the same account; otherwise a 400
        on that field.
  - [x] Changing and deleting: the same, for update, partial update and delete, on both the
        web pages and the API.
  - [x] Staff: the admin site and any staff-only view need `is_staff`; a normal account gets
        no admin access and no API route shows other accounts' data.

- [x] **Security pass 4 — tokens, sessions and headers.** (Session 31.) Each item: a fix (if
      needed), a test, one commit. Three of the five items (tokens, cookies/sessions, the
      other headers) were already correctly implemented; `accounts/tests/test_security_pass4.py`
      adds the tests that confirm it. Two gaps were found and fixed: the web password-change and
      password-reset-confirm pages did not revoke refresh tokens (only `accounts/api.py`'s did),
      and there was no Content-Security-Policy header at all.
  - [x] API tokens: sensible access and refresh lifetimes; logout blacklists the refresh token
        so it can no longer be used; a used refresh token cannot be used again after rotation.
  - [x] Password change and reset end other sign-ins: other sessions are logged out, and
        refresh tokens issued before the change stop working (API and web).
  - [x] Cookies and sessions: session and CSRF cookies are `HttpOnly`/`Secure`/`SameSite` as
        appropriate in production settings; the session id changes at login; sessions expire.
  - [x] Security headers: a Content-Security-Policy that the existing templates work under,
        plus `Referrer-Policy`, `X-Frame-Options`/frame-ancestors, and HSTS in production.
  - [x] Deployment check: `python manage.py check --deploy` with production-like settings is
        clean (or each remaining warning is explained), and `pip-audit -r requirements.txt`
        shows no known-vulnerable package (upgrade within the pinned major version if so).
        `check --deploy --fail-level WARNING` passes with no warnings at all (only the
        deliberately silenced `security.W021`, DECISIONS-style, for HSTS preload); this was
        already true before this pass and `expenses/tests/test_error_pages.py`'s
        `DeploySettingsTests` already pinned it. `pip-audit -r requirements.txt` found
        `djangorestframework==3.16.1` vulnerable to GHSA-2m8g-3cmr-wg3w (`request.data` bypasses
        `DATA_UPLOAD_MAX_MEMORY_SIZE` for JSON/form bodies) and GHSA-g47c-3xmw-q6m2 (`AdminRenderer`
        can leak a GET-only representation while rendering a failed write); bumped to 3.17.2 in
        `requirements.txt`, still within the pinned 3.x major version. A re-run of both checks
        after the bump is clean.

- [x] **Security pass 5 — errors, logs, the admin site and account deletion.** Each item: a fix
      (if needed), a test, one commit.
  - [x] Errors: with `DEBUG=False`, the web 404/500 pages and every API error response
        (`expenses/api/exceptions.py`) show a plain message and the request id, never a stack
        trace, file path, setting or SQL.
  - [x] Logs: passwords, tokens (access, refresh, reset, verification), session ids and
        `Authorization`/`Cookie` headers never appear in log lines or error reports; error
        emails to `ADMINS` use Django's sensitive-variable and sensitive-POST-parameter
        filtering on the views that handle them.
  - [x] Admin site: every model registered in the admin is limited to staff, list pages don't
        show password hashes or tokens, and changes made in the admin are recorded (Django's
        `LogEntry`) — confirm, and pin with tests.
  - [x] Account deletion (`accounts/deletion.py`): deleting an account also removes its bill
        photos and export files from storage, its refresh tokens, and its sessions; nothing
        of the account is left readable afterwards.

- [ ] **Security pass 6 — what goes in, and what comes back out.** Each item: a fix (if
      needed), a test, one commit.
  - [x] Amounts and numbers: every money field (expense amount, line items, splits,
        settlements, budgets) rejects negative, zero where it makes no sense, non-numbers, and
        values beyond the model's `max_digits`/`decimal_places`, with a 400 or a form error, not
        a 500; the same on the web forms and the API. Dates out of range are refused too.
  - [x] Text shown on pages: user-entered text (category names, notes, people's names, anything
        from a bill scan) is escaped wherever it is shown; no `|safe`, `mark_safe` or
        `autoescape off` is applied to it; JSON embedded in pages uses `json_script`.
  - [ ] Redirects: every `next` / return-URL parameter (login, logout, and any view that
        redirects to a caller-supplied URL) only goes to this site
        (`url_has_allowed_host_and_scheme`), otherwise to the default page.
  - [ ] Bill-scan output: what the scanning provider returns is treated like user input, so
        amounts, dates, text lengths and category names are validated before they prefill a
        form or reach the database, and a malformed or oversized response fails cleanly.

- [ ] **Later — more security review.** Good free starting points:
  - `python manage.py check --deploy` with the production settings;
  - `pip install pip-audit && pip-audit -r requirements.txt`, for dependencies with known
    vulnerabilities;
  - the OWASP ASVS checklist (Level 1), read against each area of the app in turn: accounts,
    uploads, exports, the admin, headers, and deployment secrets.

  Work in small passes, as pass 1 did: one theme at a time, with tests.

- [ ] **Later — the open issues** in `docs/BUILD_LOG.md` §6 (20, 21, 25, 35), when you want them.

---

## 4. Hosting checklist

On the server, in `.env` (see `.env.example` for each key):

| Setting | Value |
|---|---|
| `SECRET_KEY` | Long and random: `make env` generates one. Never reuse the local one |
| `ALLOWED_HOSTS` | Your domain |
| `POSTGRES_PASSWORD` | Long and random, set **before** the first `make up` (docs/DOCKER.md §14) |
| `WEB_BIND_ADDRESS` | `127.0.0.1` when a reverse proxy (nginx or Caddy) sits in front |
| Reverse proxy body-size limit | `client_max_body_size 6m;` (nginx) or the Caddy equivalent. Django's own limits (security pass 2, config/settings.py) reject an oversized body only once it reaches the app; the proxy is what refuses it without ever forwarding the bytes. 6m matches the app's own 5 MB rule plus headroom, so a legitimate bill photo is never what this rejects |
| `DATA_BIND_ADDRESS` | Leave at `127.0.0.1` |
| `USE_X_FORWARDED_PROTO` | `True` behind a proxy that terminates HTTPS |
| `TRUSTED_PROXY_COUNT` | The number of proxies in front: usually `1` |
| `ADMIN_URL` | A path other than `admin/` |
| `CORS_ALLOWED_ORIGINS` | The frontend's origin(s) |
| `FRONTEND_URL` | Where the frontend is served |
| `EMAIL_BACKEND` and `EMAIL_*` | A real SMTP provider, so sign-up and reset emails arrive |

In `compose.yaml`, the secure-cookie and SSL-redirect switches are turned **off** for local HTTP
(DECISIONS D35). Behind HTTPS, set them back on, by removing those three lines from the compose
environment, and run `python manage.py check --deploy` inside the web container.

**Deploy check and dependencies (security pass 4, session 31):** with those three switches back
on, `python manage.py check --deploy --fail-level WARNING` is clean -- no warnings at all, other
than the deliberately silenced `security.W021` (HSTS preload; see its comment in
config/settings.py). `pip-audit -r requirements.txt` found no known-vulnerable package as of
session 31 (`djangorestframework` was bumped from 3.16.1 to 3.17.2 in that pass for two CVEs;
see the security pass 4 entry above). Run both again before each real deployment --
`pip-audit`'s answer changes as new vulnerabilities are published, not just as this repo changes.

Keep regular backups with `make backup` (docs/DOCKER.md §12), and store them off the server.

---

## 5. When you come back with an assistant

Point it at `docs/BUILD_LOG.md` (the "Resume here" box) and this file, and say which task in
section 3 to pick up.
