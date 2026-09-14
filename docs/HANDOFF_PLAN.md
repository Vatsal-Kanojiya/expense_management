# Handoff plan — parked UI issues 28 to 32

> **Status, session 22: every task here is done, and the project is frozen (DECISIONS D27).**
> Do not start new work from this file. It remains as the record of how tasks were specified and why.

**Audience: the implementing model (Gemini Flash or equivalent), not the project owner.**
Read this file in full before writing any code. Every task below is self-contained and
independently verifiable. Do them in the order given.

---

## 0. Ground rules

These are not suggestions. A change that breaks one of these is wrong even if it works.

| # | Rule |
|---|---|
| G1 | **No new dependencies.** Nothing is added to `requirements.txt` or `requirements-dev.txt`. No CDN links, no vendored libraries, no npm. The project deliberately has zero JavaScript dependencies |
| G2 | **No new settings.** `config/settings.py` is not edited by any task here. Static files go in an app's own `static/` directory, which the default finder already reads |
| G3 | **Run `python manage.py test` after every task.** It must end `OK`. The count only ever goes up. If a task leaves it red, revert that task and stop |
| G4 | **Run `ruff check . && ruff format .`** before declaring a task done. Line length is 100, target Python 3.10 |
| G5 | **Never use a multi-line `{# #}` comment in a template.** Django only strips single-line ones; a multi-line one renders as visible text. Use `{% comment %}…{% endcomment %}`. There is a test that enforces this |
| G6 | **Match the existing comment style.** This codebase explains *why*, not *what*, in full sentences. Do not add comments that restate the code. Do not remove existing comments |
| G7 | **Do not reformat, reorganise or "clean up" code you were not asked to change.** No renaming, no reordering imports beyond what ruff does, no docstring rewrites |
| G8 | **Every queryset of user-owned data stays scoped to the request user.** `Category`, `Participant`, `Expense`, `Settlement` and `ExportJob` all belong to a user. An unscoped queryset is a security bug, and this project has hit that trap five times |
| G9 | **Stop and report after two failed attempts** at any single task. Do not improvise an alternative design |
| G10 | **One commit per task**, Conventional Commits, message `<type>(<scope>): <subject>` — see `docs/COMMIT_PLAN.md` |

### Files you must not touch

`config/` · `expenses/migrations/` except to add new ones via `makemigrations` · `expenses/splitting.py` ·
`Dockerfile` · `compose.yaml` · `.github/` · `pyproject.toml` · `docs/BUILD_LOG.md` (the owner maintains it).

### Orientation

| Thing | Where |
|---|---|
| Forms | `expenses/forms.py` — `CategoryForm`, `ParticipantForm`, `ExpenseForm`, `ExpenseItemForm`, `BaseExpenseItemFormSet`, `ExpenseItemFormSet` |
| Models | `expenses/models.py` — `Expense` carries `items_total()` and `is_balanced()` |
| Split maths | `expenses/balances.py` — `_charge_item` and `_charge_evenly`. `allocate()` in `splitting.py` guarantees the parts sum to the total exactly |
| Form/formset plumbing | `expenses/mixins.py` — `ItemFormSetMixin` |
| Templates | `templates/expenses/` — `expense_form.html`, `_item_row.html` |
| Existing JavaScript | `expenses/static/expenses/item-formset.js` — the only JS in the project. Read it before writing more |
| Tests | `expenses/tests/` — one file per question the tests answer |

---

## 1. Task list

Seven tasks in the first batch, two more in §1b. T1 and T2 are deliberately trivial: they exist to confirm the workflow before
anything risky. Do not skip ahead.

---

### T1 — Focus the first field when a create form opens (issue 29)

**Problem.** Opening New category, New person or New expense leaves the caret nowhere, so every
entry starts with a mouse click.

**Change.** Set the HTML `autofocus` attribute on the first editable field of each create form.
Set it in `expenses/forms.py`, on the widget, inside `__init__` — not in a template, so it
follows the form wherever it is rendered.

**Apply it only on create, never on edit.** `self.instance.pk` is falsy on a create form. Focusing
a pre-filled field on an edit form fights a person who came to change a different one.

| Form | Field to focus |
|---|---|
| `CategoryForm` | `name` |
| `ParticipantForm` | `name` |
| `ExpenseForm` | `category` |

**Acceptance.** Add to `expenses/tests/test_forms.py`:

- `test_create_form_focuses_the_first_field` — an unbound form renders `autofocus` on the field above.
- `test_edit_form_does_not_autofocus` — a form built with `instance=<saved object>` does not.

One pair of tests per form is enough; do not write nine.

**Do not.** Do not add `autofocus` to the line-item formset rows. Multiple autofocus attributes on
one page is invalid HTML and the browser picks arbitrarily.

---

