# API reference

> **Generated** by `python manage.py build_api_docs` on 30 September 2026 from a real run of the API. Do not edit by hand: change the code or `expenses/api/journey.py`, then regenerate. Concepts that apply to every endpoint — tokens, errors, pagination, formats — are in [API_GUIDE.md](API_GUIDE.md).

Base URL in these examples: `http://127.0.0.1:8765/api/v1`. Tokens are shortened.

## Index

| # | Method | Path | What | Auth |
|---|---|---|---|---|
| 1 | `GET` | `/health/` | [Health check](#health-check) | — |
| 2 | `POST` | `/auth/login/` | [Log in](#log-in) | — |
| 3 | `POST` | `/auth/google/` | [Sign in with Google](#sign-in-with-google) | — |
| 4 | `GET` | `/me/` | [Your profile](#your-profile) | Bearer |
| 5 | `PATCH` | `/me/` | [Update your name](#update-your-name) | Bearer |
| 6 | `POST` | `/categories/` | [Create a category](#create-a-category) | Bearer |
| 7 | `POST` | `/categories/` | [Create another category](#create-another-category) | Bearer |
| 8 | `GET` | `/categories/` | [List categories](#list-categories) | Bearer |
| 9 | `GET` | `/categories/{id}/` | [Get a category](#get-a-category) | Bearer |
| 10 | `PATCH` | `/categories/{id}/` | [Rename a category](#rename-a-category) | Bearer |
| 11 | `PUT` | `/categories/{id}/` | [Replace a category](#replace-a-category) | Bearer |
| 12 | `POST` | `/categories/` | [Create a category to delete](#create-a-category-to-delete) | Bearer |
| 13 | `DELETE` | `/categories/{id}/` | [Delete a category](#delete-a-category) | Bearer |
| 14 | `POST` | `/participants/` | [Add a person](#add-a-person) | Bearer |
| 15 | `POST` | `/participants/` | [Add another person](#add-another-person) | Bearer |
| 16 | `GET` | `/participants/` | [List people](#list-people) | Bearer |
| 17 | `GET` | `/participants/{id}/` | [Get a person](#get-a-person) | Bearer |
| 18 | `PATCH` | `/participants/{id}/` | [Rename a person](#rename-a-person) | Bearer |
| 19 | `PUT` | `/participants/{id}/` | [Replace a person](#replace-a-person) | Bearer |
| 20 | `POST` | `/participants/` | [Add a person to remove](#add-a-person-to-remove) | Bearer |
| 21 | `DELETE` | `/participants/{id}/` | [Remove a person](#remove-a-person) | Bearer |
| 22 | `POST` | `/expenses/` | [Create an expense](#create-an-expense) | Bearer |
| 23 | `POST` | `/expenses/` | [Create an even split](#create-an-even-split) | Bearer |
| 24 | `POST` | `/expenses/` | [Create an itemised bill](#create-an-itemised-bill) | Bearer |
| 25 | `GET` | `/expenses/` | [List expenses](#list-expenses) | Bearer |
| 26 | `GET` | `/expenses/` | [Filter expenses](#filter-expenses) | Bearer |
| 27 | `GET` | `/expenses/{id}/` | [Get an expense](#get-an-expense) | Bearer |
| 28 | `PATCH` | `/expenses/{id}/` | [Change part of an expense](#change-part-of-an-expense) | Bearer |
| 29 | `PUT` | `/expenses/{id}/` | [Replace an expense](#replace-an-expense) | Bearer |
| 30 | `GET` | `/expenses/{id}/split/` | [Split breakdown](#split-breakdown) | Bearer |
| 31 | `DELETE` | `/expenses/{id}/` | [Delete an expense](#delete-an-expense) | Bearer |
| 32 | `GET` | `/summary/` | [Spending summary](#spending-summary) | Bearer |
| 33 | `GET` | `/balances/` | [Balances](#balances) | Bearer |
| 34 | `POST` | `/balances/{participant_id}/settle/` | [Settle up](#settle-up) | Bearer |
| 35 | `GET` | `/settlements/` | [Repayment history](#repayment-history) | Bearer |
| 36 | `GET` | `/settlements/{id}/` | [Get a repayment](#get-a-repayment) | Bearer |
| 37 | `POST` | `/exports/` | [Request an export](#request-an-export) | Bearer |
| 38 | `GET` | `/exports/{id}/` | [Wait for the export](#wait-for-the-export) | Bearer |
| 39 | `GET` | `/exports/` | [List exports](#list-exports) | Bearer |
| 40 | `GET` | `/exports/{id}/download/` | [Download the export](#download-the-export) | Bearer |
| 41 | `POST` | `/bill-scans/` | [Upload a bill](#upload-a-bill) | Bearer |
| 42 | `GET` | `/bill-scans/{id}/` | [Wait for the scan](#wait-for-the-scan) | Bearer |
| 43 | `GET` | `/bill-scans/` | [List scans](#list-scans) | Bearer |
| 44 | `GET` | `/bill-scans/{id}/image/` | [Get the photo](#get-the-photo) | Bearer |
| 45 | `GET` | `/bill-scans/{id}/prefill/` | [Get the draft expense](#get-the-draft-expense) | Bearer |
| 46 | `POST` | `/expenses/` | [Save the scanned bill](#save-the-scanned-bill) | Bearer |
| 47 | `POST` | `/auth/refresh/` | [Refresh the tokens](#refresh-the-tokens) | — |
| 48 | `POST` | `/auth/logout/` | [Log out](#log-out) | — |
| 49 | `POST` | `/auth/signup/` | [Sign up](#sign-up) | — |
| 50 | `POST` | `/auth/verify-email/` | [Verify the email](#verify-the-email) | — |
| 51 | `POST` | `/auth/password/change/` | [Change password](#change-password) | Bearer |
| 52 | `POST` | `/auth/password/reset/` | [Request a password reset](#request-a-password-reset) | — |
| 53 | `POST` | `/auth/password/reset/confirm/` | [Set a new password](#set-a-new-password) | — |
| 54 | `POST` | `/auth/login/` | [Log in with the new password](#log-in-with-the-new-password) | — |
| 55 | `GET` | `/auth/mfa/` | [Check two-step sign-in status](#check-two-step-sign-in-status) | Bearer |
| 56 | `POST` | `/auth/mfa/setup/` | [Start two-step sign-in setup](#start-two-step-sign-in-setup) | Bearer |
| 57 | `POST` | `/auth/mfa/confirm/` | [Confirm and turn it on](#confirm-and-turn-it-on) | Bearer |
| 58 | `POST` | `/auth/login/` | [Log in again](#log-in-again) | — |
| 59 | `POST` | `/auth/mfa/verify/` | [Enter the two-step code](#enter-the-two-step-code) | — |
| 60 | `GET` | `/auth/devices/` | [List signed-in devices](#list-signed-in-devices) | Bearer |
| 61 | `POST` | `/auth/devices/{id}/sign-out/` | [Sign a device out](#sign-a-device-out) | Bearer |
| 62 | `POST` | `/auth/mfa/recovery-codes/` | [Get new recovery codes](#get-new-recovery-codes) | Bearer |
| 63 | `POST` | `/auth/mfa/disable/` | [Turn off two-step sign-in](#turn-off-two-step-sign-in) | Bearer |
| 64 | `DELETE` | `/me/` | [Delete the account](#delete-the-account) | Bearer |

---

## 0 · Start here

Check the server, sign in, read the profile. Run this folder first: it stores the access and refresh tokens every later request uses.

### Health check

`GET /health/` · no sign-in · success `200 OK`

Whether the server is up and can reach its database. No sign-in needed. Answers 503 with `unavailable` when the database cannot be reached.

**Response** `200 OK` · `application/json`

```json
{
  "status": "ok"
}
```

### Log in

`POST /auth/login/` · no sign-in · success `200 OK`

Exchange a username and password for an **access** token (sent as `Authorization: Bearer <access>`, valid 30 minutes) and a **refresh** token (valid 14 days, traded at `auth/refresh/` for a new pair). The response also carries the profile, including `self_participant`: the id that stands for this user in splits.

Ten failed attempts for one username from one address lock it for 15 minutes: 429 `rate_limited`.

**Request**

`POST /api/v1/auth/login/`

```json
{
  "username": "priya",
  "password": "Demo-Pass-2026"
}
```

**Response** `200 OK` · `application/json`

```json
{
  "access": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.<access token, valid 30 minutes>",
  "refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.<refresh token, valid 14 days>",
  "user": {
    "id": 1,
    "username": "priya",
    "email": "priya@example.com",
    "first_name": "",
    "last_name": "",
    "is_staff": false,
    "date_joined": "2026-09-30T01:17:44.886751+05:30",
    "last_login": "2026-09-30T01:17:44.926407+05:30",
    "self_participant": {
      "id": 1,
      "name": "priya (self)"
    },
    "has_password": true
  }
}
```

**Wrong password** → `401 Unauthorized`

`POST /api/v1/auth/login/`

```json
{
  "username": "priya",
  "password": "wrong"
}
```

```json
{
  "detail": "Wrong username or password.",
  "code": "invalid_credentials"
}
```

**Email not verified yet** → `403 Forbidden`

Said only when the password was right; otherwise a plain 401.

`POST /api/v1/auth/login/`

```json
{
  "username": "not.verified",
  "password": "Some-Pass-2026"
}
```

```json
{
  "detail": "Confirm your email address first: use the link we sent.",
  "code": "email_not_verified"
}
```

### Sign in with Google

`POST /auth/google/` · no sign-in · success `200 OK`

An alternative to the step above: `credential` is the ID token Google Identity Services returns from its own button. The server verifies it with Google, then finds or creates the account by its (Google-verified) email and answers exactly like a plain login -- a token pair, or `{mfa_required: true, mfa_ticket}` for an account with two-step sign-in on. `404` when the server has no `GOOGLE_OAUTH_CLIENT_ID` configured -- the feature does not exist at all until then, and the button is not shown.

**Request**

`POST /api/v1/auth/google/`

```json
{
  "credential": "google-id-token"
}
```

**Response** `200 OK` · `application/json`

```json
{
  "access": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.<access token, valid 30 minutes>",
  "refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.<refresh token, valid 14 days>",
  "user": {
    "id": 3,
    "username": "journey.google",
    "email": "journey.google@example.com",
    "first_name": "",
    "last_name": "",
    "is_staff": false,
    "date_joined": "2026-09-30T01:17:44.945012+05:30",
    "last_login": "2026-09-30T01:17:44.952672+05:30",
    "self_participant": {
      "id": 2,
      "name": "journey.google (self)"
    },
    "has_password": false
  }
}
```

### Your profile

`GET /me/` · Bearer token · success `200 OK`

The signed-in user. Call it when the app starts, to check that a stored token still works.

**Response** `200 OK` · `application/json`

```json
{
  "id": 1,
  "username": "priya",
  "email": "priya@example.com",
  "first_name": "",
  "last_name": "",
  "is_staff": false,
  "date_joined": "2026-09-30T01:17:44.886751+05:30",
  "last_login": "2026-09-30T01:17:44.926407+05:30",
  "self_participant": {
    "id": 1,
    "name": "priya (self)"
  },
  "has_password": true
}
```

**Not signed in** → `401 Unauthorized`

```json
{
  "detail": "Authentication credentials were not provided."
}
```

### Update your name

`PATCH /me/` · Bearer token · success `200 OK`

Only `first_name` and `last_name` can change; `username` and `email` are read-only and ignored if sent.

**Request**

`PATCH /api/v1/me/`

```json
{
  "first_name": "Priya",
  "last_name": "Sharma"
}
```

**Response** `200 OK` · `application/json`

```json
{
  "id": 1,
  "username": "priya",
  "email": "priya@example.com",
  "first_name": "Priya",
  "last_name": "Sharma",
  "is_staff": false,
  "date_joined": "2026-09-30T01:17:44.886751+05:30",
  "last_login": "2026-09-30T01:17:44.926407+05:30",
  "self_participant": {
    "id": 1,
    "name": "priya (self)"
  },
  "has_password": true
}
```

---

## 1 · Categories

The user's own categories. A category that still has expenses cannot be deleted (409).

### Create a category

`POST /categories/` · Bearer token · success `201 Created`

Names are unique per user, ignoring case: `Food` and `food` are one category.

**Request**

`POST /api/v1/categories/`

```json
{
  "name": "Food"
}
```

**Response** `201 Created` · `application/json`

```json
{
  "id": 1,
  "name": "Food",
  "created_at": "2026-09-30T01:17:44.970770+05:30",
  "expense_count": 0,
  "total": null,
  "last_spent_on": null,
  "last_amount": null
}
```

**Name already used** → `400 Bad Request`

`POST /api/v1/categories/`

```json
{
  "name": "food"
}
```

```json
{
  "name": [
    "You already have a category with this name."
  ]
}
```

### Create another category

`POST /categories/` · Bearer token · success `201 Created`

A second category, used by the plain expense in folder 3.

**Request**

`POST /api/v1/categories/`

```json
{
  "name": "Home"
}
```

**Response** `201 Created` · `application/json`

```json
{
  "id": 2,
  "name": "Home",
  "created_at": "2026-09-30T01:17:44.980707+05:30",
  "expense_count": 0,
  "total": null,
  "last_spent_on": null,
  "last_amount": null
}
```

### List categories

`GET /categories/` · Bearer token · success `200 OK`

Alphabetical, with the Categories screen's usage columns: `expense_count`, `total`, `last_spent_on` and `last_amount`. The last three are null for an unused category.

**Response** `200 OK` · `application/json`

```json
{
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 2,
      "name": "Home",
      "created_at": "2026-09-30T01:17:44.980707+05:30",
      "expense_count": 0,
      "total": null,
      "last_spent_on": null,
      "last_amount": null
    },
    {
      "id": 1,
      "name": "Food",
      "created_at": "2026-09-30T01:17:44.970770+05:30",
      "expense_count": 0,
      "total": null,
      "last_spent_on": null,
      "last_amount": null
    }
  ]
}
```

### Get a category

`GET /categories/{id}/` · Bearer token · success `200 OK`

One category with its usage columns. Another user's id is a 404, never a 403.

**Response** `200 OK` · `application/json`

```json
{
  "id": 1,
  "name": "Food",
  "created_at": "2026-09-30T01:17:44.970770+05:30",
  "expense_count": 0,
  "total": null,
  "last_spent_on": null,
  "last_amount": null
}
```

### Rename a category

`PATCH /categories/{id}/` · Bearer token · success `200 OK`

PATCH changes only the fields sent.

**Request**

`PATCH /api/v1/categories/2/`

```json
{
  "name": "Household"
}
```

**Response** `200 OK` · `application/json`

```json
{
  "id": 2,
  "name": "Household",
  "created_at": "2026-09-30T01:17:44.980707+05:30",
  "expense_count": 0,
  "total": null,
  "last_spent_on": null,
  "last_amount": null
}
```

### Replace a category

`PUT /categories/{id}/` · Bearer token · success `200 OK`

PUT sends every writable field; for a category that is only `name`.

**Request**

`PUT /api/v1/categories/2/`

```json
{
  "name": "Home & utilities"
}
```

**Response** `200 OK` · `application/json`

```json
{
  "id": 2,
  "name": "Home & utilities",
  "created_at": "2026-09-30T01:17:44.980707+05:30",
  "expense_count": 0,
  "total": null,
  "last_spent_on": null,
  "last_amount": null
}
```

### Create a category to delete

`POST /categories/` · Bearer token · success `201 Created`

A throwaway category for the delete that follows.

**Request**

`POST /api/v1/categories/`

```json
{
  "name": "Travel"
}
```

**Response** `201 Created` · `application/json`

```json
{
  "id": 3,
  "name": "Travel",
  "created_at": "2026-09-30T01:17:45.013610+05:30",
  "expense_count": 0,
  "total": null,
  "last_spent_on": null,
  "last_amount": null
}
```

### Delete a category

`DELETE /categories/{id}/` · Bearer token · success `204 No Content`

Only a category with no expenses can be deleted. Otherwise the answer is 409 `protected`, `blocking` says what is in the way, and nothing is deleted.

**Response** `204 No Content`

*No body.*

**Still has expenses** → `409 Conflict`

`DELETE /api/v1/categories/1/`

```json
{
  "detail": "This is still used by 1 expense, so it cannot be deleted.",
  "code": "protected",
  "blocking": {
    "expenses": 1
  }
}
```

---

## 2 · People

The people bills are split with. The list includes the user themself, marked `is_self`, which can be neither renamed nor deleted.

### Add a person

`POST /participants/` · Bearer token · success `201 Created`

Someone bills are split with. People are private to each user, and names are unique per user, ignoring case.

**Request**

`POST /api/v1/participants/`

```json
{
  "name": "Rahul"
}
```

**Response** `201 Created` · `application/json`

```json
{
  "id": 3,
  "name": "Rahul",
  "is_self": false,
  "created_at": "2026-09-30T01:17:45.035995+05:30",
  "shared_count": 0,
  "item_count": 0
}
```

**Name already used** → `400 Bad Request`

`POST /api/v1/participants/`

```json
{
  "name": "rahul"
}
```

```json
{
  "name": [
    "You already have someone with this name."
  ]
}
```

### Add another person

`POST /participants/` · Bearer token · success `201 Created`

A second person, for the itemised bill in folder 3.

**Request**

`POST /api/v1/participants/`

```json
{
  "name": "Aisha"
}
```

**Response** `201 Created` · `application/json`

```json
{
  "id": 4,
  "name": "Aisha",
  "is_self": false,
  "created_at": "2026-09-30T01:17:45.044407+05:30",
  "shared_count": 0,
  "item_count": 0
}
```

### List people

`GET /participants/` · Bearer token · success `200 OK`

Alphabetical, **including the user themself** with `is_self: true`: the People screen hides that row, and the expense form needs its id. `shared_count` and `item_count` say how many expenses and line items name each person.

**Response** `200 OK` · `application/json`

```json
{
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 4,
      "name": "Aisha",
      "is_self": false,
      "created_at": "2026-09-30T01:17:45.044407+05:30",
      "shared_count": 0,
      "item_count": 0
    },
    {
      "id": 3,
      "name": "Rahul",
      "is_self": false,
      "created_at": "2026-09-30T01:17:45.035995+05:30",
      "shared_count": 0,
      "item_count": 0
    },
    {
      "id": 1,
      "name": "priya (self)",
      "is_self": true,
      "created_at": "2026-09-30T01:17:44.931541+05:30",
      "shared_count": 0,
      "item_count": 0
    }
  ]
}
```

### Get a person

`GET /participants/{id}/` · Bearer token · success `200 OK`

One person.

**Response** `200 OK` · `application/json`

```json
{
  "id": 3,
  "name": "Rahul",
  "is_self": false,
  "created_at": "2026-09-30T01:17:45.035995+05:30",
  "shared_count": 0,
  "item_count": 0
}
```

### Rename a person

`PATCH /participants/{id}/` · Bearer token · success `200 OK`

PATCH changes only the fields sent.

**Request**

`PATCH /api/v1/participants/4/`

```json
{
  "name": "Aisha Khan"
}
```

**Response** `200 OK` · `application/json`

```json
{
  "id": 4,
  "name": "Aisha Khan",
  "is_self": false,
  "created_at": "2026-09-30T01:17:45.044407+05:30",
  "shared_count": 0,
  "item_count": 0
}
```

**Renaming yourself** → `403 Forbidden`

`PATCH /api/v1/participants/1/`

```json
{
  "name": "Someone else"
}
```

```json
{
  "detail": "This is you. It can't be renamed or deleted; it stands for you in every split.",
  "code": "self_participant"
}
```

### Replace a person

`PUT /participants/{id}/` · Bearer token · success `200 OK`

PUT sends every writable field; for a person that is only `name`.

**Request**

`PUT /api/v1/participants/4/`

```json
{
  "name": "Aisha K."
}
```

**Response** `200 OK` · `application/json`

```json
{
  "id": 4,
  "name": "Aisha K.",
  "is_self": false,
  "created_at": "2026-09-30T01:17:45.044407+05:30",
  "shared_count": 0,
  "item_count": 0
}
```

### Add a person to remove

`POST /participants/` · Bearer token · success `201 Created`

A throwaway person for the delete that follows.

**Request**

`POST /api/v1/participants/`

```json
{
  "name": "Old colleague"
}
```

**Response** `201 Created` · `application/json`

```json
{
  "id": 5,
  "name": "Old colleague",
  "is_self": false,
  "created_at": "2026-09-30T01:17:45.075469+05:30",
  "shared_count": 0,
  "item_count": 0
}
```

### Remove a person

`DELETE /participants/{id}/` · Bearer token · success `204 No Content`

Refused with 409 when the person is on a line item or paid for an expense, and with 403 for the user themself.

**Response** `204 No Content`

*No body.*

**Removing yourself** → `403 Forbidden`

`DELETE /api/v1/participants/1/`

```json
{
  "detail": "This is you. It can't be renamed or deleted; it stands for you in every split.",
  "code": "self_participant"
}
```

**On a line item** → `409 Conflict`

`DELETE /api/v1/participants/3/`

```json
{
  "detail": "This is still used by 1 item share, so it cannot be deleted.",
  "code": "protected",
  "blocking": {
    "item shares": 1
  }
}
```

---

## 3 · Expenses

A plain expense, an even split and an itemised bill with line items, shares and a tax/tip amount; then listing, filtering, editing, the split breakdown and deleting.

### Create an expense

`POST /expenses/` · Bearer token · success `201 Created`

The simplest expense: yours alone. `paid_by` may be left out and defaults to you. Amounts are strings with two decimals; dates are `YYYY-MM-DD`.

**Request**

`POST /api/v1/expenses/`

```json
{
  "category": 2,
  "amount": "1450.00",
  "spent_on": "2026-09-05",
  "note": "Electricity bill"
}
```

**Response** `201 Created` · `application/json`

```json
{
  "id": 3,
  "category": 2,
  "category_name": "Home & utilities",
  "amount": "1450.00",
  "spent_on": "2026-09-05",
  "note": "Electricity bill",
  "paid_by": 1,
  "paid_by_name": "priya (self)",
  "participants": [],
  "misc_amount": null,
  "misc_note": "",
  "items": [],
  "items_total": null,
  "unaccounted_amount": null,
  "is_balanced": true,
  "created_at": "2026-09-30T01:17:45.104378+05:30"
}
```

**Invalid values** → `400 Bad Request`

`POST /api/v1/expenses/`

```json
{
  "category": 2,
  "amount": "0",
  "spent_on": "05/09/2026"
}
```

```json
{
  "amount": [
    "Amount must be greater than zero."
  ],
  "spent_on": [
    "Date has wrong format. Use one of these formats instead: YYYY-MM-DD."
  ]
}
```

### Create an even split

`POST /expenses/` · Bearer token · success `201 Created`

No line items, several participants: the amount is split equally between them, rounded to the paisa without losing any. Send `include_self: false` with the exact list the form shows (see the integration guide, section 9).

**Request**

`POST /api/v1/expenses/`

```json
{
  "category": 1,
  "amount": "900.00",
  "spent_on": "2026-09-12",
  "note": "Dinner with Rahul",
  "paid_by": 1,
  "include_self": false,
  "participants": [
    1,
    3
  ]
}
```

**Response** `201 Created` · `application/json`

```json
{
  "id": 4,
  "category": 1,
  "category_name": "Food",
  "amount": "900.00",
  "spent_on": "2026-09-12",
  "note": "Dinner with Rahul",
  "paid_by": 1,
  "paid_by_name": "priya (self)",
  "participants": [
    3,
    1
  ],
  "misc_amount": null,
  "misc_note": "",
  "items": [],
  "items_total": null,
  "unaccounted_amount": null,
  "is_balanced": true,
  "created_at": "2026-09-30T01:17:45.116408+05:30"
}
```

### Create an itemised bill

`POST /expenses/` · Bearer token · success `201 Created`

Line items, each shared by the people who had it, and a tax/tip amount (`misc_amount`, which needs `misc_note`) split in proportion to what each person had. Lines plus misc should equal `amount`. When they are more than ₹1 apart the expense still saves, but `is_balanced` is false and it is left out of balances until corrected.

**Request**

`POST /api/v1/expenses/`

```json
{
  "category": 1,
  "amount": "1200.00",
  "spent_on": "2026-09-18",
  "note": "Team lunch",
  "paid_by": 1,
  "include_self": false,
  "participants": [
    1,
    3,
    4
  ],
  "misc_amount": "120.00",
  "misc_note": "GST and tip",
  "items": [
    {
      "name": "Pizza",
      "amount": "600.00",
      "shares": [
        {
          "participant": 1,
          "weight": 1
        },
        {
          "participant": 3,
          "weight": 1
        },
        {
          "participant": 4,
          "weight": 1
        }
      ]
    },
    {
      "name": "Drinks",
      "amount": "300.00",
      "shares": [
        {
          "participant": 3,
          "weight": 1
        },
        {
          "participant": 4,
          "weight": 1
        }
      ]
    },
    {
      "name": "Dessert",
      "amount": "180.00",
      "shares": [
        {
          "participant": 1,
          "weight": 1
        }
      ]
    }
  ]
}
```

**Response** `201 Created` · `application/json`

```json
{
  "id": 5,
  "category": 1,
  "category_name": "Food",
  "amount": "1200.00",
  "spent_on": "2026-09-18",
  "note": "Team lunch",
  "paid_by": 1,
  "paid_by_name": "priya (self)",
  "participants": [
    4,
    3,
    1
  ],
  "misc_amount": "120.00",
  "misc_note": "GST and tip",
  "items": [
    {
      "id": 2,
      "name": "Pizza",
      "amount": "600.00",
      "shares": [
        {
          "participant": 1,
          "weight": 1
        },
        {
          "participant": 3,
          "weight": 1
        },
        {
          "participant": 4,
          "weight": 1
        }
      ]
    },
    {
      "id": 3,
      "name": "Drinks",
      "amount": "300.00",
      "shares": [
        {
          "participant": 3,
          "weight": 1
        },
        {
          "participant": 4,
          "weight": 1
        }
      ]
    },
    {
      "id": 4,
      "name": "Dessert",
      "amount": "180.00",
      "shares": [
        {
          "participant": 1,
          "weight": 1
        }
      ]
    }
  ],
  "items_total": "1080.00",
  "unaccounted_amount": "0.00",
  "is_balanced": true,
  "created_at": "2026-09-30T01:17:45.127005+05:30"
}
```

**Tax/tip without a description** → `400 Bad Request`

`POST /api/v1/expenses/`

```json
{
  "category": 1,
  "amount": "1200.00",
  "spent_on": "2026-09-18",
  "note": "Team lunch",
  "paid_by": 1,
  "include_self": false,
  "participants": [
    1,
    3,
    4
  ],
  "misc_amount": "120.00",
  "misc_note": "",
  "items": [
    {
      "name": "Pizza",
      "amount": "600.00",
      "shares": [
        {
          "participant": 1,
          "weight": 1
        },
        {
          "participant": 3,
          "weight": 1
        },
        {
          "participant": 4,
          "weight": 1
        }
      ]
    },
    {
      "name": "Drinks",
      "amount": "300.00",
      "shares": [
        {
          "participant": 3,
          "weight": 1
        },
        {
          "participant": 4,
          "weight": 1
        }
      ]
    },
    {
      "name": "Dessert",
      "amount": "180.00",
      "shares": [
        {
          "participant": 1,
          "weight": 1
        }
      ]
    }
  ]
}
```

```json
{
  "misc_note": [
    "Please describe what this misc amount is for."
  ]
}
```

**A line nobody had, and you are not on the bill** → `400 Bad Request`

Without you on the bill, an unshared line would silently be charged to you.

`POST /api/v1/expenses/`

```json
{
  "category": 1,
  "amount": "1000.00",
  "spent_on": "2026-09-18",
  "note": "Rahul's party",
  "include_self": false,
  "participants": [
    3
  ],
  "items": [
    {
      "name": "Cake",
      "amount": "600.00",
      "shares": [
        {
          "participant": 3,
          "weight": 1
        }
      ]
    },
    {
      "name": "Balloons",
      "amount": "400.00"
    }
  ]
}
```

```json
{
  "items": [
    {},
    {
      "shares": [
        "You're not part of this expense, so choose who had this item."
      ]
    }
  ]
}
```

### List expenses

`GET /expenses/` · Bearer token · success `200 OK`

Newest date first, 25 per page; follow `next` for more. `count` and `total_amount` cover every page. All time unless filtered.

**Response** `200 OK` · `application/json`

```json
{
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 5,
      "category": 1,
      "category_name": "Food",
      "amount": "1200.00",
      "spent_on": "2026-09-18",
      "note": "Team lunch",
      "paid_by": 1,
      "paid_by_name": "priya (self)",
      "participants": [
        4,
        3,
        1
      ],
      "misc_amount": "120.00",
      "misc_note": "GST and tip",
      "items": [
        {
          "id": 2,
          "name": "Pizza",
          "amount": "600.00",
          "shares": [
            {
              "participant": 1,
              "weight": 1
            },
            {
              "participant": 3,
              "weight": 1
            },
            {
              "participant": 4,
              "weight": 1
            }
          ]
        },
        {
          "id": 3,
          "name": "Drinks",
          "amount": "300.00",
          "shares": [
            {
              "participant": 3,
              "weight": 1
            },
            {
              "participant": 4,
              "weight": 1
            }
          ]
        },
        {
          "id": 4,
          "name": "Dessert",
          "amount": "180.00",
          "shares": [
            {
              "participant": 1,
              "weight": 1
            }
          ]
        }
      ],
      "items_total": "1080.00",
      "unaccounted_amount": "0.00",
      "is_balanced": true,
      "created_at": "2026-09-30T01:17:45.127005+05:30"
    },
    {
      "id": 4,
      "category": 1,
      "category_name": "Food",
      "amount": "900.00",
      "spent_on": "2026-09-12",
      "note": "Dinner with Rahul",
      "paid_by": 1,
      "paid_by_name": "priya (self)",
      "participants": [
        3,
        1
      ],
      "misc_amount": null,
      "misc_note": "",
      "items": [],
      "items_total": null,
      "unaccounted_amount": null,
      "is_balanced": true,
      "created_at": "2026-09-30T01:17:45.116408+05:30"
    },
    {
      "id": 3,
      "category": 2,
      "category_name": "Home & utilities",
      "amount": "1450.00",
      "spent_on": "2026-09-05",
      "note": "Electricity bill",
      "paid_by": 1,
      "paid_by_name": "priya (self)",
      "participants": [],
      "misc_amount": null,
      "misc_note": "",
      "items": [],
      "items_total": null,
      "unaccounted_amount": null,
      "is_balanced": true,
      "created_at": "2026-09-30T01:17:45.104378+05:30"
    }
  ],
  "count": 3,
  "total_amount": "3550.00"
}
```

### Filter expenses

`GET /expenses/` · Bearer token · success `200 OK`

`start` and `end` (inclusive), `category`, and `search`, which matches the note, line items and people. `page_size` sets the page length, up to 100.

**Request**

`GET /api/v1/expenses/?start=2026-09-01&end=2026-09-30&category=1&search=lunch`

**Response** `200 OK` · `application/json`

```json
{
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 5,
      "category": 1,
      "category_name": "Food",
      "amount": "1200.00",
      "spent_on": "2026-09-18",
      "note": "Team lunch",
      "paid_by": 1,
      "paid_by_name": "priya (self)",
      "participants": [
        4,
        3,
        1
      ],
      "misc_amount": "120.00",
      "misc_note": "GST and tip",
      "items": [
        {
          "id": 2,
          "name": "Pizza",
          "amount": "600.00",
          "shares": [
            {
              "participant": 1,
              "weight": 1
            },
            {
              "participant": 3,
              "weight": 1
            },
            {
              "participant": 4,
              "weight": 1
            }
          ]
        },
        {
          "id": 3,
          "name": "Drinks",
          "amount": "300.00",
          "shares": [
            {
              "participant": 3,
              "weight": 1
            },
            {
              "participant": 4,
              "weight": 1
            }
          ]
        },
        {
          "id": 4,
          "name": "Dessert",
          "amount": "180.00",
          "shares": [
            {
              "participant": 1,
              "weight": 1
            }
          ]
        }
      ],
      "items_total": "1080.00",
      "unaccounted_amount": "0.00",
      "is_balanced": true,
      "created_at": "2026-09-30T01:17:45.127005+05:30"
    }
  ],
  "count": 1,
  "total_amount": "1200.00"
}
```

**Invalid filter** → `400 Bad Request`

`GET /api/v1/expenses/?start=yesterday`

```json
{
  "start": [
    "Enter a valid date."
  ]
}
```

### Get an expense

`GET /expenses/{id}/` · Bearer token · success `200 OK`

One expense.

**Response** `200 OK` · `application/json`

```json
{
  "id": 5,
  "category": 1,
  "category_name": "Food",
  "amount": "1200.00",
  "spent_on": "2026-09-18",
  "note": "Team lunch",
  "paid_by": 1,
  "paid_by_name": "priya (self)",
  "participants": [
    4,
    3,
    1
  ],
  "misc_amount": "120.00",
  "misc_note": "GST and tip",
  "items": [
    {
      "id": 2,
      "name": "Pizza",
      "amount": "600.00",
      "shares": [
        {
          "participant": 1,
          "weight": 1
        },
        {
          "participant": 3,
          "weight": 1
        },
        {
          "participant": 4,
          "weight": 1
        }
      ]
    },
    {
      "id": 3,
      "name": "Drinks",
      "amount": "300.00",
      "shares": [
        {
          "participant": 3,
          "weight": 1
        },
        {
          "participant": 4,
          "weight": 1
        }
      ]
    },
    {
      "id": 4,
      "name": "Dessert",
      "amount": "180.00",
      "shares": [
        {
          "participant": 1,
          "weight": 1
        }
      ]
    }
  ],
  "items_total": "1080.00",
  "unaccounted_amount": "0.00",
  "is_balanced": true,
  "created_at": "2026-09-30T01:17:45.127005+05:30"
}
```

### Change part of an expense

`PATCH /expenses/{id}/` · Bearer token · success `200 OK`

Only the fields sent change. `items` left out keeps the line items; `items: []` removes them all.

**Request**

`PATCH /api/v1/expenses/4/`

```json
{
  "note": "Dinner with Rahul at Toit"
}
```

**Response** `200 OK` · `application/json`

```json
{
  "id": 4,
  "category": 1,
  "category_name": "Food",
  "amount": "900.00",
  "spent_on": "2026-09-12",
  "note": "Dinner with Rahul at Toit",
  "paid_by": 1,
  "paid_by_name": "priya (self)",
  "participants": [
    3,
    1
  ],
  "misc_amount": null,
  "misc_note": "",
  "items": [],
  "items_total": null,
  "unaccounted_amount": null,
  "is_balanced": true,
  "created_at": "2026-09-30T01:17:45.116408+05:30"
}
```

### Replace an expense

`PUT /expenses/{id}/` · Bearer token · success `200 OK`

PUT sends the whole expense again; anything left out of the lists is removed.

**Request**

`PUT /api/v1/expenses/3/`

```json
{
  "category": 2,
  "amount": "1520.00",
  "spent_on": "2026-09-05",
  "note": "Electricity bill (August)",
  "paid_by": 1,
  "include_self": false,
  "participants": [],
  "items": []
}
```

**Response** `200 OK` · `application/json`

```json
{
  "id": 3,
  "category": 2,
  "category_name": "Home & utilities",
  "amount": "1520.00",
  "spent_on": "2026-09-05",
  "note": "Electricity bill (August)",
  "paid_by": 1,
  "paid_by_name": "priya (self)",
  "participants": [],
  "misc_amount": null,
  "misc_note": "",
  "items": [],
  "items_total": null,
  "unaccounted_amount": null,
  "is_balanced": true,
  "created_at": "2026-09-30T01:17:45.104378+05:30"
}
```

### Split breakdown

`GET /expenses/{id}/split/` · Bearer token · success `200 OK`

The Split tab: each person's share of the lines (or of the even split) and of the misc amount. `rows` is empty when `is_balanced` is false.

**Response** `200 OK` · `application/json`

```json
{
  "expense": 5,
  "is_balanced": true,
  "unaccounted_amount": "0.00",
  "rows": [
    {
      "participant": {
        "id": 1,
        "name": "priya (self)",
        "is_self": true
      },
      "items": "380.00",
      "misc": "42.22",
      "total": "422.22"
    },
    {
      "participant": {
        "id": 4,
        "name": "Aisha K.",
        "is_self": false
      },
      "items": "350.00",
      "misc": "38.89",
      "total": "388.89"
    },
    {
      "participant": {
        "id": 3,
        "name": "Rahul",
        "is_self": false
      },
      "items": "350.00",
      "misc": "38.89",
      "total": "388.89"
    }
  ],
  "items_total": "1080.00",
  "misc_total": "120.00",
  "grand_total": "1200.00"
}
```

### Delete an expense

`DELETE /expenses/{id}/` · Bearer token · success `204 No Content`

Deletes the expense with its line items and shares. There is no undo.

**Response** `204 No Content`

*No body.*

---

## 4 · Dashboard

The Overview screen's numbers for a period.

### Spending summary

`GET /summary/` · Bearer token · success `200 OK`

Total, count, average, the biggest expense, totals per category with their share of the total, and the comparison period with the percentage change (null when the earlier period had no spending). The current month when no dates are given.

**Request**

`GET /api/v1/summary/?start=2026-09-01&end=2026-09-30`

**Response** `200 OK` · `application/json`

```json
{
  "start": "2026-09-01",
  "end": "2026-09-30",
  "total": "2100.00",
  "count": 2,
  "average": "1050.00",
  "biggest": {
    "id": 5,
    "amount": "1200.00",
    "spent_on": "2026-09-18",
    "note": "Team lunch",
    "category_name": "Food"
  },
  "by_category": [
    {
      "category": 1,
      "category_name": "Food",
      "total": "2100.00",
      "count": 2,
      "share": "100.00"
    }
  ],
  "previous": {
    "start": "2026-08-01",
    "end": "2026-08-31",
    "total": "0.00",
    "count": 0
  },
  "change_percent": null
}
```

---

## 5 · Balances

Who owes whom across all expenses, settling up, and the repayment history.

### Balances

`GET /balances/` · Bearer token · success `200 OK`

`owes_you` and `you_owe`, both as positive amounts, after repayments; `gross` is before them. All time unless `start`/`end` are given.

**Response** `200 OK` · `application/json`

```json
{
  "start": null,
  "end": null,
  "owes_you": [
    {
      "participant": {
        "id": 3,
        "name": "Rahul"
      },
      "amount": "838.89"
    },
    {
      "participant": {
        "id": 4,
        "name": "Aisha K."
      },
      "amount": "388.89"
    }
  ],
  "you_owe": [],
  "owes_you_total": "1227.78",
  "you_owe_total": "0.00",
  "gross": [
    {
      "participant": {
        "id": 3,
        "name": "Rahul"
      },
      "amount": "838.89"
    },
    {
      "participant": {
        "id": 4,
        "name": "Aisha K."
      },
      "amount": "388.89"
    }
  ]
}
```

### Settle up

`POST /balances/{participant_id}/settle/` · Bearer token · success `201 Created`

Records a repayment of the whole outstanding amount, in whichever direction it runs: positive when they paid you, negative when you paid them. Safe to retry.

**Request**

`POST /api/v1/balances/3/settle/`

```json
{
  "note": "Paid by UPI"
}
```

**Response** `201 Created` · `application/json`

```json
{
  "detail": "Recorded 838.89 back from Rahul.",
  "code": "settled",
  "settlement": {
    "id": 1,
    "participant": 3,
    "participant_name": "Rahul",
    "amount": "838.89",
    "note": "Paid by UPI",
    "settled_at": "2026-09-30T01:17:45.224629+05:30"
  }
}
```

**Nothing outstanding** → `200 OK`

`POST /api/v1/balances/3/settle/`

```json
{
  "note": "Clicked twice"
}
```

```json
{
  "detail": "Nothing outstanding.",
  "code": "nothing_outstanding",
  "settlement": null
}
```

### Repayment history

`GET /settlements/` · Bearer token · success `200 OK`

Every repayment recorded, newest first. `?participant=<id>` narrows it to one person.

**Response** `200 OK` · `application/json`

```json
{
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 1,
      "participant": 3,
      "participant_name": "Rahul",
      "amount": "838.89",
      "note": "Paid by UPI",
      "settled_at": "2026-09-30T01:17:45.224629+05:30"
    }
  ]
}
```

### Get a repayment

`GET /settlements/{id}/` · Bearer token · success `200 OK`

One repayment.

**Response** `200 OK` · `application/json`

```json
{
  "id": 1,
  "participant": 3,
  "participant_name": "Rahul",
  "amount": "838.89",
  "note": "Paid by UPI",
  "settled_at": "2026-09-30T01:17:45.224629+05:30"
}
```

---

## 6 · Exports

A CSV of expenses, built in the background: request it, wait for it, download it.

### Request an export

`POST /exports/` · Bearer token · success `202 Accepted`

Answers at once with the job, `pending`. A worker builds the CSV and emails a link. Dates default to the current month.

**Request**

`POST /api/v1/exports/`

```json
{
  "start": "2026-09-01",
  "end": "2026-09-30"
}
```

**Response** `202 Accepted` · `application/json`

```json
{
  "id": 1,
  "status": "pending",
  "start": "2026-09-01",
  "end": "2026-09-30",
  "row_count": 0,
  "error": "",
  "requested_at": "2026-09-30T01:17:45.238626+05:30",
  "completed_at": null,
  "download_url": null
}
```

### Wait for the export

`GET /exports/{id}/` · Bearer token · success `200 OK`

Poll every second or two until `status` is `complete` (then `download_url` is set) or `failed` (then `error` says why). This request repeats itself until then.

**Response** `200 OK` · `application/json`

```json
{
  "id": 1,
  "status": "complete",
  "start": "2026-09-01",
  "end": "2026-09-30",
  "row_count": 2,
  "error": "",
  "requested_at": "2026-09-30T01:17:45.238626+05:30",
  "completed_at": "2026-09-30T01:17:45.353157+05:30",
  "download_url": "http://127.0.0.1:8765/api/v1/exports/1/download/"
}
```

### List exports

`GET /exports/` · Bearer token · success `200 OK`

The user's exports, newest first.

**Response** `200 OK` · `application/json`

```json
{
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 1,
      "status": "complete",
      "start": "2026-09-01",
      "end": "2026-09-30",
      "row_count": 2,
      "error": "",
      "requested_at": "2026-09-30T01:17:45.238626+05:30",
      "completed_at": "2026-09-30T01:17:45.353157+05:30",
      "download_url": "http://127.0.0.1:8765/api/v1/exports/1/download/"
    }
  ]
}
```

### Download the export

`GET /exports/{id}/download/` · Bearer token · success `200 OK`

The CSV, as an attachment. The file name is in `Content-Disposition`.

**Response** `200 OK` · `text/csv`

```
Date,Category,Amount,Note
2026-09-12,Food,900.00,Dinner with Rahul at Toit
2026-09-18,Food,1200.00,Team lunch
```

**Not ready yet** → `409 Conflict`

`GET /api/v1/exports/2/download/`

```json
{
  "detail": "This export is not ready yet.",
  "code": "not_ready"
}
```

---

## 7 · Bill scans

Photograph a bill; a vision model reads it in the background; the user confirms a draft expense built from what it read.

### Upload a bill

`POST /bill-scans/` · Bearer token · success `202 Accepted`

A multipart upload with the photo in `image`: JPEG, PNG or WebP, at most 5 MB. Answers at once with the scan, `pending`.

On a server using a real vision model, upload a real photo of a bill; the sample image only works with the default `fake` reader.

**Request**

`POST /api/v1/bill-scans/`

`multipart/form-data` with the file in `image`.

**Response** `202 Accepted` · `application/json`

```json
{
  "id": 1,
  "status": "pending",
  "provider": "",
  "error": "",
  "result": {},
  "expense": null,
  "created_at": "2026-09-30T01:17:45.377447+05:30",
  "completed_at": null,
  "image_url": "http://127.0.0.1:8765/api/v1/bill-scans/1/image/"
}
```

**Not a photo** → `400 Bad Request`

`POST /api/v1/bill-scans/`

```json
{
  "image": [
    "Please upload a JPEG, PNG or WebP photo."
  ]
}
```

### Wait for the scan

`GET /bill-scans/{id}/` · Bearer token · success `200 OK`

Poll until `status` is `done` or `failed` (then `error` says why). Scans usually take a few seconds. This request repeats itself until then.

**Response** `200 OK` · `application/json`

```json
{
  "id": 1,
  "status": "done",
  "provider": "fake",
  "error": "",
  "result": {
    "merchant": "Test Cafe",
    "bill_date": null,
    "total": "450.00",
    "lines": [
      {
        "name": "Coffee",
        "amount": "150.00"
      },
      {
        "name": "Sandwich",
        "amount": "250.00"
      }
    ],
    "tax": "50.00",
    "category_hint": "food",
    "confidence": 0.9,
    "provider": "fake"
  },
  "expense": null,
  "created_at": "2026-09-30T01:17:45.377447+05:30",
  "completed_at": "2026-09-30T01:17:45.381550+05:30",
  "image_url": "http://127.0.0.1:8765/api/v1/bill-scans/1/image/"
}
```

### List scans

`GET /bill-scans/` · Bearer token · success `200 OK`

The user's scans, newest first.

**Response** `200 OK` · `application/json`

```json
{
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 1,
      "status": "done",
      "provider": "fake",
      "error": "",
      "result": {
        "merchant": "Test Cafe",
        "bill_date": null,
        "total": "450.00",
        "lines": [
          {
            "name": "Coffee",
            "amount": "150.00"
          },
          {
            "name": "Sandwich",
            "amount": "250.00"
          }
        ],
        "tax": "50.00",
        "category_hint": "food",
        "confidence": 0.9,
        "provider": "fake"
      },
      "expense": null,
      "created_at": "2026-09-30T01:17:45.377447+05:30",
      "completed_at": "2026-09-30T01:17:45.381550+05:30",
      "image_url": "http://127.0.0.1:8765/api/v1/bill-scans/1/image/"
    }
  ]
}
```

### Get the photo

`GET /bill-scans/{id}/image/` · Bearer token · success `200 OK`

The uploaded image, for showing beside the draft.

**Response** `200 OK` · `image/png`

```
<79 bytes of image/png>
```

### Get the draft expense

`GET /bill-scans/{id}/prefill/` · Bearer token · success `200 OK`

What the model read, shaped as an expense to show for correction and then send to `POST expenses/` with `bill_scan` unchanged. `category` is set only when the model's guess matches one of the user's categories. 409 when the scan is not finished, failed, or was already saved.

**Response** `200 OK` · `application/json`

```json
{
  "bill_scan": 1,
  "category": 1,
  "amount": "450.00",
  "spent_on": "2026-09-30",
  "note": "Test Cafe",
  "misc_amount": "50.00",
  "misc_note": "Tax / tip (scanned)",
  "items": [
    {
      "name": "Coffee",
      "amount": "150.00"
    },
    {
      "name": "Sandwich",
      "amount": "250.00"
    }
  ]
}
```

**Still scanning** → `409 Conflict`

`GET /api/v1/bill-scans/2/prefill/`

```json
{
  "detail": "Still scanning. Try again in a moment.",
  "code": "not_ready"
}
```

### Save the scanned bill

`POST /expenses/` · Bearer token · success `201 Created`

The corrected draft, sent as a normal expense. Each scan can be saved once; the scan then points at the expense.

**Request**

`POST /api/v1/expenses/`

```json
{
  "bill_scan": 1,
  "category": 1,
  "amount": "450.00",
  "spent_on": "2026-09-30",
  "note": "Test Cafe",
  "misc_amount": "50.00",
  "misc_note": "Tax / tip (scanned)",
  "items": [
    {
      "name": "Coffee",
      "amount": "150.00"
    },
    {
      "name": "Sandwich",
      "amount": "250.00"
    }
  ]
}
```

**Response** `201 Created` · `application/json`

```json
{
  "id": 6,
  "category": 1,
  "category_name": "Food",
  "amount": "450.00",
  "spent_on": "2026-09-30",
  "note": "Test Cafe",
  "paid_by": 1,
  "paid_by_name": "priya (self)",
  "participants": [],
  "misc_amount": "50.00",
  "misc_note": "Tax / tip (scanned)",
  "items": [
    {
      "id": 5,
      "name": "Coffee",
      "amount": "150.00",
      "shares": []
    },
    {
      "id": 6,
      "name": "Sandwich",
      "amount": "250.00",
      "shares": []
    }
  ],
  "items_total": "400.00",
  "unaccounted_amount": "0.00",
  "is_balanced": true,
  "created_at": "2026-09-30T01:17:45.404997+05:30"
}
```

**Already saved** → `400 Bad Request`

```json
{
  "bill_scan": [
    "This bill has already been saved as an expense."
  ]
}
```

---

## 8 · Tokens and signing out

Refreshing tokens and logging out. Run last: logging out ends the session the folders above use.

### Refresh the tokens

`POST /auth/refresh/` · no sign-in · success `200 OK`

Trade the refresh token for a new pair. **The old refresh token stops working at once**: store the new one. Call this when a request fails with 401 because the access token expired, then retry the request.

**Request**

`POST /api/v1/auth/refresh/`

```json
{
  "refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.<refresh token, valid 14 days>"
}
```

**Response** `200 OK` · `application/json`

```json
{
  "access": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.<access token, valid 30 minutes>",
  "refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.<refresh token, valid 14 days>"
}
```

**Refresh token already used** → `401 Unauthorized`

`POST /api/v1/auth/refresh/`

```json
{
  "refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.<refresh token, valid 14 days>"
}
```

```json
{
  "detail": "Token is blacklisted",
  "code": "token_not_valid"
}
```

### Log out

`POST /auth/logout/` · no sign-in · success `204 No Content`

Revokes this device's refresh token. Other devices stay signed in. Discard both tokens on the client.

**Request**

`POST /api/v1/auth/logout/`

```json
{
  "refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.<refresh token, valid 14 days>"
}
```

**Response** `204 No Content`

*No body.*

**Already logged out** → `400 Bad Request`

```json
{
  "detail": "That token is invalid or already revoked.",
  "code": "token_invalid"
}
```

---

## 9 · Account lifecycle (run by hand)

Sign-up, email verification, password change and reset, two-step sign-in, and deleting the account. **Not part of an automated run.** Verification and reset need the `uid` and `token` from a mailed link, which you copy into the collection variables `verify_uid`/`verify_token` or `reset_uid`/`reset_token` by hand; the two-step sign-in requests need a code from an authenticator app, which you compute from the `secret` the setup request returns; and the last request deletes the account.

### Sign up

`POST /auth/signup/` · no sign-in · success `201 Created`

Creates the account **inactive** and emails a verification link to the frontend's `/verify-email/<uid>/<token>` route. The account cannot log in until the link is used.

**Request**

`POST /api/v1/auth/signup/`

```json
{
  "username": "new.user",
  "email": "new.user@example.com",
  "password": "First-Pass-2026",
  "password_confirm": "First-Pass-2026"
}
```

**Response** `201 Created` · `application/json`

```json
{
  "detail": "Account created. Check your email for a link to activate it.",
  "code": "verification_sent"
}
```

**Password too weak** → `400 Bad Request`

The password rules are checked once both copies match; a mismatch is reported on `password_confirm` on its own.

`POST /api/v1/auth/signup/`

```json
{
  "username": "weak.user",
  "email": "weak@example.com",
  "password": "12345",
  "password_confirm": "12345"
}
```

```json
{
  "password": [
    "This password is too short. It must contain at least 8 characters.",
    "This password is too common.",
    "This password is entirely numeric."
  ]
}
```

### Verify the email

`POST /auth/verify-email/` · no sign-in · success `200 OK`

The frontend's `/verify-email/<uid>/<token>` page calls this with the two parts of its URL. It activates the account and signs it in: the response is the same as a login.

**Request**

`POST /api/v1/auth/verify-email/`

```json
{
  "uid": "NA",
  "token": "dfp29l-7f917520a99d194cdb08fa0e87891eb1"
}
```

**Response** `200 OK` · `application/json`

```json
{
  "access": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.<access token, valid 30 minutes>",
  "refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.<refresh token, valid 14 days>",
  "user": {
    "id": 4,
    "username": "new.user",
    "email": "new.user@example.com",
    "first_name": "",
    "last_name": "",
    "is_staff": false,
    "date_joined": "2026-09-30T01:17:45.450614+05:30",
    "last_login": "2026-09-30T01:17:45.470989+05:30",
    "self_participant": {
      "id": 6,
      "name": "new.user (self)"
    },
    "has_password": true
  }
}
```

**Link already used or expired** → `400 Bad Request`

```json
{
  "detail": "This link is invalid or has expired.",
  "code": "invalid_link"
}
```

### Change password

`POST /auth/password/change/` · Bearer token · success `200 OK`

Needs the current password. Every other device is signed out; this one gets a new token pair in the response and stays signed in.

**Request**

`POST /api/v1/auth/password/change/`

```json
{
  "old_password": "First-Pass-2026",
  "new_password": "Second-Pass-2026",
  "new_password_confirm": "Second-Pass-2026"
}
```

**Response** `200 OK` · `application/json`

```json
{
  "access": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.<access token, valid 30 minutes>",
  "refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.<refresh token, valid 14 days>",
  "user": {
    "id": 4,
    "username": "new.user",
    "email": "new.user@example.com",
    "first_name": "",
    "last_name": "",
    "is_staff": false,
    "date_joined": "2026-09-30T01:17:45.450614+05:30",
    "last_login": "2026-09-30T01:17:45.481649+05:30",
    "self_participant": {
      "id": 6,
      "name": "new.user (self)"
    },
    "has_password": true
  }
}
```

**Wrong current password** → `400 Bad Request`

`POST /api/v1/auth/password/change/`

```json
{
  "old_password": "wrong",
  "new_password": "Fourth-Pass-2026",
  "new_password_confirm": "Fourth-Pass-2026"
}
```

```json
{
  "old_password": [
    "Your old password was entered incorrectly. Please enter it again."
  ]
}
```

### Request a password reset

`POST /auth/password/reset/` · no sign-in · success `200 OK`

Emails a link to the frontend's `/reset-password/<uid>/<token>` route. The answer is the same whether or not an account uses the address, so it reveals nothing.

**Request**

`POST /api/v1/auth/password/reset/`

```json
{
  "email": "new.user@example.com"
}
```

**Response** `200 OK` · `application/json`

```json
{
  "detail": "If an account uses that email, a reset link is on its way.",
  "code": "reset_sent"
}
```

### Set a new password

`POST /auth/password/reset/confirm/` · no sign-in · success `200 OK`

The frontend's `/reset-password/<uid>/<token>` page sends the two parts of its URL with the new password. Every device is signed out; the user then logs in.

**Request**

`POST /api/v1/auth/password/reset/confirm/`

```json
{
  "uid": "NA",
  "token": "dfp29l-c5e6251ffd7104b6f4776eadec3e16f3",
  "new_password": "Third-Pass-2026",
  "new_password_confirm": "Third-Pass-2026"
}
```

**Response** `200 OK` · `application/json`

```json
{
  "detail": "Your password has been set. You can log in now.",
  "code": "password_set"
}
```

**Link already used or expired** → `400 Bad Request`

```json
{
  "detail": "This link is invalid or has expired.",
  "code": "invalid_link"
}
```

### Log in with the new password

`POST /auth/login/` · no sign-in · success `200 OK`

Signing in again after the reset.

**Request**

`POST /api/v1/auth/login/`

```json
{
  "username": "new.user",
  "password": "Third-Pass-2026"
}
```

**Response** `200 OK` · `application/json`

```json
{
  "access": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.<access token, valid 30 minutes>",
  "refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.<refresh token, valid 14 days>",
  "user": {
    "id": 4,
    "username": "new.user",
    "email": "new.user@example.com",
    "first_name": "",
    "last_name": "",
    "is_staff": false,
    "date_joined": "2026-09-30T01:17:45.450614+05:30",
    "last_login": "2026-09-30T01:17:45.502716+05:30",
    "self_participant": {
      "id": 6,
      "name": "new.user (self)"
    },
    "has_password": true
  }
}
```

### Check two-step sign-in status

`GET /auth/mfa/` · Bearer token · success `200 OK`

Whether two-step sign-in -- an authenticator-app code asked for after the password -- is on, and how many recovery codes are left.

**Response** `200 OK` · `application/json`

```json
{
  "enabled": false,
  "recovery_codes_left": 0
}
```

### Start two-step sign-in setup

`POST /auth/mfa/setup/` · Bearer token · success `200 OK`

A fresh secret and an `otpauth://` URI to build a QR code from. The account is not protected yet -- that needs the first code confirmed below. Calling this again before confirming replaces the pending secret.

**Response** `200 OK` · `application/json`

```json
{
  "secret": "GSAQ7H2EKPWGC2ISGFTSVSV27U7RKVVD",
  "otpauth_uri": "otpauth://totp/Expense%20Tracker%3Anew.user?secret=GSAQ7H2EKPWGC2ISGFTSVSV27U7RKVVD&issuer=Expense%20Tracker"
}
```

### Confirm and turn it on

`POST /auth/mfa/confirm/` · Bearer token · success `200 OK`

Confirms the pending device with a code from it. Returns ten recovery codes -- shown only this once, so store them somewhere safe -- and a fresh token pair: every other refresh token is revoked, the same as a password change.

**Request**

`POST /api/v1/auth/mfa/confirm/`

```json
{
  "code": "393828"
}
```

**Response** `200 OK` · `application/json`

```json
{
  "access": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.<access token, valid 30 minutes>",
  "refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.<refresh token, valid 14 days>",
  "user": {
    "id": 4,
    "username": "new.user",
    "email": "new.user@example.com",
    "first_name": "",
    "last_name": "",
    "is_staff": false,
    "date_joined": "2026-09-30T01:17:45.450614+05:30",
    "last_login": "2026-09-30T01:17:45.522119+05:30",
    "self_participant": {
      "id": 6,
      "name": "new.user (self)"
    },
    "has_password": true
  },
  "recovery_codes": [
    "QNEM7EG2X8",
    "MHAHBFRHVP",
    "ZWNAGEAG3A",
    "XA4HQYH6HJ",
    "F2NU4V3FXK",
    "88GCHSKC44",
    "48PXWM5UY3",
    "4H7UTFP8MB",
    "75BBW7JW93",
    "4S96VUR5DT"
  ]
}
```

**Wrong code** → `400 Bad Request`

`POST /api/v1/auth/mfa/confirm/`

```json
{
  "code": "000000"
}
```

```json
{
  "code": [
    "That code is wrong."
  ]
}
```

### Log in again

`POST /auth/login/` · no sign-in · success `200 OK`

With two-step sign-in on, a right password is not enough by itself: the response carries a ticket instead of tokens. Send it, and a code, to `auth/mfa/verify/`.

**Request**

`POST /api/v1/auth/login/`

```json
{
  "username": "new.user",
  "password": "Third-Pass-2026"
}
```

**Response** `200 OK` · `application/json`

```json
{
  "mfa_required": true,
  "mfa_ticket": "eyJ1c2VyX2lkIjo0LCJwd2ZwIjoiYTEwNjg2Y2E2YmNkMTYzMjQ5MTQ2YjM2NjAyZmMxMmZkNjM0ZGYxOTY1YTM0ZDllZDRmNTgwNjFkOGZkYzQ3ZiJ9:1xBdnl:7hRAlVPseK5eU2pmzziMjsZer94GhbI4BsgyD2dNsCA"
}
```

### Enter the two-step code

`POST /auth/mfa/verify/` · no sign-in · success `200 OK`

The ticket from the login above, plus a code -- from the authenticator app, or one of the recovery codes shown at setup. Either way the response is the token pair a plain login would have returned.

Five wrong codes for one account in 15 minutes lock it: 429 `rate_limited`. Whoever holds a ticket already knows the password, so this cannot be used to lock out someone else's account.

**Request**

`POST /api/v1/auth/mfa/verify/`

```json
{
  "mfa_ticket": "eyJ1c2VyX2lkIjo0LCJwd2ZwIjoiYTEwNjg2Y2E2YmNkMTYzMjQ5MTQ2YjM2NjAyZmMxMmZkNjM0ZGYxOTY1YTM0ZDllZDRmNTgwNjFkOGZkYzQ3ZiJ9:1xBdnl:7hRAlVPseK5eU2pmzziMjsZer94GhbI4BsgyD2dNsCA",
  "code": "393828"
}
```

**Response** `200 OK` · `application/json`

```json
{
  "access": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.<access token, valid 30 minutes>",
  "refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.<refresh token, valid 14 days>",
  "user": {
    "id": 4,
    "username": "new.user",
    "email": "new.user@example.com",
    "first_name": "",
    "last_name": "",
    "is_staff": false,
    "date_joined": "2026-09-30T01:17:45.450614+05:30",
    "last_login": "2026-09-30T01:17:45.533628+05:30",
    "self_participant": {
      "id": 6,
      "name": "new.user (self)"
    },
    "has_password": true
  }
}
```

**Wrong code** → `400 Bad Request`

`POST /api/v1/auth/mfa/verify/`

```json
{
  "mfa_ticket": "eyJ1c2VyX2lkIjo0LCJwd2ZwIjoiYTEwNjg2Y2E2YmNkMTYzMjQ5MTQ2YjM2NjAyZmMxMmZkNjM0ZGYxOTY1YTM0ZDllZDRmNTgwNjFkOGZkYzQ3ZiJ9:1xBdnl:7hRAlVPseK5eU2pmzziMjsZer94GhbI4BsgyD2dNsCA",
  "code": "000000"
}
```

```json
{
  "code": [
    "That code is wrong."
  ]
}
```

**Invalid or expired ticket** → `400 Bad Request`

`POST /api/v1/auth/mfa/verify/`

```json
{
  "mfa_ticket": "not-a-real-ticket",
  "code": "000000"
}
```

```json
{
  "detail": "That sign-in has expired. Log in again.",
  "code": "invalid_ticket"
}
```

### List signed-in devices

`GET /auth/devices/` · Bearer token · success `200 OK`

The devices this account is signed in on -- a web session, or an app holding a refresh token -- most recently seen first. An account may be signed in on two at a time (`MAX_SIGNED_IN_DEVICES`): a third sign-in signs the oldest one out, and its next `auth/refresh/` gets 401. `label` is the device's User-Agent. `current` is true only for the web session making the request; an API device cannot tell which one it is. The next request signs the other one out.

**Response** `200 OK` · `application/json`

```json
[
  {
    "id": 7,
    "kind": "api",
    "label": "",
    "created_at": "2026-09-30T01:17:45.530765+05:30",
    "last_seen_at": "2026-09-30T01:17:45.530769+05:30",
    "current": false
  },
  {
    "id": 6,
    "kind": "api",
    "label": "",
    "created_at": "2026-09-30T01:17:45.520013+05:30",
    "last_seen_at": "2026-09-30T01:17:45.520015+05:30",
    "current": false
  }
]
```

### Sign a device out

`POST /auth/devices/{id}/sign-out/` · Bearer token · success `204 No Content`

Ends that device: a web session is deleted; an API device's refresh token is revoked, so it gets 401 on its next refresh. Its current access token keeps working until it expires (up to 30 minutes). Another account's device id is 404.

**Response** `204 No Content`

*No body.*

**Not one of your devices** → `404 Not Found`

`POST /api/v1/auth/devices/999999/sign-out/`

```json
{
  "detail": "No such device."
}
```

### Get new recovery codes

`POST /auth/mfa/recovery-codes/` · Bearer token · success `200 OK`

Replaces the current set of ten with a fresh one. Needs a current authenticator code, not a recovery code -- otherwise spending the last one could mint ten more.

**Request**

`POST /api/v1/auth/mfa/recovery-codes/`

```json
{
  "code": "393828"
}
```

**Response** `200 OK` · `application/json`

```json
{
  "recovery_codes": [
    "6H2F6WTNU8",
    "Z8XQCSBRJ8",
    "SSW27SP45X",
    "A3YSNWWPN7",
    "H4ZHB4RD5R",
    "734JF2DY44",
    "3JFZAT2MS5",
    "PDF9WSJDUC",
    "FV3YU62V7Z",
    "NNNVBVVYUC"
  ]
}
```

### Turn off two-step sign-in

`POST /auth/mfa/disable/` · Bearer token · success `200 OK`

Needs the current password **and** a current code -- neither is enough on its own. Deletes the device and every recovery code, and revokes other refresh tokens.

**Request**

`POST /api/v1/auth/mfa/disable/`

```json
{
  "password": "Third-Pass-2026",
  "code": "393828"
}
```

**Response** `200 OK` · `application/json`

```json
{
  "access": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.<access token, valid 30 minutes>",
  "refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.<refresh token, valid 14 days>",
  "user": {
    "id": 4,
    "username": "new.user",
    "email": "new.user@example.com",
    "first_name": "",
    "last_name": "",
    "is_staff": false,
    "date_joined": "2026-09-30T01:17:45.450614+05:30",
    "last_login": "2026-09-30T01:17:45.577598+05:30",
    "self_participant": {
      "id": 6,
      "name": "new.user (self)"
    },
    "has_password": true
  }
}
```

**Wrong password** → `400 Bad Request`

`POST /api/v1/auth/mfa/disable/`

```json
{
  "password": "wrong",
  "code": "000000"
}
```

```json
{
  "password": [
    "Wrong password."
  ]
}
```

### Delete the account

`DELETE /me/` · Bearer token · success `204 No Content`

Deletes the account and **everything in it**, irreversibly. Confirm by sending the username as `confirm`, typed by the user.

**Request**

`DELETE /api/v1/me/`

```json
{
  "confirm": "new.user"
}
```

**Response** `204 No Content`

*No body.*

**Confirmation does not match** → `400 Bad Request`

`DELETE /api/v1/me/`

```json
{
  "confirm": "new"
}
```

```json
{
  "detail": "Type your username exactly to confirm.",
  "code": "confirm_mismatch"
}
```
