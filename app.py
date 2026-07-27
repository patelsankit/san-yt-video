"""
Minimal YouTube Downloader backend.
All the actual "downloading" work is done by yt-dlp (https://github.com/yt-dlp/yt-dlp).

Downloads run in a background thread so the frontend can poll for progress
(0-100%) instead of just waiting on one long request:

  GET  /api/info                    -> title, thumbnail, duration, available qualities
  GET  /api/start-download          -> kicks off a background download, returns a job_id
  GET  /api/progress/<job_id>       -> {"status": ..., "percent": 0-100}
  GET  /api/file/<job_id>           -> streams the finished file back to the browser
"""

import os
import threading
import uuid

from flask import Flask, after_this_request, jsonify, render_template, request, send_file
import yt_dlp

app = Flask(__name__)

DOWNLOAD_DIR = os.path.join(os.path.dirname(__file__), "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Qualities we offer to the user, provided the source video actually has them.
CANDIDATE_HEIGHTS = [144, 240, 360, 480, 720, 1080, 1440, 2160]

# Cloud hosts (Render, Railway, etc.) use datacenter IPs that YouTube flags far
# more aggressively than home IPs, sometimes responding with "Sign in to
# confirm you're not a bot". The documented fix is to supply cookies from a
# logged-in YouTube session. Set the COOKIES_FILE env var to a path containing
# a Netscape-format cookies.txt (e.g. a Render "Secret File") to enable this -
# never commit that file to git. (Forcing alternate player clients like
# android/tv was tried and rejected here - it currently drops format
# availability from 27 formats/1080p down to 5 formats/360p due to unrelated
# YouTube-side experiments, without confirmed benefit against the bot check.)
YTDLP_BASE_OPTS = {}
COOKIES_FILE = os.environ.get("COOKIES_FILE")
if COOKIES_FILE and os.path.isfile(COOKIES_FILE):
    YTDLP_BASE_OPTS["cookiefile"] = COOKIES_FILE

# In-memory job tracker: job_id -> {"status": "downloading"|"processing"|"finished"|"error", "percent": int, ...}
# A plain dict is enough for a single-user local app; a lock just protects concurrent requests.
jobs = {}
jobs_lock = threading.Lock()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/info")
def info():
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"error": "Please provide a YouTube URL."}), 400

    ydl_opts = {**YTDLP_BASE_OPTS, "quiet": True, "skip_download": True, "noplaylist": True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            data = ydl.extract_info(url, download=False)
    except Exception as exc:
        return jsonify({"error": f"Could not read that video: {exc}"}), 400

    available_heights = {
        f.get("height")
        for f in data.get("formats", [])
        if f.get("vcodec") != "none" and f.get("height")
    }
    max_height = max(available_heights) if available_heights else 0
    qualities = [h for h in CANDIDATE_HEIGHTS if max_height >= h]

    return jsonify(
        {
            "title": data.get("title"),
            "thumbnail": data.get("thumbnail"),
            "duration": data.get("duration"),  # seconds
            "qualities": qualities,
        }
    )


def _make_progress_hook(job_id, phase_ranges):
    """
    yt-dlp downloads video and audio as two separate streams when merging, and
    each one reports its own independent 0-100% - taken raw, the bar would jump
    back down when the second stream starts. `phase_ranges` maps each download
    phase to a (start, end) percent slice (e.g. video = 0-90%, audio = 90-99%)
    so the bar only ever moves forward.
    """
    phase = {"index": 0}

    def hook(d):
        index = min(phase["index"], len(phase_ranges) - 1)
        lo, hi = phase_ranges[index]

        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            downloaded = d.get("downloaded_bytes", 0)
            fraction = downloaded / total if total else 0
            percent = int(lo + fraction * (hi - lo))
            with jobs_lock:
                jobs[job_id].update(status="downloading", percent=min(percent, 99))
        elif d.get("status") == "finished":
            # This stream finished; move on to the next phase's range (if any).
            phase["index"] += 1
            with jobs_lock:
                jobs[job_id].update(status="processing", percent=min(hi, 99))

    return hook


def _run_download(job_id, url, quality):
    outtmpl = os.path.join(DOWNLOAD_DIR, f"{job_id}.%(ext)s")

    if quality == "mp3":
        # Single audio-only download - it can use the full 0-99% range on its own.
        hook = _make_progress_hook(job_id, phase_ranges=[(0, 99)])
        ydl_opts = {
            **YTDLP_BASE_OPTS,
            "format": "bestaudio/best",
            "outtmpl": outtmpl,
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ],
            "quiet": True,
            "noplaylist": True,
            "progress_hooks": [hook],
        }
    else:
        # Video (large, downloaded first) gets 0-90%, audio (small) gets 90-99%,
        # then the ffmpeg merge takes it to 100% once _run_download finishes.
        hook = _make_progress_hook(job_id, phase_ranges=[(0, 90), (90, 99)])
        ydl_opts = {
            **YTDLP_BASE_OPTS,
            "format": f"bestvideo[height<={quality}][ext=mp4]+bestaudio[ext=m4a]/best[height<={quality}]",
            "outtmpl": outtmpl,
            "merge_output_format": "mp4",
            "quiet": True,
            "noplaylist": True,
            "progress_hooks": [hook],
        }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(url, download=True)
            title = result.get("title", "video")

        produced_file = next(
            (f for f in os.listdir(DOWNLOAD_DIR) if f.startswith(job_id)), None
        )
        if not produced_file:
            raise RuntimeError("Download finished but the file was not found.")

        ext = produced_file.rsplit(".", 1)[-1]
        safe_title = "".join(c for c in title if c.isalnum() or c in " -_").strip() or "video"

        with jobs_lock:
            jobs[job_id].update(
                status="finished",
                percent=100,
                filepath=os.path.join(DOWNLOAD_DIR, produced_file),
                filename=f"{safe_title}.{ext}",
            )
    except Exception as exc:
        with jobs_lock:
            jobs[job_id].update(status="error", error=str(exc))


@app.route("/api/start-download")
def start_download():
    url = request.args.get("url", "").strip()
    quality = request.args.get("quality", "").strip()  # "mp3", "360", "480", "720", "1080"
    if not url or not quality:
        return jsonify({"error": "Missing url or quality parameter."}), 400

    job_id = uuid.uuid4().hex
    with jobs_lock:
        jobs[job_id] = {"status": "downloading", "percent": 0}

    threading.Thread(target=_run_download, args=(job_id, url, quality), daemon=True).start()

    return jsonify({"job_id": job_id})


@app.route("/api/progress/<job_id>")
def progress(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
        if job and job.get("status") == "error":
            jobs.pop(job_id, None)  # one-shot: caller reads the error once, then it's cleared

    if not job:
        return jsonify({"error": "Unknown job id."}), 404

    return jsonify({k: v for k, v in job.items() if k not in ("filepath", "filename")})


@app.route("/api/file/<job_id>")
def get_file(job_id):
    with jobs_lock:
        job = jobs.get(job_id)

    if not job or job.get("status") != "finished":
        return jsonify({"error": "File is not ready yet."}), 400

    filepath = job["filepath"]
    filename = job["filename"]

    # Deleting the file here is safe on Linux/macOS: send_file already opened a
    # file descriptor, and unlinking only removes the directory entry - the data
    # stays readable through that descriptor until the response finishes sending.
    @after_this_request
    def _cleanup(response):
        try:
            os.remove(filepath)
        except OSError:
            pass
        with jobs_lock:
            jobs.pop(job_id, None)
        return response

    return send_file(filepath, as_attachment=True, download_name=filename)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
