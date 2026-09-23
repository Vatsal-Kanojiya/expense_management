# Handoff plan — bill scanning (phase 18)

**Audience: the implementing model (Claude Sonnet 5 or equivalent), not the project owner.**
Read this file in full before writing any code. Then do **exactly one task** — the first row in
§P marked `todo` — commit it, update §P, and stop. The owner starts each task by saying *go*.

Why this exists: DECISIONS D28–D30. In one line — a user photographs a bill, a vision LLM reads
it, and the app pre-fills an expense **the user then confirms**. Nothing is ever saved from a
model's output without a human pressing Save.

---

## §P. Progress

Update this table as the last step of every task. It is how the owner and the next session know
where things stand.

| Task | What | Status | Commit |
|---|---|---|---|
| S1 | `BillScan` model, migration, admin | done | this commit |
| S2 | Extraction contract + fake provider + Celery task | done | this commit |
| S3 | Upload, status and review UI | done | this commit |
| S4 | Provider registry, settings toggle, shared prompt and validation | done | this commit |
| S5 | Claude provider | done | this commit |
| S6 | Gemini and OpenAI providers | done | this commit |

Statuses: `todo` · `done` · `blocked — <one line why>`.

---

## 0. Ground rules

Everything in `docs/HANDOFF_PLAN.md` §0 applies (G3–G10 unchanged). Two rules are **replaced**
for this plan only:

| # | Rule |
|---|---|
| G1′ | **Dependencies:** only S5 may add `anthropic`, and only S6 may add `google-genai` and `openai`, to `requirements.txt`, each pinned to an exact version. Nothing else, ever |
| G2′ | **Settings:** only S4 edits `config/settings.py`, and only to add the `BILL_SCAN_*` block described there |

And four more that this feature needs:

| # | Rule |
|---|---|
| G11 | **Never guess an SDK's API.** Before writing S5/S6, read the provider's official docs (for Claude, invoke the `claude-api` skill). If you can't confirm a call shape, stop and report — G9 |
| G12 | **No network in tests.** Every test uses the `fake` provider or mocks the SDK client at the boundary. CI has no API keys and must stay green |
| G13 | **Model output is untrusted input.** It only ever fills an *unbound form's initial values*. Never `.create()` an `Expense` from it, never render it with `|safe`, never feed it to `eval`, `json.loads` of anything but the SDK's structured output |
| G14 | **Everything is owner-scoped.** `BillScan` belongs to a user. Every view uses `OwnerScopedMixin` or filters `user=request.user`. A stranger's scan is a 404, including its image |

### Files you must not touch

Same list as `HANDOFF_PLAN.md`, except `config/settings.py` in S4 and `requirements.txt` in S5/S6.
Do not modify `ExportJob`, `build_expense_export` or `balances.py`.

### Orientation

| Thing | Where | Why you care |
|---|---|---|
| The pattern to copy | `ExportJob` in `expenses/models.py`, `build_expense_export` in `expenses/tasks.py`, `ExportCreateView` in `expenses/views.py` | Bill scanning is the same shape: a user action creates a job row, a Celery task does slow work, the row carries status. Copy its idempotency guard, `on_commit` dispatch and failure recording line for line in spirit |
| Unguessable upload paths | `export_upload_path` in `models.py` | Do the same for bill images |
| Expense form + line items | `ExpenseForm`, `ExpenseItemFormSet` in `forms.py`; `ItemFormSetMixin` in `mixins.py` | S3 pre-fills these. Read `mixins.py` fully before S3 |
| Owner scoping | `OwnerScopedMixin` in `mixins.py` | G14 |
| Celery config | `config/settings.py` `CELERY_*` block | JSON serialiser, `acks_late` — pass primary keys only |

---

## 1. The contract (read before any task)

The app calls **one function** and gets **one plain object** back. No provider type ever
crosses this line.

```python
# expenses/extraction/__init__.py
def extract_bill(data: bytes, mime_type: str) -> ExtractedBill: ...
```

