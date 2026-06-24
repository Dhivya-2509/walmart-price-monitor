#!/usr/bin/env bash
# build.sh — Render build script for the Cron Job (scraper)
# Installs Python dependencies + Playwright's Chromium browser

set -e

pip install -r requirements_cloud.txt
playwright install chromium
# Note: skip install-deps (requires root); --no-sandbox in scraper handles this
