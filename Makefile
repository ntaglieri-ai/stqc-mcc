.PHONY: run migrate upgrade downgrade

ifeq ($(OS),Windows_NT)
PYTHON := $(firstword $(wildcard .venv/Scripts/python.exe venv/Scripts/python.exe))
else
PYTHON := $(firstword $(wildcard .venv/bin/python venv/bin/python))
endif
ifeq ($(PYTHON),)
PYTHON := python
endif

run:
	"$(PYTHON)" -m uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000

migrate:
	"$(PYTHON)" -m alembic revision --autogenerate -m "$(msg)"

upgrade:
	"$(PYTHON)" -m alembic upgrade head

downgrade:
	"$(PYTHON)" -m alembic downgrade -1
