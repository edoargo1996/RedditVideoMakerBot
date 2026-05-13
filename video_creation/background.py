import json
import random
import re
from pathlib import Path
from random import randrange
from typing import Any, Dict, Tuple

import yt_dlp
from moviepy import AudioFileClip, VideoFileClip
from moviepy.video.io.ffmpeg_tools import ffmpeg_extract_subclip

from utils import settings
from utils.console import print_step, print_substep
from utils import background_search as bg_search


def load_background_options():
    _background_options = {}
    # Load background videos
    with open("./utils/background_videos.json") as json_file:
        _background_options["video"] = json.load(json_file)

    # Load background audios
    with open("./utils/background_audios.json") as json_file:
        _background_options["audio"] = json.load(json_file)

    # Remove "__comment" from backgrounds
    del _background_options["video"]["__comment"]
    del _background_options["audio"]["__comment"]

    for name in list(_background_options["video"].keys()):
        pos = _background_options["video"][name][3]

        if pos != "center":
            _background_options["video"][name][3] = lambda t: ("center", pos + t)

    return _background_options


def get_start_and_end_times(video_length: int, length_of_clip: int) -> Tuple[int, int]:
    """Generates a random interval of time to be used as the background of the video.

    Args:
        video_length (int): Length of the video
        length_of_clip (int): Length of the video to be used as the background

    Returns:
        tuple[int,int]: Start and end time of the randomized interval
    """
    if int(length_of_clip) <= int(video_length):
        print_substep(
            f"Background ({length_of_clip}s) is shorter than video ({video_length}s). Using whole background.",
            style="bold yellow",
        )
        return 0, int(length_of_clip)

    initialValue = 180
    # Issue #1649 - Ensures that will be a valid interval in the video
    while int(length_of_clip) <= int(video_length + initialValue):
        if initialValue == initialValue // 2:
            print_substep(
                f"Background ({length_of_clip}s) is shorter than video ({video_length}s). Using whole background.",
                style="bold yellow",
            )
            return 0, int(length_of_clip)
        else:
            initialValue //= 2  # Divides the initial value by 2 until reach 0
    random_time = randrange(initialValue, int(length_of_clip) - int(video_length))
    return random_time, random_time + video_length


def get_background_config(mode: str):
    """Fetch the background/s configuration"""
    try:
        choice = str(settings.config["settings"]["background"][f"background_{mode}"]).casefold()
    except AttributeError:
        print_substep("No background selected. Picking random background'")
        choice = None

    # Handle default / not supported background using default option.
    # Default : pick random from supported background.
    if not choice or choice not in background_options[mode]:
        choice = random.choice(list(background_options[mode].keys()))

    return background_options[mode][choice]