### T2 — Make the date control unmistakably a picker (issue 28)

**Read this first.** The owner reported that dates can only be typed. The markup was already
checked and is correct: the field renders as `<input type="date" … value="2026-09-14">`, which is
exactly what a native picker wants. **So the bug is not a missing attribute, and you must not
"fix" it by adding one.** Two things are actually worth doing, and nothing more.

**Change A — pin the format explicitly.** `forms.DateInput(attrs={"type": "date"})` relies on
Django's default date format for the *bound* value. It currently produces ISO, but that is a
default and not a guarantee, and a non-ISO value makes a native date input silently render blank.
Pass `format="%Y-%m-%d"` explicitly to every `DateInput` in the project:

- `ExpenseForm.Meta.widgets["spent_on"]` in `expenses/forms.py`
- both `DateInput`s in `expenses/filters.py`

**Change B — stop the control being squeezed.** In the `<style>` block of `templates/base.html`,
give `input[type="date"]` a `min-width` sufficient for the calendar affordance (`11rem` is enough)
so the browser's picker button is never clipped by a narrow column.

**Acceptance.** Add to `expenses/tests/test_forms.py`:

- `test_a_bound_date_renders_in_iso_format` — build `ExpenseForm` with a saved instance whose
  `spent_on` is a known date, render it, assert `value="2026-01-15"` appears.

**Do not.** Do not add a JavaScript date-picker library. Do not change `type="date"` to anything
else. Do not touch `templates/expenses/export_list.html`, whose raw inputs are already correct.

---

### T3 — The payer becomes a visible, removable participant (issue 31)

> **Superseded — read this before the rest of T3.** The owner approved a different design during
> implementation, and it is what the code does: `Expense.paid_by` is a foreign key to `Participant`,
> and the owner is an explicit `Participant` row with `is_self=True`, named `FirstName (self)` with
> a numeric suffix on collision. The owner is in a split only when that row is selected; new
> expenses and new line rows pre-select it, and the API adds it unless `include_self` is false.
> Balances are netted per person and signed, and settlements are signed (`amount != 0`). The
> boolean design below is kept for the record only. The self-participant data model is flagged for
> redesign as known issue 34.

**Problem.** The payer is currently an unwritten share. `balances.py` hardcodes a leading `1` in
both `_charge_item` and `_charge_evenly`, then discards that portion so you never owe yourself.
Two consequences: the form never shows that you are already in the split, and a pure reimbursement
— you paid for a taxi you did not ride in — cannot be expressed, because the denominator always
includes you.

**Do not model self as a `Participant` row.** That table is per-user names with a uniqueness
constraint. A self row would appear in the address book, compete in the duplicate-name check, and
show up in balances as somebody who owes you money. All three are wrong.

**Change.**

1. **Model.** Add to `Expense` in `expenses/models.py`:
   `owner_shares = models.BooleanField(default=True)`. Run `makemigrations expenses` and commit
   the generated migration unedited. `default=True` means every existing row keeps today's
   behaviour, which is the point.
2. **Balances.** In `expenses/balances.py`, the leading `1` in both `_charge_item` and
   `_charge_evenly` becomes conditional on `expense.owner_shares`. In `_charge_item` the expense is
   reachable as `item.expense`; **add it to the existing `Prefetch` in `_expenses` rather than
   letting each item fetch its own parent**, or you will reintroduce the N+1 the query-count tests
   pin. When the owner does not share, there is no leading weight and no leading portion to discard.
3. **Form.** In `ExpenseForm`, expose `owner_shares` as a checkbox labelled with the user's first
   name, falling back to their username when the first name is empty: `f"{name} (self)"`. Place it
   immediately above `participants`.
4. **Validation, even-split path.** In `ExpenseForm.clean`, raise a field error on `owner_shares`
   if it is unticked while the expense has no participants. An expense split with nobody and not
   charged to you is owed by no one.
5. **Validation, itemised path.** In `BaseExpenseItemFormSet.clean`, when
   `self.instance.owner_shares` is False, every non-deleted line must have at least one person in
   `shared_with`. Today an unticked line means "this line is yours"; with the owner out of the split
   the same line would belong to nobody. Read `owner_shares` from `self.instance` — the mixin builds
   the formset against the parent form's instance, which already carries the cleaned value.

**Acceptance.** Add to `expenses/tests/test_balances.py`:

- `test_the_owner_can_be_left_out_of_an_even_split` — 300 shared with Rahul and Priya with
  `owner_shares=False` gives each of them 150, not 100.
- `test_the_owner_can_be_left_out_of_an_itemised_split` — the same for a line item.
- `test_the_owner_is_counted_by_default` — an expense created without mentioning `owner_shares`
  behaves exactly as before.

And to `expenses/tests/test_forms.py`:

- `test_removing_yourself_with_no_participants_is_refused`.

