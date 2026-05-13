#!/usr/bin/env python3
"""Web UI for RedditVideoMakerBot — generate Reddit videos from the browser."""

import json
import sys
import threading
import traceback
from contextlib import redirect_stdout
from datetime import datetime
from io import StringIO
from pathlib import Path

# Add parent directory to path so we can import the bot modules
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from flask import Flask, jsonify, render_template, request, send_from_directory

app = Flask(__name__, template_folder="templates", static_folder="static")

# Load bot config manually so we never block on interactive prompts.
from utils import settings
import toml

def _deep_merge(base, overlay):
    for k, v in overlay.items():
        if isinstance(v, dict) and k in base and isinstance(base[k], dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base

# Start from an empty config and fill with template defaults, then overlay user config
settings.config = {}
with open(BASE_DIR / "utils" / ".config.template.toml") as f:
    template = toml.load(f)
# Convert template entries (which are dicts with metadata) to plain values
def _flatten_template(obj):
    out = {}
    for k, v in obj.items():
        if isinstance(v, dict) and "default" in v:
            out[k] = v["default"]
        elif isinstance(v, dict):
            out[k] = _flatten_template(v)
        else:
            out[k] = v
    return out

settings.config = _flatten_template(template)

# Overlay user config.toml if it exists
if (BASE_DIR / "config.toml").exists():
    with open(BASE_DIR / "config.toml") as f:
        user_cfg = toml.load(f)
    settings.config = _deep_merge(settings.config, user_cfg)

import os
os.environ["translators_default_region"] = "EN"

from main import main

# ---------------------------------------------------------------------------
# Shared state (single-task queue is fine for a local tool)
# ---------------------------------------------------------------------------
generation = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "log": "",
    "result": None,
    "error": None,
    "video_path": None,
}


def _available_backgrounds():
    videos, audios = [], []
    with open(BASE_DIR / "utils" / "background_videos.json") as f:
        data = json.load(f)
        videos = sorted(k for k in data if not k.startswith("_"))
    with open(BASE_DIR / "utils" / "background_audios.json") as f:
        data = json.load(f)
        audios = sorted(k for k in data if not k.startswith("_"))
    return videos, audios


def _list_generated_videos():
    results_dir = BASE_DIR / "results"
    if not results_dir.exists():
        return []
    videos = []
    for p in results_dir.rglob("*.mp4"):
        videos.append({
            "name": p.name,
            "path": str(p.relative_to(BASE_DIR)),
            "size_mb": round(p.stat().st_size / (1024 * 1024), 2),
            "modified": datetime.fromtimestamp(p.stat().st_mtime).isoformat(),
        })
    videos.sort(key=lambda x: x["modified"], reverse=True)
    return videos


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    videos, audios = _available_backgrounds()
    return render_template("index.html", videos=videos, audios=audios)


@app.route("/videos")
def list_videos():
    return jsonify(_list_generated_videos())


@app.route("/generate", methods=["POST"])
def generate():
    global generation
    if generation["running"]:
        return jsonify({"error": "A generation is already in progress."}), 409

    data = request.get_json(force=True) or {}

    # Update bot config in-memory (and persist it so the bot reads it)
    cfg = settings.config

    mode = data.get("mode", "search")
    if mode == "search":
        cfg["reddit"]["thread"]["subreddit"] = ""
        cfg["reddit"]["thread"]["search_query"] = data.get("query", "AskReddit")
        cfg["reddit"]["thread"]["search_sort"] = data.get("sort", "hot")
        cfg["reddit"]["thread"]["search_time"] = data.get("time", "all")
    else:
        cfg["reddit"]["thread"]["search_query"] = ""
        cfg["reddit"]["thread"]["subreddit"] = data.get("subreddit", "AskReddit")

    cfg["settings"]["background"]["background_video"] = data.get("video", "minecraft")
    cfg["settings"]["background"]["background_audio"] = data.get("audio", "lofi")
    cfg["settings"]["tts"]["voice_choice"] = data.get("voice", "googletranslate")
    cfg["settings"]["storymode"] = data.get("storymode", False)
    cfg["settings"]["times_to_run"] = 1

    # Persist config so the bot can read it if it re-opens the file
    import toml

    with open(BASE_DIR / "config.toml", "w") as f:
        toml.dump(cfg, f)

    # Reset state
    generation = {
        "running": True,
        "started_at": datetime.now().isoformat(),
        "finished_at": None,
        "log": "",
        "result": None,
        "error": None,
        "video_path": None,
    }

    def run():
        buf = StringIO()
        try:
            with redirect_stdout(buf):
                main()
            generation["log"] = buf.getvalue()
            generation["result"] = "Video generated successfully!"

            # Find newest video
            vids = _list_generated_videos()
            if vids:
                generation["video_path"] = vids[0]["path"]
        except SystemExit as exc:
            # The bot calls exit() in several places (e.g. no comments found).
            # Treat a clean exit (code 0) as success, otherwise as error.
            generation["log"] = buf.getvalue()
            if exc.code == 0 or exc.code is None:
                generation["result"] = "Finished."
            else:
                generation["error"] = f"Bot exited with code {exc.code}"
        except Exception as exc:
            generation["log"] = buf.getvalue() + "\n" + traceback.format_exc()
            generation["error"] = str(exc)
        finally:
            generation["running"] = False
            generation["finished_at"] = datetime.now().isoformat()

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"status": "started"})


@app.route("/status")
def status():
    return jsonify(generation)


@app.route("/download/<path:filename>")
def download(filename):
    return send_from_directory(BASE_DIR, filename, as_attachment=True)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print(f"Starting RedditVideoMakerBot Web UI …")
    print(f"Open http://<your-ip>:5000 in your browser")
    # Use threaded=True so the status endpoint works while /generate runs
    app.run(host="0.0.0.0", port=5000, threaded=True, debug=False)
