# Expense Tracker

A Django application for tracking and splitting everyday spending, built as an end-to-end reference
project. It deliberately includes the parts a batteries-included framework usually hides:
user-scoped data access, database-level constraints, row locking, background jobs, scheduling, and
an LLM integration that never writes to the database on its own authority.

**Stack:** Django 5.2 · Python 3.10 · PostgreSQL (SQLite for a zero-setup run) · Celery + Redis ·
Django REST Framework · Docker Compose · GitHub Actions · vision LLMs (Claude, Gemini or OpenAI)
behind one provider interface

**Features**

- User-scoped expenses with categories, a dashboard, filters and full-text search on notes
- Bills split across participants, evenly or per line item, with a payer and a rounding tolerance
- Balances per participant and a concurrency-safe settle-up
- **Bill scanning:** photograph a bill, and a vision model pre-fills an expense for you to confirm
- CSV export generated in the background and delivered by email; a monthly digest email
- A versioned JSON API (`/api/v1/`)

Built in eighteen phases; the first sixteen end in a git tag. `docs/COMMIT_PLAN.md` is the build
order, `docs/BUILD_LOG.md` records what each phase actually cost, and `docs/DECISIONS.md` lists
every judgement call with the alternative that was rejected.

### How this was built

A learning project, built with heavy use of an AI coding assistant (Claude Code). I set the scope
and the order in which concepts were introduced, and reviewed each change. Every judgement call,
whether mine or the assistant's, is recorded in `docs/DECISIONS.md` with the alternative that was
rejected. I am now re-implementing the core mechanisms by hand, so that they are things I know
rather than things the tool knew.

---

## Setup

```bash
git clone https://github.com/Vatsal-Kanojiya/expense_management.git expense-tracker
cd expense-tracker

python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate

pip install -r requirements.txt -r requirements-dev.txt

cp .env.example .env
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
# paste that value into SECRET_KEY in .env

python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Then open http://127.0.0.1:8000/.

### Or the whole stack at once

```bash
docker compose up --build
```

Brings up web, Celery worker, beat, Redis and Postgres together, which is the only configuration
where row locking, the cache and the scheduler all behave as they do in production.

> **Note:** sign up at `/accounts/signup/` for a normal account. A superuser is only needed for
> the Django admin at `/admin/`.

Optionally install the git hooks so linting runs before each commit:

```bash
pre-commit install
```

---

## Common commands

| Command | Purpose |
|---|---|
| `python manage.py runserver` | Development server |
| `python manage.py test` | Run the test suite |
| `celery -A config worker -l info` | Start the background worker (needs Redis) |
| `python manage.py send_monthly_digests --dry-run` | Rehearse the monthly digest |
| `python manage.py check_splits` | Report expenses whose line items no longer add up |
| `python manage.py purge_exports` | Delete old export files |
| `coverage run manage.py test && coverage report` | Tests with coverage, fails under 95% |
| `ruff check . && ruff format .` | Lint and format |
| `python manage.py makemigrations --check --dry-run` | Fail if a model changed without a migration |
| `python manage.py check --deploy` | Production readiness audit |

---

## Configuration

All configuration comes from the environment via `django-environ`; see `.env.example`.

| Variable | Required | Default | Notes |
|---|---|---|---|
| `SECRET_KEY` | **yes** | *none* | No default on purpose — an unset key raises `ImproperlyConfigured` at startup rather than falling back to a shared value |
| `DEBUG` | no | `False` | Fails safe when unset |
| `ALLOWED_HOSTS` | no | `[]` | Comma separated; must be non-empty once `DEBUG=False` |
| `DATABASE_URL` | no | local SQLite | e.g. `postgres://user:pass@localhost:5432/expense_tracker` |
| `CELERY_BROKER_URL` | no | `redis://localhost:6379/0` | |
| `BILL_SCAN_PROVIDER` | no | `fake` | `fake` \| `claude` \| `gemini` \| `openai` — see below |

---

## Bill scanning

Photograph a bill, and a vision LLM reads it into a form the user still has to confirm — nothing
is ever saved from a model's output without a human pressing Save.

**The flow.** Upload creates a `BillScan` row and queues the `scan_bill` Celery task (via
`transaction.on_commit`, like every other task here). The task sends the image to the configured
provider, which asks for JSON matching a fixed schema. `normalize.py` turns that JSON into a frozen
`ExtractedBill`, the result is stored on the scan, and the review page pre-fills the normal expense
form — merchant, date, total, line items, category — for the user to correct and save.

