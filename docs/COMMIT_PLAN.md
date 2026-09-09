# Commit Plan — industry-standard Django build order

> Companion to [BUILD_LOG.md](BUILD_LOG.md) and [DJANGO_CHEATSHEET.md](DJANGO_CHEATSHEET.md).
>
> One commit = one reviewable idea. Each phase ends with a **git tag**, so months later you can run
> `git diff phase-2-auth phase-3-crud` and see exactly what a given step changed at code and
> architecture level. That is the whole point of this document.

---

## 0. The two rules that decide the order

Most of Django's build order is soft preference. Two things are genuinely hard constraints, and
getting them wrong costs real rework:

1. **Custom user model must land before the first migration you care about.** Everything else can
   be reordered. This one cannot.
2. **Auth must exist before user-scoped CRUD.** Views written without `request.user` get rewritten,
   not extended, when auth arrives.

Everything after that follows one principle:

> **Build vertical slices, not horizontal layers.**
> Not "all models → all views → all templates". Instead: one model end-to-end (model → url → view →
> form → template → test), then the next. You discover a modelling mistake while writing the form,
> not three weeks later. Horizontal layering is the single most common way a solo project stalls.

---

## 1. Conventions

**Commit messages** — Conventional Commits, so `git log --grep` is useful later:

```
feat(expenses): add category CRUD views
fix(expenses): scope expense queryset to request.user
chore(config): split settings into base/dev/prod
test(expenses): cover ownership boundaries
refactor(expenses): extract OwnerQuerysetMixin
docs: record phase 3 in build log
```

**Phase tags** — after the last commit of each phase:

```bash
git tag -a phase-1-foundation -m "Repo hygiene, custom user, settings split"
git tag -a phase-2-auth       -m "Login, logout, signup"
# later, to review what a phase actually changed:
git diff phase-1-foundation phase-2-auth --stat
git log phase-1-foundation..phase-2-auth --oneline
```

**Per-phase discipline:** last commit of every phase is a `docs:` commit updating
[BUILD_LOG.md](BUILD_LOG.md). That keeps the mind map current instead of reconstructed later.

---

## 2. The build order

Status: ✅ done · 🔜 next · ⬜ planned

### Phase 0 — Project scaffold ✅ *(commits `60fb810`, `89c3a82`)*

| # | Commit | Files | Architecture note |
|---|---|---|---|
| 0.1 | `chore: bootstrap django project` | `config/`, `manage.py` | `startproject config .` — repo root layout |
| 0.2 | `feat(expenses): add category and expense models` | `models.py`, `admin.py`, `0001_initial.py` | Domain modelling with DB-level constraints |

> ⚠️ Done slightly out of order — models landed before foundation. Phase 1 corrects this while it's
> still cheap.

---

### Phase 1 — Foundation 🔜 *(do this before any view code)*

| # | Commit | Files | Architecture note |
|---|---|---|---|
| 1.1 | `chore: add gitignore and requirements, untrack venv` | `.gitignore`, `requirements.txt` | Dependency manifest replaces committed venv |
| 1.2 | `feat(accounts): add custom user model` | `accounts/`, `settings.py`, migrations reset | **The irreversible one.** `AUTH_USER_MODEL = "accounts.User"`. No change to `expenses/models.py` because it already uses the indirection |
| 1.3 | `chore(config): move secrets to environment` | `settings.py`, `.env.example` | `SECRET_KEY`/`DEBUG` out of source. Optional-but-recommended: split `settings/base.py` + `dev.py` + `prod.py` |

**Tag:** `phase-1-foundation`
**Deferrable:** 1.3 only. 1.1 and 1.2 get more expensive every session.

---

### Phase 2 — Authentication ✅ *(tag `phase-2-auth`, built after phases 3–4.5)*

> **Outcome:** the bet held. Landing this phase changed `LOGIN_URL` and one test assertion, and
> touched **no view code in `expenses/`**. As built it is five commits — `eb84d02`, `dadf826`,
> `9b78c59`, `d853ab0`, `149aa25` — with a model change (unique email) first, because password
> reset looks users up by email and `AbstractUser` leaves it blank and non-unique.