And to `expenses/tests/test_items.py`:

- `test_an_unshared_line_is_refused_when_you_are_not_in_the_split`.

**Also.** Run the existing query-count assertions and confirm they are unchanged. Search the tests
for `assertNumQueries` before you start so you know which they are.

---

### T4 — A misc amount for tax, tip and leftovers, split by consumption (issue 32)

**Depends on T3.** Do not start it until T3 is committed and green.

**Problem.** A real bill carries money no line item accounts for: GST, a tip, a service charge, a
rounding leftover. Today there is nowhere to put it, so either the lines are fudged to hit the total
or the expense is saved unbalanced and dropped from balances.

**The design, which is decided. Do not re-open any of it.**

| Decision | Rule |
|---|---|
| One field, not several | A single misc amount per expense, plus a free-text note saying what it is. No kind dropdown, no GST-specific field, no rate or percentage field |
| It is part of the amount | The expense amount is the truth. Line items account for part of it, misc for another part. Misc is **not** added on top |
| Split by consumption | Misc is apportioned across people in proportion to what each consumed from the line items — not per head |
| Positive only | Null means none. Zero and negative are rejected. A discount is recorded by lowering the expense amount |
| Needs line items | A misc amount on an expense with no line items is rejected. An even split of the whole amount already covers everything, so misc would mean nothing |
| Under one rupee is forgiven | An expense counts as balanced when what is unaccounted is less than ₹1.00 in either direction. **The payer absorbs it** — no code distributes the remainder |
| No default value | The misc field is never pre-filled and never recalculated. The form shows the unaccounted figure live and the person types the misc amount themselves |

That last rule is deliberate and you must not "improve" it. An auto-filled field that recomputes
when line items change has to track whether the person has edited it, and that tracking is wrong the
moment they type the same number the machine would have. Showing the gap has no such state.

**Change.**

1. **One rule, one place.** In `expenses/models.py`, above the `Expense` class, define:

   ```python
   ROUNDING_TOLERANCE = Decimal("1.00")

   def unaccounted(amount, items_total, misc_amount):
       """What the lines and the misc amount leave uncovered. Positive is under, negative is over."""
   ```

   Treat a None `items_total` or `misc_amount` as zero. Every other piece of **Python** in this
   task calls this function. **Do not reimplement the subtraction or the tolerance in Python
   anywhere else.** The one unavoidable second copy is in SQL — see step 3b.

2. **Model.** Add to `Expense`:
   - `misc_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)`
   - `misc_note = models.CharField(max_length=100, blank=True)`
   - a `CheckConstraint` named `expense_misc_amount_positive`: null, or greater than zero.

   Generate the migration with `makemigrations`. Commit it unedited.

3. **Model methods.** Add `Expense.unaccounted_amount()` returning
   `unaccounted(self.amount, self.items_total(), self.misc_amount)`. Rewrite `is_balanced()` to
   return `abs(self.unaccounted_amount()) < ROUNDING_TOLERANCE` when there are items, and `True`
   when there are none. Keep its docstring and extend it; do not replace it.

3b. **The SQL copy of the rule — easy to miss, and it must change.** `ExpenseQuerySet.unbalanced()`
   in `expenses/managers.py` implements the same rule in the database, with exact equality and no
   misc. `check_splits` uses it. Left alone, `balances` will count an expense that `check_splits`
   reports as broken. Rewrite it so the database computes
   `abs(amount - items_total - coalesce(misc_amount, 0))` and keeps rows where that is
   `>= ROUNDING_TOLERANCE`, importing the constant from `models.py` rather than retyping `1.00`.
   - Use `Abs` and `Coalesce` from `django.db.models.functions`, and `Value(Decimal("0"))` for the
     fallback.
   - **Set `output_field=DecimalField(max_digits=12, decimal_places=2)` on the arithmetic
     expression.** Mixing a `Sum` annotation with plain `F()` columns otherwise raises
     `FieldError: Expression contains mixed types` on some backends.
   - Keep the existing comment about filtering on the annotation rather than re-traversing the
     relation. It is still true and still the reason for the shape of the query.
   - Its docstring says "The formset refuses these now". That stopped being true in session 19.
     Correct that one sentence. This is an explicit exception to G7.
   - Update the `check_splits` output line to include the misc amount, so a reported row shows all
     three numbers.

   SQL cannot call a Python function, so two implementations of this rule are unavoidable. What
   keeps them honest is a test that they agree — see the acceptance list.

4. **Form.** Add `misc_amount` and `misc_note` to `ExpenseForm.Meta.fields`, labelled
   `Tax, tip or other` and `What was it?`. In `ExpenseForm.clean`, when `misc_amount` is set,
   require `misc_note`. Do not require `misc_amount` when `misc_note` is set; an empty note next to
   no amount is harmless.

