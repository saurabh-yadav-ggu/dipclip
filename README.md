# YouTube Downloader — Full Stack App

## Stack
- **Backend**: Python · FastAPI · yt-dlp · FFmpeg
- **Frontend**: React · Vite (or plain HTML)

---

## 1. Backend Setup

### Prerequisites
- Python 3.10+
- FFmpeg installed on the system (`sudo apt install ffmpeg` on Ubuntu / `brew install ffmpeg` on Mac)

### Install & Run

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

API docs will be available at: http://localhost:8000/docs

---

## 2. Frontend Setup

Open `frontend/index.html` in a browser **or** serve it:

```bash
cd frontend
npx serve .
# Visit http://localhost:3000
```

> Make sure to update `API_BASE` in `frontend/index.html` if your backend runs on a different host/port.

---

## API Endpoints

### `POST /api/info`
Fetch video metadata and available formats.

**Body:**
```json
{ "url": "https://www.youtube.com/watch?v=..." }
```

**Response:**
```json
{
  "title": "Video Title",
  "thumbnail": "https://...",
  "duration": "3:45",
  "uploader": "Channel Name",
  "formats": [
    { "format_id": "137", "resolution": "1080p", "ext": "mp4", "type": "video", ... },
    { "format_id": "bestaudio", "resolution": "Audio Only", "ext": "mp3", ... }
  ]
}
```

### `POST /api/download`
Download and stream the selected format.

**Body:**
```json
{
  "url": "https://www.youtube.com/watch?v=...",
  "format_id": "137",
  "ext": "mp4",
  "resolution": "1080p",
  "title": "Video Title"
}
```

Returns the file as an attachment download.

---

## Notes
- FFmpeg is **required** for merging video+audio streams and MP3 conversion.
- Temp files are auto-deleted after each download response.
- For production, restrict `allow_origins` in the CORS config.