| # | Commit | Files | Architecture note |
|---|---|---|---|
| 2.1 | `feat(accounts): wire django.contrib.auth urls` | `config/urls.py` | `include("django.contrib.auth.urls")` — login/logout/password reset for free |
| 2.2 | `feat(accounts): add login and logout templates` | `templates/registration/` | Django looks for `registration/login.html` by convention |
| 2.3 | `feat(accounts): add signup view` | `accounts/views.py`, `forms.py` | `UserCreationForm` subclass — the one auth piece Django doesn't hand you |
| 2.4 | `chore(config): set login redirect settings` | `settings.py` | `LOGIN_REDIRECT_URL`, `LOGOUT_REDIRECT_URL`, `LOGIN_URL` |

**Tag:** `phase-2-auth`
**Why before CRUD:** every view in phase 3 uses `LoginRequiredMixin` and `request.user`. Retrofitting auth means rewriting them.

---

### Phase 3 — CRUD vertical slice ✅ *(tag `phase-3-crud`)*

> **As built**, 3.1 was folded into 3.2 — a urlconf pointing at views that don't exist yet won't
> import, so it can't stand as its own working commit. Scoping (3.4) was written *into* each slice
> rather than bolted on afterwards; the separate commit became the mixin extraction instead. Three
> commits: `03b3cff`, `f67f2ee`, `d28d166`.

Category before Expense — `Expense.category` is a FK, so you need categories to exist before the
expense form is usable.

| # | Commit | Files | Architecture note |
|---|---|---|---|
| 3.1 | `feat(expenses): add app urlconf and base template` | `expenses/urls.py`, `templates/base.html` | `include()` from root URLConf — apps own their URL namespace |
| 3.2 | `feat(expenses): add category CRUD` | `views.py`, `forms.py`, `templates/` | First full slice. CBVs (`ListView`/`CreateView`/`UpdateView`/`DeleteView`) |
| 3.3 | `feat(expenses): add expense CRUD` | `views.py`, `forms.py`, `templates/` | Second slice. `ModelForm` with `clean_*` validation |
| 3.4 | `fix(expenses): scope querysets and forms to request.user` | `views.py`, `forms.py` | **The security boundary.** `get_queryset()` filters by user; the category dropdown must only show *my* categories |
| 3.5 | `refactor(expenses): extract owner-scoping mixin` | `expenses/mixins.py` | Once 3.4 is duplicated 6×, extract it. Refactor *after* the duplication is real |

**Tag:** `phase-3-crud`
**This is the phase that matters most for interviews** — it's where user-scoping, `get_queryset` overrides, and object-level ownership live.

---

### Phase 4 — Tests ✅ *(tag `phase-4-tests`)*

> **As built:** a fourth file, `test_forms.py`, was added — the forms carry real logic (duplicate
> checks, dropdown scoping) that belongs neither with models nor views. 59 tests across 3 commits:
> `ad1273e`, `3f0eb14`, `3393334`.

| # | Commit | Files | Architecture note |
|---|---|---|---|
| 4.1 | `test(expenses): cover model constraints` | `tests/test_models.py` | Assert the DB rejects `amount <= 0` and duplicate category names |
| 4.2 | `test(expenses): cover CRUD views and auth redirects` | `tests/test_views.py` | Anonymous user → redirected to login |
| 4.3 | `test(expenses): cover ownership boundaries` | `tests/test_permissions.py` | **User A must get 404 on user B's expense** — the test that proves phase 3.4 works |

**Tag:** `phase-4-tests`
**Honest note:** in a real team these are written *in the same commit as the feature*. Splitting them out is a learning-project concession so you can see the whole test surface at once. From project 2 onward, fold them into the feature commit.

---

### Phase 5 — Read layer ✅ *(tag `phase-5-dashboard`)*

> **As built:** two commits, `34c5a4b` and `5005cba`. The aggregation was extracted to
> `managers.py` + `summaries.py` up front rather than lifted out of the view later, because phase 6
> needs it from a Celery task. Dashboard took a **date range** defaulting to the current month
> rather than a month picker, so one query shape serves both the UI and the digest.

| # | Commit | Files | Architecture note |
|---|---|---|---|
| 5.1 | `feat(expenses): add dashboard with category aggregation` | `views.py`, `templates/` | `values().annotate(Sum())` — the query the digest email will reuse |
| 5.2 | `feat(expenses): add date filtering and pagination` | `views.py`, `filters.py` | `Paginator` / `ListView.paginate_by` |
| 5.3 | `perf(expenses): add select_related to list views` | `views.py` | Fix the N+1 — measure with `qs.query` / django-debug-toolbar |

**Tag:** `phase-5-dashboard`

---

