# Multi-stage, so the image that ships has no compiler and no build cache.
#
# The stages exist for size and for attack surface: build tools are the
# usual way a container ends up with a package manager an attacker can use.

FROM python:3.10-slim AS builder

# Never write .pyc into the layer, never buffer logs (a crashed container
# would otherwise lose whatever was still in the buffer).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Requirements copied alone, before the source. Docker caches per layer, so
# this one is only rebuilt when the dependencies actually change -- copying
# the source first would reinstall everything on every edit.
COPY requirements.txt .
RUN python -m venv /opt/venv && /opt/venv/bin/pip install -r requirements.txt


FROM python:3.10-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# A non-root user. A container process running as root is root on the host
# kernel; a container escape then starts from the best possible position.
RUN useradd --create-home --uid 1000 app
WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app . .

# Collected at build time, not at start: every replica would otherwise
# repeat the same work, and a start-up that writes to the image is a
# start-up that can fail on a read-only filesystem.
#
# A throwaway key because collectstatic imports settings, which refuses to
# load without one. It never reaches the running container.
RUN SECRET_KEY=build-only DEBUG=False ALLOWED_HOSTS=localhost \
    python manage.py collectstatic --noinput

USER app

EXPOSE 8000

# gunicorn, not runserver. runserver is single-threaded, reloads on file
# change, and its own documentation says it has not been security audited.
#
# Exec form, no shell: gunicorn becomes PID 1 and receives SIGTERM directly,
# so `docker stop` drains connections instead of killing them after 10s.
CMD ["gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "3", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
