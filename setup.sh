#!/usr/bin/env bash
# Setup script for used-cars-monitor on Ubuntu LTS
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Used Cars Monitor Setup ==="

# 1. Create virtual environment
if [ ! -d "venv" ]; then
  echo "[1/5] Creating Python virtual environment..."
  python3 -m venv venv
else
  echo "[1/5] Virtual environment already exists, skipping."
fi

# 2. Install dependencies
echo "[2/5] Installing Python dependencies..."
venv/bin/pip install --quiet --upgrade pip
venv/bin/pip install --quiet -r requirements.txt

# 3. Install Playwright browsers
echo "[3/5] Installing Playwright Chromium browser..."
venv/bin/playwright install chromium
venv/bin/playwright install-deps chromium

# 4. Create .env if it doesn't exist
if [ ! -f ".env" ]; then
  echo "[4/5] Creating .env from template..."
  cp .env.example .env
  echo ""
  echo "  *** IMPORTANT: Edit .env and set TARGET_URL before running! ***"
  echo ""
else
  echo "[4/5] .env already exists, skipping."
fi

# 5. Set up cron job (3 times/day: 08:00, 14:00, 20:00)
echo "[5/5] Setting up cron job..."
PYTHON_BIN="$SCRIPT_DIR/venv/bin/python"
RUN_SCRIPT="$SCRIPT_DIR/run.py"
CRON_LINE="0 8,14,20 * * * $PYTHON_BIN $RUN_SCRIPT >> $SCRIPT_DIR/logs/cron.log 2>&1"

# Check if cron line already exists
if crontab -l 2>/dev/null | grep -qF "$RUN_SCRIPT"; then
  echo "  Cron job already configured, skipping."
else
  (crontab -l 2>/dev/null; echo "$CRON_LINE") | crontab -
  echo "  Cron job added: runs at 08:00, 14:00, 20:00 every day"
fi

echo ""
echo "=== Setup complete! ==="
echo ""
echo "Next steps:"
echo "  1. Edit .env and set TARGET_URL"
echo "  2. Run manually: venv/bin/python run.py"
echo "  3. Add --debug on first run to inspect API responses: venv/bin/python run.py --debug"
echo "  4. The generated page will be at: output/index.html"
echo ""
echo "Cron job runs at 08:00, 14:00 and 20:00 every day."
echo "Logs are saved in: $SCRIPT_DIR/logs/"