5. **Formset.** In `BaseExpenseItemFormSet.clean`:
   - if `self.instance.misc_amount` is set and there are no non-deleted lines, raise a
     non-form error;
   - replace the existing `total != expected` comparison with a call to `unaccounted()` against
     `self.instance.misc_amount` and `ROUNDING_TOLERANCE`. Keep recording the result on
     `sum_mismatch` rather than raising. **The tuple changes shape:** it becomes
     `(unaccounted_amount, expense_amount)`.

6. **Warning message.** `_warn_if_unbalanced` in `expenses/mixins.py` reads `sum_mismatch`. Update
   it for the new tuple, and word it as the amount not accounted for, for example:
   `Saved, but ₹120.00 of the ₹900.00 is not accounted for by the line items or the misc amount,
   so this expense is left out of balances until it is.`

7. **Balances — the core of the task.** In `expenses/balances.py`, when an itemised expense is
   balanced and has a `misc_amount`:

   a. **Track consumption while charging items.** Each person's consumption is the sum of their
      portions across every line. The owner is a person here, with their own running total. Two
      cases the current code handles by returning early must still record consumption: a line with
      no shares was consumed entirely by the owner, and a line's discarded leading portion is the
      owner's consumption. When T3's `owner_shares` is False the owner consumes nothing.

   b. **Convert consumption to paise** — `int(amount * 100)` — to get integer weights.

   c. **Drop every person whose consumption is zero before calling `allocate()`.** It raises
      `ValueError` on a non-positive weight. A participant on the expense but on no line consumed
      nothing and bears no misc. This is the most likely crash in the task.

   d. **Call `allocate(expense.misc_amount, weights)`** and add each participant's portion to
      `owed`. Discard the owner's portion, exactly as the item and even-split paths already do.

   Keep this inside the existing loop over `_expenses()`. **Do not add a query.** Everything needed
   is already prefetched, and the query-count tests will fail if you fetch per expense or per item.

8. **Live unaccounted figure.** New file `expenses/static/expenses/expense-totals.js`, loaded from
   the `scripts` block of `templates/expenses/expense_form.html` beside `item-formset.js`.
   - Listen for `input` events on the `<form>` itself. They bubble, so rows added later by
     `item-formset.js` are covered with no rebinding.
   - Sum the amount inputs of line-item rows, **skipping any row whose `-DELETE` checkbox is
     ticked**. A removed saved row is only hidden and still holds its value. A removed unsaved row
     has already been blanked, so it contributes zero on its own.
   - Show `₹X not accounted for` or `₹X over the total` in an element placed directly under the
     line-item table. Hide it when the difference is under ₹1.00, mirroring the server rule.
   - Treat an empty or unparseable input as zero. Never show `NaN`.
   - **Never write to the misc field.** Read it only. See the last design rule above.
   - The server rule is the authority. This display is a convenience; do not skip server-side
     validation because the script already checked.

9. **API.** Add `misc_amount` and `misc_note` to `ExpenseSerializer.Meta.fields`. The positive-only
   rule is enforced by the model constraint; add a `validate_misc_amount` for a readable error
   rather than a database exception.

**Acceptance.** Add to `expenses/tests/test_models.py`:

- `test_unaccounted_treats_missing_values_as_zero`
- `test_an_expense_within_a_rupee_is_balanced` — amount 900.00, lines 899.40, no misc.
- `test_an_expense_a_rupee_out_is_not_balanced` — amount 900.00, lines 899.00, no misc.
- `test_misc_amount_counts_towards_the_total` — amount 900.00, lines 800.00, misc 100.00.
- `test_misc_amount_must_be_positive` — assert the constraint raises `IntegrityError` on zero.
- `test_the_queryset_and_the_predicate_agree` — **the most important test in this task.** Build a
  handful of expenses covering: no items, exact, within a rupee, exactly a rupee out, covered by
  misc, and misc overshooting. Assert the set of `Expense.objects.unbalanced()` equals the set of
  expenses where `is_balanced()` is False. This is what stops the SQL and Python rules drifting.

Add to `expenses/tests/test_balances.py`:

- `test_misc_is_split_by_consumption_not_by_head` — Pizza 600 shared with Rahul, Coke 200 not
  shared, misc 80, amount 880. Owner consumed 300 + 200, Rahul 300. Rahul owes 300 + 30.
- `test_a_participant_who_consumed_nothing_bears_no_misc` — Priya on the expense but on no line
  gets nothing and nothing raises.
- `test_misc_is_not_charged_to_the_owner_when_the_owner_is_out` — with `owner_shares=False`.
- `test_misc_adds_no_queries` — extend the existing query-count test rather than writing a new one.

Add to `expenses/tests/test_forms.py` and `expenses/tests/test_items.py`:

- `test_misc_amount_needs_a_note`
- `test_misc_amount_needs_line_items`

**One existing test will look like it contradicts this task. It does not.**
`test_the_sum_is_compared_exactly_not_approximately` in `expenses/tests/test_items.py` asserts that
Decimal arithmetic is exact — that 0.10 + 0.20 is 0.30 and not a float approximation. The ₹1
tolerance does not make arithmetic approximate: sums stay exact Decimals, and the tolerance applies
only to the final *is this balanced* decision. **Do not delete or weaken that test.** Update its
comment to draw that distinction, since "money that is close enough is money that is wrong" now
reads as contradicting the tolerance.

**Do not.** Do not pre-fill or recalculate `misc_amount`, server- or client-side. Do not add a kind,
category, rate or percentage field. Do not allow negative misc. Do not distribute the sub-rupee
remainder to anyone. Do not change `allocate()` — it is on the untouchable list and does not need
to change. Do not add per-line-item misc amounts.

---

### T5 — Scope the line-item picker to the expense's participants (issue 30, part one)

**Problem.** `ExpenseItemForm.shared_with` draws from every participant the user owns. At a hundred
people, a five-line expense renders six hundred checkboxes. In a real expense the relevant set is
two to four names.

**Read this before changing anything.** This *tightens* existing behaviour rather than fixing a
bug. `Expense.shared_with()` deliberately unions expense participants with line-item share
participants, so today a line may legitimately charge someone absent from the expense. Narrowing
the queryset makes that union redundant and can orphan existing rows. Handle both.

**Change.**

1. In `expenses/mixins.py`, `ItemFormSetMixin.build_formset` currently passes
   `form_kwargs={"user": …}`. It must also pass the participant queryset the child forms should
   offer. On a bound formset this comes from the submitted expense participants; on an unbound one
   from `instance.participants`.
2. In `ExpenseItemForm.__init__`, use that queryset for `shared_with` instead of all the user's
   participants. **Union it with the shares already saved on this item**, so editing an expense
   never silently drops a person who is on a line but not on the expense.
3. In `BaseExpenseItemFormSet.clean`, add a validation error when a line charges someone who is not
   an expense participant, *and* that person is not already saved on that line. New data follows
   the tighter rule; existing data is not invalidated retroactively.

**Acceptance.** Add to `expenses/tests/test_items.py`:

- `test_a_line_can_only_charge_an_expense_participant`
- `test_an_existing_share_outside_the_participants_is_preserved`
- `test_the_picker_offers_only_the_expense_participants`

**Do not.** Do not change `Expense.shared_with()`. Do not write a data migration. Do not add
`CASCADE` anywhere.

---

### T6 — A searchable multiselect widget (issue 30, part two)

**Problem.** Even scoped, a checkbox list is the wrong control for picking names. The owner wants
something like Frappe's multiselect link field: type to filter, chips for what is chosen.

**Build it as one custom Django widget, used by both fields.** Not two widgets, not template-level
markup. This is the part of the work that is worth doing properly.

**Change.**

1. New file `expenses/widgets.py`. Define `ChipSelectMultiple(forms.SelectMultiple)` with:
   - `template_name = "expenses/widgets/chip_select.html"`
   - a `Media` inner class declaring `expenses/chip-select.js`
   Subclass `SelectMultiple`, **not** `CheckboxSelectMultiple`: a plain multi-select is the correct
   no-JavaScript fallback, and Django already renders and cleans it.
2. New template `templates/expenses/widgets/chip_select.html`. Render the real `<select multiple>`,
   plus a search input and a chip container that ship `hidden` and are revealed by the script.
3. New file `expenses/static/expenses/chip-select.js`. Read `item-formset.js` first and match its
   style: an IIFE, `"use strict"`, no framework, progressive enhancement, comments that explain why.
   The `<select>` stays the source of truth — the script filters, renders chips, and toggles
   `option.selected`. Never maintain a second copy of the selection in JavaScript.
   **It must also work on a row cloned by `item-formset.js`**, which means initialising on
   newly-inserted rows, not only at page load.
4. Use it for `ExpenseForm.participants` and `ExpenseItemForm.shared_with`.
5. Render `{{ form.media }}` in `templates/expenses/expense_form.html` inside the `scripts` block.

**Filter client-side. Do not add an autocomplete endpoint, a URL, or a view.** Participants per user
number in the dozens, so the whole list ships in the page. A server round trip per keystroke is not
justified here and adds a surface that has to be ownership-scoped.

**Acceptance.** Add to `expenses/tests/test_forms.py`:

- `test_participants_use_the_chip_widget`
- `test_the_widget_falls_back_to_a_plain_multiselect` — assert `<select multiple` is in the
  rendered HTML, which is what a person without JavaScript gets.
