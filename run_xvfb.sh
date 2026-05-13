#!/bin/sh
# Run the bot with a virtual display (required because Reddit blocks headless browsers)
cd "$(dirname "$0")"
xvfb-run -a python main.py "$@"
