.PHONY: clean test run

test:
	.venv/bin/pytest tests/ -o asyncio_mode=auto

run:
	.venv/bin/hass -c .

clean:
	# Clean python caches (excluding .venv)
	find custom_components tests -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find custom_components tests -type f -name "*.py[co]" -delete 2>/dev/null || true
	
	# Clean test/coverage artifacts
	rm -rf .pytest_cache
	rm -rf .coverage
	rm -rf htmlcov
	
	# Clean Home Assistant local test setup artifacts
	rm -rf home-assistant_v2.db*
	rm -rf home-assistant.log*
	rm -f .HA_VERSION
	rm -f .ha_run.lock
	rm -rf .storage
	rm -f configuration.yaml
	rm -f secrets.yaml
	rm -f automations.yaml
	rm -f scenes.yaml
	rm -f scripts.yaml
	rm -rf blueprints
	rm -rf tts


