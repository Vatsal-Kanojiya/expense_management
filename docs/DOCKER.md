# Running the stack in Docker

> Companion to [DECISIONS.md](DECISIONS.md) D31–D38 (why it is built this way) and
> [BUILD_LOG.md](BUILD_LOG.md) session 26 (how it was verified). Phase 11 first containerised the
> stack; phase 19 reworked it for daily use — see [COMMIT_PLAN.md](COMMIT_PLAN.md).
>
> Written for Linux with Docker Engine. Everything here is also a plain `docker compose` command;
> the `make` targets are shortcuts (D38), and §9 lists the raw command behind each one.

---

## 1. Quick start

```bash
git clone https://github.com/Vatsal-Kanojiya/expense_management.git
cd expense_management
git checkout project-dockerization

make up        # first run: creates .env, builds the image, starts five containers
```

Open **http://127.0.0.1:8765**, then create an account (§7) or run `make createsuperuser`.

The first build takes a few minutes: it downloads the Python, Postgres and Redis base images and
installs the dependencies. Later builds reuse the cached layers and take seconds unless
`requirements.txt` changed.

**You need:** Docker Engine with the Compose plugin (`docker compose version` should print v2.20 or
newer), GNU `make`, and `python3` — which `make env` uses once, to generate a secret key. Your user
should be in the `docker` group; otherwise prefix the commands with `sudo`.

---

## 2. Two modes

| | Production-like | Development |
|---|---|---|
| Start with | `make up` | `make dev` |
| Compose files | `compose.yaml` | `compose.yaml` + `compose.dev.yaml` |
| Image | `expense-tracker:prod` (Dockerfile target `runtime`) | `expense-tracker:dev` (target `dev`) |
| Code | copied into the image at build time | your checkout, bind-mounted at `/app` |
| Web server | gunicorn, 3 workers | `runserver`, reloads on every save |
| `DEBUG` | `False` | `True` |
| Worker and beat after a code change | rebuilt by `make update` | restarted automatically by `watchfiles` |
| After `git pull` | `make update` | nothing, or `make update-dev` when migrations or requirements changed (§8) |

Both modes use the **same URL, the same ports and the same data** (D36). To switch, run the other
target. Compose recreates the three app containers and leaves Postgres, Redis and every volume
alone.

Why code is never kept in a volume, although it looks convenient: D32.

---

## 3. What runs, and where

| Service | Image | What it does | Inside the container | On your machine |
|---|---|---|---|---|
| `web` | `expense-tracker:prod` or `:dev` | Runs `migrate`, then serves Django | port 8000 | **127.0.0.1:8765** |
| `worker` | same image | Celery worker: CSV exports, bill scans | — | not published |
| `beat` | same image | Celery beat: the daily `purge_exports` | — | not published |
| `db` | `postgres:16-alpine` | The database | port 5432 | **127.0.0.1:5433** |
| `redis` | `redis:7-alpine` | Broker (db 0), task results (db 1), cache (db 2) | port 6379 | **127.0.0.1:6380** |

Start-up order is enforced by healthchecks, not by hope:

```
db (pg_isready) ──┐
                  ├─► web: migrate, then listen on 8000 ──► worker
redis (ping) ─────┘                                      └► beat
```

`web` counts as healthy once it accepts connections on port 8000. It only starts listening after
`migrate` has finished, so the worker and beat never run against a half-migrated database. The
check is a plain TCP connect rather than an HTTP request, so it does not add a line to the access
log every few seconds.

Web builds the image, and the worker and beat run that same image. Compose labels each service's
build differently, so letting all three build would give three slightly different images and a
new image ID on every run (D39).

Every service has `restart: unless-stopped`: after a crash or a reboot it comes back by itself,
unless you stopped it with `make down`. Container logs are rotated at 3 × 10 MB per container.

---

## 4. Ports

Only the host side of each mapping is configurable. Inside the stack the services always talk to
each other on the standard ports, so changing a host port changes nothing else.

| `.env` key | Default | Meaning |
|---|---|---|
| `WEB_PORT` | `8765` | The site |
| `POSTGRES_PORT` | `5433` | Postgres, for psql or a GUI client (§10) |
| `REDIS_PORT` | `6380` | Redis, for `redis-cli` |
| `WEB_BIND_ADDRESS` | `127.0.0.1` | Which interface the site listens on |
| `DATA_BIND_ADDRESS` | `127.0.0.1` | Which interface Postgres and Redis listen on |

To change a port, edit `.env` and run `make up` (or `make dev`) again.

