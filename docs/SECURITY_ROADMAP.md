# Security roadmap — towards OWASP ASVS Level 2

> Started in session 31, after security passes 1–6 and the whole-branch review. This is the plan of
> action from here. Tick items as they land, and record each one in `BUILD_LOG.md` as usual.

## Where we stand

OWASP ASVS (Application Security Verification Standard) grades an application in three levels:

| Level | For | In short |
|---|---|---|
| L1 — Opportunistic | Every internet-facing app | Resists common, automated attacks |
| L2 — Standard | Apps holding personal or business data (most real apps) | Verified from the source: access control, sessions, logging, errors, usually multi-factor sign-in |
| L3 — Advanced | Banking, healthcare, critical systems | L2, plus threat modelling, formal architecture review, key management |

**Today: L1 essentially met, L2 substantially covered, neither formally verified.** Passes 1–6
(`docs/HANDOVER.md` §3) map closely onto L2's access-control, session, logging, error-handling,
upload and input chapters. What stands between us and an honest L2 claim is below.

## The plan, in order

### 1. Claim L1 formally
- [x] (Session 32: 70/70 Met or N/A, `docs/ASVS_L1.md`; V3.4.1 needs the one-year HSTS on the live
      server, a hosting-checklist step.) Walk the ASVS Level 1 requirements one by one. For each: met (with the file, test or
      setting as evidence), not applicable (why), or a gap (added below). Keep the result in
      `docs/ASVS_L1.md`.
      Done, against ASVS 5.0.0 (`docs/ASVS_L1.md`): 54 Met, 14 N/A, 2 Gap out of 70 Level 1
      requirements. One requirement found unmet during the walk (V3.3.1, cookie name prefix) was
      fixed in the same session, with a test. The two remaining gaps (V3.4.1's HSTS default,
      V15.1.1/V15.2.1's missing remediation-SLA doc, since closed) are below in §2 -- both are judgement calls,
      not code fixes, so **this box stays unticked** until a human decision closes them.

### 2. Close what we already know about
- [x] **Unverified accounts squat addresses.** A sign-up creates an inactive account, and sign-up
      then refuses that email and username. Nothing removes an account that never verifies, and
      password reset ignores inactive accounts, so an address's real owner can be locked out of
      registering. Fix: purge accounts left unverified after N days (a beat task, like
      `purge_exports`), and let a fresh sign-up for an address replace an unverified account for it.
      Done: `User.email_verified_at`, `SignUpForm`/`SignupSerializer` treat an email or username
      held only by an unverified account as available and delete it on a successful sign-up
      (`accounts/forms.py`), and `purge_unverified` (setting `UNVERIFIED_ACCOUNT_DAYS`) runs daily
      via beat.
- [ ] **Per-account login cap — decide.** Logins are limited per address and username, and per
      address. Guesses at one account spread across many addresses meet only the per-address cap.
      A per-account cap closes that but lets a stranger lock the owner out. Decide, and record the
      decision in `DECISIONS.md`.
- [ ] **Minor:** send CORS headers on the early 413 (so the React app sees "too large", not a
      network error); pin the Swagger UI version instead of `swagger-ui-dist@latest`.
- [ ] **ASVS V3.4.1 -- HSTS `max-age` default is 1 hour, not the required ≥1 year.**
      `config/settings.py`'s `SECURE_HSTS_SECONDS` defaults to `3600` on purpose (`DECISIONS.md`
      D5: start low, ramp up once HTTPS is known stable everywhere, because a wrong value with
      preload is close to irreversible). Decide whether the real deployment's HTTPS is stable
      enough to raise the *default* to `31536000` (a year), or whether to leave the default as-is
      and simply document that a production `.env` must set `SECURE_HSTS_SECONDS=31536000`
      itself. Either way, record the decision in `DECISIONS.md`. See `docs/ASVS_L1.md`'s "Gaps
      left".
