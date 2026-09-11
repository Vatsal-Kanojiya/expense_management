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