```python
# expenses/extraction/types.py — frozen dataclasses, stdlib only
ExtractedLine:  name: str, amount: Decimal
ExtractedBill:  merchant: str            # "" when unreadable
                bill_date: date | None
                total: Decimal | None
                lines: list[ExtractedLine]
                tax: Decimal             # tax + GST + service charge + tip; Decimal("0") if none
                category_hint: str       # free text, e.g. "food"; "" if unsure
                confidence: float        # 0.0–1.0, the model's own estimate
                provider: str            # "claude" | "gemini" | "openai" | "fake"
```

Failures raise `ExtractionError(message)` from `expenses/extraction/errors.py` — never a provider
exception. The Celery task catches only `ExtractionError` as a *user-facing* failure; anything
else is a bug and goes through Celery's retry.

Accepted input in this phase: `image/jpeg`, `image/png`, `image/webp`, at most 5 MB. PDFs are out
of scope (§3).

---

## 2. Tasks

### S1 — `BillScan` model

**Change.** Add to `expenses/models.py`:

- `bill_upload_path(instance, filename)` → `f"bills/{instance.user_id}/{uuid4().hex}{ext}"`, keeping
  only the original extension. Same reasoning as `export_upload_path`.
- `BillScan` with: `user` FK to `AUTH_USER_MODEL` (CASCADE, `related_name="bill_scans"`);
  `image` FileField (`upload_to=bill_upload_path`); `status` TextChoices `PENDING / RUNNING / DONE /
  FAILED`, default `PENDING`; `provider` CharField(20, blank); `result` JSONField(default=dict,
  blank=True); `error` TextField(blank); `expense` FK to `Expense`, `null=True, blank=True,
  on_delete=SET_NULL, related_name="bill_scans"`; `created_at` auto_now_add; `completed_at`
  nullable.
- `Meta`: ordering `["-created_at"]`, index on `["user", "-created_at"]`.
- `__str__` like `ExportJob`'s.

Why `SET_NULL` on `expense`: deleting the expense must not delete the record that a scan happened,
and a scan without an expense is a normal state (not yet confirmed).

Register in `expenses/admin.py` with `list_display` of user, status, provider, created_at and
`list_select_related = ["user"]`.

Run `makemigrations expenses`; the new migration is the only file in `migrations/` you create.

**Acceptance.** New file `expenses/tests/test_bill_scans.py`:
- `test_new_scan_is_pending`
- `test_upload_path_is_unguessable_and_keeps_extension`
- `test_deleting_the_expense_keeps_the_scan`

**Do not.** Add an `ImageField` — it needs Pillow, which G1′ forbids.

---

### S2 — Contract, fake provider, Celery task

**Change.**

1. Create the package `expenses/extraction/` with `types.py`, `errors.py` and `__init__.py` exactly
   as §1 describes. In this task `extract_bill` is a stub that always uses the fake provider —
   S4 replaces the dispatch.
2. `expenses/extraction/providers/fake.py`: `FakeProvider.extract(data, mime_type)` returns a
   fixed `ExtractedBill` (merchant "Test Cafe", total 450.00, two lines summing to 400.00, tax
   50.00, category_hint "food", confidence 0.9, provider "fake"). Deterministic: no randomness,
   no clock.
3. `scan_bill(self, scan_id)` in `expenses/tasks.py`, decorated like `build_expense_export`.
   Steps: re-read the row with `select_related("user")` → if `DONE`, return (idempotency) → set
   `RUNNING` with `.update()` → read `scan.image` bytes → call `extract_bill` → on success store
   `dataclasses.asdict` of the result into `result` (Decimals and dates as **strings**, because
   the JSONField must stay JSON), set `provider`, `DONE`, `completed_at`.
   On `ExtractionError`: set `FAILED` + `error[:500]` and **do not re-raise** — retrying a bill the
   model can't read just costs money. Any other exception: set `FAILED`, re-raise, let Celery retry.

**Acceptance.** Add to `test_bill_scans.py` (use `CELERY_TASK_ALWAYS_EAGER` via
`override_settings`, as the export tests do — check `test_exports.py` for the exact pattern):
- `test_task_stores_the_fake_result_as_json_strings`
- `test_task_is_idempotent_when_already_done` — assert `extract_bill` is not called
  (`unittest.mock.patch`)
