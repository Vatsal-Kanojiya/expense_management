# API reference

> **Generated** by `python manage.py build_api_docs` on 24 September 2026 from a real run of the API. Do not edit by hand: change the code or `expenses/api/journey.py`, then regenerate. Concepts that apply to every endpoint — tokens, errors, pagination, formats — are in [API_GUIDE.md](API_GUIDE.md).

Base URL in these examples: `http://127.0.0.1:8765/api/v1`. Tokens are shortened.

## Index

| # | Method | Path | What | Auth |
|---|---|---|---|---|
| 1 | `GET` | `/health/` | [Health check](#health-check) | — |
| 2 | `POST` | `/auth/login/` | [Log in](#log-in) | — |
| 3 | `GET` | `/me/` | [Your profile](#your-profile) | Bearer |
| 4 | `PATCH` | `/me/` | [Update your name](#update-your-name) | Bearer |
| 5 | `POST` | `/categories/` | [Create a category](#create-a-category) | Bearer |
| 6 | `POST` | `/categories/` | [Create another category](#create-another-category) | Bearer |
| 7 | `GET` | `/categories/` | [List categories](#list-categories) | Bearer |
| 8 | `GET` | `/categories/{id}/` | [Get a category](#get-a-category) | Bearer |
| 9 | `PATCH` | `/categories/{id}/` | [Rename a category](#rename-a-category) | Bearer |
| 10 | `PUT` | `/categories/{id}/` | [Replace a category](#replace-a-category) | Bearer |
| 11 | `POST` | `/categories/` | [Create a category to delete](#create-a-category-to-delete) | Bearer |
| 12 | `DELETE` | `/categories/{id}/` | [Delete a category](#delete-a-category) | Bearer |
| 13 | `POST` | `/participants/` | [Add a person](#add-a-person) | Bearer |
| 14 | `POST` | `/participants/` | [Add another person](#add-another-person) | Bearer |
| 15 | `GET` | `/participants/` | [List people](#list-people) | Bearer |
| 16 | `GET` | `/participants/{id}/` | [Get a person](#get-a-person) | Bearer |
| 17 | `PATCH` | `/participants/{id}/` | [Rename a person](#rename-a-person) | Bearer |
| 18 | `PUT` | `/participants/{id}/` | [Replace a person](#replace-a-person) | Bearer |
| 19 | `POST` | `/participants/` | [Add a person to remove](#add-a-person-to-remove) | Bearer |
| 20 | `DELETE` | `/participants/{id}/` | [Remove a person](#remove-a-person) | Bearer |
| 21 | `POST` | `/expenses/` | [Create an expense](#create-an-expense) | Bearer |
| 22 | `POST` | `/expenses/` | [Create an even split](#create-an-even-split) | Bearer |
| 23 | `POST` | `/expenses/` | [Create an itemised bill](#create-an-itemised-bill) | Bearer |
| 24 | `GET` | `/expenses/` | [List expenses](#list-expenses) | Bearer |
| 25 | `GET` | `/expenses/` | [Filter expenses](#filter-expenses) | Bearer |
| 26 | `GET` | `/expenses/{id}/` | [Get an expense](#get-an-expense) | Bearer |
| 27 | `PATCH` | `/expenses/{id}/` | [Change part of an expense](#change-part-of-an-expense) | Bearer |
| 28 | `PUT` | `/expenses/{id}/` | [Replace an expense](#replace-an-expense) | Bearer |
| 29 | `GET` | `/expenses/{id}/split/` | [Split breakdown](#split-breakdown) | Bearer |
| 30 | `DELETE` | `/expenses/{id}/` | [Delete an expense](#delete-an-expense) | Bearer |
| 31 | `GET` | `/summary/` | [Spending summary](#spending-summary) | Bearer |
| 32 | `GET` | `/balances/` | [Balances](#balances) | Bearer |
| 33 | `POST` | `/balances/{participant_id}/settle/` | [Settle up](#settle-up) | Bearer |
| 34 | `GET` | `/settlements/` | [Repayment history](#repayment-history) | Bearer |
| 35 | `GET` | `/settlements/{id}/` | [Get a repayment](#get-a-repayment) | Bearer |
| 36 | `POST` | `/exports/` | [Request an export](#request-an-export) | Bearer |
| 37 | `GET` | `/exports/{id}/` | [Wait for the export](#wait-for-the-export) | Bearer |
| 38 | `GET` | `/exports/` | [List exports](#list-exports) | Bearer |
| 39 | `GET` | `/exports/{id}/download/` | [Download the export](#download-the-export) | Bearer |
| 40 | `POST` | `/bill-scans/` | [Upload a bill](#upload-a-bill) | Bearer |
| 41 | `GET` | `/bill-scans/{id}/` | [Wait for the scan](#wait-for-the-scan) | Bearer |
| 42 | `GET` | `/bill-scans/` | [List scans](#list-scans) | Bearer |
| 43 | `GET` | `/bill-scans/{id}/image/` | [Get the photo](#get-the-photo) | Bearer |
| 44 | `GET` | `/bill-scans/{id}/prefill/` | [Get the draft expense](#get-the-draft-expense) | Bearer |
| 45 | `POST` | `/expenses/` | [Save the scanned bill](#save-the-scanned-bill) | Bearer |
| 46 | `POST` | `/auth/refresh/` | [Refresh the tokens](#refresh-the-tokens) | — |
| 47 | `POST` | `/auth/logout/` | [Log out](#log-out) | — |
| 48 | `POST` | `/auth/signup/` | [Sign up](#sign-up) | — |
| 49 | `POST` | `/auth/verify-email/` | [Verify the email](#verify-the-email) | — |
| 50 | `POST` | `/auth/password/change/` | [Change password](#change-password) | Bearer |
| 51 | `POST` | `/auth/password/reset/` | [Request a password reset](#request-a-password-reset) | — |
| 52 | `POST` | `/auth/password/reset/confirm/` | [Set a new password](#set-a-new-password) | — |
| 53 | `POST` | `/auth/login/` | [Log in with the new password](#log-in-with-the-new-password) | — |
| 54 | `DELETE` | `/me/` | [Delete the account](#delete-the-account) | Bearer |

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
    "date_joined": "2026-09-24T09:22:30.248546+05:30",
    "last_login": "2026-09-24T09:22:30.274920+05:30",
    "self_participant": {
      "id": 1,
      "name": "priya (self)"
    }
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
  "date_joined": "2026-09-24T09:22:30.248546+05:30",
  "last_login": "2026-09-24T09:22:30.274920+05:30",
  "self_participant": {
    "id": 1,
    "name": "priya (self)"
  }
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
  "date_joined": "2026-09-24T09:22:30.248546+05:30",
  "last_login": "2026-09-24T09:22:30.274920+05:30",
  "self_participant": {
    "id": 1,
    "name": "priya (self)"
  }
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
  "created_at": "2026-09-24T09:22:30.292983+05:30",
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
  "created_at": "2026-09-24T09:22:30.299528+05:30",
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
      "created_at": "2026-09-24T09:22:30.299528+05:30",
      "expense_count": 0,
      "total": null,
      "last_spent_on": null,
      "last_amount": null
    },
    {
      "id": 1,
      "name": "Food",
      "created_at": "2026-09-24T09:22:30.292983+05:30",
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
  "created_at": "2026-09-24T09:22:30.292983+05:30",
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
  "created_at": "2026-09-24T09:22:30.299528+05:30",
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
  "created_at": "2026-09-24T09:22:30.299528+05:30",
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
  "created_at": "2026-09-24T09:22:30.323582+05:30",
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
  "detail": "This is still used by 1 expenses, so it cannot be deleted.",
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
  "id": 2,
  "name": "Rahul",
  "is_self": false,
  "created_at": "2026-09-24T09:22:30.338411+05:30",
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
  "id": 3,
  "name": "Aisha",
  "is_self": false,
  "created_at": "2026-09-24T09:22:30.343965+05:30",
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
      "id": 3,
      "name": "Aisha",
      "is_self": false,
      "created_at": "2026-09-24T09:22:30.343965+05:30",
      "shared_count": 0,
      "item_count": 0
    },
    {
      "id": 2,
      "name": "Rahul",
      "is_self": false,
      "created_at": "2026-09-24T09:22:30.338411+05:30",
      "shared_count": 0,
      "item_count": 0
    },
    {
      "id": 1,
      "name": "priya (self)",
      "is_self": true,
      "created_at": "2026-09-24T09:22:30.277814+05:30",
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
  "id": 2,
  "name": "Rahul",
  "is_self": false,
  "created_at": "2026-09-24T09:22:30.338411+05:30",
  "shared_count": 0,
  "item_count": 0
}
```

### Rename a person

`PATCH /participants/{id}/` · Bearer token · success `200 OK`

PATCH changes only the fields sent.

**Request**

`PATCH /api/v1/participants/3/`

```json
{
  "name": "Aisha Khan"
}
```

**Response** `200 OK` · `application/json`

```json
{
  "id": 3,
  "name": "Aisha Khan",
  "is_self": false,
  "created_at": "2026-09-24T09:22:30.343965+05:30",
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

`PUT /api/v1/participants/3/`

```json
{
  "name": "Aisha K."
}
```

**Response** `200 OK` · `application/json`

```json
{
  "id": 3,
  "name": "Aisha K.",
  "is_self": false,
  "created_at": "2026-09-24T09:22:30.343965+05:30",
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
  "id": 4,
  "name": "Old colleague",
  "is_self": false,
  "created_at": "2026-09-24T09:22:30.363766+05:30",
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

`DELETE /api/v1/participants/2/`

```json
{
  "detail": "This is still used by 1 item shares, so it cannot be deleted.",
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
  "created_at": "2026-09-24T09:22:30.386917+05:30"
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

No line items, several participants: the amount is split equally between them, rounded to the paisa without losing any. Send `include_self: false` with the exact list the form shows (see the integration guide, section 7).

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
    2
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
    2,
    1
  ],
  "misc_amount": null,
  "misc_note": "",
  "items": [],
  "items_total": null,
  "unaccounted_amount": null,
  "is_balanced": true,
  "created_at": "2026-09-24T09:22:30.401486+05:30"
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
    2,
    3
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
          "participant": 2,
          "weight": 1
        },
        {
          "participant": 3,
          "weight": 1
        }
      ]
    },
    {
      "name": "Drinks",
      "amount": "300.00",
      "shares": [
        {
          "participant": 2,
          "weight": 1
        },
        {
          "participant": 3,
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
    3,
    2,
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
          "participant": 2,
          "weight": 1
        },
        {
          "participant": 3,
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
          "participant": 2,
          "weight": 1
        },
        {
          "participant": 3,
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
  "created_at": "2026-09-24T09:22:30.417059+05:30"
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
    2,
    3
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
          "participant": 2,
          "weight": 1
        },
        {
          "participant": 3,
          "weight": 1
        }
      ]
    },
    {
      "name": "Drinks",
      "amount": "300.00",
      "shares": [
        {
          "participant": 2,
          "weight": 1
        },
        {
          "participant": 3,
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
    2
  ],
  "items": [
    {
      "name": "Cake",
      "amount": "600.00",
      "shares": [
        {
          "participant": 2,
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
        3,
        2,
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
              "participant": 2,
              "weight": 1
            },
            {
              "participant": 3,
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
              "participant": 2,
              "weight": 1
            },
            {
              "participant": 3,
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
      "created_at": "2026-09-24T09:22:30.417059+05:30"
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
        2,
        1
      ],
      "misc_amount": null,
      "misc_note": "",
      "items": [],
      "items_total": null,
      "unaccounted_amount": null,
      "is_balanced": true,
      "created_at": "2026-09-24T09:22:30.401486+05:30"
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
      "created_at": "2026-09-24T09:22:30.386917+05:30"
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
        3,
        2,
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
              "participant": 2,
              "weight": 1
            },
            {
              "participant": 3,
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
              "participant": 2,
              "weight": 1
            },
            {
              "participant": 3,
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
      "created_at": "2026-09-24T09:22:30.417059+05:30"
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
    3,
    2,
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
          "participant": 2,
          "weight": 1
        },
        {
          "participant": 3,
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
          "participant": 2,
          "weight": 1
        },
        {
          "participant": 3,
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
  "created_at": "2026-09-24T09:22:30.417059+05:30"
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
    2,
    1
  ],
  "misc_amount": null,
  "misc_note": "",
  "items": [],
  "items_total": null,
  "unaccounted_amount": null,
  "is_balanced": true,
  "created_at": "2026-09-24T09:22:30.401486+05:30"
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
  "created_at": "2026-09-24T09:22:30.386917+05:30"
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
        "id": 3,
        "name": "Aisha K.",
        "is_self": false
      },
      "items": "350.00",
      "misc": "38.89",
      "total": "388.89"
    },
    {
      "participant": {
        "id": 2,
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
        "id": 2,
        "name": "Rahul"
      },
      "amount": "838.89"
    },
    {
      "participant": {
        "id": 3,
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
        "id": 2,
        "name": "Rahul"
      },
      "amount": "838.89"
    },
    {
      "participant": {
        "id": 3,
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

`POST /api/v1/balances/2/settle/`

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
    "participant": 2,
    "participant_name": "Rahul",
    "amount": "838.89",
    "note": "Paid by UPI",
    "settled_at": "2026-09-24T09:22:30.545798+05:30"
  }
}
```

**Nothing outstanding** → `200 OK`

`POST /api/v1/balances/2/settle/`

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
      "participant": 2,
      "participant_name": "Rahul",
      "amount": "838.89",
      "note": "Paid by UPI",
      "settled_at": "2026-09-24T09:22:30.545798+05:30"
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
  "participant": 2,
  "participant_name": "Rahul",
  "amount": "838.89",
  "note": "Paid by UPI",
  "settled_at": "2026-09-24T09:22:30.545798+05:30"
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
  "requested_at": "2026-09-24T09:22:30.558362+05:30",
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
  "requested_at": "2026-09-24T09:22:30.558362+05:30",
  "completed_at": "2026-09-24T09:22:30.607805+05:30",
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
      "requested_at": "2026-09-24T09:22:30.558362+05:30",
      "completed_at": "2026-09-24T09:22:30.607805+05:30",
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
  "created_at": "2026-09-24T09:22:30.638092+05:30",
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
  "created_at": "2026-09-24T09:22:30.638092+05:30",
  "completed_at": "2026-09-24T09:22:30.642320+05:30",
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
      "created_at": "2026-09-24T09:22:30.638092+05:30",
      "completed_at": "2026-09-24T09:22:30.642320+05:30",
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
  "spent_on": "2026-09-24",
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
  "spent_on": "2026-09-24",
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
  "spent_on": "2026-09-24",
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
  "created_at": "2026-09-24T09:22:30.663435+05:30"
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

Sign-up, email verification, password change and reset, and deleting the account. **Not part of an automated run.** Verification and reset need the `uid` and `token` from a mailed link, which you copy into the collection variables `verify_uid`/`verify_token` or `reset_uid`/`reset_token` by hand, and the last request deletes the account.

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

**Password too weak, and not repeated** → `400 Bad Request`

`POST /api/v1/auth/signup/`

```json
{
  "username": "weak.user",
  "email": "weak@example.com",
  "password": "12345",
  "password_confirm": "123456"
}
```

```json
{
  "password_confirm": [
    "The two password fields didn’t match."
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
  "uid": "Mw",
  "token": "dfekpi-35291c33bd4a0ee85edbdbfa8b8a87d5"
}
```

**Response** `200 OK` · `application/json`

```json
{
  "access": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.<access token, valid 30 minutes>",
  "refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.<refresh token, valid 14 days>",
  "user": {
    "id": 3,
    "username": "new.user",
    "email": "new.user@example.com",
    "first_name": "",
    "last_name": "",
    "is_staff": false,
    "date_joined": "2026-09-24T09:22:30.705172+05:30",
    "last_login": "2026-09-24T09:22:30.720721+05:30",
    "self_participant": {
      "id": 5,
      "name": "new.user (self)"
    }
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
    "id": 3,
    "username": "new.user",
    "email": "new.user@example.com",
    "first_name": "",
    "last_name": "",
    "is_staff": false,
    "date_joined": "2026-09-24T09:22:30.705172+05:30",
    "last_login": "2026-09-24T09:22:30.727250+05:30",
    "self_participant": {
      "id": 5,
      "name": "new.user (self)"
    }
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
  "uid": "Mw",
  "token": "dfekpi-b57a228afd14082681e5f72ef63ce2d1",
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
    "id": 3,
    "username": "new.user",
    "email": "new.user@example.com",
    "first_name": "",
    "last_name": "",
    "is_staff": false,
    "date_joined": "2026-09-24T09:22:30.705172+05:30",
    "last_login": "2026-09-24T09:22:30.739478+05:30",
    "self_participant": {
      "id": 5,
      "name": "new.user (self)"
    }
  }
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
