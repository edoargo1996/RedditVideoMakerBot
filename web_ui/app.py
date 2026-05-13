#!/usr/bin/env python3
"""Web UI for RedditVideoMakerBot — generate Reddit videos from the browser."""

import json
import sys
import threading
import traceback
import re
from contextlib import redirect_stdout, redirect_stderr
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


@app.route("/preview", methods=["POST"])
def preview():
    """Search Reddit and return candidate threads for preview."""
    data = request.get_json(force=True) or {}
    mode = data.get("mode", "search")
    query = data.get("query", "").strip()
    subreddit_name = data.get("subreddit", "").strip()
    sort = data.get("sort", "hot")
    time_filter = data.get("time", "all")
    limit = int(data.get("limit", 25))
    storymode = data.get("storymode", False)

    from reddit.subreddit_scraper import FakeReddit

    reddit = FakeReddit()
    threads = []

    if mode == "search" and query:
        threads = list(reddit.search(query, sort=sort, time_filter=time_filter, limit=limit))
    elif subreddit_name:
        sub = reddit.subreddit(subreddit_name)
        threads = list(sub.hot(limit=limit))
    else:
        return jsonify({"error": "Missing query or subreddit"}), 400

    if not threads:
        return jsonify({"threads": [], "message": "No threads found. Try broadening your search or changing the time filter."})

    # Apply filters (mirror utils/subreddit logic without side effects)
    blocked_raw = settings.config["reddit"]["thread"].get("blocked_words", "")
    blocked = [w.strip().lower() for w in blocked_raw.split(",") if w.strip()]
    min_comments = int(settings.config["reddit"]["thread"].get("min_comments", 0))
    allow_nsfw = settings.config["settings"].get("allow_nsfw", False)
    max_post_len = settings.config["settings"].get("storymode_max_length", 2000)

    candidates = []
    for t in threads:
        # Skip NSFW
        if t.over_18 and not allow_nsfw:
            continue
        # Skip stickied
        if t.stickied:
            continue
        # Skip blocked words
        text = (t.title or "") + " " + (t.selftext or "")
        if any(w in text.lower() for w in blocked):
            continue
        # Skip low comments (unless storymode)
        if t.num_comments <= min_comments and not storymode:
            continue
        # Storymode text length check
        if storymode:
            if not t.selftext:
                continue
            if len(t.selftext) > max_post_len:
                continue
            if len(t.selftext) < 30:
                continue
            if not t.is_self:
                continue
        candidates.append({
            "id": t.id,
            "title": t.title,
            "score": t.score,
            "num_comments": t.num_comments,
            "subreddit": getattr(t, 'subreddit', ''),
            "permalink": t.permalink,
            "author": str(t.author) if t.author else "[deleted]",
            "over_18": t.over_18,
            "is_self": t.is_self,
            "selftext_preview": (t.selftext or "")[:200] + "..." if len(t.selftext or "") > 200 else (t.selftext or ""),
        })

    return jsonify({
        "threads": candidates[:10],
        "total_found": len(threads),
        "total_valid": len(candidates),
        "message": None if candidates else "Threads were found but all were filtered (NSFW, stickied, too few comments, blocked words, or already used). Try changing filters."
    })


@app.route("/generate", methods=["POST"])
def generate():
    global generation
    if generation["running"]:
        return jsonify({"error": "A generation is already in progress."}), 409

    data = request.get_json(force=True) or {}

    # Update bot config in-memory (and persist it so the bot reads it)
    cfg = settings.config

    mode = data.get("mode", "search")
    reddit_url = data.get("reddit_url", "").strip()

    if reddit_url:
        # Extract post ID from Reddit URL
        m = re.search(r"/comments/([a-z0-9]+)", reddit_url, re.I)
        if not m:
            m = re.search(r"redd\.it/([a-z0-9]+)", reddit_url, re.I)
        if not m:
            m = re.search(r"reddit\.com/r/\w+/s/([a-z0-9]+)", reddit_url, re.I)
        if m:
            cfg["reddit"]["thread"]["post_id"] = m.group(1)
            cfg["reddit"]["thread"]["search_query"] = ""
            cfg["reddit"]["thread"]["subreddit"] = ""
        else:
            return jsonify({"error": "Could not extract post ID from Reddit URL."}), 400
    elif mode == "search":
        cfg["reddit"]["thread"]["subreddit"] = ""
        cfg["reddit"]["thread"]["search_query"] = data.get("query", "AskReddit")
        cfg["reddit"]["thread"]["search_sort"] = data.get("sort", "hot")
        cfg["reddit"]["thread"]["search_time"] = data.get("time", "all")
    else:
        cfg["reddit"]["thread"]["search_query"] = ""
        cfg["reddit"]["thread"]["subreddit"] = data.get("subreddit", "AskReddit")

    # If user picked a specific thread from preview, force that post_id
    chosen_id = data.get("chosen_thread_id", "").strip()
    if chosen_id and not reddit_url:
        cfg["reddit"]["thread"]["post_id"] = chosen_id
    elif not reddit_url:
        cfg["reddit"]["thread"]["post_id"] = ""

    cfg["settings"]["background"]["background_video"] = data.get("video", "minecraft")
    cfg["settings"]["background"]["background_audio"] = data.get("audio", "lofi")
    cfg["settings"]["background"]["use_local_only"] = data.get("use_local_only", False)

    # Local background file override
    local_video = data.get("local_video", "").strip()
    if local_video:
        cfg["settings"]["background"]["background_video"] = f"__local__:{local_video}"

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
            # Capture both stdout and stderr so tqdm/moviepy bars don't crash
            with redirect_stdout(buf), redirect_stderr(buf):
                main()
            generation["log"] = buf.getvalue()
            generation["result"] = "Video generated successfully!"

            # Find newest video
            vids = _list_generated_videos()
            if vids:
                generation["video_path"] = vids[0]["path"]
            else:
                generation["error"] = "Bot finished but no video file was created. Check the log for details."
        except SystemExit as exc:
            # The bot may call exit() in several places.
            # Treat ANY SystemExit as an error because the video wasn't produced.
            generation["log"] = buf.getvalue()
            generation["error"] = f"Bot exited early (code {exc.code}). Check the log for details."
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


