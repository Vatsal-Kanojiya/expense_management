# Running the async pieces

Two background jobs, deliberately built on different machinery. The
difference is the point.

| | CSV export | Monthly digest |
|---|---|---|
| Trigger | A user clicks a button | The 1st of the month |
| Machinery | **Celery task** | **Management command + cron** |
| Why | Request-triggered. Building inline holds the connection open for an unbounded time | Clock-triggered. Nobody is waiting, so there is nothing to unblock |
| Runs twice? | Yes — `acks_late` redelivers | Yes — cron re-fires after a restart |
| Guard | `status == COMPLETE` early return | `UniqueConstraint(user, month)`, claimed before sending |

**The rule:** reach for a queue when the trigger is a *request*. When the
trigger is a clock, a command plus cron is usually the honest answer — and
saying that in an interview is worth more than saying "I've used Celery".

---

## Development

Three processes. Redis must be running first.

```bash
# 1. Broker
redis-server                       # or: sudo systemctl start redis

# 2. Worker (separate terminal, from the repo root)
.venv/bin/celery -A config worker --loglevel=info

# 3. Web
.venv/bin/python manage.py runserver
```

Check the worker is reachable:

```bash
.venv/bin/celery -A config inspect ping        # -> pong
.venv/bin/celery -A config inspect active      # currently running tasks
.venv/bin/celery -A config inspect registered  # tasks the worker knows about
```

`registered` is the first thing to check when a task raises
`NotRegistered`: it means the worker never imported the module. The worker
is a **separate process** — restart it after editing `tasks.py`. It does not
auto-reload like `runserver`.

### Running without Redis

```bash
CELERY_TASK_ALWAYS_EAGER=True .venv/bin/python manage.py runserver
```

Tasks then run inline, inside the request. Fine for a quick UI check, and
what the test suite uses. **Never set this in production** — every
"background" job silently becomes a blocking call.

---

## The digest

```bash
# Rehearse: report what would be sent, send nothing, record nothing
python manage.py send_monthly_digests --dry-run

# A specific month
python manage.py send_monthly_digests --month 2026-08

# One user, for testing
python manage.py send_monthly_digests --month 2026-08 --user alice

# What cron runs (defaults to the previous month)
python manage.py send_monthly_digests
```

With the console email backend the message prints to stdout, so the whole
flow is inspectable with no SMTP server.

### Cron

```cron
# Monthly spending digests — 06:00 on the 1st.
# Absolute paths: cron's PATH is minimal and its cwd is not the repo.
0 6 1 * * cd /srv/expense-tracker && /srv/expense-tracker/.venv/bin/python manage.py send_monthly_digests >> /var/log/expense-tracker/digest.log 2>&1
```

Points that catch people out:

- **Absolute paths, always.** Cron does not run your shell profile, so the
  `python` on its `PATH` is not the venv's.
- **Redirect both streams.** Without `2>&1` the errors go to local mail,
  which nobody reads.
- **Cron has no `.env`.** Either `EnvironmentFile` under systemd, or a
  wrapper script that sources it. `SECRET_KEY` has no default, so the
  command will refuse to start without it — loudly, which is the intent.
- **Running twice is safe.** That is what the unique constraint is for; you
  can rerun a failed month by hand without worrying.

### systemd timer, as an alternative

Better logging (`journalctl`), dependency ordering, and no silent failures:

```ini
# /etc/systemd/system/expense-digest.service
[Service]
Type=oneshot
WorkingDirectory=/srv/expense-tracker
EnvironmentFile=/srv/expense-tracker/.env
ExecStart=/srv/expense-tracker/.venv/bin/python manage.py send_monthly_digests

# /etc/systemd/system/expense-digest.timer
[Timer]
OnCalendar=*-*-01 06:00:00
Persistent=true          # runs on next boot if the machine was off
```

`Persistent=true` is the reason a timer often beats cron: a missed run is
caught up rather than skipped. It also means a run can fire twice — which
the idempotency guard already handles.

---

## Production notes

Not done in this project, listed so the gaps are known rather than assumed:

| Concern | What's needed |
|---|---|
| Worker supervision | systemd unit or a container, so a crashed worker restarts |
| Serving exports | `FileResponse` streams through Python. Use `X-Accel-Redirect` (nginx) or a signed S3 URL |
| Old export cleanup | Nothing deletes generated files. A periodic job should remove files older than N days |
| Result backend growth | Redis keys expire by default (`result_expires`, 1 day), but verify it |
| Monitoring | Flower, or exporting Celery events to your metrics stack |
| Dead letter handling | After `max_retries` a task is simply lost; real systems route it somewhere visible |