**Opening the site to your phone or LAN.** Set the web address to every interface, and allow your
machine's LAN address as a host name:

```bash
WEB_BIND_ADDRESS=0.0.0.0
ALLOWED_HOSTS=localhost,127.0.0.1,192.168.1.50     # your machine's LAN IP
```

Then browse to `http://192.168.1.50:8765` from the phone. Leave `DATA_BIND_ADDRESS` alone.

> **Docker publishes ports around your firewall.** It writes its own iptables rules ahead of ufw
> and firewalld, so a ufw `deny` does not close a published port. Anything bound to `0.0.0.0` is
> reachable by everyone on your network. That is why both addresses default to 127.0.0.1 (D33).

---

## 5. What persists: volumes

Compose names the volumes after the project, `expense-tracker`:

| Volume | Mounted at | Used by | Holds |
|---|---|---|---|
| `expense-tracker_postgres-data` | `/var/lib/postgresql/data` | db | Every account, expense, category, settlement |
| `expense-tracker_redis-data` | `/data` | redis | Queued tasks, kept with append-only persistence |
| `expense-tracker_media` | `/data/media` | web, worker | Uploaded bill photos and generated CSV exports |
| `expense-tracker_beat-schedule` | `/data/beat` | beat | When each periodic task last ran |

Why each one exists, and why static files deliberately are not a volume: D34.

| You run | Containers | Volumes, your data |
|---|---|---|
| `make down` | removed | **kept** |
| `make up`, `make dev`, `make update` | recreated | **kept** |
| a reboot | started again automatically | **kept** |
| `make destroy` (asks first) | removed | **deleted** |

To see where a volume lives on disk (root-owned, under `/var/lib/docker/volumes/`):

```bash
docker volume inspect expense-tracker_postgres-data --format '{{ .Mountpoint }}'
```

---

## 6. Configuration: `.env`

The first `make up` or `make dev` runs `make env`, which copies `.env.example` to `.env`, puts a
fresh random `SECRET_KEY` in it, and records your user and group id (D37). It never overwrites an
existing `.env`. The file is created with mode 600, since it holds the key and the database
password. It is gitignored and dockerignored, so it never leaves your machine.

The same `.env` also serves a plain `python manage.py runserver` outside Docker. Keys that only
Docker reads are grouped at the bottom of `.env.example`.

**What reaches the containers from `.env`:**

| Key | Default when unset | Notes |
|---|---|---|
| `SECRET_KEY` | a fixed local-only value | `make env` generates a real one |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | Add your LAN IP to open the site to other devices (§4) |
| `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` | `expense_tracker` / `expense` / `expense-local-only` | Read by Postgres **only when its volume is first created**; see §14. Letters, digits, `-` and `_` only: the password is placed inside a URL |
| `HOST_UID` / `HOST_GID` | `1000` | Build arguments: who owns files the containers write (D37) |
| `EMAIL_BACKEND` / `DEFAULT_FROM_EMAIL` | console backend | Mail is printed to the container log (§7) |
| `LOG_LEVEL` | `INFO` | |
| `BILL_SCAN_PROVIDER` | `fake` | `fake`, `claude`, `gemini` or `openai`; see README, "Bill scanning" |
| `BILL_SCAN_*_MODEL`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `OPENAI_API_KEY` | not set | Passed through only when set. Leave them commented out rather than empty |
| `USE_X_FORWARDED_PROTO`, `TRUSTED_PROXY_COUNT`, `ADMIN_URL` | not set | Hosting behind a reverse proxy; see `.env.example` and HANDOVER.md §4. Passed through only when set |
| `MAX_SIGNED_IN_DEVICES` | `2` | Devices one account may be signed in on at once (docs/design/SESSION_LIMITS.md). Passed through only when set |
| `CORS_ALLOWED_ORIGINS`, `FRONTEND_URL`, `JWT_ACCESS_MINUTES`, `JWT_REFRESH_DAYS`, `API_USER_THROTTLE`, `API_ANON_THROTTLE`, `EMAIL_HOST` … `EMAIL_USE_TLS` | not set | The API for a separate frontend, and real email; each is explained in `.env.example`. Passed through only when set |

**Fixed by the compose files, whatever `.env` says:** `DEBUG` (by mode), `DATABASE_URL`, the Celery
broker and result URLs, `CACHE_URL`, `MEDIA_ROOT`, `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`
and `CSRF_COOKIE_SECURE`. The last three are off because nothing in this stack serves HTTPS (D35).

