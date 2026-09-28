# Frontend pack — Expense Tracker

Everything needed to build a frontend for Expense Tracker on its API, from scratch.

| File | What it is | Read it |
|---|---|---|
| [BRD.md](BRD.md) | **Business requirements and scope of work**: users, the domain, 29 business rules, every screen with its requirements and acceptance criteria, quality requirements, milestones and sign-off | First, fully |
| [API_GUIDE.md](API_GUIDE.md) | **Integration guide**: environments, tokens and refresh, CORS, errors and their codes, pagination, formats, writing expenses, background jobs, downloads, rate limits | Second, before writing code |
| [API_REFERENCE.md](API_REFERENCE.md) | **Every endpoint**, each with a real request and response, and its errors | While building each screen |
| [postman/](postman/) | **Postman collection** (54 requests in a runnable journey, with the recorded responses saved as examples), local and hosted environments, and a sample bill image | To try the API before coding against it |
| [openapi.yaml](openapi.yaml) | **OpenAPI 3 schema**, the machine-readable contract | To generate TypeScript types |

The reference, the collection and the schema are **generated from a real run of the API**
(`python manage.py build_api_docs`), and tests fail when they fall out of step with the code, so
they are always accurate for the commit they sit in.

## Start in 15 minutes

1. **Get an API.** Either the hosted one (the product owner sends the URL and adds your origin, for
   example `http://localhost:5173`, to the server's CORS list), or run it locally from the repository
   root with `make up`, which serves it on `http://127.0.0.1:8765`. Locally, emails such as
   verification links appear in `make logs SERVICE=web`.
2. **Get an account.** Ask for one, or sign up through the API.
3. **Explore.** Open `<server>/api/v1/docs/`, click **Authorize**, and try requests in the browser.
4. **Run the journey.** Import the Postman collection and an environment, set `username` and
   `password`, and run folder **0 · Start here**, then the rest. Read the saved example responses
   under each request.
5. **Read the BRD**, then the integration guide, then start with milestone M0 (BRD §10).

## Key facts at a glance

- Base URL: `<server>/api/v1/`. **Every path ends with `/`.**
- Auth: `POST auth/login/` returns `access` (30 min) and `refresh` (14 days). Send
  `Authorization: Bearer <access>`. Refresh tokens **rotate**, so store the new one every time.
- Money is **strings** with two decimals (`"1450.00"`). Show it as ₹ with Indian grouping.
- The expense form sends **`include_self: false`** with the exact people it shows (API guide §9).
- Lists are cursor-paginated: follow `next`. The expense list also returns `count` and
  `total_amount`.
- Errors: `{"detail", "code"}` or field errors. The code catalogue is in API guide §6.3.
- Exports and bill scans answer 202, then you poll. Downloads and images need the token, so fetch
  them as blobs (API guide §10).
- Emails link to your routes `/verify-email/:uid/:token`, `/reset-password/:uid/:token` and
  `/exports/:id`.

## For maintainers

After any API change: `make api-docs` (or `python manage.py build_api_docs`), review the diff of
`docs/frontend/`, and commit it with the change. Edit the journey in `expenses/api/journey.py`, and
the prose in `BRD.md`, `API_GUIDE.md` and this file, by hand.
