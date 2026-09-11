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