- `test_extraction_error_fails_without_retry`

**Do not.** Pass a model instance or bytes into the task. Primary key only (see `tasks.py`
docstring).

---

### S3 — Upload, status, review

**Change.** Three views, three URLs under `bills/`, three templates. All owner-scoped (G14).

| URL name | View | Behaviour |
|---|---|---|
| `bill_upload` | `BillScanCreateView` | GET: a form with one file field. POST: validate type (§1 list) and size (≤ 5 MB) in a small `BillScanForm.clean_image`; create the row; dispatch `scan_bill.delay(scan.pk)` inside `transaction.on_commit`; redirect to the list with a message |
| `bill_list` | `BillScanListView` | The user's scans, newest first, with status and a **Review** link when `DONE` and no expense yet |
| `bill_review` | `BillScanReviewView` | Only for the owner's `DONE` scans, else 404. Renders the **existing** expense create form with `initial` filled from `result` and on a valid POST saves exactly as `ExpenseCreateView` does, then sets `scan.expense` |

Pre-fill mapping (put it in one pure function, `initial_from_scan(scan, user) -> (dict, list[dict])`,
in `expenses/extraction/prefill.py`, so it's testable without views):

| Expense field | From |
|---|---|
| `note` | `merchant` (truncate to the field's `max_length`) |
| `amount` | `total` |
| `spent_on` | `bill_date`, else today |
| `category` | the user's category whose name matches `category_hint` case-insensitively, else unset |
| `misc_amount` | `tax` when > 0, with `misc_note` "Tax / tip (scanned)" |
| line items | one initial row per `lines` entry: name + amount; no shares pre-selected |

For line items, read `ItemFormSetMixin` first. Build the formset with `initial=` rows on GET only,
with enough `extra` forms to hold them. If the mixin can't take initial rows without restructuring,
**pre-fill the parent fields only, leave items empty, and write `blocked — line items` in §P**
rather than redesigning the mixin (G9).

Add a nav link "Scan a bill" next to the export link in `templates/base.html`.

**Acceptance.** Add tests:
- `test_upload_rejects_a_pdf_and_an_oversized_file`
- `test_upload_queues_the_task_on_commit` (patch `scan_bill.delay`, use
  `self.captureOnCommitCallbacks(execute=True)`)
- `test_review_of_someone_elses_scan_is_404`
- `test_review_prefills_amount_note_and_matching_category`
- `test_prefill_matches_category_case_insensitively` (pure function test)
- `test_saving_the_review_links_the_expense`

**Do not.** Save an expense on upload or when the task finishes. The review POST is the only path
that creates one (G13).

---

### S4 — Registry, toggle, shared prompt, validation

**Change.**

1. `config/settings.py` — add one block (G2′):
   ```
   BILL_SCAN_PROVIDER = env("BILL_SCAN_PROVIDER", default="fake")   # fake | claude | gemini | openai
   BILL_SCAN_MODELS = {
       "claude": env("BILL_SCAN_CLAUDE_MODEL", default="claude-sonnet-5"),
       "gemini": env("BILL_SCAN_GEMINI_MODEL", default="gemini-2.5-flash-lite"),
       "openai": env("BILL_SCAN_OPENAI_MODEL", default="gpt-5-mini"),
   }
   ```
   API keys are **not** settings: each SDK reads its own env var (`ANTHROPIC_API_KEY`,
   `GEMINI_API_KEY`, `OPENAI_API_KEY`). Add the four `BILL_SCAN_*` lines and the three key names,
   commented, to `.env.example`.
2. `expenses/extraction/providers/base.py` — a `Protocol` (or ABC) `BillProvider` with
   `name: str` and `extract(data: bytes, mime_type: str, model: str) -> ExtractedBill`.
3. `expenses/extraction/registry.py` — a dict `{"fake": ..., "claude": ..., ...}` of
   **import paths as strings**, resolved lazily with `django.utils.module_loading.import_string`.
   Lazy on purpose: a server configured for `gemini` must not need the `anthropic` package
   installed. Unknown name → `ExtractionError`.
4. `expenses/extraction/prompt.py` — the one prompt and the one JSON schema every provider sends.
   Schema fields mirror `ExtractedBill` minus `provider`, with amounts as **strings** (models
   round floats; strings keep paise exact). The prompt says: Indian bills are common; amounts in
   rupees; put GST, CGST/SGST, service charge and tip into `tax`; lines are items, never tax
   rows; return empty values rather than guessing.
5. `expenses/extraction/normalize.py` — `to_extracted_bill(raw: dict, provider: str) -> ExtractedBill`.
   Parses amount strings to `Decimal` (strip ₹, commas, spaces; quantize to 0.01; negatives and
   junk → drop the line / `None` total); parses dates in ISO, `DD/MM/YYYY` and `DD-MM-YYYY`
   (Indian order first); clamps `confidence` to 0–1; caps `lines` at 50. Every provider funnels
   through this — providers never build `ExtractedBill` themselves.
6. Make `extract_bill` dispatch: validate mime/size → look up the provider for
   `settings.BILL_SCAN_PROVIDER` → call it with `settings.BILL_SCAN_MODELS[name]` → return.

**Acceptance.** New file `expenses/tests/test_extraction.py`:
- `test_normalize_parses_rupee_strings_with_commas`
- `test_normalize_reads_indian_date_order`
- `test_normalize_drops_negative_and_junk_amounts`
- `test_unknown_provider_raises_extraction_error`
- `test_registry_does_not_import_unused_providers` (assert `"anthropic" not in sys.modules`
  after resolving `fake` — skip if already imported by another test)

---

### S5 — Claude provider

**Change.** `expenses/extraction/providers/claude.py`, `ClaudeProvider`. Add `anthropic` pinned
to `requirements.txt` (G1′).

- **First, invoke the `claude-api` skill** and follow it for image input and structured outputs
  (G11). Send the image as a base64 `image` content block plus the shared prompt; request JSON
  matching the shared schema via structured outputs; model from settings.
- Check `stop_reason` before reading content. `refusal` or `max_tokens` → `ExtractionError`.
- Map SDK errors: auth/permission/bad request → `ExtractionError` (retrying won't help);
  rate-limit/5xx/connection → re-raise so Celery retries with backoff.
- Pass the parsed dict to `to_extracted_bill(raw, "claude")`.

**Acceptance.** Tests with the SDK client mocked (G12):
- `test_claude_builds_an_image_block_and_returns_normalized_bill`
- `test_claude_refusal_becomes_extraction_error`
- `test_claude_rate_limit_is_reraised_for_retry`

---

### S6 — Gemini and OpenAI providers

**Change.** `providers/gemini.py` (`google-genai` package) and `providers/openai.py` (`openai`
package), pinned in `requirements.txt` (G1′). Same four obligations as S5: official docs first
(G11), image + shared prompt + shared schema via each SDK's structured-output feature, error
mapping (bad request/auth → `ExtractionError`; rate-limit/5xx → re-raise), and normalisation
through `to_extracted_bill`.

**Acceptance.** Mirror S5's three tests for each provider (six tests), SDK mocked. Plus one
parametrised test that sets `BILL_SCAN_PROVIDER` to each of `claude`, `gemini`, `openai` with the
provider's client mocked and asserts `extract_bill` returns an `ExtractedBill` with the right
`provider` — this is the proof the toggle works.

Finish by adding a short "Bill scanning" section to `README.md`: the env vars, the toggle, and
that the default `fake` provider means the feature works in development with no keys.

---

## 3. Definition of done

Same five conditions as `HANDOFF_PLAN.md` §2, plus: §P updated in the same commit.

## 4. Explicitly out of scope

PDF bills · multi-page bills · the API (DRF) endpoint for scans · automatic saving without review ·
per-user scan quotas or cost tracking · retrying a failed scan from the UI · picking the provider
per request · deleting uploaded images on a schedule · pre-selecting who shared each line.
Each is a reasonable next step; none belongs in this batch.
