"""
Universal downloader service.
Detects platform from URL and routes to appropriate service.
"""

import asyncio
import logging
import os
import re
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

import yt_dlp

from config.settings import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


# ─── Data Classes ──────────────────────────────────────────────────────────────

@dataclass
class MediaInfo:
    """Information about a media item before download."""
    title: str
    platform: str
    url: str
    thumbnail: Optional[str] = None
    duration: Optional[int] = None
    uploader: Optional[str] = None
    view_count: Optional[int] = None
    available_qualities: List[str] = field(default_factory=list)
    is_audio_only: bool = False
    file_size_approx: Optional[int] = None


@dataclass
class DownloadResult:
    """Result of a download operation."""
    success: bool
    file_path: Optional[str] = None
    title: Optional[str] = None
    platform: Optional[str] = None
    format: Optional[str] = None
    file_size: Optional[int] = None
    duration: Optional[int] = None
    error: Optional[str] = None


# ─── Platform Detection ────────────────────────────────────────────────────────

PLATFORM_PATTERNS = {
    "youtube": [
        r"(?:https?://)?(?:www\.)?youtube\.com/",
        r"(?:https?://)?youtu\.be/",
        r"(?:https?://)?(?:www\.)?youtube\.com/shorts/",
    ],
    "instagram": [
        r"(?:https?://)?(?:www\.)?instagram\.com/",
        r"(?:https?://)?instagr\.am/",
    ],
    "tiktok": [
        r"(?:https?://)?(?:www\.)?tiktok\.com/",
        r"(?:https?://)?vm\.tiktok\.com/",
        r"(?:https?://)?vt\.tiktok\.com/",
    ],
    "facebook": [
        r"(?:https?://)?(?:www\.)?facebook\.com/",
        r"(?:https?://)?fb\.watch/",
        r"(?:https?://)?(?:www\.)?fb\.com/",
    ],
    "twitter": [
        r"(?:https?://)?(?:www\.)?twitter\.com/",
        r"(?:https?://)?(?:www\.)?x\.com/",
        r"(?:https?://)?t\.co/",
    ],
    "pinterest": [
        r"(?:https?://)?(?:www\.)?pinterest\.com/",
        r"(?:https?://)?pin\.it/",
    ],
    "soundcloud": [
        r"(?:https?://)?(?:www\.)?soundcloud\.com/",
    ],
    "vimeo": [
        r"(?:https?://)?(?:www\.)?vimeo\.com/",
    ],
    "reddit": [
        r"(?:https?://)?(?:www\.)?reddit\.com/",
        r"(?:https?://)?redd\.it/",
    ],
    "telegram": [
        r"(?:https?://)?t\.me/",
        r"(?:https?://)?telegram\.me/",
    ],
}


def detect_platform(url: str) -> str:
    """Detect platform from URL."""
    url_lower = url.lower()
    for platform, patterns in PLATFORM_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, url_lower):
                return platform
    return "unknown"


def is_url(text: str) -> bool:
    """Check if text is a URL."""
    url_pattern = re.compile(
        r"^(?:https?://)"
        r"(?:\S+(?::\S*)?@)?"
        r"(?:(?!(?:10|127)(?:\.\d{1,3}){3})"
        r"(?!(?:169\.254|192\.168)(?:\.\d{1,3}){2})"
        r"(?!172\.(?:1[6-9]|2\d|3[0-1])(?:\.\d{1,3}){2})"
        r"(?:[1-9]\d?|1\d\d|2[01]\d|22[0-3])"
        r"(?:\.(?:1?\d{1,2}|2[0-4]\d|25[0-5])){2}"
        r"(?:\.(?:[1-9]\d?|1\d\d|2[0-4]\d|25[0-4]))"
        r"|(?:(?:[a-z\u00a1-\uffff0-9]-*)*[a-z\u00a1-\uffff0-9]+)"
        r"(?:\.(?:[a-z\u00a1-\uffff0-9]-*)*[a-z\u00a1-\uffff0-9]+)*"
        r"(?:\.(?:[a-z\u00a1-\uffff]{2,})))"
        r"(?::\d{2,5})?"
        r"(?:/\S*)?$",
        re.IGNORECASE,
    )
    return bool(url_pattern.match(text.strip()))


# ─── Quality Mapping ───────────────────────────────────────────────────────────

QUALITY_MAP = {
    "360p": "bestvideo[height<=360]+bestaudio/best[height<=360]",
    "480p": "bestvideo[height<=480]+bestaudio/best[height<=480]",
    "720p": "bestvideo[height<=720]+bestaudio/best[height<=720]",
    "1080p": "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
    "best": "bestvideo+bestaudio/best",
    "audio": "bestaudio/best",
}


# ─── Main Downloader Service ───────────────────────────────────────────────────