### Phase 6 — Async and scheduled work ✅ *(tag `phase-6-async`)*

> **As built:** three commits — `a970a57`, `cda81e5`, `92cb1e5`. Verified against a real Redis and a
> real worker rather than eager mode alone. The digest bug (`iterator()` + commit-in-loop) is the
> clearest example in this project of why `TransactionTestCase` exists.

The phase this whole project exists to demonstrate. See BUILD_LOG §5 for the Celery-vs-cron rationale.

| # | Commit | Files | Architecture note |
|---|---|---|---|
| 6.1 | `chore: add celery and redis broker` | `config/celery.py`, `settings.py` | `app.autodiscover_tasks()`, `__init__.py` wiring |
| 6.2 | `feat(expenses): add async csv export` | `tasks.py`, `views.py` | **Request-triggered** — view returns immediately, task emails the file. The pattern interviewers probe |
| 6.3 | `feat(expenses): add monthly digest management command` | `management/commands/`, `models.py` | `MonthlyDigest(user, month)` unique constraint = idempotency |
| 6.4 | `feat: add beat/cron schedule for digest` | `settings.py` or crontab | Scheduled, not request-triggered — deliberately *not* Celery-first |

**Tag:** `phase-6-async`

---

### Phase 7 — Production readiness ⬜

| # | Commit | Files | Architecture note |
|---|---|---|---|
| 7.1 | `chore: fix check --deploy warnings` | `settings/prod.py` | HSTS, secure cookies, `ALLOWED_HOSTS` |
| 7.2 | `feat: add 404 and 500 templates` | `templates/` | Only render with `DEBUG=False` |
| 7.3 | `chore: add logging configuration` | `settings.py` | `LOGGING` dict — the thing everyone skips |
| 7.4 | `docs: add readme with setup and architecture` | `README.md` | The file a reviewer opens first |

**Tag:** `phase-7-production`

---

## 3. Practice branches — re-implementing a phase by hand

The tags mark history. They are **not** where you practise: checking out a tag puts you in detached
HEAD, so you cannot commit. Branch off the tag instead.

The loop: start from the state *before* a phase, write that phase yourself from memory, then diff
your version against the reference.

```bash
# 1. Start from the state before phase 3, on a writable branch
git switch -c practice/phase-3 phase-1-foundation

# 2. Write the phase yourself. urls.py, forms.py, views.py, templates.
#    Do NOT look at the reference. Use the BUILD_LOG concept list as the spec.

# 3. Compare against the reference when you are done or stuck
git diff practice/phase-3 phase-3-crud -- expenses/ templates/ config/

# 4. One file at a time is usually more useful than the whole diff
git diff practice/phase-3 phase-3-crud -- expenses/views.py

# 5. Go back to the real line of work
git switch master
```

**Why this works here:** phase 3 added no migrations, and `.env` and `db.sqlite3` are gitignored, so
they survive the switch. The app runs on either branch with no re-migration and no re-setup. Check
this holds before practising a phase that *does* add migrations:

```bash
git diff <from-tag> <to-tag> --stat -- '*/migrations/*'   # empty = safe to switch freely
```

If a phase does add migrations, run `migrate` after switching, or keep a separate SQLite file per
branch via `DATABASE_URL` in `.env`.

**Grading yourself.** An empty diff is not the goal — naming and ordering will differ harmlessly.
What matters is whether you independently arrived at the load-bearing decisions. For phase 3 those are:

- `get_queryset()` scoped by user on **every** detail-bound view (not just the list)
- scoping in `get_queryset`, not `get_object`
- `user` excluded from the form's fields
- `ModelChoiceField.queryset` scoped in the form's `__init__`
- `select_related` on the list view
- a `clean_*` method backing each DB constraint

Miss one of those and the diff is telling you something real. Everything else is style.

---

## 4. Reviewing your own work later

```bash
git tag                                          # every phase boundary
git log --oneline phase-2-auth..phase-3-crud     # commits in the CRUD phase
git diff phase-2-auth phase-3-crud --stat        # files a phase touched
git diff phase-2-auth phase-3-crud -- config/settings.py   # settings drift only
git log --oneline --grep="^feat"                 # features only
git log -p --follow expenses/views.py            # how one file evolved
```

The `--stat` diff between two phase tags is the single most useful command here — it answers "what
did adding auth actually change?" in one line, which is exactly the question an interviewer asks
and the one you can't answer from memory six projects later.
