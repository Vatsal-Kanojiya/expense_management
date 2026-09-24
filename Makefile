# The front door to the Docker stack. Every target is a thin `docker compose`
# call, and docs/DOCKER.md §9 shows the raw command behind each one. Make
# is here to save typing, not to be a second place the stack is defined:
# if a target starts to need logic, that logic belongs in Compose. D38.
#
#   make           list the targets
#   make up        production-like, http://127.0.0.1:8765
#   make dev       the same stack, with your checkout mounted live

COMPOSE := docker compose
DEV     := docker compose -f compose.yaml -f compose.dev.yaml

# Docker 29's containerd image store gives every build a provenance
# attestation stamped with the build time, so even a fully cached build
# gets a new image ID -- and Compose then recreates every app container on
# each `make up`, with nothing changed. Without the default attestations an
# unchanged tree rebuilds to the same ID and nothing restarts. They matter
# for images pushed to a registry, not for these local ones.
export BUILDX_NO_DEFAULT_ATTESTATIONS := 1

# Set on the command line, e.g. `make logs SERVICE=worker`.
SERVICE ?=
CMD     ?=
ARGS    ?=
FILE    ?=

.DEFAULT_GOAL := help
.PHONY: help env up dev down ps logs update update-dev shell manage migrate \
        createsuperuser test lint psql redis-cli backup restore-db restore-media \
        destroy url

help: ## List the targets
	@awk 'BEGIN {FS = ":.*## "} /^[a-z-]+:.*## / {printf "  %-16s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# A file target: made once, never overwritten. `up` and `dev` depend on it,
# so the first run creates it without being asked. Mode 600, because it
# holds the secret key and the database password.
.env:
	@key=$$(python3 -c 'import secrets; print(secrets.token_urlsafe(50))' 2>/dev/null \
	    || openssl rand -hex 40 2>/dev/null); \
	if [ -z "$$key" ]; then echo "Need python3 or openssl to generate SECRET_KEY." >&2; exit 1; fi; \
	uid=$$(id -u); gid=$$(id -g); \
	if [ "$$uid" = 0 ]; then uid=1000; gid=1000; fi; \
	sed -e "s|^SECRET_KEY=.*|SECRET_KEY=$$key|" \
	    -e "s|^HOST_UID=.*|HOST_UID=$$uid|" \
	    -e "s|^HOST_GID=.*|HOST_GID=$$gid|" .env.example > .env; \
	chmod 600 .env; \
	echo "Created .env with a fresh SECRET_KEY and HOST_UID=$$uid, HOST_GID=$$gid."

env: .env ## Create .env from .env.example, once (secret key, your UID/GID)
	@echo ".env is in place. Ports, passwords and keys: docs/DOCKER.md §6."

up: .env ## Production-like: build and start in the background
	$(COMPOSE) up -d --build --remove-orphans
	@$(MAKE) --no-print-directory url

dev: .env ## Development: build and start with your checkout mounted live
	$(DEV) up -d --build --remove-orphans
	@$(MAKE) --no-print-directory url

url:
	@addr=$$($(COMPOSE) port web 8000 2>/dev/null | sed 's/^0\.0\.0\.0:/127.0.0.1:/'); \
	if [ -n "$$addr" ]; then \
	  echo; echo "  Running at http://$$addr"; \
	  echo "  make logs  follows the output;  make ps  shows health;  make down  stops it."; \
	fi

down: ## Stop and remove the containers; data volumes are kept
	$(COMPOSE) down --remove-orphans

ps: ## Show each service's status and health
	$(COMPOSE) ps

logs: ## Follow the logs (all, or SERVICE=web|worker|beat|db|redis)
	$(COMPOSE) logs -f --tail=100 $(SERVICE)

update: ## git pull, then rebuild and restart the production-like stack
	git pull --ff-only
	@$(MAKE) --no-print-directory up

update-dev: ## git pull, rebuild the dev image if needed, then migrate
	git pull --ff-only
	@$(MAKE) --no-print-directory dev
	$(COMPOSE) exec web python manage.py migrate --noinput

shell: ## Open a bash shell in the web container
	$(COMPOSE) exec web bash

manage: ## Run a manage.py command: make manage CMD="showmigrations"
	$(COMPOSE) exec web python manage.py $(CMD)

migrate: ## Apply database migrations
	$(COMPOSE) exec web python manage.py migrate

createsuperuser: ## Create an active account that can also use /admin/
	$(COMPOSE) exec web python manage.py createsuperuser

test: ## Run the test suite on Postgres, in a throwaway container (ARGS=...)
	$(DEV) build web
	$(DEV) run --rm web python manage.py test --noinput $(ARGS)

lint: ## ruff check and ruff format --check, in the dev image
	$(DEV) build web
	$(DEV) run --rm --no-deps web sh -c "ruff check --no-cache . && ruff format --check --no-cache ."

psql: ## Open psql on the database
	$(COMPOSE) exec db sh -c 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"'

redis-cli: ## Open redis-cli (database 0 is the Celery queue: look, do not flush)
	$(COMPOSE) exec redis redis-cli

# The dump is written through stdout, so it lands on your disk and never in
# a container or a volume. A failed step removes its half-written file.
backup: ## Dump the database and archive media into backups/
	@mkdir -p backups
	@ts=$$(date +%Y%m%d-%H%M%S); db=backups/db-$$ts.dump; media=backups/media-$$ts.tar.gz; \
	$(COMPOSE) exec -T db sh -c 'pg_dump -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" --format=custom' \
	    > $$db || { rm -f $$db; exit 1; }; \
	$(COMPOSE) exec -T web tar czf - -C /data/media . > $$media || { rm -f $$media; exit 1; }; \
	echo "Wrote $$db ($$(du -h $$db | cut -f1)) and $$media ($$(du -h $$media | cut -f1))."

# The app containers are stopped for the restore, so nothing writes while
# tables are dropped and recreated, and started again even if it fails.
restore-db: ## Restore a database dump: make restore-db FILE=backups/db-<ts>.dump
	@test -f "$(FILE)" || { echo "Usage: make restore-db FILE=backups/db-<timestamp>.dump" >&2; exit 1; }
	$(COMPOSE) stop web worker beat
	@$(COMPOSE) exec -T db sh -c 'pg_restore -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" --clean --if-exists --no-owner' \
	    < "$(FILE)"; status=$$?; \
	$(COMPOSE) start web worker beat; \
	exit $$status

restore-media: ## Restore a media archive: make restore-media FILE=backups/media-<ts>.tar.gz
	@test -f "$(FILE)" || { echo "Usage: make restore-media FILE=backups/media-<timestamp>.tar.gz" >&2; exit 1; }
	$(COMPOSE) exec -T web tar xzf - -C /data/media < "$(FILE)"

destroy: ## Remove the containers AND delete every data volume (asks first)
	@printf 'This deletes the database, uploaded bills and exports for good. Type "yes" to continue: '; \
	read answer; \
	if [ "$$answer" = yes ]; then $(COMPOSE) down -v --remove-orphans; else echo "Aborted; nothing deleted."; fi
