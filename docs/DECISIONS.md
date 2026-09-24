# Decisions taken without asking

> Companion to [BUILD_LOG.md](BUILD_LOG.md) (what happened) and
> [COMMIT_PLAN.md](COMMIT_PLAN.md) (what happens next). This file records
> **judgement calls made during autonomous sessions**, so a decision you did
> not personally make is never invisible.
>
> Format: what was decided · what else was on the table · why this one.
> Anything here is reversible. If a call looks wrong, the alternative is
> written down next to it.

---

## Session 8 — phase 7 and the roadmap rewrite

### D1. Work stays on `master`; no feature branches

**Decided:** phases land as direct commits on `master`, one annotated tag per
phase, exactly as sessions 1-7 did.

**Alternative:** a `phase-N/*` branch per phase, merged with `--no-ff`.

**Why:** the repo's entire history is linear on `master`, and
[COMMIT_PLAN.md](COMMIT_PLAN.md) §3 already assigns branches a different job —
`practice/*` branches cut from a phase tag, for re-implementing a phase from
memory. Introducing merge commits would make `git diff phase-6-async
phase-7-production` noisier, and that diff is the stated reason the tags exist.
Branching per phase would also fight the practice workflow rather than support
it.

**Reverse it if:** you ever want a phase reviewed before it lands, or you start
working from two machines.

### D2. `SECURE_SSL_REDIRECT` is relaxed in CI's test job, not in settings

**Decided:** `settings.py` keeps `SECURE_SSL_REDIRECT` defaulting to `True`
whenever `DEBUG` is off. The CI **test** job sets it to `False` in its own env;
the `deploy-checks` job does not.

**Alternatives considered:**

| Option | Rejected because |
|---|---|
| Run tests with `DEBUG=True` | Error templates only render with `DEBUG=False`. The phase's own feature would go untested |
| Detect the test runner inside `settings.py` | Settings that behave differently under test are how "works in CI, fails in prod" is born |
| `@override_settings` on every affected test | 106 tests. The decorator would outnumber the assertions |

**Why:** the relaxation is a property of *how the suite is run*, not of the
application, so it belongs in the runner's environment. Keeping the real
default in `settings.py` means the deploy-checks job still gates on the value
that ships.

### D3. Deploy checks are asserted from a subprocess

**Decided:** `DeploySettingsTests` shells out to `manage.py check --deploy`
with a controlled environment, in both directions — production config must
pass, development config must fail.

**Alternative:** `@override_settings(DEBUG=False)` and call the check inline.

**Why:** it does not work. The `if not DEBUG` block in `settings.py` runs at
import time, long before any test. Overriding the flag afterwards changes the
flag and nothing else, so the test would assert against settings that were
never applied. A subprocess is the only honest version, and it happens to
exercise the same code path CI does.

**Cost:** roughly two seconds of subprocess startup in the suite.

### D4. `security.W021` is silenced rather than satisfied

**Decided:** `SILENCED_SYSTEM_CHECKS = ["security.W021"]`, with the reason in a
comment beside it.

**Alternative:** set `SECURE_HSTS_PRELOAD = True` and let the check pass.

**Why:** preload submits the domain to a list compiled into browser binaries.
Removal takes months, and it breaks any subdomain that cannot serve HTTPS. It
is a decision about a specific deployment that does not exist yet. Silencing a
check with a written reason is more honest than flipping a flag to quiet it.

### D5. HSTS starts at one hour, not one year

**Decided:** `SECURE_HSTS_SECONDS` defaults to `3600`, overridable by env.

**Why:** browsers cache the header. A wrong value is close to irreversible for
its full duration, and the usual advice is to ramp up only once HTTPS is known
to be stable on every subdomain. The default should be the safe end of that
ramp, not the destination.

### D6. The expense tracker runs to phase 16 before the next project starts

**Decided:** phases 8-16 are built here, then the larger product is built
separately.

**Why:** your call, recorded here because it reverses an earlier
recommendation of mine to close this project at phase 7. The reasoning that
won: concepts learned under a deadline in a throwaway-scale app are cheaper
than concepts learned inside a product you also care about shipping.

### D7. Split expenses replace tags and budgets as the phase 8 domain

**Decided:** phase 8 adds participants, line items and per-item shares. The
previously planned `Tag` and `Budget` models are dropped.

**Why:** tags and budgets were chosen to give `ManyToManyField` and `F()`
somewhere to live, which is concept-first design. Splitting is a real feature
that *demands* the same machinery and more: an explicit through model carrying
a share weight, two levels of prefetch, inline formsets, a cross-row invariant
no `CheckConstraint` can express, and decimal remainders. Settlement moves to
phase 13, where the row lock it needs is the point of the phase.