class DownloaderService:
    """Universal media downloader using yt-dlp."""

    def __init__(self):
        self.download_dir = Path(settings.DOWNLOAD_DIR)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self._semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_DOWNLOADS)

    def _get_ydl_opts(
        self,
        output_path: str,
        quality: str = "720p",
        audio_only: bool = False,
        progress_hook: Optional[Callable] = None,
    ) -> dict:
        """Build yt-dlp options."""
        format_str = QUALITY_MAP.get(quality, QUALITY_MAP["720p"])
        if audio_only:
            format_str = QUALITY_MAP["audio"]

        opts = {
            "outtmpl": output_path,
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
            "writesubtitles": False,
            "writethumbnail": False,
            "socket_timeout": 30,
            "retries": 3,
            "fragment_retries": 3,
            "file_access_retries": 3,
            "extractor_retries": 3,
            "format": format_str,
        }

        # Audio extraction options
        if audio_only:
            opts["postprocessors"] = [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ]

        # Merge video+audio with ffmpeg
        if not audio_only:
            opts["merge_output_format"] = "mp4"
            opts["postprocessors"] = [
                {"key": "FFmpegVideoConvertor", "preferedformat": "mp4"}
            ]

        # Proxy settings
        if settings.YTDLP_PROXY:
            opts["proxy"] = settings.YTDLP_PROXY

        # Cookies
        if settings.YTDLP_COOKIES_FILE and os.path.exists(settings.YTDLP_COOKIES_FILE):
            opts["cookiefile"] = settings.YTDLP_COOKIES_FILE

        # Progress hook
        if progress_hook:
            opts["progress_hooks"] = [progress_hook]

        return opts

    async def get_media_info(self, url: str) -> Optional[MediaInfo]:
        """Extract media information without downloading."""
        platform = detect_platform(url)

        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
            "skip_download": True,
            "socket_timeout": 30,
        }

        if settings.YTDLP_PROXY:
            ydl_opts["proxy"] = settings.YTDLP_PROXY
        if settings.YTDLP_COOKIES_FILE:
            ydl_opts["cookiefile"] = settings.YTDLP_COOKIES_FILE

        try:
            loop = asyncio.get_event_loop()
            info = await loop.run_in_executor(
                None, self._extract_info, url, ydl_opts
            )

            if not info:
                return None

            # Extract available qualities
            formats = info.get("formats", [])
            heights = set()
            for f in formats:
                h = f.get("height")
                if h and h in (360, 480, 720, 1080):
                    heights.add(h)

            qualities = [f"{h}p" for h in sorted(heights)]
            if not qualities:
                qualities = ["best"]

            return MediaInfo(
                title=info.get("title", "Unknown"),
                platform=platform,
                url=url,
                thumbnail=info.get("thumbnail"),
                duration=info.get("duration"),
                uploader=info.get("uploader") or info.get("channel"),
                view_count=info.get("view_count"),
                available_qualities=qualities,
                is_audio_only=info.get("acodec") == "none",
                file_size_approx=info.get("filesize_approx"),
            )

        except Exception as e:
            logger.error(f"Error extracting info for {url}: {e}")
            return None

    def _extract_info(self, url: str, opts: dict) -> Optional[dict]:
        """Synchronous info extraction (run in executor)."""
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(url, download=False)
        except Exception as e:
            logger.error(f"yt-dlp extraction error: {e}")
            return None

    async def download(
        self,
        url: str,
        quality: str = "720p",
        audio_only: bool = False,
        progress_hook: Optional[Callable] = None,
    ) -> DownloadResult:
        """Download media from URL."""
        platform = detect_platform(url)
        file_id = str(uuid.uuid4())[:8]
        ext = "mp3" if audio_only else "mp4"
        output_template = str(self.download_dir / f"{file_id}.%(ext)s")

        async with self._semaphore:
            try:
                ydl_opts = self._get_ydl_opts(
                    output_template, quality, audio_only, progress_hook
                )

                loop = asyncio.get_event_loop()
                info = await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        self._download_sync,
                        url,
                        ydl_opts,
                    ),
                    timeout=settings.DOWNLOAD_TIMEOUT,
                )

                if not info:
                    return DownloadResult(
                        success=False, error="Failed to download media"
                    )

                # Find the downloaded file
                file_path = self._find_downloaded_file(file_id, ext)

                if not file_path or not os.path.exists(file_path):
                    return DownloadResult(
                        success=False, error="Downloaded file not found"
                    )

                file_size = os.path.getsize(file_path)

                # Check size limit
                max_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
                if file_size > max_bytes:
                    os.remove(file_path)
                    return DownloadResult(
                        success=False,
                        error=f"File too large ({file_size // (1024*1024)}MB > {settings.MAX_FILE_SIZE_MB}MB)",
                    )

                return DownloadResult(
                    success=True,
                    file_path=file_path,
                    title=info.get("title", "Unknown"),
                    platform=platform,
                    format="mp3" if audio_only else "mp4",
                    file_size=file_size,
                    duration=info.get("duration"),
                )

            except asyncio.TimeoutError:
                return DownloadResult(
                    success=False, error="Download timeout exceeded"
                )
            except Exception as e:
                logger.error(f"Download error for {url}: {e}", exc_info=True)
                return DownloadResult(success=False, error=str(e))

    def _download_sync(self, url: str, opts: dict) -> Optional[dict]:
        """Synchronous download (run in executor)."""
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(url, download=True)
        except Exception as e:
            logger.error(f"Download sync error: {e}")
            return None

    def _find_downloaded_file(self, file_id: str, preferred_ext: str) -> Optional[str]:
        """Find the downloaded file in the download directory."""
        # Try preferred extension first
        preferred = self.download_dir / f"{file_id}.{preferred_ext}"
        if preferred.exists():
            return str(preferred)

        # Search for any file with the file_id
        for f in self.download_dir.glob(f"{file_id}.*"):
            return str(f)

        return None

    @staticmethod
    def cleanup_file(file_path: str) -> None:
        """Remove a temporary file."""
        try:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
                logger.debug(f"Cleaned up: {file_path}")
        except Exception as e:
            logger.warning(f"Failed to clean up {file_path}: {e}")


# Singleton instance
_downloader: Optional[DownloaderService] = None


def get_downloader() -> DownloaderService:
    """Get or create downloader service singleton."""
    global _downloader
    if _downloader is None:
        _downloader = DownloaderService()
    return _downloader