- [x] **ASVS V15.1.1 / V15.2.1 -- no documented remediation-time-frame policy for vulnerable
      dependencies.** `pip-audit` is already run before each deploy (`HANDOVER.md` §4), but no doc
      states an actual SLA (e.g. "critical within N days, high within N days"). Pick the numbers
      and write them down -- `docs/DECISIONS.md` or a new short section of this file is the
      natural place. See `docs/ASVS_L1.md`'s "Gaps left". **Done in session 32:** `SECURITY.md`
      (7/14/30/90 days by severity) and `.github/dependabot.yml`.

### 3. The L2 gaps
- [x] **Multi-factor sign-in (TOTP).** An authenticator-app code after the password, with
      one-time recovery codes. Web pages and API both; the React app needs enrol, challenge and
      recovery screens. The biggest item here.
      Done: `accounts.TOTPDevice`/`RecoveryCode` (`accounts/models.py`), the TOTP math in
      `accounts/totp.py`, the signed login ticket and shared code check in `accounts/mfa.py`,
      the `auth/mfa/*` API endpoints and web pages, and the admin login redirecting to the site
      login so it gets the same second step. See `docs/design/MFA.md`.
- [x] **Breached-password check.** Django's `CommonPasswordValidator` rejects common passwords but
      not known-leaked ones. Add a validator using the Have I Been Pwned range API (k-anonymity: only
      the first five characters of the password's SHA-1 leave the server), failing open if the
      service is unreachable.
      Done: `accounts/password_validation.py`'s `PwnedPasswordValidator`, setting
      `PWNED_PASSWORDS_ENABLED` (off in tests, `config/test_runner.py`).
- [x] **A security event trail.** One structured log (or table) of: sign-ins and failures, password
      changes and resets, token revocations, verification, account deletion, admin changes — each
      with user, time, address and request id. Today only failed logins are logged.
      Done: `accounts.SecurityEvent` + `accounts/audit.py`, wired into the web pages, the API and
      the admin login; retention via `purge_security_events`
      (setting `SECURITY_EVENT_RETENTION_DAYS`).

### 4. Features that touch security

- [x] **Sign in with Google.** Design notes below. `POST /api/v1/auth/google/` and the login/
      sign-up pages' button (callback mode); verified with `google-auth`, linked by email with
      the three cases the design lists, multi-factor sign-in still applies through the same
      ticket as a password login. `accounts/google.py`, `accounts/tests/test_google_login.py`.
- [ ] **Optional: a 6-digit emailed code** as an alternative to the verification link, which suits a
      mobile app better. Same signed, expiring, single-use rules as the link.

## Design notes: Sign in with Google

The full designs: [design/MFA.md](design/MFA.md) and [design/GOOGLE_SIGNIN.md](design/GOOGLE_SIGNIN.md).

It fits the current architecture without changing anything that exists.

- **API / React (the main path).** The React app shows Google's own button (Google Identity
  Services) and receives a signed **ID token** from Google. It posts that to a new endpoint,
  `POST /api/v1/auth/google/`. The server verifies the token's signature, audience (our client id)
  and expiry with Google's `google-auth` library, then finds or creates the user and returns our own
  token pair through the existing `issue_tokens()`. From there, everything — refresh, logout,
  revocation, rate limits — works exactly as it does now.
- **Web pages.** The same button on the login page, posting to a matching Django view that signs
  the user in with a session. (`django-allauth` is the alternative if many providers are wanted
  later; for Google alone, one endpoint is less to maintain.)
- **Rules that keep it safe:**
  - Link to an existing account by email **only if Google says `email_verified`**; otherwise a
    stranger's Google account could claim someone's account here.
  - A Google-created account is active at once (Google has verified the address) and has an
    unusable password; "set a password" then goes through password reset.
  - The endpoint is rate-limited like login, and the ID token is marked sensitive in error reports.
  - The CSP gains Google's sign-in hosts (`accounts.google.com`) on the pages that show the button.
- **Needs from you:** a Google Cloud project with an OAuth client id (free), the site's real
  domains added as authorised origins, and HTTPS in production (localhost is allowed for
  development).
- **Bonus for L2:** users who sign in with Google get Google's own multi-factor protection. It does
  not replace MFA for password accounts.
