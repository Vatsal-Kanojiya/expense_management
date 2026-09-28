# Multi-stage, so the image that ships has no compiler and no build cache.
#
# The stages exist for size and for attack surface: build tools are the
# usual way a container ends up with a package manager an attacker can use.
#
# Four stages, and their order is load-bearing:
#
#   builder      production dependencies, in a venv
#   dev-builder  the same venv plus the linters, coverage and watchfiles
#   dev          the dev venv and no source -- compose.dev.yaml bind-mounts
#                the checkout over /app instead (DECISIONS D31, D32)
#   runtime      the production venv and the source
#
# runtime is LAST, so `docker build .` with no --target still produces the
# production image. compose.yaml asks for it by name anyway.

FROM python:3.10-slim AS builder

# Never write .pyc into the layer, never buffer logs (a crashed container
# would otherwise lose whatever was still in the buffer).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Requirements copied alone, before the source. Docker caches per layer, so
# this one is only rebuilt when the dependencies actually change -- copying
# the source first would reinstall everything on every edit.
COPY requirements.txt .
RUN python -m venv /opt/venv && /opt/venv/bin/pip install -r requirements.txt


FROM builder AS dev-builder

COPY requirements-dev.txt .
RUN /opt/venv/bin/pip install -r requirements-dev.txt


# What dev and runtime share: the interpreter settings, the app user and the
# directories that user must be able to write.
FROM python:3.10-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    MEDIA_ROOT=/data/media

# A non-root user. A container process running as root is root on the host
# kernel; a container escape then starts from the best possible position.
#
# Its ids come from the build, not a constant: in development the container
# writes into your checkout (a new migration, a file ruff reformatted), and
# those files should be yours, not uid 1000's or root's. compose.yaml passes
# HOST_UID/HOST_GID from .env; the defaults suit a registry build. D37.
#
# The group is reused when the host's gid already exists in the image
# (gid 100, "users", on some distributions) rather than failing the build.
ARG APP_UID=1000
ARG APP_GID=1000
RUN (getent group "$APP_GID" >/dev/null || groupadd --gid "$APP_GID" app) \
    && useradd --create-home --uid "$APP_UID" --gid "$APP_GID" app \
    && mkdir -p /app /data/media /data/beat \
    && chown "$APP_UID:$APP_GID" /app /data/media /data/beat

# The directories themselves, not only their contents, must belong to the
# app user. Phase 11 had `COPY --chown` give it the files while WORKDIR left
# /app owned by root, so nothing could create a file there: beat died on its
# schedule file and every upload and export failed (BUILD_LOG issues 38, 39).
# Media and beat's schedule now live under /data, on volumes, and a new
# named volume copies this ownership when compose first creates it. D34.
WORKDIR /app


FROM base AS dev

COPY --from=dev-builder /opt/venv /opt/venv

USER app

EXPOSE 8000

# compose.dev.yaml replaces this with migrate-then-runserver; it is here so
# the image does something sensible on its own.
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]


FROM base AS runtime

COPY --from=builder /opt/venv /opt/venv

# Numeric ids rather than the name, so this still works when the group
# was reused above and is not called "app".
ARG APP_UID=1000
ARG APP_GID=1000
COPY --chown=${APP_UID}:${APP_GID} . .

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
