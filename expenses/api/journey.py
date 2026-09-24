"""The API's user journey, described once and rendered three ways.

``build_api_docs`` runs these steps against a throwaway database with the
test client, and from that single run writes the Postman collection (the
steps as runnable requests, the recorded responses as saved examples), the
Markdown API reference, and the OpenAPI snapshot (DECISIONS D48). Nothing
in an example is typed by hand: every response in the pack is one the API
actually returned.

A step is one request in the journey. Its ``capture`` map names values to
carry forward -- an id, a token -- as collection variables, exactly as the
Postman test scripts generated from it do. ``examples`` are extra requests,
mostly errors, recorded for the documentation and never part of the
runnable journey.
"""

import json
import re
import struct
import uuid
import zlib
from dataclasses import dataclass, field
from datetime import date
from http import HTTPStatus

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

API_PREFIX = "/api/v1"
DOC_BASE = "http://127.0.0.1:8765/api/v1"
FRONTEND = "http://localhost:5173"
TOKEN_PLACEHOLDERS = {
    "access": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.<access token, valid 30 minutes>",
    "refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.<refresh token, valid 14 days>",
}

# The account the journey signs in as: in real use, one an admin created.
MAIN_USER = {"username": "priya", "password": "Demo-Pass-2026", "email": "priya@example.com"}

# Defaults for the by-hand account folder, stored as collection variables.
ACCOUNT_VARIABLES = {
    "signup_username": "new.user",
    "signup_email": "new.user@example.com",
    "signup_password": "First-Pass-2026",
    "signup_new_password": "Second-Pass-2026",
    "reset_password": "Third-Pass-2026",
}