- `test_the_widget_queryset_is_still_scoped_to_the_user` — the scoping trap this project has hit
  five times. Changing a widget must not change which rows it offers.

**Do not.** Do not load Select2, Choices.js, jQuery or anything else (G1). Do not remove
`item-formset.js` or change its behaviour.

---

### T7 — A Split tab on the expense page (issue 33)

**Depends on T3 and T4.** Both must be committed and green.

**Problem.** The balances page totals what each person owes across all expenses. Nothing shows how
one expense splits: who owes what for this dinner, how much of it is items and how much is misc.
The numbers are already computed per expense inside `balances()` and then thrown into running
totals, so they are never visible.

**Decided behaviour. Do not re-open it.**

| Rule | Detail |
|---|---|
| Where | The existing edit page for a saved expense. Two in-page tabs: **Details** (the current form) and **Split**. No new URL, no new view, no browser tab. The create page gets no tabs |
| When the tab exists | Only when the expense is balanced (`is_balanced()` is True) **and** at least one participant is involved, through the even split or through a line share. Otherwise neither the tab button nor the panel is rendered at all. Not disabled, not greyed — absent |
| What it shows | The split **as last saved**. It does not update while the person edits the form. Say so in one line of muted text at the top of the panel |
| No-JavaScript fallback | Both sections render one after the other, as the page does today plus the split below |

**Change.**

1. **One implementation of the split — the core of the task.** In `expenses/balances.py`, add
   `split_expense(expense)`. Move the per-expense logic out of the loop in `balances()` into it:
   the item path, the even-split path, and T4's misc apportionment. It returns `None` when the
   expense is not balanced, otherwise a list of rows, one per person:

   ```python
   @dataclass(frozen=True)
   class SplitRow:
       participant: Participant | None   # None is the owner
       items: Decimal                    # their portions of line items, or of the even split
       misc: Decimal                     # their portion of misc_amount; Decimal("0") when none
       total: Decimal                    # items + misc
   ```

   Owner row first, then participants ordered by name. **Keep the owner's row.** `balances()`
   discards it; `split_expense()` must not, because the tab shows it. When T3's `owner_shares` is
   False there is no owner row.

2. **`balances()` becomes a sum over `split_expense()`.** For each expense from `_expenses()`, call
   `split_expense()`, skip `None`, skip the owner row, add each participant's `total` to `owed`.
   After this change there must be no split arithmetic left in `balances()` itself.
   **The existing tests in `expenses/tests/test_balances.py` must pass without being edited.** That
   is the proof the refactor changed no numbers. If one fails, the refactor is wrong — do not
   change the test.

3. **View.** In `ExpenseUpdateView.get_context_data`, add `split` to the context:
   `split_expense()` on a **freshly fetched** copy of the expense —
   `Expense.objects.for_user(self.request.user)` with the same prefetches `_expenses()` uses,
   `.get(pk=self.object.pk)`.
   **Do not pass `self.object`.** When a submission fails validation, Django has already copied the
   rejected values onto `self.object`, so it would mix an unsaved amount with saved line items and
   show a split that never existed. Set `split` to `None` when the involvement rule above fails.

4. **Template.** In `templates/expenses/expense_form.html`, when `split` is present, render a tab
   bar with two buttons and wrap the existing form card and a new split card as the two panels.
   The split panel is a table: person (`You` for the owner row), items, misc, total, using the
   existing `rupees` filter. Show the misc column only when the expense has a `misc_amount`. Add a
   final row with the column totals.

5. **Tabs script.** New file `expenses/static/expenses/expense-tabs.js`, loaded in the `scripts`
   block. Same style as `item-formset.js`: IIFE, `"use strict"`, progressive enhancement. On load,
   hide the split panel and reveal the tab bar, which ships `hidden`. Buttons toggle panel `hidden`
   and `aria-selected`. Use `role="tablist"`, `role="tab"` and `role="tabpanel"`. Nothing else —
   no remembering the last tab, no URL hash.

**Acceptance.** Add to `expenses/tests/test_balances.py`:

- `test_split_rows_sum_to_the_accounted_amount` — for an itemised expense with misc, the row
  totals sum **exactly** to `items_total() + misc_amount`. For an even split, exactly to `amount`.
- `test_split_includes_the_owner_row`
- `test_split_has_no_owner_row_when_the_owner_is_out`
- `test_split_is_none_when_unbalanced`
- `test_split_shows_misc_per_person` — reuse T4's example: Rahul's row is items 300, misc 30,
  total 330.

Add to `expenses/tests/test_views.py`:

- `test_the_split_tab_appears_for_a_balanced_shared_expense`
- `test_the_split_tab_is_absent_when_unbalanced`
- `test_the_split_tab_is_absent_for_an_expense_that_is_yours_alone`
- `test_the_split_tab_is_absent_on_the_create_page`
- `test_a_rejected_edit_shows_the_saved_split` — post an invalid change to the amount, assert the
  rendered split still reflects the saved amount.