def download_background_video(background_config):
    """Downloads the background/s video from YouTube or searches automatically."""
    Path("./assets/backgrounds/video/").mkdir(parents=True, exist_ok=True)
    # background_config: [uri, filename, credit, position, search_query?]
    uri = background_config[0]
    filename = background_config[1]
    credit = background_config[2]
    search_query = background_config[4] if len(background_config) > 4 else None
    target = Path(f"assets/backgrounds/video/{credit}-{filename}")
    if target.is_file():
        return

    use_local_only = settings.config.get("settings", {}).get("background", {}).get("use_local_only", False)
    if use_local_only:
        print_substep("use_local_only is enabled. Skipping download, generating fallback...", style="bold yellow")
        _generate_fallback_video(target, credit)
        print_substep("Fallback video generated! 🎉", style="bold green")
        return

    print_step(
        "We need to download the backgrounds videos. they are fairly large but it's only done once. 😎"
    )
    print_substep("Downloading the backgrounds videos... please be patient 🙏 ")

    # 1) Try direct URL if present
    if uri:
        print_substep(f"Downloading {filename} from {uri}")
        ydl_opts = {
            "format": "bestvideo[height<=1080][ext=mp4]/best[ext=mp4]/best",
            "outtmpl": str(target),
            "retries": 10,
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download(uri)
            print_substep("Background video downloaded successfully! 🎉", style="bold green")
            return
        except Exception as exc:
            print_substep(f"Direct YouTube download failed ({exc}).", style="bold yellow")

    # 2) Try automatic YouTube search
    if search_query:
        print_substep(f"Searching YouTube for: {search_query}")
        try:
            if bg_search.search_and_download_video(search_query, target):
                print_substep("Background video downloaded via search! 🎉", style="bold green")
                return
        except Exception as exc:
            print_substep(f"Auto-search failed ({exc}).", style="bold yellow")

    # 3) Try Pexels if API key is configured
    pexels_key = settings.config.get("settings", {}).get("pexels_api_key", "")
    if pexels_key and search_query:
        print_substep(f"Searching Pexels for: {search_query}")
        try:
            urls = bg_search.search_pexels_video(search_query, pexels_key)
            for url in urls:
                if bg_search.download_direct_video(url, target):
                    print_substep("Background video downloaded from Pexels! 🎉", style="bold green")
                    return
        except Exception as exc:
            print_substep(f"Pexels search failed ({exc}).", style="bold yellow")

    # 4) Fallback local generation
    print_substep("Generating local fallback video...", style="bold yellow")
    _generate_fallback_video(target, credit)
    print_substep("Fallback video generated! 🎉", style="bold green")


def _generate_fallback_video(target: Path, label: str):
    """Generate a 10-minute animated fallback video with ffmpeg (Game of Life looped)."""
    from subprocess import run, DEVNULL
    from tempfile import TemporaryDirectory
    label_safe = label.replace("'", "")

    with TemporaryDirectory() as tmpdir:
        short = Path(tmpdir) / "short.mp4"
        # 1) Generate a short 60-second clip (fast, low bitrate)
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", "life=s=1080x1920:r=30:mold=10:ratio=0.3:life_color=0x00e5ff:death_color=0x0f1115",
            "-t", "60",
            "-vf", f"drawtext=text='{label_safe}':fontsize=80:fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2:box=1:boxcolor=black@0.5,format=yuv420p",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "32",
            "-maxrate", "2M",
            "-bufsize", "4M",
            "-pix_fmt", "yuv420p",
            str(short),
        ]
        run(cmd, stdout=DEVNULL, stderr=DEVNULL, check=True)

        # 2) Loop the short clip to 10 minutes instantly with stream_loop + copy
        cmd2 = [
            "ffmpeg", "-y",
            "-stream_loop", "9",
            "-i", str(short),
            "-t", "600",
            "-c", "copy",
            str(target),
        ]
        run(cmd2, stdout=DEVNULL, stderr=DEVNULL, check=True)


def download_background_audio(background_config):
    """Downloads the background/s audio from YouTube or searches automatically."""
    Path("./assets/backgrounds/audio/").mkdir(parents=True, exist_ok=True)
    # background_config: [uri, filename, credit, search_query?]
    uri = background_config[0]
    filename = background_config[1]
    credit = background_config[2]
    search_query = background_config[3] if len(background_config) > 3 else None
    target = Path(f"assets/backgrounds/audio/{credit}-{filename}")
    if target.is_file():
        return

    use_local_only = settings.config.get("settings", {}).get("background", {}).get("use_local_only", False)
    if use_local_only:
        print_substep("use_local_only is enabled. Skipping download, generating fallback audio...", style="bold yellow")
        _generate_fallback_audio(target)
        print_substep("Fallback audio generated! 🎉", style="bold green")
        return

    print_step(
        "We need to download the backgrounds audio. they are fairly large but it's only done once. 😎"
    )
    print_substep("Downloading the backgrounds audio... please be patient 🙏 ")

    # 1) Try direct URL if present
    if uri:
        print_substep(f"Downloading {filename} from {uri}")
        ydl_opts = {
            "outtmpl": str(target),
            "format": "bestaudio/best",
            "extract_audio": True,
            "audio_format": "mp3",
            "retries": 10,
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([uri])
            print_substep("Background audio downloaded successfully! 🎉", style="bold green")
            return
        except Exception as exc:
            print_substep(f"Direct YouTube download failed ({exc}).", style="bold yellow")

    # 2) Try automatic YouTube search
    if search_query:
        print_substep(f"Searching YouTube for: {search_query}")
        try:
            if bg_search.search_and_download_audio(search_query, target):
                print_substep("Background audio downloaded via search! 🎉", style="bold green")
                return
        except Exception as exc:
            print_substep(f"Auto-search failed ({exc}).", style="bold yellow")

    # 3) Fallback procedural lofi generation
    print_substep("Generating procedural lofi music as fallback...", style="bold yellow")
    try:
        bg_search.generate_lofi_music(target, duration=600)
        print_substep("Procedural lofi generated! 🎉", style="bold green")
    except Exception as exc:
        print_substep(f"Procedural generation failed ({exc}). Using silent fallback...", style="bold yellow")
        _generate_fallback_audio(target)
        print_substep("Silent fallback audio generated! 🎉", style="bold green")


def _generate_fallback_audio(target: Path):
    """Generate a 10-minute silent MP3 with ffmpeg."""
    from subprocess import run, DEVNULL
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", "anullsrc=r=44100:cl=stereo",
        "-t", "600",
        "-acodec", "libmp3lame",
        "-q:a", "4",
        str(target),
    ]
    run(cmd, stdout=DEVNULL, stderr=DEVNULL, check=True)


