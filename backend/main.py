import os
import uuid
import asyncio
import tempfile
import json
import base64
from pathlib import Path
from typing import Optional, Dict, Any

import yt_dlp
import imageio_ffmpeg
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, StreamingResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ── App Setup ─────────────────────────────────────────────────────────────────

app = FastAPI(
    title="YT Downloader API",
    description="Download YouTube videos in multiple resolutions and formats",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DOWNLOAD_DIR = Path(tempfile.gettempdir()) / "yt_downloader"
DOWNLOAD_DIR.mkdir(exist_ok=True)

# ── Job tracking state ────────────────────────────────────────────────────────
DOWNLOAD_JOBS: Dict[str, Dict[str, Any]] = {}

# ── Schemas ───────────────────────────────────────────────────────────────────

class InfoRequest(BaseModel):
    url: str

class DownloadRequest(BaseModel):
    url: str
    format_id: str          # yt-dlp format id
    ext: str                # "mp4" | "webm" | "mp3" | "m4a"
    resolution: str         # e.g. "1080p" or "Audio Only"
    title: str
    needs_merge: Optional[bool] = False
    type: Optional[str] = "video"

# ── Helpers ───────────────────────────────────────────────────────────────────

def get_cookies_file() -> Optional[str]:
    """Get cookies from environment variable only (Vercel compatible)"""
    # Try environment variable (base64 encoded)
    cookies_b64 = os.environ.get("YOUTUBE_COOKIES_B64")
    if cookies_b64:
        try:
            # Remove any whitespace or newlines that might have been added
            cookies_b64 = cookies_b64.strip().replace('\n', '').replace('\r', '')
            cookies_content = base64.b64decode(cookies_b64).decode('utf-8')
            # Write to /tmp directory which is writable on Vercel
            temp_cookie_file = Path("/tmp") / "cookies.txt"
            temp_cookie_file.write_text(cookies_content)
            return str(temp_cookie_file)
        except Exception as e:
            print(f"Error decoding cookies: {e}")
            pass
    
    return None

RESOLUTION_ORDER = {
    "2160p": 0, "1440p": 1, "1080p": 2, "720p": 3,
    "480p": 4, "360p": 5, "240p": 6, "144p": 7, "Audio Only": 99,
}

def format_duration(seconds: Optional[int]) -> str:
    if not seconds:
        return "Unknown"
    h, remainder = divmod(seconds, 3600)
    m, s = divmod(remainder, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"

def format_filesize(size: Optional[int]) -> str:
    if not size:
        return "Unknown size"
    size_float = float(size)
    for unit in ["B", "KB", "MB", "GB"]:
        if size_float < 1024:
            return f"{size_float:.1f} {unit}"
        size_float /= 1024
    return f"{size_float:.1f} TB"

def safe_filename(name: str) -> str:
    return "".join(c for c in name if c.isalnum() or c in " ._-").strip()[:80]

def make_progress_hook(job_id: str):
    def progress_hook(d):
        if job_id not in DOWNLOAD_JOBS:
            return
        
        if d['status'] == 'downloading':
            downloaded = d.get('downloaded_bytes', 0)
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            
            if total > 0:
                pct = (downloaded / total) * 100
                DOWNLOAD_JOBS[job_id]["progress"] = round(pct, 1)
            
            speed = d.get('speed')
            if speed:
                DOWNLOAD_JOBS[job_id]["speed"] = format_filesize(speed) + "/s"
            
            eta = d.get('eta')
            if eta is not None:
                DOWNLOAD_JOBS[job_id]["eta"] = format_duration(eta)
                
            DOWNLOAD_JOBS[job_id]["status"] = "downloading"
            
        elif d['status'] == 'finished':
            DOWNLOAD_JOBS[job_id]["status"] = "processing"
            DOWNLOAD_JOBS[job_id]["progress"] = 100.0
            
    return progress_hook

def make_postprocessor_hook(job_id: str):
    def postprocessor_hook(d):
        if job_id not in DOWNLOAD_JOBS:
            return
            
        pp_name = d.get('postprocessor', '')
        status = d.get('status', '')
        
        if status == 'started':
            if 'ffmpeg' in pp_name.lower():
                DOWNLOAD_JOBS[job_id]["status"] = "merging"
            else:
                DOWNLOAD_JOBS[job_id]["status"] = "processing"
        elif status == 'finished':
            DOWNLOAD_JOBS[job_id]["status"] = "processing"
            
    return postprocessor_hook

# ── Background Task ──────────────────────────────────────────────────────────

async def run_download_task(job_id: str, req: DownloadRequest):
    try:
        try:
            ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            ffmpeg_path = None
            
        out_template = str(DOWNLOAD_DIR / job_id)
        
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "progress_hooks": [make_progress_hook(job_id)],
            "postprocessor_hooks": [make_postprocessor_hook(job_id)],
            # Add options to bypass bot detection
            "extractor_args": {
                "youtube": {
                    "player_client": ["android", "ios", "web"],
                    "player_skip": ["configs", "webpage", "js", "age_gate", "login"],
                }
            },
            "user_agent": "Mozilla/5.0 (Linux; Android 10; SM-G973F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
            "nocheckcertificate": True,
            "ignoreerrors": True,
        }
        if ffmpeg_path:
            ydl_opts["ffmpeg_location"] = ffmpeg_path
        
        # Add cookie support
        cookies_file = get_cookies_file()
        if cookies_file:
            ydl_opts["cookiefile"] = cookies_file
            
        is_audio = req.resolution == "Audio Only" or req.type == "audio"
        
        if is_audio:
            if req.ext == "mp3":
                ydl_opts["format"] = "bestaudio/best"
                ydl_opts["postprocessors"] = [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }]
            else:
                ydl_opts["format"] = "bestaudio[ext=m4a]/bestaudio/best"
            ydl_opts["outtmpl"] = out_template + ".%(ext)s"
        else:
            if req.needs_merge:
                if req.ext == "mp4":
                    ydl_opts["format"] = f"{req.format_id}+bestaudio[ext=m4a]/bestaudio/best"
                else:
                    ydl_opts["format"] = f"{req.format_id}+bestaudio/best"
                ydl_opts["merge_output_format"] = req.ext
            else:
                ydl_opts["format"] = req.format_id
                
            ydl_opts["outtmpl"] = out_template + ".%(ext)s"

        loop = asyncio.get_event_loop()
        
        def _download():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([req.url])
                
        DOWNLOAD_JOBS[job_id]["status"] = "downloading"
        await loop.run_in_executor(None, _download)
        
        # Locate the actual output file
        final_path = None
        for candidate in DOWNLOAD_DIR.iterdir():
            if candidate.stem == job_id:
                final_path = candidate
                break
                
        if not final_path or not final_path.exists():
            raise Exception("Output file not found after download")
            
        actual_ext = final_path.suffix.lstrip('.')
        download_name = f"{safe_filename(req.title)}.{actual_ext}"
        
        media_types = {
            "mp4": "video/mp4",
            "webm": "video/webm",
            "m4a": "audio/mp4",
            "mp3": "audio/mpeg",
            "ogg": "audio/ogg",
        }
        media_type = media_types.get(actual_ext, "application/octet-stream")
        
        DOWNLOAD_JOBS[job_id].update({
            "status": "completed",
            "progress": 100.0,
            "file_path": str(final_path),
            "download_name": download_name,
            "media_type": media_type,
        })
        
    except Exception as e:
        DOWNLOAD_JOBS[job_id].update({
            "status": "failed",
            "error": str(e),
        })

# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/")
async def serve_frontend():
    """Serve the frontend HTML file"""
    # Try multiple possible paths for the HTML file
    possible_paths = [
        Path(__file__).parent.parent / "index.html",  # Project root
        Path("/var/task/index.html"),  # Vercel deployment path
        Path(__file__).parent.parent.parent / "index.html",  # One level up
    ]
    
    for html_path in possible_paths:
        if html_path.exists():
            return HTMLResponse(content=html_path.read_text())
    
    # If not found, return error with debug info
    return HTMLResponse(
        content=f"<h1>Frontend not found</h1><p>Checked paths: {[str(p) for p in possible_paths]}</p>",
        status_code=404
    )


@app.post("/api/info")
async def get_video_info(req: InfoRequest):
    """
    Fetch video metadata + all available download formats, grouped by resolution and container.
    """
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        # Add options to bypass bot detection
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "ios", "web"],
                "player_skip": ["configs", "webpage", "js", "age_gate", "login"],
            }
        },
        "user_agent": "Mozilla/5.0 (Linux; Android 10; SM-G973F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
        "nocheckcertificate": True,
        "ignoreerrors": True,
    }
    
    # Add cookie support
    cookies_file = get_cookies_file()
    if cookies_file:
        ydl_opts["cookiefile"] = cookies_file

    try:
        loop = asyncio.get_event_loop()

        def _extract():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(req.url, download=False)

        info = await loop.run_in_executor(None, _extract)
    except yt_dlp.utils.DownloadError as e:
        raise HTTPException(status_code=400, detail=f"Could not fetch video: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Find the best audio sizes first to add to video size estimations
    best_m4a_audio_size = 0
    best_webm_audio_size = 0
    for f in info.get("formats", []):
        vcodec = f.get("vcodec", "none")
        acodec = f.get("acodec", "none")
        ext    = f.get("ext", "")
        if vcodec == "none" and acodec and acodec != "none":
            size = f.get("filesize") or f.get("filesize_approx") or 0
            if ext == "m4a" and size > best_m4a_audio_size:
                best_m4a_audio_size = size
            elif ext == "webm" and size > best_webm_audio_size:
                best_webm_audio_size = size

    video_formats = []
    seen_video = {} # map of (resolution, target_ext) -> index in video_formats

    for f in info.get("formats", []):
        vcodec = f.get("vcodec", "none")
        acodec = f.get("acodec", "none")
        height = f.get("height")
        ext    = f.get("ext", "")
        fps    = f.get("fps")

        if height and vcodec and vcodec != "none":
            res = f"{height}p"
            
            if ext in ["mp4", "m4v"]:
                target_ext = "mp4"
            elif ext in ["webm", "mkv"]:
                target_ext = "webm"
            else:
                continue

            key = (res, target_ext)
            tbr = f.get("tbr") or 0
            has_audio = acodec and acodec != "none"
            size = f.get("filesize") or f.get("filesize_approx") or 0

            # Estimate merged size if it needs merge
            if not has_audio:
                audio_size = best_m4a_audio_size if target_ext == "mp4" else best_webm_audio_size
                estimated_size = size + audio_size if size > 0 else 0
            else:
                estimated_size = size

            fmt_item = {
                "format_id": f["format_id"],
                "resolution": res,
                "ext": target_ext,
                "type": "video",
                "filesize": format_filesize(estimated_size) if estimated_size > 0 else "Unknown size",
                "_filesize_bytes": estimated_size,
                "fps": fps,
                "vcodec": vcodec,
                "acodec": acodec,
                "needs_merge": not has_audio,
                "_tbr": tbr
            }

            if key in seen_video:
                idx = seen_video[key]
                existing_item = video_formats[idx]
                if tbr > existing_item["_tbr"]:
                    video_formats[idx] = fmt_item
            else:
                seen_video[key] = len(video_formats)
                video_formats.append(fmt_item)

    # Clean up private sorting keys
    for vf in video_formats:
        vf.pop("_tbr", None)
        vf.pop("_filesize_bytes", None)

    # Sort video formats by resolution
    video_formats.sort(key=lambda x: RESOLUTION_ORDER.get(x["resolution"], 50))

    # Add standard Audio-only options (mp3, m4a, webm)
    audio_formats = [
        {
            "format_id": "bestaudio",
            "resolution": "Audio Only",
            "ext": "mp3",
            "type": "audio",
            "filesize": format_filesize(best_m4a_audio_size) if best_m4a_audio_size else "Unknown size",
            "fps": None,
            "vcodec": None,
            "acodec": "mp3",
            "needs_merge": False,
        },
        {
            "format_id": "bestaudio",
            "resolution": "Audio Only",
            "ext": "m4a",
            "type": "audio",
            "filesize": format_filesize(best_m4a_audio_size) if best_m4a_audio_size else "Unknown size",
            "fps": None,
            "vcodec": None,
            "acodec": "aac",
            "needs_merge": False,
        },
        {
            "format_id": "bestaudio",
            "resolution": "Audio Only",
            "ext": "webm",
            "type": "audio",
            "filesize": format_filesize(best_webm_audio_size) if best_webm_audio_size else "Unknown size",
            "fps": None,
            "vcodec": None,
            "acodec": "opus",
            "needs_merge": False,
        }
    ]

    return {
        "title":      info.get("title", "Unknown Title"),
        "thumbnail":  info.get("thumbnail"),
        "duration":   format_duration(info.get("duration")),
        "uploader":   info.get("uploader", "Unknown"),
        "view_count": info.get("view_count"),
        "formats":    video_formats + audio_formats,
    }


@app.post("/api/download")
async def download(req: DownloadRequest):
    """
    Download a video/audio synchronously and return the file.
    """
    job_id = str(uuid.uuid4())
    # Initialize job tracking
    DOWNLOAD_JOBS[job_id] = {
        "status": "pending",
        "progress": 0.0,
        "speed": "0 B/s",
        "eta": "00:00",
        "error": None,
        "file_path": None,
        "download_name": None,
        "media_type": None,
    }
    # Run the download task synchronously
    await run_download_task(job_id, req)
    job = DOWNLOAD_JOBS.get(job_id)
    if not job or job["status"] != "completed":
        raise HTTPException(status_code=500, detail="Download failed")
    file_path = Path(job["file_path"])
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found after download")
    # Return the file and clean up after response
    def _cleanup():
        try:
            file_path.unlink(missing_ok=True)
            DOWNLOAD_JOBS.pop(job_id, None)
        except Exception:
            pass
    return FileResponse(
        path=str(file_path),
        filename=job["download_name"],
        media_type=job["media_type"],
        background=BackgroundTasks().add_task(_cleanup)
    )


@app.get("/api/download/progress/{job_id}")
async def get_download_progress(job_id: str):
    """
    SSE endpoint to listen to real-time download/merge progress.
    """
    if job_id not in DOWNLOAD_JOBS:
        raise HTTPException(status_code=404, detail="Job not found")
        
    async def event_generator():
        try:
            while True:
                job = DOWNLOAD_JOBS.get(job_id)
                if not job:
                    break
                
                yield f"data: {json.dumps(job)}\n\n"
                
                if job["status"] in ["completed", "failed"]:
                    break
                    
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            pass
            
    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/download/file/{job_id}")
async def get_download_file(job_id: str, background_tasks: BackgroundTasks):
    """
    Retrieve the finished file and queue it for local deletion.
    """
    job = DOWNLOAD_JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    if job["status"] != "completed" or not job["file_path"]:
        raise HTTPException(status_code=400, detail="Download not completed yet or failed")
        
    file_path = Path(job["file_path"])
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Physical file not found")
        
    download_name = job["download_name"]
    media_type = job["media_type"]
    
    def _cleanup():
        try:
            file_path.unlink(missing_ok=True)
            DOWNLOAD_JOBS.pop(job_id, None)
        except Exception:
            pass
            
    background_tasks.add_task(_cleanup)
    
    return FileResponse(
        path=str(file_path),
        filename=download_name,
        media_type=media_type,
    )