def sample_bill_png():
    """A small, valid PNG. The default `fake` provider reads any image the same way."""
    width = height = 16
    raw = b"".join(b"\x00" + b"\xf5\xf0\xe6" * width for _ in range(height))

    def chunk(kind, data):
        body = kind + data
        return (
            struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


# --- The vocabulary -----------------------------------------------------------


@dataclass(frozen=True)
class V:
    """A collection variable used as a bare JSON value: ``"category": {{category_id}}``."""

    name: str


@dataclass(frozen=True)
class Raw:
    """A whole request body taken from one variable: ``{{draft_expense}}``."""

    name: str


@dataclass(frozen=True)
class Upload:
    """A multipart upload of the sample bill."""

    field: str = "image"
    filename: str = "sample-bill.png"
    content_type: str = "image/png"


MISSING = object()
WHOLE_BODY = "$"


@dataclass
class Example:
    name: str
    expect: int
    method: str | None = None
    path: str | None = None
    body: object = MISSING
    public: bool | None = None
    setup: object = None  # callable(journey), just before the request
    teardown: object = None  # callable(journey), just after
    before_main: bool = False  # recorded before the step's own request
    note: str = ""


@dataclass
class Step:
    folder: str
    name: str
    method: str
    path: str
    expect: int
    description: str
    body: object = None
    public: bool = False
    capture: dict = field(default_factory=dict)
    poll: tuple | None = None  # (field, values that mean finished, the value that means success)
    before: object = None  # callable(journey), in-process only
    after: object = None  # callable(journey, response body), in-process only
    examples: list = field(default_factory=list)


# --- In-process helpers the journey needs -------------------------------------


def _read_link(route):
    """The uid and token from the newest mailed link to a frontend route."""
    match = re.search(rf"{FRONTEND}/{route}/([^/\s]+)/([^/\s]+)", mail.outbox[-1].body)
    return match.group(1), match.group(2)


def _after_signup(journey, body):
    journey.vars["verify_uid"], journey.vars["verify_token"] = _read_link("verify-email")


def _after_reset_request(journey, body):
    journey.vars["reset_uid"], journey.vars["reset_token"] = _read_link("reset-password")


def _make_unverified(journey):
    from django.contrib.auth import get_user_model

    get_user_model().objects.create_user(
        "not.verified", "not.verified@example.com", "Some-Pass-2026", is_active=False
    )


def _placeholder_expense(journey, share_with=None):
    from expenses.models import Category, Expense, ExpenseItem, ItemShare

    expense = Expense.objects.create(
        user=journey.user,
        category=Category.objects.get(pk=journey.vars["category_id"]),
        amount=10,
        spent_on=date(2026, 9, 1),
        note="placeholder",
    )
    if share_with is not None:
        item = ExpenseItem.objects.create(expense=expense, name="Tea", amount=10)
        ItemShare.objects.create(item=item, participant_id=journey.vars[share_with])


def _remove_placeholders(journey):
    from expenses.models import Expense

    Expense.objects.filter(user=journey.user, note="placeholder").delete()


def _pending_export(journey):
    from expenses.models import ExportJob

    job = ExportJob.objects.create(user=journey.user, start=date(2026, 9, 1), end=date(2026, 9, 30))
    journey.vars["pending_export_id"] = job.pk


def _pending_scan(journey):
    from expenses.models import BillScan

    scan = BillScan.objects.create(
        user=journey.user,
        image=SimpleUploadedFile("waiting.png", sample_bill_png(), "image/png"),
    )
    journey.vars["pending_scan_id"] = scan.pk


def _keep_refresh_token(journey):
    journey.vars["old_refresh_token"] = journey.vars["refresh_token"]


# --- The journey --------------------------------------------------------------

START = "0 · Start here"
CATEGORIES = "1 · Categories"
PEOPLE = "2 · People"
EXPENSES = "3 · Expenses"
DASHBOARD = "4 · Dashboard"
BALANCES = "5 · Balances"
EXPORTS = "6 · Exports"
SCANS = "7 · Bill scans"
SIGN_OUT = "8 · Tokens and signing out"
ACCOUNT = "9 · Account lifecycle (run by hand)"

FOLDER_NOTES = {
    START: "Check the server, sign in, read the profile. Run this folder first: it stores the "
    "access and refresh tokens every later request uses.",
    CATEGORIES: "The user's own categories. A category that still has expenses cannot be "
    "deleted (409).",
    PEOPLE: "The people bills are split with. The list includes the user themself, marked "
    "`is_self`, which can be neither renamed nor deleted.",
    EXPENSES: "A plain expense, an even split and an itemised bill with line items, shares and "
    "a tax/tip amount; then listing, filtering, editing, the split breakdown and deleting.",
    DASHBOARD: "The Overview screen's numbers for a period.",
    BALANCES: "Who owes whom across all expenses, settling up, and the repayment history.",
    EXPORTS: "A CSV of expenses, built in the background: request it, wait for it, download it.",
    SCANS: "Photograph a bill; a vision model reads it in the background; the user confirms a "
    "draft expense built from what it read.",
    SIGN_OUT: "Refreshing tokens and logging out. Run last: logging out ends the session the "
    "folders above use.",
    ACCOUNT: "Sign-up, email verification, password change and reset, and deleting the account. "
    "**Not part of an automated run.** Verification and reset need the `uid` and `token` from a "
    "mailed link, which you copy into the collection variables `verify_uid`/`verify_token` or "
    "`reset_uid`/`reset_token` by hand, and the last request deletes the account.",
}

SEPTEMBER = "start=2026-09-01&end=2026-09-30"

ITEMISED_BILL = {
    "category": V("category_id"),
    "amount": "1200.00",
    "spent_on": "2026-09-18",
    "note": "Team lunch",
    "paid_by": V("self_participant_id"),
    "include_self": False,
    "participants": [V("self_participant_id"), V("participant_id"), V("participant2_id")],
    "misc_amount": "120.00",
    "misc_note": "GST and tip",
    "items": [
        {
            "name": "Pizza",
            "amount": "600.00",
            "shares": [
                {"participant": V("self_participant_id"), "weight": 1},
                {"participant": V("participant_id"), "weight": 1},
                {"participant": V("participant2_id"), "weight": 1},
            ],
        },
        {
            "name": "Drinks",
            "amount": "300.00",
            "shares": [
                {"participant": V("participant_id"), "weight": 1},
                {"participant": V("participant2_id"), "weight": 1},
            ],
        },
        {
            "name": "Dessert",
            "amount": "180.00",
            "shares": [{"participant": V("self_participant_id"), "weight": 1}],
        },
    ],
}

STEPS = [
    # 0 · Start here ----------------------------------------------------------
    Step(
        START,
        "Health check",
        "GET",
        "/health/",
        200,
        "Whether the server is up and can reach its database. No sign-in needed. Answers 503 "
        "with `unavailable` when the database cannot be reached.",
        public=True,
    ),
    Step(
        START,
        "Log in",
        "POST",
        "/auth/login/",
        200,
        "Exchange a username and password for an **access** token (sent as `Authorization: "
        "Bearer <access>`, valid 30 minutes) and a **refresh** token (valid 14 days, traded at "
        "`auth/refresh/` for a new pair). The response also carries the profile, including "
        "`self_participant`: the id that stands for this user in splits.\n\n"
        "Ten failed attempts for one username from one address lock it for 15 minutes: 429 "
        "`rate_limited`.",
        body={"username": "{{username}}", "password": "{{password}}"},
        public=True,
        capture={
            "access_token": "access",
            "refresh_token": "refresh",
            "self_participant_id": "user.self_participant.id",
        },
        examples=[
            Example("Wrong password", 401, body={"username": "{{username}}", "password": "wrong"}),
            Example(
                "Email not verified yet",
                403,
                body={"username": "not.verified", "password": "Some-Pass-2026"},
                setup=_make_unverified,
                note="Said only when the password was right; otherwise a plain 401.",
            ),
        ],
    ),
    Step(
        START,
        "Your profile",
        "GET",
        "/me/",
        200,
        "The signed-in user. Call it when the app starts, to check that a stored token still "
        "works.",
        examples=[Example("Not signed in", 401, public=True)],
    ),
    Step(
        START,
        "Update your name",
        "PATCH",
        "/me/",
        200,
        "Only `first_name` and `last_name` can change; `username` and `email` are read-only "
        "and ignored if sent.",
        body={"first_name": "Priya", "last_name": "Sharma"},
    ),
    # 1 · Categories ------------------------------------------------------------
    Step(
        CATEGORIES,
        "Create a category",
        "POST",
        "/categories/",
        201,
        "Names are unique per user, ignoring case: `Food` and `food` are one category.",
        body={"name": "Food"},
        capture={"category_id": "id"},
        examples=[Example("Name already used", 400, body={"name": "food"})],
    ),
    Step(
        CATEGORIES,
        "Create another category",
        "POST",
        "/categories/",
        201,
        "A second category, used by the plain expense in folder 3.",
        body={"name": "Home"},
        capture={"home_category_id": "id"},
    ),
    Step(
        CATEGORIES,
        "List categories",
        "GET",
        "/categories/",
        200,
        "Alphabetical, with the Categories screen's usage columns: `expense_count`, `total`, "
        "`last_spent_on` and `last_amount`. The last three are null for an unused category.",
    ),
    Step(
        CATEGORIES,
        "Get a category",
        "GET",
        "/categories/{{category_id}}/",
        200,
        "One category with its usage columns. Another user's id is a 404, never a 403.",
    ),
    Step(
        CATEGORIES,
        "Rename a category",
        "PATCH",
        "/categories/{{home_category_id}}/",
        200,
        "PATCH changes only the fields sent.",
        body={"name": "Household"},
    ),
    Step(
        CATEGORIES,
        "Replace a category",
        "PUT",
        "/categories/{{home_category_id}}/",
        200,
        "PUT sends every writable field; for a category that is only `name`.",
        body={"name": "Home & utilities"},
    ),
    Step(
        CATEGORIES,
        "Create a category to delete",
        "POST",
        "/categories/",
        201,
        "A throwaway category for the delete that follows.",
        body={"name": "Travel"},
        capture={"temp_category_id": "id"},
    ),
    Step(
        CATEGORIES,
        "Delete a category",
        "DELETE",
        "/categories/{{temp_category_id}}/",
        204,
        "Only a category with no expenses can be deleted. Otherwise the answer is 409 "
        "`protected`, `blocking` says what is in the way, and nothing is deleted.",
        examples=[
            Example(
                "Still has expenses",
                409,
                path="/categories/{{category_id}}/",
                setup=_placeholder_expense,
                teardown=_remove_placeholders,
            )
        ],
    ),
    # 2 · People ------------------------------------------------------------------
    Step(
        PEOPLE,
        "Add a person",
        "POST",
        "/participants/",
        201,
        "Someone bills are split with. People are private to each user, and names are unique "
        "per user, ignoring case.",
        body={"name": "Rahul"},
        capture={"participant_id": "id"},
        examples=[Example("Name already used", 400, body={"name": "rahul"})],
    ),
    Step(
        PEOPLE,
        "Add another person",
        "POST",
        "/participants/",
        201,
        "A second person, for the itemised bill in folder 3.",
        body={"name": "Aisha"},
        capture={"participant2_id": "id"},
    ),
    Step(
        PEOPLE,
        "List people",
        "GET",
        "/participants/",
        200,
        "Alphabetical, **including the user themself** with `is_self: true`: the People screen "
        "hides that row, and the expense form needs its id. `shared_count` and `item_count` say "
        "how many expenses and line items name each person.",
    ),
    Step(PEOPLE, "Get a person", "GET", "/participants/{{participant_id}}/", 200, "One person."),
    Step(
        PEOPLE,
        "Rename a person",
        "PATCH",
        "/participants/{{participant2_id}}/",
        200,
        "PATCH changes only the fields sent.",
        body={"name": "Aisha Khan"},
        examples=[
            Example(
                "Renaming yourself",
                403,
                path="/participants/{{self_participant_id}}/",
                body={"name": "Someone else"},
            )
        ],
    ),
    Step(
        PEOPLE,
        "Replace a person",
        "PUT",
        "/participants/{{participant2_id}}/",
        200,
        "PUT sends every writable field; for a person that is only `name`.",
        body={"name": "Aisha K."},
    ),
    Step(
        PEOPLE,
        "Add a person to remove",
        "POST",
        "/participants/",
        201,
        "A throwaway person for the delete that follows.",
        body={"name": "Old colleague"},
        capture={"temp_participant_id": "id"},
    ),
    Step(
        PEOPLE,
        "Remove a person",
        "DELETE",
        "/participants/{{temp_participant_id}}/",
        204,
        "Refused with 409 when the person is on a line item or paid for an expense, and with "
        "403 for the user themself.",
        examples=[
            Example("Removing yourself", 403, path="/participants/{{self_participant_id}}/"),
            Example(
                "On a line item",
                409,
                path="/participants/{{participant_id}}/",
                setup=lambda journey: _placeholder_expense(journey, share_with="participant_id"),
                teardown=_remove_placeholders,
            ),
        ],
    ),
    # 3 · Expenses ------------------------------------------------------------------
    Step(
        EXPENSES,
        "Create an expense",
        "POST",
        "/expenses/",
        201,
        "The simplest expense: yours alone. `paid_by` may be left out and defaults to you. "
        "Amounts are strings with two decimals; dates are `YYYY-MM-DD`.",
        body={
            "category": V("home_category_id"),
            "amount": "1450.00",
            "spent_on": "2026-09-05",
            "note": "Electricity bill",
        },
        capture={"simple_expense_id": "id"},
        examples=[
            Example(
                "Invalid values",
                400,
                body={"category": V("home_category_id"), "amount": "0", "spent_on": "05/09/2026"},
            )
        ],
    ),
    Step(
        EXPENSES,
        "Create an even split",
        "POST",
        "/expenses/",
        201,
        "No line items, several participants: the amount is split equally between them, "
        "rounded to the paisa without losing any. Send `include_self: false` with the exact "
        "list the form shows (see the integration guide, section 7).",
        body={
            "category": V("category_id"),
            "amount": "900.00",
            "spent_on": "2026-09-12",
            "note": "Dinner with Rahul",
            "paid_by": V("self_participant_id"),
            "include_self": False,
            "participants": [V("self_participant_id"), V("participant_id")],
        },
        capture={"even_expense_id": "id"},
    ),
    Step(
        EXPENSES,
        "Create an itemised bill",
        "POST",
        "/expenses/",
        201,
        "Line items, each shared by the people who had it, and a tax/tip amount (`misc_amount`, "
        "which needs `misc_note`) split in proportion to what each person had. Lines plus misc "
        "should equal `amount`. When they are more than ₹1 apart the expense still saves, but "
        "`is_balanced` is false and it is left out of balances until corrected.",
        body=ITEMISED_BILL,
        capture={"expense_id": "id"},
        examples=[
            Example(
                "Tax/tip without a description",
                400,
                body={**ITEMISED_BILL, "misc_note": ""},
            ),
            Example(
                "A line nobody had, and you are not on the bill",
                400,
                body={
                    "category": V("category_id"),
                    "amount": "1000.00",
                    "spent_on": "2026-09-18",
                    "note": "Rahul's party",
                    "include_self": False,
                    "participants": [V("participant_id")],
                    "items": [
                        {
                            "name": "Cake",
                            "amount": "600.00",
                            "shares": [{"participant": V("participant_id"), "weight": 1}],
                        },
                        {"name": "Balloons", "amount": "400.00"},
                    ],
                },
                note="Without you on the bill, an unshared line would silently be charged to you.",
            ),
        ],
    ),
    Step(
        EXPENSES,
        "List expenses",
        "GET",
        "/expenses/",
        200,
        "Newest date first, 25 per page; follow `next` for more. `count` and `total_amount` "
        "cover every page. All time unless filtered.",
    ),
    Step(
        EXPENSES,
        "Filter expenses",
        "GET",
        "/expenses/?" + SEPTEMBER + "&category={{category_id}}&search=lunch",
        200,
        "`start` and `end` (inclusive), `category`, and `search`, which matches the note, line "
        "items and people. `page_size` sets the page length, up to 100.",
        examples=[Example("Invalid filter", 400, path="/expenses/?start=yesterday")],
    ),
    Step(EXPENSES, "Get an expense", "GET", "/expenses/{{expense_id}}/", 200, "One expense."),
    Step(
        EXPENSES,
        "Change part of an expense",
        "PATCH",
        "/expenses/{{even_expense_id}}/",
        200,
        "Only the fields sent change. `items` left out keeps the line items; `items: []` "
        "removes them all.",
        body={"note": "Dinner with Rahul at Toit"},
    ),
    Step(
        EXPENSES,
        "Replace an expense",
        "PUT",
        "/expenses/{{simple_expense_id}}/",
        200,
        "PUT sends the whole expense again; anything left out of the lists is removed.",
        body={
            "category": V("home_category_id"),
            "amount": "1520.00",
            "spent_on": "2026-09-05",
            "note": "Electricity bill (August)",
            "paid_by": V("self_participant_id"),
            "include_self": False,
            "participants": [],
            "items": [],
        },
    ),
    Step(
        EXPENSES,
        "Split breakdown",
        "GET",
        "/expenses/{{expense_id}}/split/",
        200,
        "The Split tab: each person's share of the lines (or of the even split) and of the misc "
        "amount. `rows` is empty when `is_balanced` is false.",
    ),
    Step(
        EXPENSES,
        "Delete an expense",
        "DELETE",
        "/expenses/{{simple_expense_id}}/",
        204,
        "Deletes the expense with its line items and shares. There is no undo.",
    ),
    # 4 · Dashboard ------------------------------------------------------------------
    Step(
        DASHBOARD,
        "Spending summary",
        "GET",
        "/summary/?" + SEPTEMBER,
        200,
        "Total, count, average, the biggest expense, totals per category with their share of "
        "the total, and the comparison period with the percentage change (null when the "
        "earlier period had no spending). The current month when no dates are given.",
    ),
    # 5 · Balances --------------------------------------------------------------------
    Step(
        BALANCES,
        "Balances",
        "GET",
        "/balances/",
        200,
        "`owes_you` and `you_owe`, both as positive amounts, after repayments; `gross` is "
        "before them. All time unless `start`/`end` are given.",
    ),
    Step(
        BALANCES,
        "Settle up",
        "POST",
        "/balances/{{participant_id}}/settle/",
        201,
        "Records a repayment of the whole outstanding amount, in whichever direction it runs: "
        "positive when they paid you, negative when you paid them. Safe to retry.",
        body={"note": "Paid by UPI"},
        capture={"settlement_id": "settlement.id"},
        examples=[Example("Nothing outstanding", 200, body={"note": "Clicked twice"})],
    ),
    Step(
        BALANCES,
        "Repayment history",
        "GET",
        "/settlements/",
        200,
        "Every repayment recorded, newest first. `?participant=<id>` narrows it to one person.",
    ),
    Step(
        BALANCES,
        "Get a repayment",
        "GET",
        "/settlements/{{settlement_id}}/",
        200,
        "One repayment.",
    ),
    # 6 · Exports ----------------------------------------------------------------------
    Step(
        EXPORTS,
        "Request an export",
        "POST",
        "/exports/",
        202,
        "Answers at once with the job, `pending`. A worker builds the CSV and emails a link. "
        "Dates default to the current month.",
        body={"start": "2026-09-01", "end": "2026-09-30"},
        capture={"export_id": "id"},
    ),
    Step(
        EXPORTS,
        "Wait for the export",
        "GET",
        "/exports/{{export_id}}/",
        200,
        "Poll every second or two until `status` is `complete` (then `download_url` is set) or "
        "`failed` (then `error` says why). This request repeats itself until then.",
        poll=("status", ("complete", "failed"), "complete"),
    ),
    Step(EXPORTS, "List exports", "GET", "/exports/", 200, "The user's exports, newest first."),
    Step(
        EXPORTS,
        "Download the export",
        "GET",
        "/exports/{{export_id}}/download/",
        200,
        "The CSV, as an attachment. The file name is in `Content-Disposition`.",
        examples=[
            Example(
                "Not ready yet",
                409,
                path="/exports/{{pending_export_id}}/download/",
                setup=_pending_export,
            )
        ],
    ),
    # 7 · Bill scans ---------------------------------------------------------------------
    Step(
        SCANS,
        "Upload a bill",
        "POST",
        "/bill-scans/",
        202,
        "A multipart upload with the photo in `image`: JPEG, PNG or WebP, at most 5 MB. "
        "Answers at once with the scan, `pending`.\n\nOn a server using a real vision model, "
        "upload a real photo of a bill; the sample image only works with the default `fake` "
        "reader.",
        body=Upload(),
        capture={"bill_scan_id": "id"},
        examples=[
            Example(
                "Not a photo",
                400,
                body=Upload(filename="bill.pdf", content_type="application/pdf"),
            )
        ],
    ),
    Step(
        SCANS,
        "Wait for the scan",
        "GET",
        "/bill-scans/{{bill_scan_id}}/",
        200,
        "Poll until `status` is `done` or `failed` (then `error` says why). Scans usually take a "
        "few seconds. This request repeats itself until then.",
        poll=("status", ("done", "failed"), "done"),
    ),
    Step(SCANS, "List scans", "GET", "/bill-scans/", 200, "The user's scans, newest first."),
    Step(
        SCANS,
        "Get the photo",
        "GET",
        "/bill-scans/{{bill_scan_id}}/image/",
        200,
        "The uploaded image, for showing beside the draft.",
    ),
    Step(
        SCANS,
        "Get the draft expense",
        "GET",
        "/bill-scans/{{bill_scan_id}}/prefill/",
        200,
        "What the model read, shaped as an expense to show for correction and then send to "
        "`POST expenses/` with `bill_scan` unchanged. `category` is set only when the model's "
        "guess matches one of the user's categories. 409 when the scan is not finished, failed, "
        "or was already saved.",
        capture={"draft_expense": WHOLE_BODY},
        examples=[
            Example(
                "Still scanning",
                409,
                path="/bill-scans/{{pending_scan_id}}/prefill/",
                setup=_pending_scan,
            )
        ],
    ),
    Step(
        SCANS,
        "Save the scanned bill",
        "POST",
        "/expenses/",
        201,
        "The corrected draft, sent as a normal expense. Each scan can be saved once; the scan "
        "then points at the expense.",
        body=Raw("draft_expense"),
        examples=[Example("Already saved", 400)],
    ),
    # 8 · Tokens and signing out -----------------------------------------------------------
    Step(
        SIGN_OUT,
        "Refresh the tokens",
        "POST",
        "/auth/refresh/",
        200,
        "Trade the refresh token for a new pair. **The old refresh token stops working at "
        "once**: store the new one. Call this when a request fails with 401 because the access "
        "token expired, then retry the request.",
        body={"refresh": "{{refresh_token}}"},
        public=True,
        before=_keep_refresh_token,
        capture={"access_token": "access", "refresh_token": "refresh"},
        examples=[
            Example(
                "Refresh token already used",
                401,
                body={"refresh": "{{old_refresh_token}}"},
            )
        ],
    ),
    Step(
        SIGN_OUT,
        "Log out",
        "POST",
        "/auth/logout/",
        204,
        "Revokes this device's refresh token. Other devices stay signed in. Discard both tokens "
        "on the client.",
        body={"refresh": "{{refresh_token}}"},
        public=True,
        examples=[Example("Already logged out", 400)],
    ),
    # 9 · Account lifecycle (run by hand) ---------------------------------------------------
    Step(
        ACCOUNT,
        "Sign up",
        "POST",
        "/auth/signup/",
        201,
        "Creates the account **inactive** and emails a verification link to the frontend's "
        "`/verify-email/<uid>/<token>` route. The account cannot log in until the link is used.",
        body={
            "username": "{{signup_username}}",
            "email": "{{signup_email}}",
            "password": "{{signup_password}}",
            "password_confirm": "{{signup_password}}",
        },
        public=True,
        after=_after_signup,
        examples=[
            Example(
                "Password too weak, and not repeated",
                400,
                body={
                    "username": "weak.user",
                    "email": "weak@example.com",
                    "password": "12345",
                    "password_confirm": "123456",
                },
            )
        ],
    ),
    Step(
        ACCOUNT,
        "Verify the email",
        "POST",
        "/auth/verify-email/",
        200,
        "The frontend's `/verify-email/<uid>/<token>` page calls this with the two parts of its "
        "URL. It activates the account and signs it in: the response is the same as a login.",
        body={"uid": "{{verify_uid}}", "token": "{{verify_token}}"},
        public=True,
        capture={"access_token": "access", "refresh_token": "refresh"},
        examples=[Example("Link already used or expired", 400)],
    ),
    Step(
        ACCOUNT,
        "Change password",
        "POST",
        "/auth/password/change/",
        200,
        "Needs the current password. Every other device is signed out; this one gets a new "
        "token pair in the response and stays signed in.",
        body={
            "old_password": "{{signup_password}}",
            "new_password": "{{signup_new_password}}",
            "new_password_confirm": "{{signup_new_password}}",
        },
        capture={"access_token": "access", "refresh_token": "refresh"},
        examples=[
            Example(
                "Wrong current password",
                400,
                body={
                    "old_password": "wrong",
                    "new_password": "Fourth-Pass-2026",
                    "new_password_confirm": "Fourth-Pass-2026",
                },
            )
        ],
    ),
    Step(
        ACCOUNT,
        "Request a password reset",
        "POST",
        "/auth/password/reset/",
        200,
        "Emails a link to the frontend's `/reset-password/<uid>/<token>` route. The answer is "
        "the same whether or not an account uses the address, so it reveals nothing.",
        body={"email": "{{signup_email}}"},
        public=True,
        after=_after_reset_request,
    ),
    Step(
        ACCOUNT,
        "Set a new password",
        "POST",
        "/auth/password/reset/confirm/",
        200,
        "The frontend's `/reset-password/<uid>/<token>` page sends the two parts of its URL "
        "with the new password. Every device is signed out; the user then logs in.",
        body={
            "uid": "{{reset_uid}}",
            "token": "{{reset_token}}",
            "new_password": "{{reset_password}}",
            "new_password_confirm": "{{reset_password}}",
        },
        public=True,
        examples=[Example("Link already used or expired", 400)],
    ),
    Step(
        ACCOUNT,
        "Log in with the new password",
        "POST",
        "/auth/login/",
        200,
        "Signing in again after the reset.",
        body={"username": "{{signup_username}}", "password": "{{reset_password}}"},
        public=True,
        capture={"access_token": "access", "refresh_token": "refresh"},
    ),
    Step(
        ACCOUNT,
        "Delete the account",
        "DELETE",
        "/me/",
        204,
        "Deletes the account and **everything in it**, irreversibly. Confirm by sending the "
        "username as `confirm`, typed by the user.",
        body={"confirm": "{{signup_username}}"},
        examples=[
            Example("Confirmation does not match", 400, body={"confirm": "new"}, before_main=True)
        ],
    ),
]


# --- Running it ------------------------------------------------------------------


class JourneyError(AssertionError):
    pass


def _resolve(value, variables):
    if isinstance(value, V):
        return variables[value.name]
    if isinstance(value, Raw):
        return variables[value.name]
    if isinstance(value, str):
        return re.sub(r"\{\{(\w+)\}\}", lambda match: str(variables[match.group(1)]), value)
    if isinstance(value, dict):
        return {key: _resolve(item, variables) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve(item, variables) for item in value]
    return value


def _dig(data, path):
    if path == WHOLE_BODY:
        return data
    for part in path.split("."):
        data = data[part]
    return data


def scrub(value):
    """Make a recorded body safe and readable: no live tokens, public-looking URLs."""
    if isinstance(value, dict):
        return {
            key: TOKEN_PLACEHOLDERS[key] if key in TOKEN_PLACEHOLDERS else scrub(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [scrub(item) for item in value]
    if isinstance(value, str):
        return value.replace("http://testserver" + API_PREFIX, DOC_BASE)
    return value


class Journey:
    """Drives STEPS through the test client and keeps what came back."""

    def __init__(self, user):
        self.user = user
        self.client = APIClient()
        self.vars = {**MAIN_USER, **ACCOUNT_VARIABLES}
        self.records = []

    def send(self, method, path, body, public):
        url = API_PREFIX + _resolve(path, self.vars)
        extra = {} if public else {"HTTP_AUTHORIZATION": f"Bearer {self.vars['access_token']}"}
        call = getattr(self.client, method.lower())

        if isinstance(body, Upload):
            upload = SimpleUploadedFile(body.filename, sample_bill_png(), body.content_type)
            response = call(url, {body.field: upload}, format="multipart", **extra)
            sent = {body.field: f"<file {body.filename}, {body.content_type}>"}
        elif body is None:
            response = call(url, **extra)
            sent = None
        else:
            sent = _resolve(body, self.vars)
            response = call(url, sent, format="json", **extra)

        return url, sent, response

    @staticmethod
    def read(response):
        content_type = response.get("Content-Type", "")
        if response.status_code == 204:
            return content_type, None
        if "json" in content_type:
            return content_type, response.json()
        content = b"".join(response.streaming_content) if response.streaming else response.content
        if content_type.startswith("text/"):
            return content_type, content.decode()
        return content_type, f"<{len(content)} bytes of {content_type}>"

    def record(self, step, method, path, body, public, expect):
        url, sent, response = self.send(method, path, body, public)
        content_type, received = self.read(response)
        if response.status_code != expect:
            raise JourneyError(
                f"{step.name}: {method} {url} answered {response.status_code}, "
                f"expected {expect}: {received}"
            )
        return {
            "method": method,
            "url": url,
            "body": sent,
            "status": response.status_code,
            "content_type": content_type,
            "response": received,
        }

    def run(self):
        for step in STEPS:
            if step.before:
                step.before(self)

            early = [self.example(step, e) for e in step.examples if e.before_main]
            main = self.record(step, step.method, step.path, step.body, step.public, step.expect)
            body = main["response"]

            if step.poll and body.get(step.poll[0]) != step.poll[2]:
                raise JourneyError(f"{step.name}: finished as {body.get(step.poll[0])}")
            for variable, path in step.capture.items():
                self.vars[variable] = _dig(body, path)
            if step.after:
                step.after(self, body)

            late = [self.example(step, e) for e in step.examples if not e.before_main]
            self.records.append({"step": step, "main": main, "examples": early + late})
        return self.records

    def example(self, step, example):
        if example.setup:
            example.setup(self)
        recorded = self.record(
            step,
            example.method or step.method,
            example.path or step.path,
            step.body if example.body is MISSING else example.body,
            step.public if example.public is None else example.public,
            example.expect,
        )
        if example.teardown:
            example.teardown(self)
        return {"example": example, **recorded}


# --- Rendering: shared ---------------------------------------------------------------


def template_path(path):
    """`/categories/{{home_category_id}}/?x=1` -> `/categories/{id}/`, as the schema names it."""
    route = re.sub(r"\{\{\w+\}\}", "{id}", path.split("?")[0])
    return route.replace("/balances/{id}/", "/balances/{participant_id}/")


def schema_path(path):
    """Any path, with its ids generalised, to compare against the OpenAPI schema."""
    return re.sub(r"\{\{?\w+\}?\}", "{}", path.split("?")[0])


def status_line(code):
    return f"{code} {HTTPStatus(code).phrase}"


def as_json(value):
    return json.dumps(value, indent=2, ensure_ascii=False)


def _raw_body(body):
    """A Postman raw body: variables stay variables, ids unquoted."""
    if isinstance(body, Raw):
        return "{{" + body.name + "}}"

    def mark(value):
        if isinstance(value, V):
            return f"@@{value.name}@@"
        if isinstance(value, dict):
            return {key: mark(item) for key, item in value.items()}
        if isinstance(value, list):
            return [mark(item) for item in value]
        return value

    return re.sub(r'"@@(\w+)@@"', r"{{\1}}", as_json(mark(body)))


# --- Rendering: Postman ---------------------------------------------------------------


def _postman_url(path):
    raw = "{{baseUrl}}" + path
    route, _, query = path.partition("?")
    # Postman rebuilds the URL from `path`, not `raw`, and the trailing slash
    # survives only as a final empty segment. Dropping it sends
    # /auth/login instead of /auth/login/, which Django cannot redirect for
    # a POST -- found by running the collection in Newman.
    url = {"raw": raw, "host": ["{{baseUrl}}"], "path": route.split("/")[1:]}
    if query:
        url["query"] = [
            {"key": key, "value": value}
            for key, _, value in (pair.partition("=") for pair in query.split("&"))
        ]
    return url


def _postman_request(method, path, body, public, description=None):
    request = {"method": method, "header": [], "url": _postman_url(path)}
    if public:
        request["auth"] = {"type": "noauth"}
    if isinstance(body, Upload):
        request["body"] = {
            "mode": "formdata",
            "formdata": [{"key": body.field, "type": "file", "src": body.filename}],
        }
    elif body is not None:
        request["header"].append({"key": "Content-Type", "value": "application/json"})
        request["body"] = {
            "mode": "raw",
            "raw": _raw_body(body),
            "options": {"raw": {"language": "json"}},
        }
    if description:
        request["description"] = description
    return request


def _test_script(step):
    lines = [
        f'pm.test("{status_line(step.expect)}", function () {{',
        f"    pm.response.to.have.status({step.expect});",
        "});",
    ]
    if step.poll:
        name, finished, success = step.poll
        lines += [
            "const json = pm.response.json();",
            f"const finished = {json.dumps(list(finished))};",
            'const tries = Number(pm.collectionVariables.get("poll_tries") || 0);',
            f"if (!finished.includes(json.{name}) && tries < 30) {{",
            '    pm.collectionVariables.set("poll_tries", tries + 1);',
            "    setTimeout(function () {}, 1000);",
            "    postman.setNextRequest(pm.info.requestName);",
            "} else {",
            '    pm.collectionVariables.set("poll_tries", 0);',
            f'    pm.test("Finished as {success}", function () {{',
            f'        pm.expect(json.{name}).to.eql("{success}");',
            "    });",
            "}",
        ]
    if step.capture:
        lines.append("const body = pm.response.json();")
        for variable, path in step.capture.items():
            value = "JSON.stringify(body)" if path == WHOLE_BODY else "body." + path
            lines.append(f'pm.collectionVariables.set("{variable}", {value});')
    return lines


def _postman_example(name, step, recorded):
    content_type = recorded["content_type"]
    body = recorded["response"]
    text = "" if body is None else (as_json(scrub(body)) if "json" in content_type else body)
    path = recorded["url"][len(API_PREFIX) :]
    sent = recorded["body"]
    original = _postman_request(
        recorded["method"],
        path,
        Upload() if isinstance(step.body, Upload) and sent else None,
        False,
    )
    if sent is not None and not isinstance(step.body, Upload):
        original["header"].append({"key": "Content-Type", "value": "application/json"})
        original["body"] = {
            "mode": "raw",
            "raw": as_json(scrub(sent)),
            "options": {"raw": {"language": "json"}},
        }
    return {
        "name": name,
        "originalRequest": original,
        "status": HTTPStatus(recorded["status"]).phrase,
        "code": recorded["status"],
        "_postman_previewlanguage": "json" if "json" in content_type else "text",
        "header": [{"key": "Content-Type", "value": content_type}] if content_type else [],
        "body": text,
    }


def postman_collection(records):
    folders = {}
    for record in records:
        step = record["step"]
        description = step.description
        if step.poll:
            description += "\n\n*In the Postman runner this request repeats until finished.*"
        item = {
            "name": step.name,
            "event": [
                {
                    "listen": "test",
                    "script": {"type": "text/javascript", "exec": _test_script(step)},
                }
            ],
            "request": _postman_request(
                step.method, step.path, step.body, step.public, description
            ),
            "response": [
                _postman_example(status_line(record["main"]["status"]), step, record["main"])
            ]
            + [
                _postman_example(f"{e['example'].name} ({status_line(e['status'])})", step, e)
                for e in record["examples"]
            ],
        }
        folders.setdefault(step.folder, []).append(item)

    captured = sorted(
        {name for step in STEPS for name in step.capture}
        | {
            "old_refresh_token",
            "verify_uid",
            "verify_token",
            "reset_uid",
            "reset_token",
            "poll_tries",
        }
    )
    return {
        "info": {
            "_postman_id": str(uuid.uuid5(uuid.NAMESPACE_URL, "expense-tracker-api-v1")),
            "name": "Expense Tracker API v1",
            "description": COLLECTION_DESCRIPTION,
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "auth": {
            "type": "bearer",
            "bearer": [{"key": "token", "value": "{{access_token}}", "type": "string"}],
        },
        "variable": [{"key": "baseUrl", "value": DOC_BASE}]
        + [{"key": key, "value": value} for key, value in ACCOUNT_VARIABLES.items()]
        + [{"key": name, "value": ""} for name in captured],
        "item": [
            {"name": folder, "description": FOLDER_NOTES[folder], "item": items}
            for folder, items in folders.items()
        ],
    }


def postman_environment(name, base_url):
    return {
        "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"expense-tracker-env-{name}")),
        "name": f"Expense Tracker · {name}",
        "values": [
            {"key": "baseUrl", "value": base_url, "type": "default", "enabled": True},
            {"key": "username", "value": "", "type": "default", "enabled": True},
            {"key": "password", "value": "", "type": "secret", "enabled": True},
        ],
        "_postman_variable_scope": "environment",
    }


COLLECTION_DESCRIPTION = """\
Every endpoint of the Expense Tracker API, as a journey you can run, with the \
responses the API actually returned saved as examples under each request.

**Set up**

1. Import this collection and one of the environments beside it \
(`local` for the Docker stack on your machine, `hosted` for the live server).
2. In the environment, set `username` and `password` to an account you were given.
3. Select the environment, then run folder **0 · Start here**. It logs in and \
stores the tokens every other request uses.

**Run everything**

Open the Collection Runner, untick folder **9** (it needs links from emails, \
and it deletes an account), and run. Folders 0 to 8 create their own data, \
carry ids from one request to the next in collection variables, and check \
every status code.

**Read**

Each request's description says what it is for and what can go wrong; its \
saved examples show the real response for success and for each error. The \
business rules behind them are in `docs/frontend/BRD.md`, and the conventions \
(tokens, errors, pagination, formats) in `docs/frontend/API_GUIDE.md`.

*Generated by `python manage.py build_api_docs`. Do not edit by hand: \
regenerate it.*
"""


# --- Rendering: the Markdown reference ------------------------------------------------


def _md_block(value, content_type="application/json"):
    if value is None:
        return "*No body.*"
    if "json" in content_type:
        return "```json\n" + as_json(scrub(value)) + "\n```"
    return "```\n" + str(value).strip() + "\n```"


def reference_markdown(records, generated_on):
    lines = [
        "# API reference",
        "",
        "> **Generated** by `python manage.py build_api_docs` on "
        f"{generated_on:%-d %B %Y} from a real run of the API. Do not edit by hand: change the "
        "code or `expenses/api/journey.py`, then regenerate. Concepts that apply to every "
        "endpoint — tokens, errors, pagination, formats — are in "
        "[API_GUIDE.md](API_GUIDE.md).",
        "",
        f"Base URL in these examples: `{DOC_BASE}`. Tokens are shortened.",
        "",
        "## Index",
        "",
        "| # | Method | Path | What | Auth |",
        "|---|---|---|---|---|",
    ]
    for number, record in enumerate(records, 1):
        step = record["step"]
        anchor = re.sub(r"[^a-z0-9 -]", "", step.name.lower()).replace(" ", "-")
        lines.append(
            f"| {number} | `{step.method}` | `{template_path(step.path)}` | "
            f"[{step.name}](#{anchor}) | {'—' if step.public else 'Bearer'} |"
        )

    current_folder = None
    for record in records:
        step, main = record["step"], record["main"]
        if step.folder != current_folder:
            current_folder = step.folder
            lines += ["", "---", "", f"## {step.folder}", "", FOLDER_NOTES[step.folder]]

        lines += [
            "",
            f"### {step.name}",
            "",
            f"`{step.method} {template_path(step.path)}` · "
            f"{'no sign-in' if step.public else 'Bearer token'} · "
            f"success `{status_line(step.expect)}`",
            "",
            step.description,
            "",
        ]
        if main["body"] is not None:
            lines += ["**Request**", "", f"`{main['method']} {main['url']}`", ""]
            if isinstance(step.body, Upload):
                lines += [
                    f"`multipart/form-data` with the file in `{step.body.field}`.",
                    "",
                ]
            else:
                lines += [_md_block(main["body"]), ""]
        elif "?" in main["url"]:
            lines += ["**Request**", "", f"`{main['method']} {main['url']}`", ""]
        lines += [
            f"**Response** `{status_line(main['status'])}`"
            + (f" · `{main['content_type']}`" if main["content_type"] else ""),
            "",
            _md_block(main["response"], main["content_type"]),
        ]

        for recorded in record["examples"]:
            example = recorded["example"]
            lines += ["", f"**{example.name}** → `{status_line(recorded['status'])}`", ""]
            if example.note:
                lines += [example.note, ""]
            if example.path or example.body is not MISSING:
                lines += [f"`{recorded['method']} {recorded['url']}`", ""]
                if recorded["body"] is not None and not isinstance(step.body, Upload):
                    lines += [_md_block(recorded["body"]), ""]
            lines.append(_md_block(recorded["response"], recorded["content_type"]))

    return "\n".join(lines) + "\n"
