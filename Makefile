PYTHON ?= python3
GATEWAY_PY ?= $(shell if [ -x gateway/.venv/bin/python ]; then printf '%s\n' gateway/.venv/bin/python; elif [ -x gateway/.venv/Scripts/python.exe ]; then printf '%s\n' gateway/.venv/Scripts/python.exe; else printf '%s\n' gateway/.venv/bin/python; fi)
PIO ?= $(shell sh scripts/find-platformio.sh 2>/dev/null || printf '%s\n' pio)
WEB_HOST ?= 0.0.0.0
WEB_PORT ?= 8000
FIRMWARE_DIR := firmware/xiao_nrf52840_sense

.PHONY: help setup web check require-platformio firmware upload monitor report process train evaluate pipeline clean

help:
	@echo "CatSense V0 commands"
	@echo "  make setup     Create gateway virtualenv and install Python deps"
	@echo "  make web       Run the local web logger"
	@echo "  make check     Run lightweight source checks"
	@echo "  make firmware  Build firmware with PlatformIO"
	@echo "  make upload    Upload firmware over USB"
	@echo "  make monitor   Open PlatformIO serial monitor"
	@echo "  make report    Run raw data quality report"
	@echo "  make process   Build processed CSV/features from raw data"
	@echo "  make train     Train baseline model"
	@echo "  make evaluate  Evaluate model by recording session"
	@echo "  make pipeline  Run report, process, train, and evaluate"
	@echo "  make clean     Remove generated caches"

setup:
	$(PYTHON) -m venv gateway/.venv
	$(GATEWAY_PY) -m pip install --upgrade pip
	$(GATEWAY_PY) -m pip install -r gateway/requirements.txt

web:
	"$(GATEWAY_PY)" gateway/web_logger.py --host $(WEB_HOST) --port $(WEB_PORT)

check:
	sh scripts/check.sh

require-platformio:
	@if ! command -v "$(PIO)" >/dev/null 2>&1 && [ ! -x "$(PIO)" ]; then \
		echo "PlatformIO not found."; \
		echo "Install it with: python3 -m pip install -U platformio"; \
		echo "macOS/Linux default: $$HOME/.platformio/penv/bin"; \
		echo "Windows Git Bash default: $$HOME/.platformio/penv/Scripts"; \
		exit 127; \
	fi

firmware: require-platformio
	cd $(FIRMWARE_DIR) && "$(PIO)" run

upload: require-platformio
	cd $(FIRMWARE_DIR) && "$(PIO)" run --target upload

monitor: require-platformio
	cd $(FIRMWARE_DIR) && "$(PIO)" device monitor

report:
	cd gateway && ../$(GATEWAY_PY) dataset_report.py

process:
	cd gateway && ../$(GATEWAY_PY) build_dataset.py

train:
	cd gateway && ../$(GATEWAY_PY) train_baseline.py

evaluate:
	cd gateway && ../$(GATEWAY_PY) evaluate_by_session.py

pipeline: report process train evaluate

clean:
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	find . -name "*.pyc" -type f -delete