After editing `.env`, run `make up` or `make dev` again. Compose recreates exactly the containers
whose configuration changed.

---

## 7. First run: accounts and email

Email goes to the container log; no mail server is involved. Signing up at `/accounts/signup/`
sends a verification link, and the account stays inactive until that link is opened. To find the
link:

```bash
make logs SERVICE=web      # look for http://127.0.0.1:8765/accounts/verify/...
```

Alternatively, `make createsuperuser` creates an account that is active straight away and can also
use the admin at `/admin/`.

Export-ready emails are sent by the worker, so they appear in `make logs SERVICE=worker`.

---

## 8. Updating the code

**Production-like:**

```bash
make update        # git pull --ff-only, then docker compose up -d --build
```

The image is rebuilt, and the dependency layer comes from cache unless `requirements.txt` changed.
Web, worker and beat are recreated from the new image, and web runs `migrate` before it serves
again. Postgres, Redis and every volume are untouched. If the pull brought nothing new, the image is
identical and nothing restarts.

**Development:** your checkout *is* the code, so a plain `git pull` is live at once. `runserver`
reloads itself, and `watchfiles` restarts the worker and beat when a `.py` file changes. Two things
do not happen on their own:

| The pull brought | Run |
|---|---|
| new migrations | `make migrate` |
| changed `requirements*.txt` | `make dev` (rebuilds the dev image) |
| either, or you are not sure | `make update-dev`, which pulls, rebuilds if needed, and migrates |

Creating a migration in development: `make manage CMD=makemigrations`. The new file appears in your
checkout, owned by you (D37).

---

## 9. Everyday commands

`make help` prints this list. `DEV` below stands for
`docker compose -f compose.yaml -f compose.dev.yaml`.

| Make target | Raw command | What it does |
|---|---|---|
| `make env` | *(copies `.env.example`)* | Create `.env` once, with a secret key and your UID/GID |
| `make up` | `docker compose up -d --build` | Production-like: build and start in the background |
| `make dev` | `DEV up -d --build` | Development: build and start with live code |
| `make down` | `docker compose down` | Stop and remove the containers; **data kept** |
| `make ps` | `docker compose ps` | Status and health of each service |
| `make logs [SERVICE=web]` | `docker compose logs -f --tail=100 web` | Follow the logs |
| `make update` | `git pull --ff-only && docker compose up -d --build` | Pull and redeploy, production-like |
| `make update-dev` | `git pull --ff-only && DEV up -d --build && … migrate` | Pull, rebuild if needed, migrate |
| `make shell` | `docker compose exec web bash` | A shell in the web container |
| `make manage CMD="…"` | `docker compose exec web python manage.py …` | Any management command |
| `make migrate` | `… manage.py migrate` | Apply migrations |
| `make createsuperuser` | `… manage.py createsuperuser` | An active account with admin access |
| `make test [ARGS=…]` | `DEV run --rm web python manage.py test --noinput` | The test suite, on Postgres (§13) |
| `make lint` | `DEV run --rm --no-deps web ruff check .` | Lint and format check |
| `make psql` | `docker compose exec db psql …` | A psql prompt inside the db container |
| `make redis-cli` | `docker compose exec redis redis-cli` | A Redis prompt |
| `make backup` | `pg_dump` + `tar`, see §12 | Database and media into `backups/` |
| `make restore-db FILE=…` | `pg_restore`, see §12 | Restore a database dump |
| `make restore-media FILE=…` | `tar`, see §12 | Restore a media archive |
| `make destroy` | `docker compose down -v` | Delete containers **and all data** (asks first) |

One difference from the raw commands: the Makefile exports `BUILDX_NO_DEFAULT_ATTESTATIONS=1`.
On Docker 29's containerd image store, a build otherwise carries a timestamped attestation, so
every `up --build` produces a new image ID and recreates the app containers, even with nothing
changed. It is harmless, only slower. Export the variable in your shell to get the same behaviour
from raw commands (D39).

---

## 10. Connecting from your machine

Postgres, with any client, using the password from `.env`:

```bash
psql -h 127.0.0.1 -p 5433 -U expense expense_tracker
```

In DBeaver, pgAdmin or DataGrip: host `127.0.0.1`, port `5433`, database `expense_tracker`, user
`expense`.

Redis: `redis-cli -p 6380`. Database 0 is the Celery queue, so look but do not flush it.

To run `manage.py` on your machine against the Docker database, point `DATABASE_URL` at the
published port:

```bash
DATABASE_URL=postgres://expense:expense-local-only@127.0.0.1:5433/expense_tracker python manage.py shell
```

