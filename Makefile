# ─────────────────────────────────────────────────────────────────────────────
# airkal — low-rate peer state sharing over UDP with Kalman prediction
#           (PX4 SITL demo; see PLAN.md)
#
# Fresh host bring-up:
#   make install          # python venv + dependencies
#   make build            # PX4 SITL docker image (one-time, ~10-30 min)
#   make run N=3          # SITL x3 + agents x3 + C2 + netstats
#   → open http://localhost:8080, press "start", play with the rate slider
#   make down             # stop everything, leave nothing behind
# ─────────────────────────────────────────────────────────────────────────────

N          ?= 3
C2_PORT    ?= 8080
IMAGE_NAME ?= airkal-sitl
PX4_TAG    := $(strip $(shell cat sitl/VERSION))
IMAGE      := $(IMAGE_NAME):$(PX4_TAG)
VENV       := .venv
PY         := $(VENV)/bin/python
ROOT       := $(CURDIR)

export IMAGE N C2_PORT PY ROOT

.DEFAULT_GOAL := help
.PHONY: help install build test coverage up agents c2 stats run down status \
        logs verify smoke clean distclean

help: ## show this help
	@echo "airkal targets:"
	@grep -hE '^[a-z][a-z0-9-]*:.*##' $(MAKEFILE_LIST) | \
	  awk -F':.*## ' '{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'
	@echo "variables: N=$(N) C2_PORT=$(C2_PORT) IMAGE=$(IMAGE)"

# ── one-time setup ───────────────────────────────────────────────────────────

install: ## create python venv and install dependencies
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install --quiet --upgrade pip
	$(VENV)/bin/pip install --quiet -r requirements.txt -r requirements-dev.txt
	@echo "install: ok ($(VENV))"

build: ## build the pinned PX4 SITL docker image
	docker build -t $(IMAGE) --build-arg PX4_TAG=$(PX4_TAG) sitl/

# ── tests ────────────────────────────────────────────────────────────────────

test: ## run the unit test suite
	$(PY) -m pytest tests/

coverage: ## unit tests + coverage gate (>=80% on kalmanlib/ + common/)
	$(PY) -m pytest tests/ --cov=kalmanlib --cov=common \
	  --cov-report=term-missing --cov-fail-under=80

# ── lifecycle (everything by hand, on demand) ────────────────────────────────

up: ## start N SITL containers and wait until MAVLink is healthy
	scripts/up.sh $(N)

agents: ## start N agents (background; logs in var/log/)
	scripts/agents.sh $(N)

c2: ## start the C2 server (background; web page on :$(C2_PORT))
	scripts/c2.sh

stats: ## live UDP traffic table in this terminal (Ctrl-C to quit)
	$(PY) -m netstats.main

run: up agents c2 ## full stack: up + agents + c2 + netstats (background)
	scripts/netstats-bg.sh
	@echo "run: fleet of $(N) is up — open http://localhost:$(C2_PORT)"

down: ## stop agents, C2, netstats and all SITL containers
	scripts/down.sh

status: ## what is running, which ports
	scripts/status.sh

logs: ## tail all component logs
	tail -n 30 -F var/log/*.log

# ── verification ─────────────────────────────────────────────────────────────

verify: ## per-instance MAVLink/EKF check: heartbeat + ODOMETRY covariance
	$(PY) scripts/verify_sitl.py --n $(N)

smoke: ## end-to-end smoke test on 1 drone (SITL + agent + rate command)
	scripts/smoke.sh

# ── housekeeping ─────────────────────────────────────────────────────────────

clean: ## remove caches and runtime state (keeps venv + image)
	rm -rf var .pytest_cache .coverage htmlcov
	find . -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true

distclean: clean ## also remove the venv and the SITL image
	rm -rf $(VENV)
	docker rmi $(IMAGE) 2>/dev/null || true
