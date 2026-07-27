# YouTube Downloader

A minimal web app to fetch a YouTube video's info and download it as MP3 or MP4
(360p/480p/720p/1080p, whichever the source video actually has).

All the real "downloading" work is done by [yt-dlp](https://github.com/yt-dlp/yt-dlp)
(open-source, free, actively maintained). This project is just a thin Flask
wrapper around it plus a plain HTML/CSS/JS frontend.

## Folder structure

```
ytvideodownload/
├── app.py                 # Flask app: 2 routes (/api/info, /api/download) + serves the page
├── requirements.txt
├── templates/
│   └── index.html
├── static/
│   ├── style.css
│   └── script.js
├── downloads/              # temp files land here during a download, then get deleted
└── README.md
```

## Prerequisites

- Python 3.9+
- **ffmpeg** installed and on your PATH (needed to merge video+audio into MP4 and to
  extract MP3 audio). Check with `ffmpeg -version`.
  - Ubuntu/Debian: `sudo apt install ffmpeg`
  - macOS: `brew install ffmpeg`
  - Windows: `winget install ffmpeg` (or download from ffmpeg.org and add to PATH)

## Installation

```bash
cd ytvideodownload

# create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# install dependencies (Flask + yt-dlp)
pip install -r requirements.txt
```

## Running locally

```bash
python3 app.py
```

Then open **http://127.0.0.1:5000** in your browser.

1. Paste a YouTube URL.
2. Click **Fetch** → see thumbnail, title, duration, and the formats available for that video.
3. Click **MP3**, **360p**, **480p**, **720p**, or **1080p** → the file downloads immediately
   (only qualities the source video actually has are shown).

## How it works

- `GET /api/info?url=...` — runs `yt_dlp.YoutubeDL().extract_info(url, download=False)`
  to read metadata only (no download), and inspects the `formats` list to figure out
  the max resolution available so the UI only offers real options.
- `GET /api/download?url=...&quality=...` — runs yt-dlp for real:
  - `quality=mp3` → downloads best audio, converts to MP3 via ffmpeg (`FFmpegExtractAudio`).
  - `quality=360|480|720|1080` → downloads best video at that height + best audio,
    merges them into one MP4 via ffmpeg (`merge_output_format: mp4`).
  - The resulting file is streamed back to the browser as an attachment, then deleted
    from `downloads/` right after.

## Why yt-dlp instead of an API?

| Option | Notes |
|---|---|
| **yt-dlp** (used here) | Free, open-source, self-hosted, no API keys or quotas. Actively patched within days whenever YouTube changes something. Gives direct access to every format/quality + metadata. |
| Cobalt.tools API | The old public instance is gone — current cobalt requires self-hosting your own instance or obtaining a key from someone else's instance, so it's no longer a true zero-setup free API. |
| RapidAPI free "YouTube downloader" APIs | Free tiers are heavily rate-limited (often 50–500 requests/month), many just wrap yt-dlp internally anyway, and they get taken down often. Adds signup + API key friction for no real benefit over using yt-dlp directly. |

## Limitations

- **Single-video only** — playlists are intentionally not supported (`noplaylist: True`).
- **Synchronous downloads** — the Flask dev server processes one download at a time per
  worker and blocks on it (simplest possible code); fine for personal/local use, not built
  for concurrent multi-user traffic. For that you'd want a task queue (e.g. Celery) — out
  of scope for "as simple as possible."
- **YouTube can rate-limit or throttle** requests from your IP if you download a lot in a
  short time; yt-dlp will surface an error message in that case.
- **Legal note**: only download videos you have the right to download (your own content,
  Creative Commons videos, or with the owner's permission). Downloading copyrighted content
  without permission may violate YouTube's Terms of Service in your jurisdiction.
- **Not production-hardened**: no auth, no upload limits, uses Flask's built-in dev server
  (`debug=True`). Fine for local/personal use; put behind a real WSGI server (gunicorn) and
  disable debug mode before exposing it publicly.
