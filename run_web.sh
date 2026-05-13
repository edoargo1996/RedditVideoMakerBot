#!/bin/sh
# Start the RedditVideoMakerBot web UI.
# On headless servers use:  xvfb-run -a ./run_web.sh
cd "$(dirname "$0")"
source venv/bin/activate
python web_ui/app.py "$@"