- `test_the_split_tab_is_scoped_to_the_owner` — another user requesting the edit page gets 404, as
  today. Guards against the fresh fetch in step 3 being written unscoped.
- `test_the_edit_page_query_count_does_not_grow_with_items` — an expense with one line and one with
  five lines render with the same number of queries. Compare the two counts to each other; do not
  hardcode a number.

**Do not.** Do not compute or update the split in JavaScript. Do not add a detail view, URL or
API field for the split. Do not render a disabled or empty Split tab. Do not duplicate any split
arithmetic in the view or template — both only read `split_expense()`'s rows. Do not edit
existing balance tests.

---

## 1b. Second batch — form state and required markers (issues 36 and 37)

**Added session 22, after T1 to T7 were committed.** Do T8 before T9. T8 is a real data-loss bug;
T9 is presentation. Both are small. If either needs more than the files named in it, stop and report.

---

### T8 — Line items vanish when the expense form has an error (issue 36)

> **Done at the owner's request, session 22. Do not implement.** Kept as the record of
> the diagnosis. See BUILD_LOG issue 36.

**Problem.** Fill in line items and tick who shared each one, leave a required field such as `note`
empty, and submit. The page comes back with the error — and every line item gone. The person has to
type them all again.

**This is a bug, not missing persistence.** Nothing needs storing. The browser already sent every
line item in the POST. The server receives them and then discards them when it re-renders.

**Root cause, verified by reproduction.** In `expenses/mixins.py`, `ItemFormSetMixin` builds a
*bound* formset (one carrying the POST data) only inside `form_valid()`. When the **parent** form is
invalid, Django never calls `form_valid()`. It calls `form_invalid()`, which calls
`get_context_data(form=form)` with no formset — and `get_context_data` falls back to
`self.build_formset(instance=self.object)` with no `data`. That is an **unbound** formset, so the
page re-renders empty.

A reproduction on current `master` confirmed it: parent error `{'note': ['This field is required.']}`,
`formset.is_bound` is `False`, the re-rendered item names are `[None]`, and the item text is absent
from the response.

The comment above that `setdefault` line says "form_invalid re-renders with a bound formset". **That
comment is wrong.** It describes only the path where the *formset* fails inside `form_valid`, and it
is the reason the bug was invisible in review.

**There is a second, smaller symptom of the same cause.** Because the formset is never validated
when the parent fails, its own errors — an item with no amount, say — only appear *after* the person
fixes the parent field and resubmits. Two round trips to find two mistakes.

**Change.** In `expenses/mixins.py`, add a `form_invalid` method to `ItemFormSetMixin`:

1. Build the formset with `self.build_formset(instance=form.instance, data=self.request.POST)`.
   Use `form.instance`, not `self.object`, so the formset's sum check sees the amount that was
   *posted* rather than the one last saved. This mirrors what `form_valid` already does.
2. Call `formset.is_valid()` so the formset's own errors are populated and render in the same
   response as the parent's. Ignore its return value here — the response is an error page either way.
3. Return `self.render_to_response(self.get_context_data(form=form, formset=formset))`.

Then **correct the comment** above `context.setdefault("formset", ...)` so it states what actually
passes a bound formset in: both `form_valid` (when the formset fails) and the new `form_invalid`
(when the parent fails). Keep `setdefault`; do not change it to assignment.

**No template or JavaScript change is needed.** Both were checked. `chip-select.js` rebuilds its chips
from options that arrive already selected, and `item-formset.js` trusts the rendered `TOTAL_FORMS`. A
correct server re-render restores the rows *and* the people ticked on each row with no client work.

**Acceptance.** Create `expenses/tests/test_form_state.py`. Post to both `expense_create` and
`expense_update` with `note` empty, two line items, and one item's `shared_with` ticked. Use
`expenses/tests/helpers.py` for the management form data. Assert:

- `test_line_items_survive_a_parent_form_error` — `response.context["formset"].is_bound` is `True`,
  and both item names appear in `response.content`.
- `test_item_shares_survive_a_parent_form_error` — the ticked participant is still selected in the
  re-rendered row.
- `test_parent_and_formset_errors_show_together` — post with `note` empty **and** one item with no
  amount. Both the `note` error and the item amount error are in the same response.
- `test_nothing_is_saved_on_a_parent_form_error` — `Expense.objects.count()` and
  `ExpenseItem.objects.count()` are unchanged.
- `test_update_keeps_edited_items_on_error` — on `expense_update`, change an existing item's name,
  blank the `note`, submit. The *edited* name is re-rendered, not the saved one.

