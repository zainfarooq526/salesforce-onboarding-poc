.PHONY: install api web test eval up

install:
	cd backend && pip install -r requirements-dev.txt
	cd frontend && npm install

api:
	cd backend && flask --app wsgi run --port 5000 --debug

web:
	cd frontend && npm run dev

test:
	cd backend && pytest -q

eval:
	cd backend && python -m eval.run_eval --report ../docs/eval-report.md

up:
	docker compose up --build
