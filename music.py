"""
Music search service using YouTube Search Python and yt-dlp.
Provides search, download, and caching capabilities.
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import List, Optional

from config.settings import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


@dataclass
class MusicResult:
    """A single music search result."""
    youtube_id: str
    title: str
    artist: Optional[str]
    duration: int       # seconds
    thumbnail: Optional[str]
    url: str
    view_count: Optional[int] = None

    @property
    def duration_str(self) -> str:
        """Format duration as MM:SS."""
        minutes = self.duration // 60
        seconds = self.duration % 60
        return f"{minutes}:{seconds:02d}"


class MusicSearchService:
    """YouTube-based music search and download service."""

    def __init__(self):
        self._cache: dict = {}

    async def search(self, query: str, limit: int = 5) -> List[MusicResult]:
        """Search for music on YouTube."""
        cache_key = f"search:{query.lower()}:{limit}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        try:
            results = await asyncio.get_event_loop().run_in_executor(
                None, self._search_sync, query, limit
            )
            if results:
                self._cache[cache_key] = results
                # Evict old cache entries (simple LRU)
                if len(self._cache) > 200:
                    oldest = next(iter(self._cache))
                    del self._cache[oldest]
            return results
        except Exception as e:
            logger.error(f"Music search error for '{query}': {e}")
            return []

    def _search_sync(self, query: str, limit: int) -> List[MusicResult]:
        """Synchronous YouTube search using yt-dlp."""
        try:
            import yt_dlp

            ydl_opts = {
                "quiet": True,
                "no_warnings": True,
                "extract_flat": True,
                "skip_download": True,
                "socket_timeout": 20,
                "default_search": "ytsearch",
            }

            search_url = f"ytsearch{limit}:{query}"

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(search_url, download=False)

            results = []
            if info and "entries" in info:
                for entry in info["entries"]:
                    if not entry:
                        continue

                    yt_id = entry.get("id", "")
                    if not yt_id:
                        continue

                    duration = entry.get("duration") or 0
                    # Skip very long videos (not music)
                    if duration > 1800:  # 30 minutes
                        continue

                    # Extract artist from title
                    title = entry.get("title", "Unknown")
                    artist = entry.get("uploader") or entry.get("channel")

                    result = MusicResult(
                        youtube_id=yt_id,
                        title=title,
                        artist=artist,
                        duration=int(duration),
                        thumbnail=entry.get("thumbnail"),
                        url=f"https://www.youtube.com/watch?v={yt_id}",
                        view_count=entry.get("view_count"),
                    )
                    results.append(result)

            return results[:limit]

        except Exception as e:
            logger.error(f"Sync search error: {e}")
            return []

    async def download_audio(
        self,
        youtube_id: str,
        output_dir: str,
        progress_hook=None,
    ) -> Optional[str]:
        """Download audio from YouTube video as MP3."""
        try:
            import yt_dlp
            from pathlib import Path

            output_path = str(Path(output_dir) / f"{youtube_id}.%(ext)s")

            ydl_opts = {
                "format": "bestaudio/best",
                "outtmpl": output_path,
                "quiet": True,
                "no_warnings": True,
                "socket_timeout": 30,
                "retries": 3,
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "192",
                    },
                    {
                        "key": "FFmpegMetadata",
                        "add_metadata": True,
                    },
                ],
            }

            if settings.YTDLP_PROXY:
                ydl_opts["proxy"] = settings.YTDLP_PROXY
            if settings.YTDLP_COOKIES_FILE:
                ydl_opts["cookiefile"] = settings.YTDLP_COOKIES_FILE
            if progress_hook:
                ydl_opts["progress_hooks"] = [progress_hook]

            url = f"https://www.youtube.com/watch?v={youtube_id}"

            await asyncio.get_event_loop().run_in_executor(
                None, self._download_sync, url, ydl_opts
            )

            # Find the downloaded file
            mp3_path = Path(output_dir) / f"{youtube_id}.mp3"
            if mp3_path.exists():
                return str(mp3_path)

            # Search for any file with youtube_id
            for f in Path(output_dir).glob(f"{youtube_id}.*"):
                return str(f)

            return None

        except Exception as e:
            logger.error(f"Audio download error for {youtube_id}: {e}")
            return None

    def _download_sync(self, url: str, opts: dict) -> None:
        """Synchronous download wrapper."""
        import yt_dlp
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])

    async def get_video_info(self, youtube_id: str) -> Optional[MusicResult]:
        """Get info for a specific YouTube video."""
        try:
            import yt_dlp

            url = f"https://www.youtube.com/watch?v={youtube_id}"
            opts = {
                "quiet": True,
                "no_warnings": True,
                "skip_download": True,
                "socket_timeout": 20,
            }

            info = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._get_info_sync(url, opts),
            )

            if not info:
                return None

            return MusicResult(
                youtube_id=youtube_id,
                title=info.get("title", "Unknown"),
                artist=info.get("uploader") or info.get("channel"),
                duration=int(info.get("duration", 0)),
                thumbnail=info.get("thumbnail"),
                url=url,
                view_count=info.get("view_count"),
            )

        except Exception as e:
            logger.error(f"Get video info error: {e}")
            return None

    def _get_info_sync(self, url: str, opts: dict) -> Optional[dict]:
        """Synchronous info extraction."""
        import yt_dlp
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(url, download=False)
        except Exception:
            return None


# Singleton
_music_service: Optional[MusicSearchService] = None


def get_music_service() -> MusicSearchService:
    """Get or create music service singleton."""
    global _music_service
    if _music_service is None:
        _music_service = MusicSearchService()
    return _music_service