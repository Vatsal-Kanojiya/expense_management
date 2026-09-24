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
| 3 | `security-hardening` | Security pass 1 (commit `ea732e4`) and this file | Fixes done; tests to write (task 1) |

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

- [ ] **Security pass 2 — files in and out of the app.** Each item: a fix, a test, one commit.
  - [x] Bill photos: check the file's actual contents, not only the type the browser declares,
        and store and serve it with the verified type (`BillScanForm`, `bill_upload_path`,
        the scan `image` endpoint).
  - [x] Upload size: refuse oversized uploads as early as Django allows, and add a body-size
        limit for the reverse proxy to the hosting checklist in section 4.
  - [x] A per-user limit on creating scans and exports, shared by the web pages and the API, in
        `accounts/ratelimit.py`'s style. Scans and exports each occupy a background worker,
        and scans can cost money with a real provider.
  - [ ] CSV exports: make cells that start with `=`, `+`, `-` or `@` safe to open in
        spreadsheet programs (`_write_csv` in `expenses/tasks.py`).

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

Keep regular backups with `make backup` (docs/DOCKER.md §12), and store them off the server.

---

## 5. When you come back with an assistant

Point it at `docs/BUILD_LOG.md` (the "Resume here" box) and this file, and say which task in
section 3 to pick up.