**Design decisions** (full reasoning in `docs/DECISIONS.md`, D28–D30):

- **One interface, many providers.** Each provider implements `extract(data, mime_type, model) ->
  ExtractedBill`. The registry imports providers lazily, so a server configured for Gemini does
  not need the Anthropic SDK installed.
- **One parser.** Providers never build an `ExtractedBill` themselves; all raw output goes through
  `normalize.py`, so there is one place that decides what a malformed amount or an ambiguous date
  means. Dates are read day-first (`05/09/2026` is 5 September); negative or unparseable amounts are
  dropped rather than raising.
- **Money stays exact.** Amounts are `Decimal` in memory and strings in the JSON result, never
  floats.
- **Not every failure is retried.** A network error or rate limit is transient, so Celery retries
  it. An `ExtractionError` (the model looked and could not read the bill) is not: retrying the same
  image costs money for no better odds.
- **Idempotent.** A redelivered task for a finished scan does nothing, and a scan that already
  produced an expense cannot be reviewed again, so a double-click or the back button cannot create a
  second expense.
- **A fake provider by default.** `fake` returns a fixed sample bill with no API key, network call
  or cost, which is why the feature works out of the box in development and in CI.

**Choosing a provider** is a runtime toggle, not a code change:

| Variable | Default | Notes |
|---|---|---|
| `BILL_SCAN_PROVIDER` | `fake` | `fake` \| `claude` \| `gemini` \| `openai` |
| `BILL_SCAN_CLAUDE_MODEL` | `claude-sonnet-5` | Used when `BILL_SCAN_PROVIDER=claude` |
| `BILL_SCAN_GEMINI_MODEL` | `gemini-2.5-flash-lite` | Used when `BILL_SCAN_PROVIDER=gemini` |
| `BILL_SCAN_OPENAI_MODEL` | `gpt-5-mini` | Used when `BILL_SCAN_PROVIDER=openai` |

To use a real provider, also set that provider's own API key as its SDK expects
(`ANTHROPIC_API_KEY`, `GEMINI_API_KEY` or `OPENAI_API_KEY`). These are read directly by each SDK,
not through a Django setting.

---

## Project layout

```
config/              Settings, root URLConf, Celery app, middleware, WSGI/ASGI
accounts/            Custom user model (email login), signup, email verification,
                     login and password-reset rate limiting, ordered account deletion
expenses/            Domain app
  models.py            Category, Expense, ExpenseItem, ItemShare, Participant,
                       Settlement, ExportJob, MonthlyDigest, BillScan
  managers.py          ExpenseQuerySet — chainable query building blocks
  mixins.py            Owner-scoping mixins  <- the security model lives here
  views.py             Class-based views for expenses, people, balances, exports, bills
  forms.py             ModelForms and the line-item formset, all user-scoped
  splitting.py         Even and per-item split arithmetic, with rounding tolerance
  balances.py          Who owes whom, derived from expenses and settlements
  settlements.py       Settle-up: read-then-write under select_for_update
  summaries.py         Period aggregation, shared with the digest email
  cache.py, signals.py Per-user cached aggregates and their invalidation on write
  tasks.py             Celery tasks: CSV export, bill scanning, export purge
  extraction/          Bill scanning: types, prompt, normaliser, registry, providers
  api/                 DRF serializers, viewsets, cursor pagination
  management/          send_monthly_digests, check_splits, purge_exports
  tests/               The test suite (see below)
templates/           Project-wide templates
docs/                Build log, decisions, plans and study notes
```

---

## Architecture notes

**Every query is scoped to the request user.** `OwnerScopedMixin` bundles `LoginRequiredMixin` with
a `get_queryset()` filter, so login and scoping cannot be applied separately by accident. Scoping
lives in `get_queryset` rather than `get_object`, which covers list, update and delete in one place
— another user's primary key simply is not in the queryset, so Django raises 404 before any
permission code runs. The API does the same; its `IsOwner` permission is defence in depth, not the
boundary, because DRF never calls `has_object_permission` on a list.

**404, never 403.** A 403 confirms the row exists, leaking exactly what scoping hides. A test pins
that a forbidden id and a nonexistent id are indistinguishable.

**Ownership is never a form field.** `user` is excluded from every form and assigned server-side
from the session, so it cannot be reassigned by a crafted POST. Forms receive the user only to
scope their own validation and their dropdowns.

