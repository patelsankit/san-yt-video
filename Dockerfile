FROM python:3.11-slim

# ffmpeg is required by yt-dlp to merge video+audio into MP4 and to extract MP3 audio.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# --workers 1 --threads 8: the app tracks download progress in an in-memory
# dict shared across requests via background threads. Multiple worker
# *processes* would each get their own memory, breaking progress polling -
# one process with several threads keeps state shared while still handling
# concurrent requests.
CMD gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 8 --timeout 120
