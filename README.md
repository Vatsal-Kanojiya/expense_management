# Expense Tracker

A small Django application for tracking personal spending by category, built as an end-to-end
reference project — deliberately including the parts a batteries-included framework usually hides:
user-scoped data access, database-level constraints, background jobs and scheduling.

**Stack:** Django 5.2 · Python 3.10 · SQLite (dev) / Postgres-ready via `DATABASE_URL`

---

## Setup

```bash
git clone <repo-url> expense-tracker
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
| `python manage.py test` | Run the test suite (169 tests) |
| `celery -A config worker -l info` | Start the background worker (needs Redis) |
| `python manage.py send_monthly_digests --dry-run` | Rehearse the monthly digest |
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

---

## Project layout

```
config/            Project settings, root URLConf, WSGI/ASGI
accounts/          Custom user model (accounts.User)
expenses/          Domain app
  models.py          Category, Expense
  managers.py        ExpenseQuerySet - chainable query building blocks
  summaries.py       Period aggregation, shared with the digest email
  filters.py         Forms that validate query-string parameters
  tasks.py           Celery tasks (CSV export)
  management/        send_monthly_digests - cron-driven, idempotent
  forms.py           ModelForms with user-scoped validation
  views.py           Class-based CRUD views
  mixins.py          Owner-scoping mixins  <- the security model lives here
  tests/             models / forms / views / permissions
templates/         Project-wide templates
docs/              Build log, commit plan, Django cheatsheet
```

---

## Architecture notes

**Every query is scoped to the request user.** `OwnerScopedMixin` bundles `LoginRequiredMixin` with
a `get_queryset()` filter, so login and scoping cannot be applied separately by accident. Scoping
lives in `get_queryset` rather than `get_object`, which covers list, update and delete in one place
— another user's primary key simply is not in the queryset, so Django raises 404 before any
permission code runs.

**404, never 403.** A 403 confirms the row exists, leaking exactly what scoping hides. A test pins
that a forbidden id and a nonexistent id are indistinguishable.

**Ownership is never a form field.** `user` is excluded from every form and assigned server-side
from the session, so it cannot be reassigned by a crafted POST. Forms receive the user only to
scope their own validation — notably `ExpenseForm` narrows the category dropdown, without which the
form would both leak other users' category names and accept their ids.

**Two layers of validation.** Database constraints (`UniqueConstraint`, `CheckConstraint`)
*guarantee* correctness; form `clean_*` methods *explain* it. Both are needed: a `ModelForm` cannot
validate `UniqueConstraint(user, name)` because Django skips constraints touching fields absent
from the form, so without the form layer a duplicate would surface as an `IntegrityError` 500.

**`on_delete` is chosen per relation.** `Expense.category` uses `PROTECT` so spending history is
never destroyed by tidying up a category; the user foreign keys use `CASCADE`.

---

## Testing

135 tests, 100% statement coverage, organised by what breaks when they fail:

| File | Question it answers |
|---|---|
| `tests/test_models.py` | What does the database guarantee, even if application code is wrong? |
| `tests/test_forms.py` | What does the application explain instead of returning a 500? |
| `tests/test_views.py` | Does the request/response cycle work for the happy paths? |
| `tests/test_permissions.py` | Can one user reach another user's data? |
| `tests/test_summaries.py` | Does the aggregation compute the right numbers, with no request? |
| `tests/test_dashboard.py` | Do the dashboard and filters behave at the view layer? |
| `tests/test_templates.py` | Does anything template-shaped reach the browser? |
| `accounts/tests/` | Login, logout, signup, password change and reset |

`test_permissions.py` is the file that must never be allowed to go red.

CI runs lint, format check, the migration check, Django's system checks, and the suite with its
coverage threshold on every push and pull request.

---

## Known limitations

Tracked in full in [docs/BUILD_LOG.md](docs/BUILD_LOG.md). The two that matter most:

- **Account deletion is broken.** `user.delete()` raises `ProtectedError` for any user with
  expenses, because the cascade to their categories collides with `PROTECT` on `Expense.category`.
  A tripwire test documents this and will fail once it is fixed.
- **Case sensitivity is inconsistent.** The database constraint is exact-match while the form check
  is case-insensitive, so the admin can create both `Food` and `food` for one user.

---

## Documentation

| Doc | Contents |
|---|---|
| [docs/BUILD_LOG.md](docs/BUILD_LOG.md) | Living build log, settings change ledger, known issues |
| [docs/COMMIT_PLAN.md](docs/COMMIT_PLAN.md) | Phase-by-phase build order and the practice-branch workflow |
| [docs/DJANGO_CHEATSHEET.md](docs/DJANGO_CHEATSHEET.md) | Commands with the reasoning behind them |
| [docs/STUDY_MAP.md](docs/STUDY_MAP.md) | Topics ranked by depth required, and why |
| [docs/RUNNING_ASYNC.md](docs/RUNNING_ASYNC.md) | Running the worker, the digest, cron and systemd |
