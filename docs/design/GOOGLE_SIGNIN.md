# Sign in with Google — design

> Written by the main session (session 31) before implementation; SECURITY_ROADMAP.md §4.


Off unless `GOOGLE_OAUTH_CLIENT_ID` is set (env, default empty): then the endpoints answer 404 and
the web button is not shown.

### Verifying Google's ID token (`accounts/google.py`)
- `google.oauth2.id_token.verify_oauth2_token(token, google.auth.transport.requests.Request(),
  audience=settings.GOOGLE_OAUTH_CLIENT_ID)`. This checks the signature against Google's keys,
  the audience and expiry. Also require `iss` in (`accounts.google.com`,
  `https://accounts.google.com`) and **`email_verified` is true**; otherwise refuse.
- Any failure → one generic refusal ("Google sign-in failed"), logged without the token.
- Pin `google-auth` (installed today only as a dependency of another package).

### Finding or creating the user (one function, used by the API and the web page)
- Match an existing account by email, case-insensitively.
  - Active account: sign in as it.
  - Unverified account (`is_active=False`, `email_verified_at` null): Google has just proved the
    address, so activate it and set `email_verified_at`.
  - Deactivated, verified account (`is_active=False`, `email_verified_at` set): refuse, as a
    password login would.
- No match: create the user through the **same path as sign-up** (whatever sign-up does after
  creating the user — e.g. the "self" participant — must happen here too), active at once, with
  `email_verified_at` set and `set_unusable_password()`. Username from the email's local part,
  cleaned to what Django usernames allow, with a numeric suffix if taken.
- Record `SecurityEvent`s: `google_login_succeeded`, `google_login_failed`, `signed_up` (with
  `detail={"via": "google"}` for a new account).

### Multi-factor still applies
- If the user has MFA enabled, Google sign-in stops at the same second step as a password login:
  the API returns `{"mfa_required": true, "mfa_ticket": ...}`, the web page redirects to the code
  page. Build the ticket so it does not depend on having a usable password (a hash of the stored
  password field still works: an unusable password is a stored value too).

### API
- `POST auth/google/` `{credential}` → the usual `issue_tokens()` body, or the MFA ticket.
  `400` with code `google_failed` on refusal; rate-limited like the login's per-address cap
  (`login-ip`), `429 rate_limited`. `@sensitive_variables()`.

### Web pages
- Login and sign-up pages: Google's button via Google Identity Services, in **callback mode**, not
  redirect mode, so the credential comes back to our own page and is posted with our CSRF token.
  - The loader `https://accounts.google.com/gsi/client` plus a small static file
    (`static/js/google-signin.js`) that receives the credential and POSTs it to a new view
    `accounts:google_login` with the CSRF header, then follows the redirect it returns. No inline
    script: the CSP stays as it is apart from the additions below.
  - The client id reaches the page through a `data-` attribute, not inline script.
- `accounts:google_login` (POST only): verify, find or create, then `login()` or the MFA step;
  honour a safe `next`.
- CSP: on the login and sign-up pages only, allow Google's hosts: `script-src
  https://accounts.google.com/gsi/client`, `frame-src https://accounts.google.com/gsi/`,
  `connect-src https://accounts.google.com/gsi/`, `style-src https://accounts.google.com/gsi/style`.
  Keep the default policy everywhere else, as the Swagger page's own policy is done now.

### Accounts without a usable password
- Password change: they have no current password to give. Show "Set a password" instead,
  pointing to password reset (which works for them, as they are active with an email).
- API `auth/me/` gains `has_password` (bool) so the React app can do the same.

### Documentation
- `.env.example` and `docs/HANDOVER.md` §4: `GOOGLE_OAUTH_CLIENT_ID`, and how to get one (Google
  Cloud console → OAuth client, type "Web application", authorised JavaScript origins = the site's
  and the React app's origins).
- `docs/frontend/API_GUIDE.md` and `BRD.md`: the endpoint, the React flow (Google's button →
  credential → `auth/google/`), MFA interplay, `has_password`.
- Regenerate with `python manage.py build_api_docs`.

### Tests (`accounts/tests/test_google_login.py`, never calling Google: mock `verify_oauth2_token`)
- Off when unconfigured (404, no button).
- New user created active, unusable password, same side effects as sign-up.
- Existing active user by email (case-insensitive); unverified account activated; deactivated
  verified account refused; `email_verified` false refused; bad `iss` refused; verifier raising →
  refused, token not logged.
- MFA user gets the ticket, not tokens (API) / the code page (web).
- Rate limit; events; the CSP on the login page includes Google's hosts and other pages don't;
  password change for a Google-only user points to reset; `has_password` in `auth/me/`.
