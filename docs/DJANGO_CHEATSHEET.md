# Django Cheatsheet — commands + the *why* behind them

> Companion to [BUILD_LOG.md](BUILD_LOG.md). The commands are the easy half; the **Why it matters**
> notes are the half that signals you've actually shipped Django rather than followed a tutorial.
>
> This project: Django 5.2.17 · Python 3.10.12 · SQLite (dev)

---

## 1. Bootstrap a project

```bash
mkdir expense-tracker && cd expense-tracker
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install django
django-admin startproject config . # ← note the trailing dot
python manage.py startapp expenses
```

Then register the app in `config/settings.py`:

```python
INSTALLED_APPS = [
    ...,
    "expenses",
]
```

### 1.1 Why the trailing dot — `startproject config .`

This is the single highest-signal-per-keystroke decision in the whole bootstrap.

**Without the dot** (`django-admin startproject config`):

```
expense-tracker/
└── config/              ← a wrapper directory that does nothing
    ├── manage.py
    └── config/          ← the actual settings package
        ├── settings.py
        ├── urls.py
        ├── wsgi.py
        └── asgi.py
```

`startproject` has to put `manage.py` *somewhere*, so when you don't tell it where, it invents a
container directory. You end up with `config/config/`, `manage.py` buried one level down, and a
repo root that contains exactly one folder.

**With the dot** — "scaffold into the directory I'm already in":

```
expense-tracker/         ← repo root (already exists, already git init'd)
├── manage.py            ← at the root, where every tool expects it
├── config/              ← settings package, named once
│   ├── settings.py
│   ├── urls.py
│   ├── wsgi.py
│   └── asgi.py
└── expenses/            ← apps sit as siblings, not nested under config
```

Why it actually matters, in descending order of how often it bites you:

