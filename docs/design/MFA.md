# Multi-factor sign-in — design

> Written by the main session (session 31) before implementation; SECURITY_ROADMAP.md §3.


Authenticator-app codes (RFC 6238) after the password, with one-time recovery codes. Optional per
user; once a user turns it on, every way of signing in asks for it.

### Storage (accounts app)
- `TOTPDevice`: `user` (OneToOne, CASCADE), `secret` (base32, 32 chars), `confirmed` (bool),
  `last_used_step` (BigInteger, default 0), `created_at`, `confirmed_at` (null).
  An unconfirmed device does nothing; starting enrolment again replaces it.
- `RecoveryCode`: `user` (FK, CASCADE), `code_hash` (stored with `make_password`), `used_at` (null).
  Ten per set, each 10 characters from an unambiguous alphabet, shown exactly once. Generating a
  new set deletes the old one.
- A user "has MFA" when a confirmed device exists (one helper, `mfa_enabled(user)`).

### TOTP (`accounts/totp.py`, standard library only)
- HMAC-SHA1, 6 digits, 30-second steps, `secrets.token_bytes(20)` secret, base32 without padding.
- Verify accepts the current step and one either side; compare with `hmac.compare_digest`.
- **No replay:** a step at or before `device.last_used_step` is refused; on success store the
  matched step. Update it with a conditional UPDATE (`filter(last_used_step__lt=step)`), so two
  simultaneous requests with the same code cannot both succeed.
- `otpauth://totp/<issuer>:<username>?secret=...&issuer=...` URI; issuer from setting
  `MFA_ISSUER` (default "Expense Tracker").
- Recovery codes: accept with or without separators, case-insensitive; check against every unused
  code's hash; a match sets `used_at` (conditional update, same reason).

### The second step, shared by every way in
- After the password (or later, Google) is accepted for a user with MFA, **no session and no
  tokens are issued yet**. Instead an **MFA ticket**: `django.core.signing.dumps` with salt
  `"accounts.mfa-login"`, holding the user id and a hash of the current password hash (so a
  password change voids it), checked with `max_age` 300 seconds.
- Code attempts are limited **per account**: 5 failures per 15 minutes (`MFA_LIMIT`,
  `MFA_WINDOW` in `accounts/ratelimit.py`, keyed like the password-change limit — on the account
  only). A success clears it. Whoever holds a ticket already knows the password, so an account
  key cannot be used by a stranger to lock anyone out.
- Record `SecurityEvent`s: `mfa_challenge_passed`, `mfa_challenge_failed`, `mfa_enabled`,
  `mfa_disabled`, `recovery_code_used`, `recovery_codes_regenerated` (add them to the choices).

### API (accounts/api.py; new routes under `auth/`)
- `POST auth/login/`: unchanged for users without MFA. With MFA: `200`
  `{"mfa_required": true, "mfa_ticket": "..."}` and nothing else.
- `POST auth/mfa/verify/` `{mfa_ticket, code}` (TOTP or recovery code): on success the usual
  `issue_tokens()` body; bad or expired ticket `400 invalid_ticket`; wrong code `400` on `code`;
  over the limit `429 rate_limited`. Mark the view `@sensitive_variables()`.
- `GET auth/mfa/`: `{enabled, recovery_codes_left}`.
- `POST auth/mfa/setup/`: starts enrolment; returns `{secret, otpauth_uri}`. Refused (`400`) if
  already enabled.
- `POST auth/mfa/confirm/` `{code}`: confirms the pending device; returns
  `{recovery_codes: [...]}` once; revokes the user's other refresh tokens and returns a fresh pair.
- `POST auth/mfa/disable/` `{password, code}`: needs the current password **and** a current code
  or recovery code; deletes device and codes; revokes other refresh tokens.
- `POST auth/mfa/recovery-codes/` `{code}`: a new set, needs a current TOTP code.

### Web pages (accounts/views.py, templates in the existing style)
- Login: when the password is right and the user has MFA, do **not** call `login()`. Store the
  ticket in the session (cycle the session key), and redirect to `accounts:login_mfa`, keeping a
  safe `next` (validate with `url_has_allowed_host_and_scheme`, as LoginView does).
- `accounts:login_mfa`: a code form; on success `login(request, user, backend=...)` and redirect
  to the safe `next`.
- Account page gains "Two-step sign-in": set up (show the QR code, the secret for manual entry,
  and a code box), then the recovery codes once; disable (password + code); new recovery codes.
- QR code: an inline SVG built server-side with `segno` (pure Python, no dependencies; pin it).
  Inline SVG needs no CSP change.

### The admin site
- Its own login form would skip the second step. Replace `throttled_admin_login` so the admin
  login simply redirects to the site's login (`accounts:login?next=<admin index>`). Staff then
  reach the admin with the session the site login created, MFA included. Update the pass-1 admin
  tests to match (the admin login now redirects; the limit is the site login's).

### Changing the settings is limited too (added in review)
- Disabling and new recovery codes go through `mfa.check_for_change`: wrong passwords count
  against the per-account password-change limit, wrong codes against `MFA_LIMIT`, on the web and
  the API alike. Both actions are reachable from a signed-in session alone, which is what a
  stolen session gives; unlimited, it could guess its way to turning two-step sign-in off.
- A ticket stops working if the account is deactivated between the two steps.

### Sessions and tokens
- Enabling or disabling MFA revokes the user's other refresh tokens (`revoke_refresh_tokens`),
  then issues a fresh pair for this client (API) or keeps this session (web).
- Known limitation, to document: other *web sessions* stay signed in until they expire, because
  Django ties sessions only to the password hash.

### Documentation
- `docs/frontend/API_GUIDE.md`: the two-step login, the enrolment flow, error codes.
- `docs/frontend/BRD.md`: business rules and the screens the React app needs (login code step,
  enrol with QR, recovery codes shown once, disable).
- Regenerate with `python manage.py build_api_docs`, and add the second step to the journey in
  `expenses/api/journey.py` if the recorded journey covers login.

### Tests (`accounts/tests/test_mfa.py`)
- TOTP against the RFC 6238 test vectors; window ±1; a reused step is refused; the conditional
  update refuses a double use.
- API: login without MFA unchanged; with MFA returns only a ticket; verify with TOTP and with a
  recovery code (which then cannot be reused); expired, tampered and pre-password-change tickets
  refused; the per-account limit; setup/confirm/disable/regenerate, including disable needing
  both password and code.
- Web: the login stops at the code page with no session user; a correct code signs in and honours
  a safe `next`, refuses an off-site one; the admin login redirects to the site login.
- Events recorded; nothing secret in them.
