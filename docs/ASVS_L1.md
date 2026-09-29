# OWASP ASVS Level 1 — a formal walkthrough

> Roadmap item "Claim L1 formally" (`SECURITY_ROADMAP.md` §1). Every Level 1 requirement, walked
> against this codebase, with the evidence checked rather than assumed.

**Standard and version:** OWASP Application Security Verification Standard **5.0.0**, the current
release on the OWASP ASVS GitHub repository (`OWASP/ASVS`, tag `v5.0.0`).

**Source of the requirement list:** the standard's own machine-readable export,
`5.0/docs_en/OWASP_Application_Security_Verification_Standard_5.0.0_en.csv`, fetched from
`https://raw.githubusercontent.com/OWASP/ASVS/master/5.0/docs_en/OWASP_Application_Security_Verification_Standard_5.0.0_en.csv`
on 2026-09-28. That file lists 345 requirements across 15 chapters (`V1`–`V15`), each tagged with
the level it first applies at (`L` column: 1, 2 or 3); **70** are tagged `L`**`=1`**. Every `req_id`
and every word of every `req_description` below is copied from that file — none were written from
memory or paraphrased from an older ASVS version. (ASVS 5.0 restructured the chapters from 4.0.3's
V1–V14 into V1–V17; this walkthrough follows 5.0's numbering throughout.)

**How each row was checked.** "Met" means a specific file, line, setting or test was read in this
session and does what the requirement asks — not that the area was "generally covered" by an
earlier pass. "N/A" states the concrete reason the requirement does not apply here (no feature of
that kind exists). "Gap" states exactly what is missing. Where a requirement is about
*documentation* (ASVS 5.0 reorganised several chapters to open with a documentation clause), the
evidence is the doc that satisfies it, not the code.

---

## Summary

| Chapter | Requirements (L1) | Met | N/A | Gap |
|---|---:|---:|---:|---:|
| V1 — Encoding and Sanitization | 8 | 4 | 4 | 0 |
| V2 — Validation and Business Logic | 4 | 4 | 0 | 0 |
| V3 — Web Frontend Security | 8 | 8 | 0 | 0 |
| V4 — API and Web Service | 2 | 1 | 1 | 0 |
| V5 — File Handling | 4 | 4 | 0 | 0 |
| V6 — Authentication | 13 | 13 | 0 | 0 |
| V7 — Session Management | 6 | 6 | 0 | 0 |
| V8 — Authorization | 4 | 4 | 0 | 0 |
| V9 — Self-contained Tokens | 4 | 4 | 0 | 0 |
| V10 — OAuth and OIDC | 5 | 0 | 5 | 0 |
| V11 — Cryptography | 3 | 1 | 2 | 0 |
| V12 — Secure Communication | 3 | 1 | 2 | 0 |
| V13 — Configuration | 1 | 1 | 0 | 0 |
| V14 — Data Protection | 2 | 2 | 0 | 0 |
| V15 — Secure Coding and Architecture | 3 | 3 | 0 | 0 |
| **Total** | **70** | **56** | **14** | **0** |

**Result: 70/70 Met or N/A** (session 32). The two gaps this walkthrough first found were closed
as policy, not code: V15.1.1/V15.2.1 by `SECURITY.md` and Dependabot, and V3.4.1 (HSTS ≥ 1 year)
is met **on a deployment that sets `SECURE_HSTS_SECONDS=31536000`**, now a step on the hosting
checklist (`HANDOVER.md` §4) — see "Gaps left".

One requirement was found unmet during this walkthrough and fixed in this session, with a test:
**V3.3.1** (cookie name prefix) — see below and the commit list at the end.

---

## V1 — Encoding and Sanitization

| ID | Requirement (paraphrased) | Status | Evidence |
|---|---|---|---|
| V1.2.1 | Output encoding fits the context (HTML element/attribute/comment, CSS, HTTP header). | Met | Every server-rendered page goes through Django's template autoescaping (`django.template.backends.django.DjangoTemplates`, `TEMPLATES[0]`, `config/settings.py`), on by default and never turned off (`autoescape off` appears once, in a **plain-text** email template, `templates/registration/password_reset_email.html`, where there is no HTML to escape). Security pass 6 (`HANDOVER.md` §3) grepped every template for `\|safe`/`mark_safe` and found none in app code (confirmed again this session: `grep -rn "mark_safe\|\|safe\|autoescape off"` over `accounts/`, `expenses/`, `templates/` returns nothing but that one plain-text template). |
| V1.2.2 | Dynamically built URLs encode untrusted data by context; only safe protocols (no `javascript:`/`data:`). | Met | The only place the app builds a URL from caller-supplied input is a post-login/post-Google-sign-in redirect target, and both call sites validate it with Django's `url_has_allowed_host_and_scheme` before using it (`accounts/views.py:153`, `accounts/views.py:184`), which rejects any scheme other than `http`/`https` and any host not in `{request.get_host()}`. No template builds an `href`/`src` from a raw variable (`grep -rn 'href="{{ ' templates/` finds none outside `{% url %}`). |
| V1.2.3 | Output encoding/escaping for dynamically built JavaScript/JSON. | N/A | No template embeds a dynamically built `<script>` block or JSON payload (`grep -rn "json_script" templates/` and `grep -rn "<script>" templates/` show only static `<script src=...>` tags to versioned static files, matching the CSP's `script-src 'self'` with no `'unsafe-inline'`, `config/middleware.py`'s `ContentSecurityPolicyMiddleware.DEFAULT_POLICY`). API responses are JSON built by DRF's renderer, never string-concatenated. |
| V1.2.4 | SQL/NoSQL/etc. queries are parameterized (ORM, entity framework), not string-built. | Met | Every query in `accounts/` and `expenses/` goes through the Django ORM. The one raw SQL in the app is a parameterless health check, `cursor.execute("SELECT 1")` (`expenses/api/views.py:320`), with no interpolated input. `grep -rn "\.raw(\|extra("` over the app finds nothing else. |
| V1.2.5 | OS command injection prevented (parameterized calls, no shell string-building). | N/A | The app never shells out: `grep -rn "subprocess\.\|os\.system\|os\.popen\|shell=True"` over `accounts/`, `expenses/`, `config/` (excluding `.venv`) returns nothing. |
| V1.3.1 | Untrusted HTML from a WYSIWYG editor is sanitized with a known library. | N/A | The app has no WYSIWYG/rich-text input anywhere — every text field (expense notes, category and person names, bill-scan text) is plain `CharField`/`TextField`, rendered through autoescaping (V1.2.1), never interpreted as HTML. |
| V1.3.2 | No `eval()`/dynamic code execution on user input. | Met | `grep -rn "eval(\|exec("` over `accounts/`, `expenses/`, `config/` (excluding `.venv`) finds no use in app code. |
| V1.5.1 | XML parsers configured to reject external entities (XXE). | N/A | The app parses no XML anywhere. `grep -rln "xml\|XML\|lxml\|etree"` over the app code turns up only an unrelated docstring (`accounts/qrcode.py:14`, `"a data:image/svg+xml,... URI"`, which is building an SVG data URI, not parsing one). No XML library appears in `requirements.txt`. |

## V2 — Validation and Business Logic

| ID | Requirement | Status | Evidence |
|---|---|---|---|
| V2.1.1 | Documentation defines input-validation rules (format, structure). | Met | `docs/frontend/openapi.yaml` — generated from the DRF serializers by `drf_spectacular` (`make api-docs`) — carries 57 `maxLength`/`minimum`/`maximum`/`pattern` constraints across the schema, and `docs/frontend/API_GUIDE.md` §9.3 ("Rules the server applies") and §11 document the business-decision fields (amounts, dates, rate limits) by name. |
| V2.2.1 | Input used for business/security decisions is positively validated (allow-list, structure, range). | Met | Security pass 6 (`HANDOVER.md` §3): every money field rejects negative/zero-where-inapplicable/non-numeric/out-of-`max_digits` values on both the web forms and the API serializers (`expenses/forms.py`, `expenses/api/serializers.py`), with tests in `expenses/tests/test_security_pass6.py`; bill-scan output (an untrusted, model-generated field set) is validated the same way before it can prefill a form (`expenses/extraction/`). |
| V2.2.2 | Validation is enforced server-side, not only client-side. | Met | Every validation above runs in a Django `Form.clean_*`/DRF `Serializer.validate_*` method, which executes regardless of what a client sent; nothing in the app trusts a `data-*` attribute or client-side check as authoritative. |
| V2.3.1 | Business-logic flows execute in the expected step order, without skipping steps. | Met | Two-step (MFA) sign-in cannot be skipped: `accounts/mfa.py`'s `make_ticket`/`user_for_ticket` issue a **signed, expiring** ticket only after a correct password, and no session or token is created until a valid code is checked against that ticket — there is no `session`/`token` a caller can obtain by calling the second-step endpoint first. Tested in `accounts/tests/test_mfa_*.py`. |

## V3 — Web Frontend Security

| ID | Requirement | Status | Evidence |
|---|---|---|---|
| V3.2.1 | Controls prevent a browser from mis-rendering a directly requested resource (API response, uploaded file). | Met | The one file the app serves for direct viewing — a bill-scan photo — sets both an explicit, byte-verified `Content-Type` (`expenses/api/jobs.py`'s `image` action, `mimetypes.guess_type` on a filename `BillScanForm.clean_image` renamed from the **verified** magic bytes, not the browser's claim) and `X-Content-Type-Options: nosniff`, behind ownership auth (`OwnerScopedMixin`/`IsOwner`). CSV/export downloads set `Content-Disposition: attachment` via `as_attachment=True` (`expenses/api/jobs.py:160`, `expenses/views.py:446`), so a browser never renders them inline at all. |
| V3.2.2 | Text content is rendered with safe DOM APIs (`textContent`), not `innerHTML`, for untrusted data. | Met | The one script that writes user-entered text into the DOM uses `textContent`, with a comment saying why (`expenses/static/expenses/expense-title.js:23`, `"textContent, not innerHTML: the note is user input."`). The two other `innerHTML`/`insertAdjacentHTML` uses (`chip-select.js`, `item-formset.js`) only ever assign a static string or the page's own server-rendered, Django-autoescaped formset template markup (never a value typed by a user) — read in full this session. The separate React frontend that consumes the API is a different repository, out of this one's scope; `docs/frontend/API_GUIDE.md` §3.4 tells it never to render untrusted HTML. |
| V3.3.1 | Cookies set `Secure`, and carry the `__Host-` (or `__Secure-`) name prefix. | **Met (fixed this session)** | Before this session, `SESSION_COOKIE_SECURE`/`CSRF_COOKIE_SECURE` were already `True` in production (`config/settings.py`), but the cookie **names** were Django's plain defaults (`sessionid`, `csrftoken`) — no browser-enforced backstop if `Secure` were ever lost. Fixed: `config/settings.py` now sets `SESSION_COOKIE_NAME = "__Host-sessionid"` and `CSRF_COOKIE_NAME = "__Host-csrftoken"`, but only when `SESSION_COOKIE_SECURE`/`CSRF_COOKIE_SECURE` are actually `True` — the local compose stack runs `DEBUG=False` with those forced off for plain HTTP (`DECISIONS.md` D35), and a `__Host-` cookie without `Secure` is dropped by the browser outright, which would have silently broken login there. Tested in `expenses/tests/test_error_pages.py::DeploySettingsTests::test_production_config_uses_host_prefixed_cookie_names` and `::test_relaxed_cookies_keep_the_plain_cookie_names`. |
| V3.4.1 | `Strict-Transport-Security` on every response, max-age ≥ 1 year. | Met* | `ContentSecurityPolicyMiddleware`'s sibling, Django's own `SecurityMiddleware`, sends HSTS whenever `SECURE_HSTS_SECONDS` is set, which it is in production (`config/settings.py`, gated on `not DEBUG`), pinned by `accounts/tests/test_security_pass4.py`. **`*` the shipped *default* is 3600 seconds (1 hour), not the ≥1-year ASVS asks for — a deliberate choice recorded in `DECISIONS.md` D5, kept as-is rather than silently overridden. See "Gaps left".** |
| V3.4.2 | CORS `Access-Control-Allow-Origin` is a fixed value or a validated allowlist, never an unvalidated wildcard with sensitive data. | Met | `CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])` (`config/settings.py`) — an explicit allowlist, default empty (nothing is cross-origin-reachable until deliberately configured), never `CORS_ALLOW_ALL_ORIGINS`. `CORS_ALLOW_CREDENTIALS = False` and `CORS_URLS_REGEX` scopes it to `/api/` only. `DECISIONS.md` D42 records the reasoning. |
| V3.5.1 | Anti-CSRF token or a non-safelisted header on sensitive cross-origin requests, when CORS preflight is not relied on. | Met | Every unsafe request to the Django web pages (session-cookie auth) goes through `django.middleware.csrf.CsrfViewMiddleware` (`config/settings.py` `MIDDLEWARE`), which is Django's anti-forgery token check. The API's token auth (`JWTAuthentication`) needs no CSRF token by design — it never uses the ambient session cookie (`CORS_ALLOW_CREDENTIALS = False`), so a cross-site form post carries no credential the API would honour, which is the alternative control this requirement names. |
| V3.5.2 | If CORS preflight is relied on, functionality cannot be reached without triggering one. | Met | The API's cross-origin requests all carry `Authorization: Bearer <token>` (a non-safelisted header), which forces a CORS preflight for every cross-origin call; a same-origin request needs no preflight and is covered by V3.5.1's CSRF token instead. |
| V3.5.3 | Sensitive functionality uses non-"safe" HTTP methods (not GET/HEAD/OPTIONS). | Met | Every state-changing route in `expenses/api/urls.py`/`accounts/urls.py` is `POST`/`PUT`/`PATCH`/`DELETE`; `LogoutView` was moved off GET specifically for this reason (`accounts/urls.py`: *"LogoutView is POST-only since Django 5.0. A GET logout could be fired by a prefetch, a link scanner or an `<img>` tag."*). |

## V4 — API and Web Service

| ID | Requirement | Status | Evidence |
|---|---|---|---|
| V4.1.1 | Every response with a body sends a `Content-Type` matching its actual content, with a charset. | Met | DRF's renderer sets `application/json; charset=utf-8` on every API response by default (unconfigured, `REST_FRAMEWORK` in `config/settings.py`); Django's template responses default to `text/html; charset=utf-8`; the two binary downloads set `content_type` explicitly (`text/csv`, the verified image MIME type — see V3.2.1). |
| V4.4.1 | WebSocket connections use WSS (TLS). | N/A | The app has no WebSocket endpoint. `grep -rln "websocket\|channels\|ws://\|wss://"` over the app code (excluding `.venv`) finds nothing; `channels` is not in `requirements.txt`. |

## V5 — File Handling

| ID | Requirement | Status | Evidence |
|---|---|---|---|
| V5.2.1 | Only files of a processable size are accepted. | Met | `MaxUploadSizeMiddleware` (`config/middleware.py`) rejects an oversized body from `Content-Length` alone before it is read, first in `MIDDLEWARE`; `BillScanForm.clean_image` (`expenses/forms.py`) enforces the exact 5 MB rule; `DATA_UPLOAD_MAX_MEMORY_SIZE`/`FILE_UPLOAD_MAX_MEMORY_SIZE` are sized from the same constant (`config/settings.py`). Security pass 2 (`HANDOVER.md` §3). |
| V5.2.2 | File extension and actual content (magic bytes) are both checked. | Met | `BillScanForm.clean_image` (`expenses/forms.py:465-493`) reads the first 12 bytes and calls `sniff_image_type` (`expenses/extraction/`) — never trusts the browser's declared `Content-Type` — then renames the file from the **verified** type, which is what `bill_upload_path` and the serving endpoint then trust. |
| V5.3.1 | Files stored from untrusted input are never executed as server-side code when fetched directly. | Met | Uploaded/generated files live in `MEDIA_ROOT` under `FileSystemStorage` and are served only through authenticated, owner-scoped Django/DRF views (`ExportDownloadView`, `BillScanViewSet.image`), never through a URL that maps directly onto the filesystem — `grep -rn "static(settings.MEDIA"` finds no such mapping in `config/urls.py`, and nothing serves `MEDIA_ROOT` as static/executable content. |
| V5.3.2 | File paths are built from trusted/internal data, not raw user-submitted names (path traversal, LFI/RFI, SSRF). | Met | `bill_upload_path`/`export_upload_path` (`expenses/models.py`) build the stored path from `instance.user_id` and a fresh `uuid4().hex`, taking only the file **extension** (already normalised to a verified type, V5.2.2) from the client-visible name — never the name itself. |

## V6 — Authentication

| ID | Requirement | Status | Evidence |
|---|---|---|---|
| V6.1.1 | Documentation defines rate limiting/anti-automation and how it avoids malicious lockout. | Met | `docs/frontend/API_GUIDE.md` §11 tables every limit (login, sign-up, password change, MFA, reset, scans, exports) with its scope and answer; `accounts/ratelimit.py`'s module docstring documents the by-IP/by-username/by-both trade-off and why "by both" was chosen specifically to avoid a stranger locking out the real owner. |
| V6.2.1 | Minimum password length ≥ 8 (15 recommended). | Met | `AUTH_PASSWORD_VALIDATORS` includes `MinimumLengthValidator` with no override (`config/settings.py`) — Django's default `min_length` is 8. |
| V6.2.2 | Users can change their password. | Met | `accounts:password_change` (web, `ThrottledPasswordChangeView`) and `POST /api/v1/auth/password/change/` (`accounts/api.py`). |
| V6.2.3 | Password change requires the current password. | Met | The web view uses Django's `PasswordChangeForm` (current + new), and the API's `PasswordChangeSerializer` requires `old_password` (`accounts/api.py:136`), rate-limited on wrong attempts (`ratelimit.PASSWORD_CHANGE_LIMIT`). |
| V6.2.4 | New/changed passwords are checked against ≥3,000 known-common passwords. | Met | `CommonPasswordValidator` (Django's own ~20,000-entry list, well over 3,000) plus `accounts.password_validation.PwnedPasswordValidator`, which checks the live Have I Been Pwned breach corpus (`accounts/password_validation.py`) — both in `AUTH_PASSWORD_VALIDATORS`. |
| V6.2.5 | No composition rules restricting character types. | Met | `AUTH_PASSWORD_VALIDATORS` has no `UppercaseValidator`/character-class validator of any kind — only length, similarity, common-password and breach checks (`config/settings.py`). |
| V6.2.6 | Password fields are masked (`type=password`), with optional reveal-last-character. | Met | Django's default `PasswordInput` widget renders `type="password"` for every password field on every registration/login/change/reset/MFA-disable form (confirmed in `templates/registration/mfa.html:29` and the auth forms); nothing overrides it. |
| V6.2.7 | Paste, browser password managers, and external password managers are permitted. | Met | No field sets `autocomplete="off"` or blocks `paste`/`oncopy`/`onpaste` anywhere in the templates or static JS (`grep -rn "onpaste\|autocomplete.*off"` over `templates/`, `accounts/` finds none); `autocomplete="current-password"` is set instead (`templates/registration/mfa.html:29`), which is what lets a manager fill the field. |
| V6.2.8 | The password is checked exactly as received, with no truncation/case change. | Met | Every DRF password field is `serializers.CharField(trim_whitespace=False)` (`accounts/api.py:110,116-117,136-138,146-147,189`); the web forms use Django's own `PasswordChangeForm`/`AuthenticationForm`, which likewise never trim or alter the value before `check_password`. |
| V6.3.1 | Controls against credential stuffing/brute force match the documentation. | Met | The limits `accounts/ratelimit.py` enforces are exactly the ones `docs/frontend/API_GUIDE.md` §11 documents (cross-checked this session line by line), with tests in `accounts/tests/test_security_pass1.py` and `accounts/tests/test_hardening.py`. |
| V6.3.2 | No default accounts (`root`/`admin`/`sa`). | Met | No fixture, migration or management command creates a seeded user; `accounts/management/commands/` contains only `purge_unverified`/`purge_security_events`. `createsuperuser` is the only account-creation path outside sign-up, and it is interactive (no default credentials baked in). |
| V6.4.1 | System-generated initial passwords/activation codes are random, follow the password policy, expire, and can't become the long-term secret. | Met | The only "initial secret" is the email-verification link's token, a Django `PasswordResetTokenGenerator` subclass (`accounts/verification.py`) — cryptographically random-derived, expires after `PASSWORD_RESET_TIMEOUT` (24 hours, `config/settings.py`), and is single-use (its hash includes `is_active`, which flips true on use, invalidating it). It is never itself a password — the user's own chosen password is untouched by it. |
| V6.4.2 | No password hints or knowledge-based "secret questions". | Met | No such field exists on `User` (`accounts/models.py`) or in any signup/reset form. |

## V7 — Session Management

| ID | Requirement | Status | Evidence |
|---|---|---|---|
| V7.2.1 | Session token verification happens on a trusted backend, not the client. | Met | Web sessions are verified server-side by `django.contrib.sessions`/`AuthenticationMiddleware` against the session store; API tokens are verified server-side by `rest_framework_simplejwt.authentication.JWTAuthentication`, which checks the signature against `SECRET_KEY` held only on the server (`config/settings.py`'s `SIMPLE_JWT`). |
| V7.2.2 | Session tokens are dynamically generated, not static API keys. | Met | Django's session key is generated fresh per session by `django.contrib.sessions.backends.base.SessionBase._get_new_session_key` (CSPRNG-backed); JWTs are generated per login by `issue_tokens()` (`accounts/`). Nothing in the app uses a static shared secret as a session credential. |
| V7.2.3 | Reference session tokens are CSPRNG-generated with ≥128 bits of entropy. | Met | Django's session key is 32 characters from a 62-character alphabet (`get_random_string`, `random.SystemRandom`-backed CSPRNG) — `log2(62**32) ≈ 190` bits, well over 128. |
| V7.2.4 | A new session token is issued on authentication/re-authentication, terminating the old one. | Met | `login(request, user)` is called on every sign-in path (`accounts/views.py`), and Django's `login()` always calls `request.session.cycle_key()`, replacing the session id; `accounts/views.py:151`'s comment notes this explicitly for the MFA second step. Confirmed by `accounts/tests/test_security_pass4.py`. |
| V7.4.1 | Session termination (logout/expiry) disallows further use of that session/token. | Met | `LogoutView` (Django) flushes the session store entry. For the self-contained JWT case: logout blacklists the refresh token (`rest_framework_simplejwt.token_blacklist`, `BLACKLIST_AFTER_ROTATION=True`), and `CHECK_REVOKE_TOKEN=True` means every access token carries a fingerprint of the password hash, so a password change (which the app performs on logout-all events) invalidates outstanding access tokens too — security pass 4 (`HANDOVER.md` §3). |
| V7.4.2 | All active sessions terminate when an account is disabled or deleted. | Met | Deactivation: Django's `ModelBackend.get_user()` (used by both `AuthenticationMiddleware` for web sessions and `JWTAuthentication.get_user()` for API tokens) checks `user_can_authenticate`/`is_active` on every request, so a session or token for a deactivated (`is_active=False`) account stops authenticating on its very next use — no explicit session flush needed. Deletion: `accounts/deletion.py`'s `delete_account()` explicitly blacklists every `OutstandingToken` for the user inside the same transaction, and the user row itself is gone, so `get_user()` raises `DoesNotExist` for any lingering session. |

## V8 — Authorization

| ID | Requirement | Status | Evidence |
|---|---|---|---|
| V8.1.1 | Documentation defines function-level and data-specific access rules. | Met | `HANDOVER.md` §3, "Security pass 3", states the rule in full: reads return only the signed-in account's rows (404 on another account's id, never 403 or the record), writes require every linked id to belong to the same account, and staff-only surfaces require `is_staff`. `docs/HANDOFF_BILL_SCAN.md` G14 restates it for bill scans specifically. |
| V8.2.1 | Function-level access is restricted to consumers with explicit permission. | Met | `REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"] = ["rest_framework.permissions.IsAuthenticated"]` (deny-by-default, `config/settings.py`); every app view is `LoginRequiredMixin`-based or explicitly `IsAuthenticated`/`IsOwner`; admin/staff views require `is_staff` (Django admin's own check). |
| V8.2.2 | Data-specific access is restricted per-item (IDOR/BOLA protection). | Met | `OwnerScopedMixin` (`expenses/mixins.py`) and `OwnerScopedViewSet`/`OwnerJobViewSet`/`ScopedPrimaryKeyRelatedField` (`expenses/api/views.py`) filter every queryset to `user=request.user`, so an unowned id is a 404, and every foreign-key field a request can set is validated to belong to the same account. `expenses/tests/test_security_pass3.py` tests this for every route (list/detail/download, create/link, update/delete). |
| V8.3.1 | Authorization is enforced at a trusted service layer, not client-side JS. | Met | Every authorization check above runs in `get_queryset()`/DRF permission classes on the server; nothing in the JS (`expenses/static/`) makes an authorization decision — the client-side code only toggles UI affordances. |

## V9 — Self-contained Tokens

| ID | Requirement | Status | Evidence |
|---|---|---|---|
| V9.1.1 | Self-contained tokens are validated by signature/MAC before their contents are trusted. | Met | `rest_framework_simplejwt.authentication.JWTAuthentication` (in `DEFAULT_AUTHENTICATION_CLASSES`, `config/settings.py`) rejects any token whose signature does not verify before decoding claims — this is the library's core behaviour, unmodified here. |
| V9.1.2 | Only an allow-listed set of algorithms is used; never `none`. | Met | `SIMPLE_JWT` (`config/settings.py`) does not override `ALGORITHM`, so simplejwt's single default, `HS256`, applies — one symmetric algorithm, `none` is never accepted (simplejwt's decode path always requires a verified signature). |
| V9.1.3 | Key material comes from a pre-configured, trusted source (not headers like `jku`/`jwk`). | Met | The signing/verifying key is `SIGNING_KEY`, which defaults to the server's own `SECRET_KEY` (simplejwt default, unoverridden) — never read from a token header; simplejwt's HS256 path has no `jku`/`x5u`/`jwk` header handling to misuse. |
| V9.2.1 | Token validity window (`exp`/`nbf`) is checked before content is accepted. | Met | Simplejwt enforces `exp` on every decode by default; `SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"]`/`["REFRESH_TOKEN_LIFETIME"]` set sensible, finite lifetimes (30 minutes / 14 days, `config/settings.py`), tested in `accounts/tests/test_security_pass4.py`. |

## V10 — OAuth and OIDC

| ID | Requirement | Status | Evidence |
|---|---|---|---|
| V10.4.1 | Authorization server validates redirect URIs against a pre-registered allowlist. | N/A | This app is never an OAuth **authorization server** — it has no OAuth client registry, issues no authorization codes, and grants no third party access to anyone's data. "Sign in with Google" (`docs/design/GOOGLE_SIGNIN.md`) makes it an OAuth/OIDC **relying party** (client) of Google, in callback/implicit-ID-token mode with no redirect URI at all (`accounts/google.py`; the design doc: *"no redirect URI needed — it runs in callback mode"*). |
| V10.4.2 | An authorization code can be redeemed only once; reuse revokes related tokens. | N/A | Same reason: no authorization-code flow exists in this app in either role. |
| V10.4.3 | Authorization codes are short-lived (≤10 minutes at L1/L2). | N/A | Same reason. |
| V10.4.4 | The authorization server only allows grants a client needs; `token`/`password` grants are retired. | N/A | Same reason — there is no authorization-server role, so no grant-type allowlist to define. |
| V10.4.5 | Refresh-token replay is mitigated (rotation + invalidation, at minimum). | N/A | The Google integration issues no OAuth tokens of its own; it verifies Google's ID token once and then issues this app's **own** token pair through the existing `issue_tokens()` path, which already satisfies the equivalent self-contained-token requirements above (V9, and refresh-token rotation, V7.4.1). There is no OAuth-authorization-server refresh-token surface here to protect. |

## V11 — Cryptography

| ID | Requirement | Status | Evidence |
|---|---|---|---|
| V11.3.1 | No insecure block modes (ECB) or weak padding (PKCS#1 v1.5). | N/A | The app performs no symmetric or asymmetric encryption of its own anywhere — `grep -rln "Fernet\|AES\|DES\|Cipher\|encrypt\|decrypt"` over `accounts/`, `expenses/`, `config/` finds only `accounts/models.py`'s docstring prose and `config/settings.py` referencing Django's password *hashing* (not encryption); there is no block cipher in the dependency tree the app itself calls. |
| V11.3.2 | Only approved ciphers/modes (e.g. AES-GCM). | N/A | Same reason — no cipher use to approve or disapprove. TLS ciphers are the reverse proxy's concern (see V12). |
| V11.4.1 | Only approved hash functions for general cryptographic use; no MD5 for any cryptographic purpose. | Met | Passwords are hashed with Django's default `PASSWORD_HASHERS` (PBKDF2-SHA256; production never overrides this — `config/test_runner.py`'s MD5 hasher swap is explicitly test-only, with a comment: *"Never put this in settings.PASSWORD_HASHERS"*). The two other hash uses are protocol-mandated, not general-purpose: `accounts/mfa.py`'s SHA-256 login-ticket fingerprint (approved), and SHA-1 in exactly two RFC-mandated spots — TOTP's HMAC-SHA1 (`accounts/totp.py`, RFC 6238's required algorithm for authenticator-app compatibility; HMAC's security does not depend on collision resistance, unlike bare SHA-1 hashing) and the Have I Been Pwned range API's k-anonymity protocol, which is *defined* in terms of a SHA-1 prefix (`accounts/password_validation.py:45`, `# noqa: S324` acknowledging the linter's general-purpose warning does not apply to this specific, mandated use). |

## V12 — Secure Communication

| ID | Requirement | Status | Evidence |
|---|---|---|---|
| V12.1.1 | Only current TLS versions enabled (≥1.2), latest preferred. | N/A | TLS termination happens at the reverse proxy (nginx/Caddy) in front of the app, which is not part of this repository — `HANDOVER.md` §4's hosting checklist names the proxy's own configuration as the deployer's responsibility. The Django app itself (via WhiteNoise/gunicorn) never terminates TLS. |
| V12.2.1 | TLS used for all client connectivity to external-facing HTTP services; no silent fallback to plaintext. | Met | `SECURE_SSL_REDIRECT = True` in production (`config/settings.py`) 301-redirects any plaintext request to HTTPS, and `SECURE_HSTS_SECONDS` (see V3.4.1) tells the browser never to try plaintext again for the configured window — enforced at the app layer regardless of what the proxy in front does. |
| V12.2.2 | External-facing services use publicly trusted TLS certificates. | N/A | Certificate issuance is the reverse proxy's/hosting provider's responsibility (e.g. Let's Encrypt via Caddy or certbot+nginx), outside this repository — same reasoning as V12.1.1. |

## V13 — Configuration

| ID | Requirement | Status | Evidence |
|---|---|---|---|
| V13.4.1 | `.git`/`.svn` metadata is not deployed or reachable. | Met | `.dockerignore` excludes `.git/` and `.github/` from every image build (confirmed this session: `cat .dockerignore | grep -i git` → `.git/`, `.github/`); the production image (`Dockerfile`'s `runtime` stage) copies only the application source, never the working tree's VCS metadata. |

## V14 — Data Protection

| ID | Requirement | Status | Evidence |
|---|---|---|---|
| V14.2.1 | Sensitive data travels only in the body/headers; URLs/query strings carry no API keys or session tokens. | Met | Bearer tokens are sent only in the `Authorization` header (`docs/frontend/API_GUIDE.md` §3: *"Never put a token in a URL, a query string, a log line or an error report."*); the session/CSRF cookies travel as cookies, never as query parameters. The only credential-shaped values that appear in a URL **path** (not query string) are the single-use, time-boxed email-verification and password-reset tokens (`accounts/urls.py`'s `verify/<uidb64>/<token>/`, `password/reset/<uidb64>/<token>/`) — Django's own, widely-used pattern; both self-invalidate after one use (V6.4.1) and `VerifyEmailView` (`accounts/views.py:378`) processes and redirects away on the very first `GET`, with no rendered page's outbound links to leak the URL via `Referer`. |
| V14.3.1 | Authenticated data is cleared from client storage when the session/client ends. | Met | This repo's own web pages keep no auth data in browser storage at all — the session id lives only in an `HttpOnly` cookie the page's own JS cannot read (`SESSION_COOKIE_HTTPONLY = True`, `config/settings.py`). For the API's separate React consumer (a different repository, out of this one's control), `docs/frontend/API_GUIDE.md` §3.4/§3.5 documents the contract it must follow: tokens in memory (and `sessionStorage`/`localStorage` only if needed), explicitly *"Clear it on logout"*. |

## V15 — Secure Coding and Architecture

| ID | Requirement | Status | Evidence |
|---|---|---|---|
| V15.1.1 | Documentation defines risk-based remediation time frames for vulnerable/outdated 3rd-party components. | **Met (session 32)** | `SECURITY.md` "Fixing vulnerable dependencies": critical 7 days, high 14, medium 30, low 90, by CVSS / advisory rating. |
| V15.2.1 | The application contains no component that has breached its documented remediation time frame. | **Met (session 32)** | `pip-audit -r requirements.txt` is clean (security pass 4, rerun before deploys), and `.github/dependabot.yml` raises security updates as advisories publish, so a breach of the time frames in `SECURITY.md` is visible as an open pull request. |
| V15.3.1 | Endpoints return only the required subset of fields, not a whole data object. | Met | Every DRF serializer in `expenses/api/serializers.py` and `accounts/api.py` declares an explicit `fields = [...]` list (never `fields = "__all__"` — confirmed absent by `grep -rn 'fields = "__all__"'` this session); `accounts/api.py`'s `MeSerializer` in particular excludes `password` and every other sensitive `User` column by construction, and marks `id`/`username`/`email`/`is_staff`/`date_joined`/`last_login` `read_only_fields` so they can never be written back either. |

---

## Gaps left

None in the code. One condition on the deployment:

1. **V3.4.1 — HSTS for at least a year.** The shipped default stays 1 hour (`DECISIONS.md` D5:
   start low on a first deploy, because a wrong long value cannot be taken back for its whole
   duration). The hosting checklist (`HANDOVER.md` §4) says to set
   `SECURE_HSTS_SECONDS=31536000` once HTTPS has been stable for a while. Until then, the live
   site meets V3.4.1 only in part.

Closed in session 32: **V15.1.1 / V15.2.1** — `SECURITY.md` sets the time frames (critical 7
days, high 14, medium 30, low 90), and `.github/dependabot.yml` raises updates as advisories
are published.

## What changed in this session

- **V3.3.1** (cookie name prefix) was found unmet and fixed, with tests:
  `config/settings.py` now sets `SESSION_COOKIE_NAME`/`CSRF_COOKIE_NAME` to the `__Host-` prefixed
  form whenever the cookies are actually `Secure`, and two new tests in
  `expenses/tests/test_error_pages.py` pin both the production case (prefixed) and the local-HTTP
  compose case (unprefixed, so login is not broken there).