---

## 11. Background jobs

The worker runs CSV exports and bill scans. Beat triggers `purge_exports` once a day, and because
its schedule lives in the `beat-schedule` volume, the 24-hour clock survives restarts (issue 42).

The monthly digest is deliberately a cron job, not a beat task (RUNNING_ASYNC.md). With Docker,
cron calls into the running web container:

```cron
# Monthly spending digests, 06:00 on the 1st. -T: cron has no terminal.
0 6 1 * * cd /path/to/expense_management && docker compose exec -T web python manage.py send_monthly_digests >> /tmp/expense-digest.log 2>&1
```

---

## 12. Backups

The stack must be running.

```bash
make backup                                        # writes two files into backups/
make restore-db FILE=backups/db-20260924-101500.dump
make restore-media FILE=backups/media-20260924-101500.tar.gz
```

| File | Made with | Restored with |
|---|---|---|
| `backups/db-<timestamp>.dump` | `pg_dump --format=custom` inside the db container | `pg_restore --clean --if-exists`; web, worker and beat are stopped for the restore and started again after |
| `backups/media-<timestamp>.tar.gz` | `tar` of `/data/media` inside the web container | `tar` extracted back into `/data/media` |

`backups/` is gitignored and dockerignored: a dump holds everyone's financial history and must never
reach a commit or an image.

---

## 13. Running the tests in Docker

```bash
make test                                   # the whole suite
make test ARGS=expenses.tests.test_balances # one module
make lint                                   # ruff check + ruff format --check
```

The suite runs in a throwaway container from the dev image, against the Docker Postgres, so the
Postgres-only tests that SQLite skips run too. Django creates and drops its own test database. The
test runner sends uploaded test files to a temporary directory, so the media volume is never touched
(issue 41).

---

## 14. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `Bind for 127.0.0.1:8765 failed: port is already allocated` | Another program holds the port. Change `WEB_PORT` (or `POSTGRES_PORT` / `REDIS_PORT`) in `.env`, then `make up` |
| `password authentication failed for user "expense"` after changing `POSTGRES_PASSWORD` | Postgres reads the password only when the volume is first created. Change it inside the database too: `make psql`, then `ALTER USER expense PASSWORD 'new-one';` — or `make destroy` if the data does not matter |
| `Permission denied` on a file in your checkout, in development | `HOST_UID`/`HOST_GID` in `.env` do not match `id -u`/`id -g`. Fix them, then `make dev` to rebuild |
| `toomanyrequests` from Docker Hub during a build | Anonymous pulls are rate-limited per IP. `docker login`, or wait an hour |
| A container keeps restarting | `make logs SERVICE=<name>`; the reason is in the last lines |
| Works at 127.0.0.1, but the phone gets `Bad Request (400)` | The LAN IP is missing from `ALLOWED_HOSTS` (§4) |
| The stack is running again after a reboot | That is `restart: unless-stopped`. `make down` stops it until the next `make up` |
| `No directory at: /app/staticfiles/` warning in development | Harmless. With `DEBUG` on, static files come from the apps, not from `collectstatic` |
| Every raw `docker compose up -d --build` recreates web, worker and beat | The build attestation described under §9. Use `make up`, or export `BUILDX_NO_DEFAULT_ATTESTATIONS=1` |
| Disk filling up | `docker system df`, then `docker image prune` for old images; each `make update` leaves the previous image dangling |

---

## 15. How this was verified

Every command in this document was run end to end in session 26. The runs used a Linux user with
uid 1001 in the `docker` group, working from a fresh clone with no `.env`, volumes or app images:

| Check | Result |
|---|---|
| `make up` from nothing | 55 s including the build; five services up, web healthy; ports on 127.0.0.1 only |
| Browser: sign up, verify, log in, add an expense | passes in Chromium |
| Bill scan and CSV export, which cross between web and worker | both pass (both failed on phase 11's stack) |
| `make down`, then `make up`; a Redis restart with a task queued | data, uploads, exports and the queued task all survive |
| `make update` after a pushed commit | new code served, new migration applied by web |
| `make dev`: edits live, worker restarts, file ownership | passes; files created inside are owned by uid 1001 |
| `make test` | 477 tests on Postgres, none skipped, media volume untouched |
| `make backup`, `make destroy`, both restores | everything back |
| Opened to the LAN | login works; Postgres stays closed |
| Docker daemon stopped and started (a reboot) | all five containers back by themselves |

Details, and the four things only running it could find, are in BUILD_LOG session 26.
