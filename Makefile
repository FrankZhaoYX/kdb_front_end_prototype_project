.PHONY: help setup data kdb kdb-q app dev test clean stop

PY      := ./.venv/bin/python
PIP     := ./.venv/bin/pip
KDB_PORT?= 5000
APP_PORT?= 8000
# Loopback by default. APP_HOST=0.0.0.0 exposes the console to your network --
# there is no auth in front of it, see DESIGN.md.
APP_HOST?= 127.0.0.1
export KDB_HTML2PDF ?= $(CURDIR)/scripts/html2pdf.sh

help:
	@echo "setup    create .venv and install dependencies"
	@echo "data     download the public CSVs and build the dataset"
	@echo ""
	@echo "kdb      run the kdb+ gateway on embedded KDB-X   (port $(KDB_PORT))"
	@echo "kdb-q    run the same kdb/*.q under a standalone q binary"
	@echo "app      run the FastAPI front-end                (port $(APP_PORT))"
	@echo "dev      run both, backgrounded, tailing the logs"
	@echo ""
	@echo "test     run the end-to-end suite against real kdb+"
	@echo "stop     stop anything started by 'make dev'"

setup:
	python3 -m venv .venv
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	@echo "done. next: make data"

data:
	./scripts/fetch_raw.sh

# Hosts kdb/*.q on a socket using embedded KDB-X, since KDB-X ships as a
# library rather than a standalone q binary.
kdb:
	$(PY) scripts/serve_q.py -p $(KDB_PORT)

# The same q sources under a real q binary, if you have one on PATH.
kdb-q:
	q kdb/start.q -p $(KDB_PORT)

app:
	KDB_PORT=$(KDB_PORT) $(PY) -m uvicorn app.main:app \
	  --host $(APP_HOST) --port $(APP_PORT) --reload

dev:
	@mkdir -p var/log
	@$(PY) scripts/serve_q.py -p $(KDB_PORT) > var/log/kdb.log 2>&1 & echo $$! > var/kdb.pid
	@sleep 4
	@KDB_PORT=$(KDB_PORT) $(PY) -m uvicorn app.main:app --host $(APP_HOST) \
	  --port $(APP_PORT) > var/log/app.log 2>&1 & echo $$! > var/app.pid
	@sleep 2
	@echo "open http://$(APP_HOST):$(APP_PORT)   (make stop to shut down)"
	@tail -f var/log/kdb.log var/log/app.log

# The suite starts its own gateway; KDB_TEST_PORT points it at one you run.
test:
	$(PY) -m pytest -q

stop:
	@-kill `cat var/kdb.pid 2>/dev/null` 2>/dev/null || true
	@-kill `cat var/app.pid 2>/dev/null` 2>/dev/null || true
	@rm -f var/kdb.pid var/app.pid
	@echo "stopped"

clean:
	rm -rf var/reports/* var/log/* .pytest_cache
	find . -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
