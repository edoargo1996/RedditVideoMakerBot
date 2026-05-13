import yt_dlp
from pathlib import Path
from typing import Optional, List


def search_youtube(query: str, max_results: int = 5, mode: str = "video") -> List[str]:
    """Search YouTube and return a list of video URLs."""
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "default_search": "ytsearch",
        "playlistend": max_results,
    }
    search_query = f"ytsearch{max_results}:{query}"
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(search_query, download=False)
            entries = info.get("entries", [])
            urls = []
            for entry in entries:
                if entry and entry.get("url"):
                    vid = entry["url"]
                    if not vid.startswith("http"):
                        vid = f"https://www.youtube.com/watch?v={vid}"
                    urls.append(vid)
            return urls
    except Exception as exc:
        print(f"[search_youtube] Search failed: {exc}")
        return []


def download_youtube_video(url: str, output_path: Path, retries: int = 3) -> bool:
    """Download a YouTube video to output_path using yt_dlp."""
    ydl_opts = {
        "format": "bestvideo[height<=1080][ext=mp4]/best[ext=mp4]/best",
        "outtmpl": str(output_path),
        "retries": retries,
        "quiet": True,
        "no_warnings": True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        return output_path.is_file() and output_path.stat().st_size > 1024
    except Exception as exc:
        print(f"[download_youtube_video] Failed: {exc}")
        return False


def download_youtube_audio(url: str, output_path: Path, retries: int = 3) -> bool:
    """Download a YouTube audio track to output_path using yt_dlp."""
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": str(output_path),
        "retries": retries,
        "quiet": True,
        "no_warnings": True,
        "extract_audio": True,
        "audio_format": "mp3",
    }
    # If output ends with .mp3, yt_dlp may not rename if extract_audio is False
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        # yt_dlp may write to a different extension first
        candidates = list(output_path.parent.glob(output_path.stem + ".*"))
        for cand in candidates:
            if cand.suffix in (".mp3", ".m4a", ".webm", ".opus") and cand.stat().st_size > 1024:
                if cand.suffix != ".mp3":
                    mp3_path = cand.with_suffix(".mp3")
                    if not mp3_path.exists():
                        import subprocess
                        subprocess.run(
                            ["ffmpeg", "-y", "-i", str(cand), "-q:a", "2", str(mp3_path)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True,
                        )
                        cand.unlink(missing_ok=True)
                    return mp3_path.is_file()
                return True
        return output_path.is_file() and output_path.stat().st_size > 1024
    except Exception as exc:
        print(f"[download_youtube_audio] Failed: {exc}")
        return False


def search_and_download_video(query: str, output_path: Path, max_results: int = 5) -> bool:
    """Search YouTube for query and download the first working result."""
    urls = search_youtube(query, max_results=max_results, mode="video")
    for url in urls:
        if download_youtube_video(url, output_path):
            return True
    return False


def search_and_download_audio(query: str, output_path: Path, max_results: int = 5) -> bool:
    """Search YouTube for query and download the first working audio result."""
    urls = search_youtube(query, max_results=max_results, mode="audio")
    for url in urls:
        if download_youtube_audio(url, output_path):
            return True
    return False


def generate_lofi_music(output_path: Path, duration: int = 600):
    """Generate procedural lofi-style music with ffmpeg.

    Uses layered sine waves + pink noise + reverb/echo
    to create a chill ambient track.
    """
    import subprocess
    freqs = [110, 164.81, 196.00, 220, 261.63, 329.63]
    expr = "+".join([f"{0.5/len(freqs)}*sin({f}*2*PI*t)" for f in freqs])
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"aevalsrc=exprs={expr}:s=44100:d={duration}",
        "-f", "lavfi", "-i", f"anoisesrc=a=0.02:d={duration}",
        "-filter_complex",
        (
            "[0:a][1:a]amix=inputs=2:duration=first[mixed];"
            "[mixed]lowpass=f=600[low];"
            "[low]aecho=0.8:0.9:1000|1500:0.3|0.2[echo];"
            f"[echo]afade=t=in:ss=0:d=5,afade=t=out:st={duration-5}:d=5[fade];"
            "[fade]loudnorm[out]"
        ),
        "-map", "[out]",
        "-t", str(duration),
        "-acodec", "libmp3lame",
        "-q:a", "2",
        str(output_path),
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)


# ---------------------------------------------------------------------------
# Pexels fallback (requires a free API key from pexels.com/api/)
# ---------------------------------------------------------------------------

def search_pexels_video(query: str, api_key: str, per_page: int = 5) -> List[str]:
    """Search Pexels videos and return list of direct video file URLs."""
    import requests
    headers = {"Authorization": api_key}
    params = {"query": query, "orientation": "portrait", "per_page": per_page}
    try:
        r = requests.get("https://api.pexels.com/videos/search", headers=headers, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        urls = []
        for vid in data.get("videos", []):
            files = vid.get("video_files", [])
            best = None
            for f in files:
                if f.get("file_type") == "video/mp4":
                    if best is None or (f.get("width", 0) > best.get("width", 0) and f.get("width", 0) <= 1080):
                        best = f
            if best:
                urls.append(best["link"])
        return urls
    except Exception as exc:
        print(f"[search_pexels_video] Failed: {exc}")
        return []


def download_direct_video(url: str, output_path: Path) -> bool:
    """Download a video from a direct URL."""
    import requests
    try:
        r = requests.get(url, stream=True, timeout=60)
        r.raise_for_status()
        with open(output_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
        return output_path.is_file() and output_path.stat().st_size > 1024
    except Exception as exc:
        print(f"[download_direct_video] Failed: {exc}")
        return False
