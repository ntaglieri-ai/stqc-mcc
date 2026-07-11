.PHONY: run migrate upgrade downgrade

run:
	./venv/bin/uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000

migrate:
	alembic revision --autogenerate -m "$(msg)"

upgrade:
	./venv/bin/alembic upgrade head

downgrade:
	./venv/bin/alembic downgrade -1