| Reason | Consequence of getting it wrong |
|---|---|
| `manage.py` at repo root | `python manage.py runserver` works from where you already `cd`'d. Otherwise every command, CI step, and README line needs an extra `cd config` |
| Docker / deploy | `COPY . .` + `CMD ["python", "manage.py", "migrate"]` just works. Nested layouts need `WORKDIR /app/config` and path juggling |
| Tooling defaults | pytest, ruff, coverage, tox, `pyproject.toml` all assume the project root *is* the repo root |
| No `config/config/` stutter | The inner package name appears once, so imports and tracebacks read cleanly |
| Apps are siblings | `expenses/` next to `config/`, not buried inside it — the dependency direction (`config` knows about apps, apps don't know about `config`) matches the folder layout |

### 1.2 Why name it `config` and not `expense_tracker`

The settings package name is not cosmetic — it gets baked into three settings and one env var:

```python
# config/settings.py
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
# config/manage.py, wsgi.py, asgi.py
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
```

| Naming it `config` | Naming it after the project |
|---|---|
| Stable — renaming the product never touches settings | Rename the project → rename the package → update `ROOT_URLCONF`, `WSGI_APPLICATION`, `DJANGO_SETTINGS_MODULE`, Dockerfile, gunicorn command |
| `expense_tracker` stays free as an *app* name | Project package and app can't share a name — Python import collision |
| Reads as "this is the configuration layer" | Reads as "this is the app", which it isn't |
| Matches `cookiecutter-django` / *Two Scoops of Django* convention — the layout reviewers recognise | Matches the default tutorial |

**The honest version:** the layout alone won't win you an interview. Being able to say *"I use
`startproject config .` so `manage.py` sits at the repo root and the settings package name doesn't
change when the product gets renamed"* — in one sentence, unprompted — is the actual signal. The
convention is a conversation opener; the reasoning is the credential.

---

## 2. Apps and migrations

```bash
python manage.py startapp expenses          # scaffold an app
python manage.py makemigrations             # model changes → migration file
python manage.py makemigrations expenses    # scope to one app
python manage.py migrate                    # apply migrations to the DB
python manage.py showmigrations             # what's applied, what isn't
python manage.py sqlmigrate expenses 0001   # print the SQL a migration will run
python manage.py migrate expenses zero      # unapply every migration for an app
python manage.py makemigrations --check --dry-run   # CI guard: fail if models drifted
```

**Why it matters:**

- **`makemigrations` writes a file; `migrate` runs it.** Two separate steps on purpose. Migration
  files are **source code — commit them.** This is the biggest single difference from Frappe, where
  `bench migrate` syncs schema from DocType JSON and there's no artifact to review.
- **`sqlmigrate` is the interview answer.** "How do you know what a migration will do to
  production?" → you print the SQL and read it. Almost nobody at junior level knows this command.
- **`makemigrations --check --dry-run` in CI** fails the build if someone edited a model and forgot
  to generate the migration. One line, catches a whole class of "works on my machine".
- **`migrate app zero`** is how you unwind cleanly in dev instead of deleting the DB and hoping.

---

## 3. Running and inspecting

```bash
python manage.py runserver                  # dev server, :8000
python manage.py runserver 0.0.0.0:8000     # reachable from other devices / containers
python manage.py createsuperuser            # admin login
python manage.py shell                      # Python REPL with Django loaded
python manage.py dbshell                    # straight into the DB client
python manage.py check                      # system checks without starting the server
python manage.py check --deploy             # production-readiness audit
python manage.py test                       # run the test suite
python manage.py collectstatic              # gather static files for prod
python manage.py flush                      # wipe data, keep schema
```

**Why it matters:**

- **`check --deploy`** audits `DEBUG`, `SECRET_KEY`, `ALLOWED_HOSTS`, HSTS, secure cookies. Running
  it unprompted is a strong signal — it says you've thought past `runserver`.
- **`shell` vs `dbshell`**: ORM-level vs SQL-level. Knowing which one you need for a given question
  is a real skill.
- **`runserver` is not a production server.** Say this out loud in an interview; gunicorn/uvicorn
  behind nginx is the answer.

---

## 4. Useful ORM one-liners in `manage.py shell`

```python
from django.contrib.auth import get_user_model
from expenses.models import Category, Expense

User = get_user_model()          # never import User directly — see §5
u = User.objects.first()

Expense.objects.filter(user=u).select_related("category")   # 1 query, not N+1
Expense.objects.filter(user=u).values("category__name").annotate(total=Sum("amount"))

print(Expense.objects.filter(user=u).query)   # see the generated SQL
```

`print(qs.query)` is the ORM equivalent of `sqlmigrate` — proof you can debug what the ORM emits
rather than trusting it.

---

## 5. Small things that separate "did a tutorial" from "has shipped"

Ranked by how much they actually signal.

| # | The thing | Why it signals experience |
|---|---|---|
| 1 | **Custom user model created before the first migration** | The one decision Django makes genuinely painful to reverse. See §6 — **this project hasn't done it yet** |
| 2 | `settings.AUTH_USER_MODEL` / `get_user_model()`, never `from django.contrib.auth.models import User` | Direct import hard-couples you to the default user. ✅ already done in [expenses/models.py](../expenses/models.py) |
| 3 | Migrations committed to git | Shows you treat schema as reviewable code |
| 4 | DB-level `constraints`, not just form validation | Form validation can be bypassed; the DB can't. ✅ already done (`UniqueConstraint`, `CheckConstraint`) |
| 5 | `.gitignore` + `requirements.txt`, venv **not** committed | ❌ not yet — see BUILD_LOG §6 |
| 6 | `select_related` / `prefetch_related` where it matters | N+1 queries are the #1 Django performance question |
| 7 | `startproject config .` | §1 above |
| 8 | `on_delete` chosen deliberately per relation | `PROTECT` on `Expense.category` (don't orphan expenses) vs `CASCADE` on `user` — ✅ you got this right |
| 9 | `check --deploy` before shipping | Nobody does this at junior level |
| 10 | Knowing `runserver` isn't for production | Table stakes, but people still get it wrong |

---

## 6. ⚠️ Decision that is cheap now and expensive later: custom user model

Django's own docs call this "highly recommended" even if you don't need it yet. Swapping
`AUTH_USER_MODEL` **after** migrations exist and data is live is one of the genuinely nasty
migrations in Django.

**Right now the cost is near zero** — `0001_initial` exists but the SQLite DB is throwaway.
In session 4, with dashboard queries and test fixtures written against it, it won't be.

```bash
python manage.py startapp accounts
```

```python
# accounts/models.py
from django.contrib.auth.models import AbstractUser

class User(AbstractUser):
    pass          # empty today; the point is the seam exists

# config/settings.py
INSTALLED_APPS = [..., "accounts", "expenses"]
AUTH_USER_MODEL = "accounts.User"
```

Then, because there's no data worth keeping:

```bash
rm db.sqlite3 expenses/migrations/0001_initial.py
python manage.py makemigrations accounts expenses
python manage.py migrate
python manage.py createsuperuser
```

Because [expenses/models.py](../expenses/models.py) already references `settings.AUTH_USER_MODEL`
rather than importing `User`, **no model code changes** — that's exactly the payoff of signal #2
above, and it's a good story to be able to tell.
