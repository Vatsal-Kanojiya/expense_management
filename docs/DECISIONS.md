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