def chop_background(background_config: Dict[str, Tuple], video_length: int, reddit_object: dict):
    """Generates the background audio and footage to be used in the video and writes it to assets/temp/background.mp3 and assets/temp/background.mp4

    Args:
        reddit_object (Dict[str,str]) : Reddit object
        background_config (Dict[str,Tuple]]) : Current background configuration
        video_length (int): Length of the clip where the background footage is to be taken out of
    """
    thread_id = re.sub(r"[^\w\s-]", "", reddit_object["thread_id"])

    if settings.config["settings"]["background"][f"background_audio_volume"] == 0:
        print_step("Volume was set to 0. Skipping background audio creation . . .")
    else:
        print_step("Finding a spot in the backgrounds audio to chop...✂️")
        audio_choice = f"{background_config['audio'][2]}-{background_config['audio'][1]}"
        background_audio = AudioFileClip(f"assets/backgrounds/audio/{audio_choice}")
        start_time_audio, end_time_audio = get_start_and_end_times(
            video_length, background_audio.duration
        )
        background_audio = background_audio.subclipped(start_time_audio, end_time_audio)
        background_audio.write_audiofile(f"assets/temp/{thread_id}/background.mp3")

    print_step("Finding a spot in the backgrounds video to chop...✂️")
    video_choice = f"{background_config['video'][2]}-{background_config['video'][1]}"
    background_video = VideoFileClip(f"assets/backgrounds/video/{video_choice}")
    if background_video.duration < video_length:
        print_substep(
            f"Background ({background_video.duration:.1f}s) is shorter than video ({video_length}s). Looping background...",
            style="bold yellow",
        )
        from moviepy import concatenate_videoclips
        loops_needed = int(video_length / background_video.duration) + 1
        looped = concatenate_videoclips([background_video] * loops_needed)
        new = looped.subclipped(0, video_length)
        new.write_videofile(f"assets/temp/{thread_id}/background.mp4")
    else:
        start_time_video, end_time_video = get_start_and_end_times(
            video_length, background_video.duration
        )
        # Extract video subclip
        try:
            with VideoFileClip(f"assets/backgrounds/video/{video_choice}") as video:
                new = video.subclipped(start_time_video, end_time_video)
                new.write_videofile(f"assets/temp/{thread_id}/background.mp4")

        except (OSError, IOError):  # ffmpeg issue see #348
            print_substep("FFMPEG issue. Trying again...")
            ffmpeg_extract_subclip(
                f"assets/backgrounds/video/{video_choice}",
                start_time_video,
                end_time_video,
                outputfile=f"assets/temp/{thread_id}/background.mp4",
            )
    print_substep("Background video chopped successfully!", style="bold green")
    return background_config["video"][2]


# Create a tuple for downloads background (background_audio_options, background_video_options)
background_options = load_background_options()