**Two layers of validation.** Database constraints (`UniqueConstraint`, `CheckConstraint`)
*guarantee* correctness; form `clean_*` methods *explain* it. Category names are unique per user
case-insensitively, via `UniqueConstraint(Lower("name"), "user")`, so the database and the form
agree.

**Read-then-write is locked.** Settling up reads a balance and writes a settlement based on it.
`select_for_update()` on the participant row inside `transaction.atomic()` makes the second of two
concurrent requests wait and read the updated balance, instead of both writing against the old one.

**Tasks are queued after commit.** Every Celery task is dispatched with `transaction.on_commit`.
Calling `.delay()` inside an open transaction lets a fast worker read a row that does not exist
yet, or act on one that is then rolled back.

**`on_delete` is chosen per relation.** `Expense.category` uses `PROTECT` so spending history is
never destroyed by tidying up a category. Deleting an account therefore deletes in dependency order,
explicitly, in `accounts/deletion.py`, rather than loosening that protection to `CASCADE`.

**No N+1 on list pages.** The expense list uses `select_related` for the category and payer and
nested `Prefetch` objects for line items and their shares, and tests pin the query count so a
regression fails the build.

---

## Testing

Run with `python manage.py test`. CI fails the build below 95% coverage. Tests are organised by
what breaks when they fail:

| Where | Question it answers |
|---|---|
| `test_models.py`, `test_postgres.py` | What does the database guarantee, even if application code is wrong? |
| `test_forms.py`, `test_form_state.py` | What does the application explain instead of returning a 500? |
| `test_views.py`, `test_dashboard.py`, `test_templates.py` | Does the request/response cycle work? |
| `test_permissions.py`, `test_api.py` | Can one user reach another user's data, through the site or the API? |
| `test_orm.py` | Do list pages keep a fixed query count? |
| `test_concurrency.py` | Does settle-up stay correct under concurrent requests? |
| `test_splits.py`, `test_splitting.py`, `test_balances.py` | Do splits and balances add up to the paisa? |
| `test_exports.py`, `test_digests.py` | Are background jobs idempotent and correct? |
| `test_bill_scans.py`, `test_extraction.py`, `test_*_provider.py` | Is model output parsed safely, and are failures classified correctly? Real providers are tested against mocked SDK clients, so no test makes a network call. |
| `accounts/tests/` | Signup, verification, login, password reset, rate limiting, deletion |

`test_permissions.py` is the file that must never be allowed to go red. Nine tests need PostgreSQL
(full-text search, row locking) and are skipped on SQLite.

CI runs lint, format check, the migration check, Django's system checks, the suite with its
coverage threshold, and `check --deploy` on every push and pull request.

---

## Known limitations

Tracked in full in [docs/BUILD_LOG.md](docs/BUILD_LOG.md) §6. The ones that matter most:

- **The self participant is unprotected in the API.** The web pages hide it, but API clients can
  rename or delete it. Parked pending a redesign of the self-participant model (issue 34).
- **A participant on a line item cannot be deleted.** `ItemShare.participant` is `PROTECT`; the view
  explains this instead of erroring, but there is no bulk re-share yet (issue 25).
- **No worker supervision or monitoring.** A crashed worker stays down, and a task that exhausts
  its retries is lost silently (issue 20).
- **Exports stream through Python.** Fine in development; production wants `X-Accel-Redirect` or a
  signed storage URL (issue 21).

---

## Documentation

| Doc | Contents |
|---|---|
| [docs/DECISIONS.md](docs/DECISIONS.md) | Every judgement call, with the alternative rejected and why |
| [docs/BUILD_LOG.md](docs/BUILD_LOG.md) | Living build log, settings change ledger, known issues |
| [docs/COMMIT_PLAN.md](docs/COMMIT_PLAN.md) | Phase-by-phase build order and the practice-branch workflow |
| [docs/HANDOFF_BILL_SCAN.md](docs/HANDOFF_BILL_SCAN.md) | How the bill-scanning phase was planned and built, task by task |
| [docs/RUNNING_ASYNC.md](docs/RUNNING_ASYNC.md) | Running the worker, the digest, cron and systemd |
| [docs/DJANGO_CHEATSHEET.md](docs/DJANGO_CHEATSHEET.md) | Commands with the reasoning behind them |
| [docs/STUDY_MAP.md](docs/STUDY_MAP.md) | Topics ranked by depth required, and why |
| `docs/phase-ledger.html`, `docs/concept-atlas.html` | Visual study pages: what each phase covers, and where each concept lives in the code |

---

## Licence

MIT. See [LICENSE](LICENSE).
