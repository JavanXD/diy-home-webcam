.PHONY: test smoke diagnose timelapse sync-logo setup-r2 smoke-public help

help:
	@echo "Targets: test smoke diagnose timelapse sync-logo setup-r2 smoke-public"

test:
	cd pi/camera && python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt pytest pillow && .venv/bin/pytest -q
	cd pi/pipeline && python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt pytest && .venv/bin/pytest -q

smoke:
	./scripts/smoke-local.sh

diagnose:
	./scripts/diagnose.sh

timelapse:
	python3 scripts/make-timelapse.py \
	  -i data/outbox/history/example/landscape \
	  -o data/timelapse/example-landscape.gif \
	  --width 960 --delay-ms 150 --max-frames 300

sync-logo:

setup-r2:
	./scripts/setup-r2.sh

smoke-public:
	./scripts/smoke-public.sh
