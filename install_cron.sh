#!/bin/bash
# Install LOCAL cron job for the weekly content planner.
# Runs every Sunday at 8 PM local time.
#
# NOTE: The primary scheduler is GitHub Actions (.github/workflows/weekly-planner.yml).
# This local cron is an optional backup for offline use.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="$SCRIPT_DIR/venv/bin/python3"
MAIN="$SCRIPT_DIR/main.py"
LOG="$SCRIPT_DIR/output/planner.log"

# Verify paths
if [ ! -f "$PYTHON" ]; then
    echo "Error: Python not found at $PYTHON"
    echo "Run: python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

CRON_CMD="0 20 * * 0 cd $SCRIPT_DIR && $PYTHON $MAIN plan >> $LOG 2>&1"

# Check if cron job already exists
if crontab -l 2>/dev/null | grep -q "$MAIN plan"; then
    echo "Cron job already installed. Current entry:"
    crontab -l | grep "$MAIN plan"
    exit 0
fi

# Add to crontab
(crontab -l 2>/dev/null; echo "$CRON_CMD") | crontab -

echo "Cron job installed:"
echo "  Schedule: Every Sunday at 8:00 PM"
echo "  Command:  $CRON_CMD"
echo "  Log:      $LOG"
echo ""
echo "To verify: crontab -l"
echo "To remove: crontab -l | grep -v '$MAIN plan' | crontab -"