**Each test must fail on the code before your change.** Run the file against `master` first and
confirm the first three fail. If they pass before your change, the test is wrong — fix the test.

**Do not.**

- Do not store form state in the session, `localStorage`, cookies or the database. The POST already
  carries it; persistence would be a second copy that can disagree with what was submitted.
- Do not add JavaScript to save or restore rows.
- Do not change `form_valid`, `build_formset` or `_warn_if_unbalanced`.
- Do not catch the parent form's errors and save anyway.

---

### T9 — Mark required fields with a red asterisk (issue 37)

> **Done at the owner's request, session 22. Do not implement.** Kept as the record of
> the diagnosis. See BUILD_LOG issue 37.

**Problem.** Nothing shows which fields are mandatory, so the first a person learns that `note` is
required is the error after submitting.

**Why this is one CSS rule and no Python.** Django already renders the HTML `required` attribute on
every required input, and omits it on optional ones. This was checked against `ExpenseForm` and
against Django's own `AuthenticationForm`: category, amount, spent-on, note, username and password
carry it; paid-by, split-evenly-with and both misc fields do not. Every create and edit form in the
project renders through `{{ form.as_p }}`, which puts the `<label>` and its input as siblings inside
one `<p>`. So CSS can find required fields directly, on every form at once, including the Django auth
forms we do not own.

**Change, part one — every `as_p` form.** In `templates/base.html`, inside the existing `<style>`
block and directly after the `label { ... }` rule, add:

```css
p:has(> :is(input, select, textarea)[required]) > label::after {
  content: " *" / "";
  color: var(--danger);
}
```

- `:has()` selects the row whose input is required. It is supported in every current browser.
- `/ ""` gives the asterisk empty alternative text. Screen readers already announce "required" from
  the attribute, so reading "star" as well would be noise.
- `var(--danger)` is the existing red, which already has a dark-mode value. Do not hard-code a colour.

**Change, part two — the line-item table.** Formset rows deliberately do **not** carry the `required`
attribute: a blank spare row must be submittable, so the rule above cannot reach them. In
`templates/expenses/expense_form.html`, mark the **Item** and **Amount** column headers only:

```html
<th>Item <span class="required-mark" aria-hidden="true">*</span></th>
```

and add one more rule beside the first: `.required-mark { color: var(--danger); }`. Do not mark
**Shared with** or **Remove**.

**Deliberately not starred: "What was it?" (`misc_note`).** It is required *only when* a misc amount is
entered, enforced in `ExpenseForm.clean()`. A permanent asterisk would claim it is always mandatory,
which is false. Leave it unmarked; its existing error message covers the conditional case.

**Acceptance.** Add to `expenses/tests/test_templates.py`:

- `test_required_fields_render_the_required_attribute` — render the new-expense page and assert the
  `category`, `amount`, `spent_on` and `note` inputs carry `required`, and `paid_by`, `misc_amount`
  and `misc_note` do not. This is the property the CSS depends on; if a future change drops the
  attribute, this test is what notices.
- `test_line_item_required_columns_are_marked` — the page contains exactly two `required-mark` spans.

Then **check it in a browser**, because a test cannot see CSS: open New expense, Log in, and New
category, and confirm a red asterisk sits beside each required label and no optional one.

**Do not.**

- Do not add `required_css_class` to form classes or subclass Django's auth forms. The CSS rule
  already covers them without touching Python.
- Do not replace `{{ form.as_p }}` or render fields individually. That is issue 35, parked.
- Do not add the asterisk inside label text in Python (for example `label="Note *"`). It would be
  read aloud, copied into error messages, and wrong for any form rendered without that CSS.

---

## 2. Definition of done

A task is done when all five hold:

1. `python manage.py test` ends `OK` with a higher count than before the task.
2. `ruff check .` passes and `ruff format .` reports no changes.
3. `python manage.py check` reports no issues.
4. The new tests named in the task exist and fail if the change is reverted.
5. One commit, Conventional Commits, scope `expenses` unless the change is elsewhere.

## 3. What is explicitly out of scope

Do not attempt these. They are known, deliberate, and documented in `docs/BUILD_LOG.md` §6.

- Issue 5 — `.venv/` in git history. Requires rewriting history.
- Issue 6 — no superuser. A local command, not a code change.
- Issues 20 and 21 — worker supervision and export streaming. Both are deployment concerns.
- Issue 25 — bulk re-share on participant deletion. Not part of this batch.
- Anything touching Celery, Redis, Docker, or CI.
- **Layout and space optimisation of the expense form (issue 30, part three).** Parked by the owner.
  It is presentation, not function, and the owner may replace the server-rendered UI with a
  separate frontend such as React. Do not replace `{{ form.as_p }}`, do not add grid CSS, do not
  create a field partial. If a task above seems to need a layout change to work, it does not —
  stop and report instead.