@app.route("/add_background", methods=["POST"])
def add_background():
    """Add a custom background theme (video or audio) and trigger download."""
    data = request.get_json(force=True) or {}
    bg_type = data.get("type", "video")  # 'video' or 'audio'
    key = data.get("key", "").strip().lower()
    query = data.get("query", "").strip()
    url = data.get("url", "").strip()

    if not key or not query:
        return jsonify({"error": "Missing 'key' or 'query'"}), 400

    # Sanitize key for filename
    safe_key = re.sub(r"[^\w\-]", "", key)
    if not safe_key:
        return jsonify({"error": "Invalid key"}), 400

    if bg_type == "video":
        json_path = BASE_DIR / "utils" / "background_videos.json"
        entry = [url or "", f"{safe_key}.mp4", "Custom", "center", query]
    else:
        json_path = BASE_DIR / "utils" / "background_audios.json"
        entry = [url or "", f"{safe_key}.mp3", "Custom", query]

    with open(json_path, "r+", encoding="utf-8") as f:
        bg_data = json.load(f)
        if safe_key in bg_data:
            return jsonify({"error": f"Theme '{safe_key}' already exists"}), 409
        bg_data[safe_key] = entry
        f.seek(0)
        json.dump(bg_data, f, indent=4)
        f.truncate()

    # Trigger background download in a thread so we don't block
    def _download():
        try:
            from video_creation import background as bg_mod
            if bg_type == "video":
                bg_mod.download_background_video(entry)
            else:
                bg_mod.download_background_audio(entry)
        except Exception as exc:
            print(f"[add_background] download thread error: {exc}")

    threading.Thread(target=_download, daemon=True).start()

    return jsonify({"status": "added", "key": safe_key})


@app.route("/search_background", methods=["POST"])
def search_background():
    """Preview YouTube search results for a query."""
    data = request.get_json(force=True) or {}
    query = data.get("query", "").strip()
    bg_type = data.get("type", "video")
    if not query:
        return jsonify({"error": "Missing query"}), 400

    from utils import background_search as bs
    try:
        urls = bs.search_youtube(query, max_results=5)
        return jsonify({"results": urls})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/backgrounds")
def list_backgrounds():
    """Return available background themes."""
    videos, audios = _available_backgrounds()
    return jsonify({"videos": videos, "audios": audios})


@app.route("/local_backgrounds")
def list_local_backgrounds():
    """Return locally downloaded background video files."""
    video_dir = BASE_DIR / "assets" / "backgrounds" / "video"
    files = []
    if video_dir.exists():
        for p in sorted(video_dir.glob("*.mp4")):
            files.append({
                "name": p.name,
                "size_mb": round(p.stat().st_size / (1024 * 1024), 2),
                "modified": datetime.fromtimestamp(p.stat().st_mtime).isoformat(),
            })
    return jsonify({"files": files})


@app.route("/config", methods=["GET", "POST"])
def config_route():
    if request.method == "GET":
        return jsonify({
            "pexels_api_key": settings.config.get("settings", {}).get("pexels_api_key", ""),
        })
    data = request.get_json(force=True) or {}
    key = data.get("pexels_api_key", "").strip()
    settings.config.setdefault("settings", {})
    settings.config["settings"]["pexels_api_key"] = key
    with open(BASE_DIR / "config.toml", "w") as f:
        toml.dump(settings.config, f)
    return jsonify({"status": "saved"})


@app.route("/clear_done", methods=["POST"])
def clear_done():
    """Clear the done-videos list so previously generated threads can be reused."""
    done_path = BASE_DIR / "video_creation" / "data" / "videos.json"
    try:
        with open(done_path, "w", encoding="utf-8") as f:
            json.dump([], f)
        return jsonify({"status": "cleared"})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


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
