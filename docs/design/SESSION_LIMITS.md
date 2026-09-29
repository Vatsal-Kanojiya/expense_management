# Sign-in limits per account — design

> Written by the main session (session 32), from the owner's decision: at most two devices signed
> in at a time, and a cap on wrong passwords per account. SECURITY_ROADMAP.md §2.

## 1. Wrong passwords, per account

Today a login is refused after 10 failures for one username **from one address**, or 50 from one
address across usernames (`accounts/ratelimit.py`). Guesses at one account spread over many
addresses meet only the per-address cap.

- New limit, keyed on the **username alone** (lower-cased, as `_key` does), not the address:
  `LOGIN_ACCOUNT_LIMIT = 20` failures per `LOGIN_ACCOUNT_WINDOW = 15 minutes`.
- It joins `login_blocked()` and `record_login_failure()`, so every way in — the web page, the API,
  and (through the site login) the admin — shares it. A **successful** sign-in clears it, as it
  clears the per-username count.
- Google sign-in does not use a password, so this count does not block it.
- The trade-off, accepted by the owner: anyone can lock an account's password sign-in for up to
  15 minutes by failing 20 times. Google sign-in and an already signed-in device keep working, and
  the lock clears itself. Record `login_blocked` events as today.

## 2. At most two devices signed in at a time

"Signed in" means a web session, or an API refresh-token chain (one device holding a refresh
token, rotated on each refresh). Both count towards one limit: `MAX_SIGNED_IN_DEVICES` (setting,
env, default 2).

### Storage
- `accounts.SignedInDevice`: `user` (FK, CASCADE), `kind` (`web` / `api`), `session_key`
  (web; blank for api), `refresh_jti` (api; blank for web), `created_at`, `last_seen_at`, and a
  short `label` (the User-Agent, truncated to 200 characters, for the list below). Index on user.

### Registering a sign-in
- **Web:** on `user_logged_in` (`accounts/signals.py` already listens) — after `login()` has
  cycled the key, record `request.session.session_key`. This covers the login page, the MFA code
  step, Google sign-in and the admin (which now goes through the site login).
- **API:** in `issue_tokens()`, record the new refresh token's `jti`. Every API path that signs a
  device in goes through it (login, MFA verify, Google, verify-email, password change, MFA
  confirm/disable).
- **Refresh:** `RefreshView` rotates the refresh token; move the device's `refresh_jti` to the new
  token's `jti` and update `last_seen_at`, so a device keeps one record for its whole chain.
- **Session-key rotation:** `update_session_auth_hash()` and `cycle_key()` give a live session a
  new key. Wherever the app calls them for a signed-in user (password change, MFA pages), update
  the device's `session_key` with a small helper (`devices.rekey(request, old_key)`), so the
  current device is not lost from the count.

### Enforcing the limit
- After registering, if the user has more than the limit, **end the oldest by `last_seen_at`**
  until they are within it:
  - web: delete that `Session` row (`django.contrib.sessions.models.Session`);
  - api: blacklist that refresh token's `OutstandingToken` (by `jti`).
  Record a `SecurityEvent` `device_signed_out` (new choice) with the device's kind and label.
- Before counting, drop records that are already dead: a web record whose session no longer exists
  or has expired; an api record whose token is blacklisted or expired. Otherwise a device that
  simply went away would push out a live one.
- **Known limitation, document it:** an API device that is signed out keeps its current access
  token until it expires (up to 30 minutes, `JWT_ACCESS_MINUTES`); it cannot refresh.

### Ending a sign-in normally
- Web logout (`user_logged_out`) and API logout remove the record. `revoke_refresh_tokens()`
  (password change, reset, MFA changes) removes the user's api records it revokes. Account
  deletion cascades.

### Seeing and ending devices (small, but it makes the limit usable)
- `GET auth/devices/` → the user's devices: `id`, `kind`, `label`, `created_at`, `last_seen_at`,
  `current` (true for the one making the request, where it can tell).
- `POST auth/devices/<id>/sign-out/` → ends that device (the same way as above).
- Web: a "Signed-in devices" section on the account (MFA) page, with a sign-out button per device.

### Documentation
- `docs/frontend/API_GUIDE.md` and `BRD.md`: the limit (a third sign-in signs out the oldest
  device), what the signed-out device sees (401 on refresh → sign in again), the devices
  endpoints, and the per-account password cap in the rate-limit table.
- `.env.example`: `MAX_SIGNED_IN_DEVICES`.
- Regenerate with `python manage.py build_api_docs`.

### Tests
- Per-account cap: 20 failures spread over different addresses block the 21st even with the right
  password; web and API share it; a success clears it; Google sign-in is not blocked by it.
- Devices: a third sign-in (any mix of web and API) ends the oldest; the ended web session is
  anonymous on its next request; the ended API device's refresh gets 401; refresh keeps one record
  and updates `last_seen_at`; dead records don't push out live ones; the current web device
  survives a password change; logout removes the record; the devices list and sign-out endpoint,
  including that one user cannot sign out another's device (404); events recorded.