**Explicitly out of scope:** debt simplification (collapsing "A owes B, B owes
C"). It is a graph problem and it is where this design would stop being
bounded. Per-participant balances are shown raw.

### D8. Commit granularity is tuned for interruption, not for review

**Decided:** during autonomous sessions, each commit is a self-contained,
green, lint-clean unit — schema in one, pure logic in another, UI in a third —
and the build log carries a **"Resume here"** block naming what is done and
what is next.

**Alternative:** one large commit per phase, or work-in-progress commits.

**Why:** a session can end at any point. Anything uncommitted is lost, and
anything committed broken is worse than nothing. Ordering the work so the data
layer and pure logic land before the UI means an interrupted phase leaves a
working, tested foundation rather than a half-wired feature. The build log
block exists so a session starting with no memory of this one can pick up
without re-deriving the decisions.

## Session 12 — phase 11

### D9. Settings stay in one file; no base/dev/prod split

**Decided:** `config/settings.py` remains a single env-driven module.
COMMIT_PLAN listed 11.2 as `chore(config): split settings into base/dev/prod`,
closing known issue 7. That commit was not made.

**Why the plan changed:** the split solves a problem this project does not
have. Its purpose is to vary configuration per environment, and every setting
that varies here already does so through `django-environ`, proven across three
environments at once — local development, CI, and now a container. Splitting
would add three files and an import graph without adding a single capability,
and it would fragment the settings ledger in BUILD_LOG §3, which is currently
one table anyone can read top to bottom.

Single-module-plus-environment is also the 12-factor answer and what most
recent Django projects do. The split is the older convention, not the better
one.

**What is genuinely lost:** nothing operationally. For interview purposes the
split is a common talking point, so it is worth being able to describe: `base.py`
holds the shared settings, `dev.py` and `prod.py` import `*` from it and
override, and `DJANGO_SETTINGS_MODULE` selects one.

**Reverse it if:** the environments stop differing only by values — if
production needs different `INSTALLED_APPS` or a different middleware chain,
`if` statements in one file become worse than two files.

**Issue 7 is therefore closed as "won't do", not fixed.** Issue 14's Docker half
is genuinely done.

### D10. The test runner swaps three settings, not one

**Decided:** `FastTestRunner` now overrides `STORAGES` and `STATIC_ROOT`
alongside `PASSWORD_HASHERS`.

**Why:** WhiteNoise indexes every collected static file when the middleware is
constructed, and the test client builds a handler per client instance, so the
suite rescanned hundreds of files hundreds of times. Measured: 3.6s before
phase 11, 14.6s after, 3.7s with the swaps.

**Alternative:** drop `WhiteNoiseMiddleware` from `MIDDLEWARE` during tests.
Faster still, and it would make the middleware-ordering assertion test nothing.
Pointing `STATIC_ROOT` at an empty temporary directory keeps the middleware in
the chain in its real position while making the scan free.

## Session 15 — phase 14

### D11. Cache invalidation is explicit, not signal-driven

**Decided:** `bump_version(user_id)` is called at each write site — the
expense create, update and delete views, and the API ViewSet's
`perform_create` / `perform_update` / `perform_destroy`.

**Alternative:** a `post_save` / `post_delete` receiver on `Expense`,
`ExpenseItem`, `ItemShare` and `Settlement`, which would catch every write
including the admin, the shell and data migrations.

**Why explicit, for now:** the signal version is genuinely more correct and
genuinely more invisible. Someone reading `ExpenseCreateView` would have no
way to know a cache was being invalidated, and the project has been
deliberately biased toward code that explains itself at the call site.

**The cost is real and is logged as issue 26**, with a test asserting the
staleness rather than pretending it away. A 15-minute timeout is the
backstop.

**Revisit in phase 15**, which covers signals directly. This is exactly the
case where they earn their keep, and deciding it there with the trade-off
already felt is better than guessing now.

### D12. Version-stamped keys, not key deletion

**Decided:** every summary key embeds a per-user version integer.
Invalidating means incrementing it.

**Why:** deleting the right keys would mean knowing every date range anyone
has ever viewed. Bumping one integer makes the whole family unreachable at
once. `cache.incr` is atomic on Redis, so concurrent writers cannot collide.

**The cost:** orphaned entries occupy memory until they expire. At this scale
that is nothing, and Redis evicts under pressure anyway.

### D13. Caching is disabled in tests by default

**Decided:** `FastTestRunner` swaps in `DummyCache`. Tests that are about the
cache re-enable it with `override_settings`.

**Why:** Django does not clear the cache between tests. A cached dashboard
survived into the next test and made its pinned query count wrong — 2 queries
where 8 were expected — breaking an assertion that had nothing to do with
caching. A test that caches by accident passes for a reason nobody chose.

## Session 16 — phase 15

### D14. Signals are used exactly once, for cache invalidation

**Decided:** D11 is reversed. `bump_version` is no longer called from the
views and the API; a `post_save` / `post_delete` receiver in
`expenses/signals.py` handles every write path at once. Known issue 26 is
closed.

**Why the reversal:** D11 said "revisit in phase 15 with the trade-off
already felt", and having felt it, the signal wins for this specific concern.
Three properties decide it:

1. It is not business logic. Nothing about the meaning of "record an expense"
   involves a cache.
2. Forgetting is silent. A missed bump does not raise, fail a test, or look
   wrong in review. It serves one user a stale number indefinitely.
3. The write sites are unbounded — views, API, admin, shell, migrations,
   management commands, Celery tasks. The ORM is the one chokepoint they all
   share.

**The rule this project settles on:** a signal is right when the concern is
cross-cutting, invisible by nature, and must not be forgotten. Cache
invalidation and audit logging qualify. "Create a related row when this one
is saved" does not — that is business logic hiding from its caller.

**The documented limit:** `bulk_create` and `queryset.update()` do not fire
signals, because they operate on rows rather than instances. A test asserts
this rather than leaving it to be discovered.

### D15. The nav badge context processor never computes anything

**Decided:** `nav_summary` reads a cached value and returns nothing on a miss.
The balances view populates the cache as a side effect of work it already does.

**Why:** the first version walked every expense to count balances. A context
processor runs on *every* template render, so that added four to six queries
to every request in the project and broke three pinned query counts. The tax
arrived exactly on schedule.

**The trade:** the badge is absent until the user visits the balances page
once. That is the right trade for a decoration — a nav badge is never worth a
query, let alone six.

## Session 17 — phase 16

### D16. Rate limiting is hand-written, not django-axes

**Decided:** roughly forty lines in `accounts/ratelimit.py`, backed by the
cache, keyed on `(client address, identifier)`.

**Alternative:** `django-axes`, which is the right answer for production. It
has lockout policies, an admin interface, and a decade of edge cases already
handled.

**Why hand-written here:** the keying decision is the whole design, and a
library hides it. By address alone, one office behind one NAT is one blocked
building. By username alone, an attacker locks any account out of its own
login for free. By both, a single source against a single account is slowed,
which is the shape of credential stuffing.

**What it does not do,** stated in the module rather than implied: it does not
stop a distributed attack, and its fixed window lets a determined caller get
up to twice the limit across a boundary. A sliding window costs a sorted set
per key and is not worth it at this scale.

### D17. Email verification reuses Django's password-reset token machinery

**Decided:** no new model and no new column. `PasswordResetTokenGenerator` is
subclassed with `is_active` mixed into the hash, and `is_active=False` is the
existing flag that keeps an unverified user out.

**Why:** a custom token table would reimplement signing, expiry and
single-use semantics that the framework already gets right. Mixing `is_active`
into the hash makes the link self-invalidating on use with nothing stored.

**Subclassed rather than reused directly** so a verification link can never be
replayed as a password-reset link.

### D18. Account deletion is ordered, not a changed `on_delete`

**Decided:** `accounts/deletion.py` deletes expenses, then settlements, then
participants, then categories, then the user.

**Alternatives rejected:** switching the FKs to `CASCADE` would fix deletion
and remove the protection that stops someone deleting a category out from
under a year of expenses. `SET_NULL` on `Expense.category` would make the
column nullable, so every query and template must handle a category-less
expense forever, to solve a problem that happens once per account.

**The kept test `test_the_plain_delete_still_raises`** documents why this
module exists. Without it, someone would eventually delete it as redundant.

## Session 20 — paid-by, explicit self, per-expense split breakdown

### D19. Self is a `Participant(is_self=True)` row, not a `BooleanField` on `Expense`

**Decided:** auto-create one `Participant(is_self=True, name="You")` per user.
This row appears in the "Paid by" dropdown and the "Split among" checkboxes
alongside every other participant. The balance engine treats it uniformly.

**Alternative (recommended in issue #31):** a `BooleanField(default=True)` on
`Expense`, toggling whether the owner is counted as one implicit share. The
`+1` in `balances.py` becomes conditional on the flag.

**Why the reversal:** the `BooleanField` solves only one of two problems —
whether self is in the split. It does not solve "who paid", because the payer
must be selectable from a set of people, and a boolean has no identity. Making
self a `Participant` unifies payer and consumer into one model: one dropdown,
one set of validation rules, one balance engine, zero special cases in
`_charge_item` and `_charge_evenly`.

**The three trade-offs issue #31 flagged, and how each is handled:**

| Concern | Solution |
|---|---|
| Self leaks into the People list | Filter `is_self=True` out of `ParticipantListView.get_queryset()` |
| Self collides with the `UniqueConstraint(Lower(name), user)` | The name "You" is reserved at the model level; `clean_name` rejects it for regular participants |
| Self appears in the balances table as "someone who owes you" | The balance engine now tracks `(debtor, creditor)` pairs uniformly — self owing a participant is as natural as the reverse |

**Reverse it if:** the number of special-case filters for `is_self` exceeds
three or four. At that point the boolean is cheaper.

### D20. `Expense.paid_by` is a FK to `Participant`, default = self-participant

**Decided:** `Expense.paid_by = ForeignKey(Participant, null=True,
on_delete=PROTECT, related_name="paid_expenses")`. Null during migration only;
data migration populates it to the self-participant for all existing rows.
Default on the form (not the model) is the self-participant.

**Alternatives considered:**

| Option | Rejected because |
|---|---|
| No `paid_by` field — owner is always the payer | Cannot record that a friend paid |
| `paid_by` as a `CharField` (free text) | Cannot join to participants for balance computation |
| `paid_by` as FK to `User` | Not all payers are registered users. A `Participant` is a name owned by a user, which is exactly the right granularity |

**`on_delete=PROTECT`:** a participant who paid for an expense cannot be
deleted. This matches the existing `PROTECT` on `ItemShare.participant` — you
cannot delete someone who is on a bill.

### D21. Split breakdown is a tab on the expense form, not a separate page

**Decided:** the expense create/edit view gets a new tab (alongside the
existing line items card) showing who consumed what, who paid, and who owes
whom. The tab auto-appears when the expense is balanced (`is_balanced()` is
true). No new URL.

**Alternatives considered:**

| Option | Rejected because |
|---|---|
| A separate detail page (`/expenses/<pk>/`) | The user explicitly requested no new pages. The expense form already has all the context |
| Inline expansion in the expense list | Too much data for a table row; would clutter the list with 4-column sub-tables |
| Both (summary in list + detail page) | Over-engineered for the current need |

**Why a tab and not a static section:** the breakdown is derived from line
items and participants, which are being edited on the same page. A tab that
reacts to the current form state (valid vs invalid, balanced vs unbalanced)
gives immediate feedback without navigating away.

> **Superseded in part (session 21).** As built, the tab does **not** react to the form. It shows the
> split as last saved, recomputed from a fresh database fetch, and is absent when the saved expense
> is unbalanced or involves nobody else. A split computed from unsaved typing would describe numbers
> that never existed, and after a rejected submission Django has already copied the rejected values
> onto the form's instance. HANDOFF_PLAN T7 records the as-built rule.

---

## Session 21 — review of the handoff implementation

### D22. The first JavaScript is dependency-free and progressive *(recorded late, from session 19)*

**Decided:** add-and-remove line items in `item-formset.js`, then the chip widget, live unaccounted
figure and tabs in the same style: one IIFE per file, no framework, no build step, served from the
app's own `static/` directory. Every script enhances markup that already works without it.

**Alternatives:** HTMX for server-rendered row fragments; Select2 or Choices.js for the picker; a
separate React frontend.

**Why:** the owner is learning Django, not a frontend toolchain, and may later replace the UI with
React outright. Hand-written scripts cost nothing to delete. A dependency would have added a
supply-chain surface and a settings change for a UI that might not survive.

### D23. Settlements are signed, not given a direction field

**Decided:** `Settlement.amount` is signed and constrained `!= 0`. Positive is the participant paying
the owner; negative is the owner paying the participant. Balances net per person.

**Alternative:** an explicit `direction` field, as session 20 suggested deferring.

**Why:** outstanding stays one expression, `balance - sum(settlements)`, identical for both
directions. A direction field makes every aggregate branch on it, and a missed branch silently
double-counts. The cost is a column that reads less obviously in the database, paid for in
the constraint name and model comment.

### D24. The self participant is named `FirstName (self)`

**Decided:** first name, or username when empty, plus `(self)`, plus a numeric suffix on collision.
Migration 0008 was corrected in place and 0010 renames rows the old 0008 created.

**Alternatives:** keep "You" and skip the collision; exclude `is_self` rows from the uniqueness
constraint.

**Why:** "You" crashed the backfill for anyone with a contact already named that. Excluding self rows
from the constraint would allow two identical names in one picker. The owner asked for their own
name. Editing an applied migration is normally wrong; it is acceptable here because the old version
could not run on the databases it would fail on, and 0010 covers those it succeeded on.

### D25. The API includes the owner by default, with `include_self` to opt out

**Decided:** a write-only `include_self`, default true, adds the self participant to a split that
names others, at expense level and on each shared line.

**Alternative:** API clients must list the self participant explicitly.

**Why:** the web form pre-selects the owner; an API client has no form. Without a default, a request
naming only Rahul charges Rahul the whole bill, which is the exact bug the review found. Explicit
opt-out keeps pure reimbursements expressible.

**Known weakness:** the self participant is still an ordinary row in the API — listable, renamable,
deletable. Parked as issue 34 pending a redesign of the self-participant model.

## Session 22 — form state, and freezing the project

### D26. Bugs that break working functionality are fixed directly, not handed off

**Decided:** the rule that implementation goes to a cheaper model (see HANDOFF_PLAN) applies to new
features and polish only. A bug that loses data or breaks a flow that used to work is fixed, verified
and committed in the same session.

**What prompted it:** the line-item state loss was first answered with a handoff spec, T8, instead of a
fix. The owner had already spent the day on the app and needed it working. The spec was accurate and
still the wrong response.

**Why the split is sound:** a handoff saves tokens on work whose shape is open — new screens, new
widgets — where a written plan prevents a cheap model from producing bulk. A diagnosed bug has no open
shape. Once the root cause is known the fix is a few lines, and routing it through a spec, a second
model and a review costs more than it saves.

**Reverse it if:** a bug's fix turns out to be large or to need design decisions. Then it is a feature
in disguise, and the handoff path fits again.

### D27. The expense tracker is frozen

**Decided:** no further features or polish. Only bugs that lose data or break a working flow are
fixed. Issues 28 to 35 and anything like them stay on the backlog.

**Alternative:** keep refining — finish the parked layout work (issue 35), the self-participant API gap
(issue 34), and whatever the next click-through turns up.

**Why:** the project exists to teach Django through sixteen phases, and it has. Session 22 made the cost
of continuing concrete: a full day went on chip pickers, date widgets and autofocus, which carry almost
no Django interview value. Polish on a learning project has no natural end, and the goal this project
serves — hands-on Django, after a January 2026 interview lost for lack of it — is better met by
project 2 built solo than by a more polished project 1.

**What is not lost:** the phase 17 domain work was real modelling — who paid, explicit self
participation, a misc amount split by consumption, signed settlements. Those are worth keeping and
worth being able to explain.

**Reverse it if:** this project is ever turned into a real product. Then the backlog becomes the
roadmap. Until then, it is a reference, not a work in progress.

---

## Session 25 — bill scanning

### D28. The freeze is lifted for one feature: bill scanning

**Decided:** D27 stands for polish. Bill scanning is admitted as phase 18 because it is not
polish — it adds an external API integration, a provider abstraction and a second async job type,
none of which the project had.

**Reverse it if:** the work drifts into UI refinement. Then D27 applies again.

### D29. A vision LLM, not a dedicated invoice parser

**Decided:** extraction goes to a vision LLM with a JSON schema we define.

**Alternatives:** Azure Document Intelligence (500 free pages a month), AWS Textract
AnalyzeExpense, Google Document AI.

**Why:** parsers return *their* schema — vendor, total, items, tax — and are strongest on formal
typed invoices. This app's bills are mostly restaurant and shop receipts, and its schema has
things a parser cannot fill: a category from the user's own list, and `misc_amount` for tax, tip
and service charge together. A vision LLM returns our shape directly.

**Reverse it if:** a bake-off on real bills shows a parser needs fewer corrections.

### D30. One provider layer, three providers, one setting

**Decided:** the app calls `extract_bill(data, mime_type)` and receives a plain `ExtractedBill`.
Claude, Gemini and OpenAI sit behind a registry keyed by `BILL_SCAN_PROVIDER`; a `fake` provider
is the default so the feature works in development and CI with no keys.

**Why:** prices and quality in this market move monthly. Switching must be a config change, not a
code change. Lazy imports mean a deployment only installs the SDK it uses. Every provider funnels
through one normaliser, so money and date parsing is written once.

**The rule that makes it safe:** model output only ever fills a form a human confirms. No expense
is created from a scan without the user pressing Save.

---

## Session 26 — Docker for daily use

The brief, in the owner's words: dockerize the whole project on its own branch; the database and
anything else that must survive goes in volumes; code updates when the code is pulled; Django and
Postgres reachable from outside the containers on ports that do not collide with the owner's other
projects; a production-like and a development way to run it; and all of it documented. Phase 11 had
already containerised the stack, so this is a rework of that, not a first attempt — and running
phase 11's stack before touching it turned up three bugs of its own (BUILD_LOG issues 38–40).

### D31. Two modes from two files: `compose.yaml` is production-like, `compose.dev.yaml` an overlay

**Decided:** `compose.yaml` is the whole stack, production-like — code baked into the image,
`DEBUG` off, gunicorn. `compose.dev.yaml` is layered on top of it (`-f compose.yaml -f
compose.dev.yaml`) and states only what differs in development: the image target, `DEBUG`, the
commands, and a bind mount of the checkout.

**Alternatives:** one file with Compose profiles; two standalone files; a development setup only.

**Why:** profiles choose *which services* run, not *how* a service runs. Web is the same service in
both modes with a different command, so profiles would mean `web` and `web-dev` side by side with
every dependency written twice. Two standalone files drift — a port changed in one is forgotten in
the other. An overlay can only say what is different, so ports, volumes and healthchecks have one
home.

**Reverse it if:** the overlay ends up overriding most of the base. Then the modes are really two
stacks.

### D32. Code never lives in a named volume

**Decided:** in the production-like mode the code is copied into the image at build time and
updated by rebuilding. In development it is bind-mounted from the checkout. No named volume ever
holds code.

**Alternative:** a named volume at `/app`, as the owner asked about.

**Why:** Docker fills a named volume from the image once, when the volume is created. From then
on the volume wins over the image at that path, so a rebuilt image with new code starts and runs
the *old* code, silently. It is the classic stale-code trap. The two sound shapes are the two
modes: the image is the unit of deployment (pull, rebuild — `make update`), or the checkout is
(pull, and that is all — edits are live).

**Reverse it if:** never, for code. Named volumes are for state.

### D33. Host ports 8765, 5433 and 6380, loopback-only by default, all configurable

**Decided:** on the host, web is 8765, Postgres 5433 and Redis 6380. Inside the containers the
standard 8000, 5432 and 6379 are unchanged. Every host port is a `.env` variable, and they listen on
127.0.0.1 unless told otherwise, through two separate switches: `WEB_BIND_ADDRESS` and
`DATA_BIND_ADDRESS`.

**Alternative:** phase 11's `8000:8000` on every interface.

**Why:** the owner runs several projects, and 8000, 5432 and 6379 are exactly the ports every other
Django project and every locally installed Postgres and Redis already hold. 5433 and 6380 are "the
default plus one", so they still read as Postgres and Redis at a glance. Only the host side moves,
so nothing inside the stack — `DATABASE_URL`, the broker URLs — changes with it.

Loopback by default because **Docker publishes ports by writing firewall rules ahead of ufw**. A
ufw rule does not close a published port. Postgres with a local-only password on `0.0.0.0` is open
to the LAN and to every café network the laptop joins. Web and data have separate switches so the
site can be opened to a phone without opening the database.

**Reverse it if:** a port collides. Change it in `.env`; nothing else refers to it.

### D34. Four named volumes hold everything that must survive; media moves out of `/app`

**Decided:**

| Volume | Holds | Mounted in |
|---|---|---|
| `postgres-data` | the database | db |
| `redis-data` | Redis with append-only persistence: queued tasks survive a restart | redis |
| `media` | uploaded bill photos and generated CSV exports, at `/data/media` | web, worker |
| `beat-schedule` | when each periodic task last ran, at `/data/beat` | beat |

`MEDIA_ROOT` becomes an environment setting (default unchanged), and the image sets it to
`/data/media`.

**Alternative:** phase 11's single `postgres-data` volume, with media inside `/app`.

**Why:** each volume holds a fact that exists nowhere else. **Media** is handed between containers:
web writes the upload and the worker reads it; the worker writes the export and web serves it.
Under phase 11 each container had its own `/app/media`, so no file could cross (issue 40).
**Beat** measures each interval from the last run, which it keeps in a file. Lose the file on
restart and the 24-hour `purge_exports` clock starts again from zero, so a machine that is never up
for 24 hours straight never purges (issue 42). **Redis** holds a queued task that no worker has
picked up yet, and nowhere else.

Media sits outside `/app` because in development `/app` is your checkout. A volume mounted
inside a bind mount makes Docker create the mount point in your checkout, owned by root.

**Deliberately not volumes:** static files are built into the image by `collectstatic` and must
change with it — a volume would pin the first build's CSS, which is D32 again. The cache is Redis
database 2, disposable by design.

**Reverse it if:** media moves to object storage. The `media` volume then goes away.

### D35. Secure cookies can be switched off by environment, as the SSL redirect already could

**Decided:** `SESSION_COOKIE_SECURE` and `CSRF_COOKIE_SECURE` are read from the environment,
default `True`. `compose.yaml` sets both to `False` next to the existing `SECURE_SSL_REDIRECT:
"False"`, for the same reason: nothing in this stack terminates TLS.

**Alternative:** leave them hardcoded, since Chromium treats loopback as a secure context. Measured
before the change: with phase 11's stack, a real Chromium logs in at `http://localhost:8000` and
`http://127.0.0.1:8000` with Secure cookies.

**Why:** loopback is the only place that holds. Over plain HTTP to a LAN address — the phone case in
D33 — the browser drops a Secure cookie, so the session never sticks and every POST fails CSRF.
Defaults stay `True` everywhere else. A test asserts that switching them off fails `check --deploy`,
and CI's deploy job never sets them, so a real deployment cannot pick the switch up quietly.

**Measured after the change (BUILD_LOG session 26, V13):** with the site opened on a non-loopback
address, login works with the switches off. With them on — Django's secure default — the same
login fails with 403 CSRF, while `127.0.0.1` still works.

**Reverse it if:** the local stack gains TLS, for example Caddy in front. Then the switches go back
to their defaults.

### D36. One project, one dataset: both modes share the same volumes

**Decided:** both modes run as the compose project `expense-tracker` and use the same four volumes.
Switching mode is one command, and the data comes along.

**Alternative:** a separate project name for development, with its own volumes.

**Why:** one developer on one machine. The data's value is that it is the same data; a second copy
means signing up twice and wondering which one is on screen. Tests need no isolation from it —
Django's runner creates its own test database, and after issue 41 the test runner keeps test
uploads out of the media volume too.

**Reverse it if:** development experiments start damaging data worth keeping. Then
`COMPOSE_PROJECT_NAME` in the dev commands is a one-line change.

### D37. The container user takes the host user's UID and GID

**Decided:** the image creates its non-root user from the build arguments `APP_UID` and `APP_GID`,
fed from `HOST_UID` and `HOST_GID` in `.env`, which `make env` fills with `id -u` and `id -g`. The
default stays 1000. The user also owns `/app` itself, not just the files copied into it.

**Alternative:** phase 11's fixed UID 1000, whose `COPY --chown` changed the files but left `/app`
owned by root — the cause of issues 38 and 39.

**Why:** in development the container writes into your checkout — a migration from
`makemigrations`, a file `ruff --fix` rewrote. Those files belong to whoever the container runs as.
With a fixed 1000 on a machine where you are 1001, a migration Django just generated is not yours
to edit, and as root it needs sudo to delete. With matching IDs the container's writes cannot be
told apart from your own. The production-like image uses the same IDs so the two modes can share
the media volume (D36): what one writes, the other can overwrite.

**Reverse it if:** the image is built for a registry by CI/CD. Build it with the defaults; the
arguments default to exactly that.

### D38. Make is the front door; Compose stays the mechanism

**Decided:** a `Makefile` wraps the everyday operations. Each target is a thin `docker compose`
call, and `docs/DOCKER.md` shows the raw command next to every target.

**Alternatives:** shell scripts; raw Compose commands only.

**Why:** the development command is `docker compose -f compose.yaml -f compose.dev.yaml up -d
--build`. That is long enough to get wrong, and getting it wrong silently starts the other mode.
Make is on every Linux machine, gives `make help` for free, and needs nothing installed. The targets
stay thin on purpose so that Make does not become a second place where the stack is defined.

**Reverse it if:** targets start to grow logic. That logic belongs in Compose or in a management
command.

### D39. Only web builds the image, and local builds skip the default attestations

*Taken during verification, after D31–D38 were written.*

**Decided:** in both compose files only `web` has a `build`. Worker and beat name the image web
builds, with `pull_policy: never`. The Makefile exports `BUILDX_NO_DEFAULT_ATTESTATIONS=1`.

**Alternatives:** a `build` on all three services, which the phase 19 plan had; setting
`provenance: false` in the compose file.

**Why:** measured, not assumed. With the plan's layout, every `make up` recreated all three app
containers even when nothing had changed, and it had two causes. First, Compose writes the building
service's name into the image as a label, so three `build` sections produce three images that
differ only by that label, and the last one to finish takes the tag. Second, Docker 29's
containerd image store attaches a provenance attestation stamped with the build time, so even a
fully cached build gets a new image ID. Building once removes the first cause, and the variable
removes the second. `provenance: false` in the compose file was tried and did not make the ID
stable. `pull_policy: never` stops a first run from asking Docker Hub for an image that only
exists locally, which printed "not found" errors before web's build created it.

**Cost:** local images carry no provenance attestation, the record of how an image was built.
That record matters for images pulled from a registry, not for images that never leave the
machine. Raw `docker compose up --build`, without the variable, still works; it just recreates
the app containers each time.

**Reverse it if:** CI/CD starts building images for a registry. Build those with the default
attestations, or more.

---

## Session 27 — an API a remote frontend can be built on

The brief: the app is about to be hosted. A React developer — a fresher, practising — will build a
new UI against it from her own machine, and a mobile app or a public web portal may follow. So
**every action the Django pages offer must have an API endpoint**, and the API must be usable from
another origin and from a native app. The business-requirements document and the Postman
collection for that developer come in the next phase. This one makes the backend ready for them.

### D40. The API reaches parity with the Django pages, and the pages stay

**Decided:** every action on a Django page gets an endpoint under `/api/v1/`: account, categories,
people, expenses and their split, dashboard, balances and settling up, exports, and bill scans.
The Django pages are neither removed nor changed; they keep working beside the new UI.

**Alternative:** only the endpoints the first React screens need, added as the screens appear.

**Why:** a frontend developer building "from the document alone" needs the whole contract up
front, and a contract that grows screen by screen is one she has to keep asking about. Parity also
gives a simple test of done: walk the Django pages and find a matching endpoint for each action.
The domain code was already out of the views (`summaries.py`, `balances.py`, `settlements.py`,
`extraction/prefill.py`), so each endpoint is a thin wrapper.

**Reverse it if:** the new UI replaces the Django pages entirely. Then the pages can go, and the
API is already the whole product.

### D41. JWT bearer tokens alongside sessions

**Decided:** `djangorestframework-simplejwt`, with a short-lived access token, a refresh token
that rotates on use, and a blacklist so that logout and a password change really revoke access.
Session authentication stays, for the browsable API and any same-origin client.

**Alternatives:** sessions only, served from the same origin (the recommendation in session 26,
before the brief changed); DRF's built-in `TokenAuthentication`; `django-rest-knox`.

**Why:** the brief changed. The frontend will be developed on a different machine against the live
server, which makes it cross-origin, and a native app has no cookie jar worth relying on. Bearer
tokens work the same in both. DRF's own tokens never expire and allow one per user, so logging out
on a phone would log out the laptop. Knox is sound but little known. SimpleJWT is the standard a
MERN developer has already met. Rotation plus the blacklist closes JWT's usual weak spot, a
refresh token that cannot be taken back.

**Known trade:** a token kept in browser storage can be read by any script that XSS gets onto the
page, which an HttpOnly session cookie cannot. The frontend documentation (next phase) says where
to keep each token. Access tokens are short-lived so that a leak expires quickly.

**Reverse it if:** the only client is ever a same-origin web UI. Then sessions are simpler and
safer.

### D42. CORS by an explicit allow-list, API paths only, no credentials

**Decided:** `django-cors-headers`, with origins from `CORS_ALLOWED_ORIGINS` in the environment
(for example `http://localhost:5173` for a Vite dev server), applied only to `/api/`. Credentials
(cookies) are not allowed cross-origin.

**Why:** a wildcard would let any site script the API with a stolen token. Tokens travel in the
`Authorization` header, so cross-origin cookies are unnecessary. Not sending them also means
cross-origin requests need no CSRF token, and CSRF stays enforced for the session path.

### D43. The API contract is generated from the code

**Decided:** `drf-spectacular` publishes an OpenAPI 3 schema at `/api/schema/` and Swagger UI at
`/api/docs/`. Every custom endpoint declares its request and response serializers. A test fails if
generating the schema produces a warning. The next phase's Postman collection is generated from
this schema, not written by hand.

**Why:** hand-written API docs drift from the code on the first change after they are written. A
schema generated from the serializers is the code, and a warning-free test keeps it complete.

### D44. Every rule a Django page enforces is restated at the API

**Decided:** the API gains the rules it had skipped:

- Login is rate-limited with the web's limiter, and an unverified account gets a distinct refusal.
- A tax/tip amount needs a description and line items.
- If you are not on an expense, each of its line items must name who had it.
- Anyone a line item charges is added to the expense's participants.
- The self participant is marked `is_self`, and cannot be renamed or deleted (issue 34).
- A delete that the database protects returns 409 with a reason instead of a 500 (issue 44).

**Why:** the rule this project keeps relearning: a rule the database cannot hold must be restated
at every entry point. The API is about to become the main entry point. Adding line-item people to
the participants also prevents a cross-entry-point loss: the web edit form offers only an
expense's participants, so a share the API created outside them would be dropped the first time
someone saved that expense on the web (issue 45).

### D45. An email links back to the UI that asked for it

**Decided:** a new setting, `FRONTEND_URL`. Verification, password-reset and export-ready emails
triggered through the API link to `FRONTEND_URL` routes (`/verify-email/<uid>/<token>`,
`/reset-password/<uid>/<token>`, `/exports/<id>`), and the frontend completes the action through
the API. Emails triggered by the Django pages keep linking to the Django pages. Unset, everything
links to the Django pages, as before.

**Why:** a link to a page the person never used — or to an API URL a browser cannot authenticate
against — is a dead end.

### D46. API defaults that differ from the pages, on purpose

**Decided:**

- The expense list and balances cover all time unless `start`/`end` are given. The Django pages
  default to the current month.
- The dashboard summary and exports keep the current-month default.
- Throttle rates are environment settings, with the per-user default raised from 1000 to 3000
  requests an hour.
- The expense list returns `count` and `total_amount` for the whole filtered set, although phase
  10 had a test asserting that cursor pagination carries no count.

**Why:** a page has a sensible first view; an API should return what was asked for. Balances in
particular: settling up always settles the *all-time* outstanding amount, so a month-scoped "owes
you" beside a settle button would disagree with what the button does. A single-page app fires
several requests per screen and polls a scan's status, which 1000 an hour would throttle in
ordinary use. On the count: phase 10's reasoning was that a cursor cannot know the total without
the scan it exists to avoid, and that still holds for the paginator. But the Expenses page shows
the filtered total, and a client cannot add up pages it has not fetched. One aggregate over the
filtered set costs a single query per request, not one per row, and the query-count test pins it.
