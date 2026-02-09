import yt_dlp
import os
import re
import time
import logging
import uuid
import shutil
from typing import Optional, Dict, List
from app.settings.config import settings

logger = logging.getLogger("turboclip.youtube")

# Simple TTL cache for video info (avoids repeated yt-dlp calls for same URL)
_info_cache: Dict[str, dict] = {}
_INFO_CACHE_TTL = 600  # 10 minutes


class YouTubeService:
    def __init__(self):
        self.download_dir = settings.DOWNLOAD_DIR
        os.makedirs(self.download_dir, exist_ok=True)

        # Locate ffmpeg — check config, then PATH
        self.ffmpeg_dir = None
        if settings.FFMPEG_PATH and os.path.isdir(settings.FFMPEG_PATH):
            self.ffmpeg_dir = settings.FFMPEG_PATH
        elif shutil.which('ffmpeg'):
            self.ffmpeg_dir = os.path.dirname(shutil.which('ffmpeg'))

        if not self.ffmpeg_dir:
            logger.warning(
                "FFmpeg not found! Video+audio stream merging will fail. "
                "Set FFMPEG_PATH in .env or install ffmpeg to your system PATH."
            )

    def get_video_info(self, url: str) -> Dict:
        # Check cache first
        cached = _info_cache.get(url)
        if cached and time.time() - cached["_ts"] < _INFO_CACHE_TTL:
            logger.debug("Video info cache hit: %s", url)
            return cached["data"]
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
        }
        if self.ffmpeg_dir:
            ydl_opts['ffmpeg_location'] = self.ffmpeg_dir

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

            formats = []
            for f in info.get('formats', []):
                if f.get('vcodec') != 'none':
                    formats.append({
                        'format_id': f.get('format_id'),
                        'ext': f.get('ext'),
                        'quality': f.get('format_note') or f.get('height', 'unknown'),
                        'filesize': f.get('filesize') or f.get('filesize_approx'),
                        'has_audio': f.get('acodec') != 'none'
                    })

            result = {
                'video_id': info.get('id'),
                'title': info.get('title'),
                'duration': info.get('duration'),
                'thumbnail': info.get('thumbnail'),
                'uploader': info.get('uploader'),
                'upload_date': info.get('upload_date'),
                'description': info.get('description'),
                'view_count': info.get('view_count'),
                'tags': info.get('tags') or [],
                'available_formats': formats
            }

            _info_cache[url] = {"data": result, "_ts": time.time()}

            return result

    def download_video(self, url: str, format: str = "mp4", quality: str = "720p", progress_callback: Optional[callable] = None, download_dir: Optional[str] = None) -> Dict:
        download_id = str(uuid.uuid4())
        target_dir = download_dir or self.download_dir
        os.makedirs(target_dir, exist_ok=True)
        output_template = os.path.join(target_dir, f'{download_id}.%(ext)s')

        quality_map = {
            '360p': 'bestvideo[height<=360]+bestaudio/best[height<=360]',
            '480p': 'bestvideo[height<=480]+bestaudio/best[height<=480]',
            '720p': 'bestvideo[height<=720]+bestaudio/best[height<=720]',
            '1080p': 'bestvideo[height<=1080]+bestaudio/best[height<=1080]',
            'best': 'bestvideo+bestaudio/best',
            'audio': 'bestaudio/best'
        }

        # For MP4: prefer H.264 (avc1) video so the codec is compatible with MP4 container.
        # VP9/AV1 inside MP4 = audio plays but video doesn't show in most players.
        if format == 'mp4':
            quality_map = {
                '360p': 'bestvideo[height<=360][vcodec^=avc1]+bestaudio/bestvideo[height<=360]+bestaudio/best[height<=360]',
                '480p': 'bestvideo[height<=480][vcodec^=avc1]+bestaudio/bestvideo[height<=480]+bestaudio/best[height<=480]',
                '720p': 'bestvideo[height<=720][vcodec^=avc1]+bestaudio/bestvideo[height<=720]+bestaudio/best[height<=720]',
                '1080p': 'bestvideo[height<=1080][vcodec^=avc1]+bestaudio/bestvideo[height<=1080]+bestaudio/best[height<=1080]',
                'best': 'bestvideo[vcodec^=avc1]+bestaudio/bestvideo+bestaudio/best',
                'audio': 'bestaudio/best'
            }

        format_selector = quality_map.get(quality, quality_map['720p'])

        ydl_opts = {
            'format': format_selector,
            'outtmpl': output_template,
            'quiet': True,
            'no_warnings': True,
        }

        # BUG 1 FIX: Tell yt-dlp where ffmpeg is so it can merge video+audio
        if self.ffmpeg_dir:
            ydl_opts['ffmpeg_location'] = self.ffmpeg_dir

        # Set the output container format
        if format in ('mp4', 'mkv', 'webm'):
            ydl_opts['merge_output_format'] = format

        # MP4 container needs compatible codecs:
        # - Video: H.264 (preferred via format selector above)
        # - Audio: AAC (Opus isn't supported in MP4)
        if format == 'mp4':
            ydl_opts['postprocessor_args'] = {
                'merger': ['-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k']
            }

        if progress_callback:
            ydl_opts['progress_hooks'] = [progress_callback]

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

            downloaded_file = self._find_output_file(target_dir, download_id, format)

            if not downloaded_file:
                raise Exception(
                    f"Download completed but output file not found. "
                    f"FFmpeg may not be configured correctly. "
                    f"ffmpeg_dir={self.ffmpeg_dir}"
                )

            # Verify the merged file has both video and audio streams
            streams = self._verify_merged_streams(downloaded_file)
            if not streams['has_video'] or not streams['has_audio']:
                logger.warning(
                    "Merged file missing streams (video=%s, audio=%s). Attempting fallback merge.",
                    streams['has_video'], streams['has_audio']
                )
                fallback = self._merge_streams_fallback(target_dir, download_id, format)
                if fallback:
                    downloaded_file = fallback
                    streams = self._verify_merged_streams(downloaded_file)
                    if not streams['has_video'] or not streams['has_audio']:
                        logger.error("Fallback merge still missing streams: %s", streams)
                else:
                    logger.error("Fallback merge failed — serving file as-is")

            # If MP4, verify the video codec is compatible (not VP9/AV1).
            if format == 'mp4':
                downloaded_file = self._ensure_mp4_h264(downloaded_file)

            # Clean up leftover intermediate stream files
            self._cleanup_intermediate_files(target_dir, download_id, downloaded_file)

            # Rename from UUID to video title
            downloaded_file = self._rename_to_title(downloaded_file, info.get('title'))

            file_size = os.path.getsize(downloaded_file) if os.path.exists(downloaded_file) else None

            return {
                'download_id': download_id,
                'video_id': info.get('id'),
                'title': info.get('title'),
                'duration': info.get('duration'),
                'file_path': downloaded_file,
                'file_size': file_size,
                'format': format,
                'quality': quality
            }

    def download_audio_only(self, url: str, format: str = "mp3", download_dir: Optional[str] = None, progress_callback: Optional[callable] = None) -> Dict:
        download_id = str(uuid.uuid4())
        target_dir = download_dir or self.download_dir
        os.makedirs(target_dir, exist_ok=True)
        output_template = os.path.join(target_dir, f'{download_id}.%(ext)s')

        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': output_template,
            'quiet': True,
            'no_warnings': True,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': format,
                'preferredquality': '192',
            }],
        }

        if self.ffmpeg_dir:
            ydl_opts['ffmpeg_location'] = self.ffmpeg_dir

        if progress_callback:
            ydl_opts['progress_hooks'] = [progress_callback]

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

            audio_file = os.path.join(target_dir, f'{download_id}.{format}')
            if not os.path.exists(audio_file):
                # Fallback: find any file matching the download id
                audio_file = self._find_output_file(target_dir, download_id, format)

            if not audio_file:
                raise Exception(
                    f"Audio extraction failed. FFmpeg is required for audio conversion. "
                    f"ffmpeg_dir={self.ffmpeg_dir}"
                )

            # Rename from UUID to video title
            audio_file = self._rename_to_title(audio_file, info.get('title'))

            file_size = os.path.getsize(audio_file) if os.path.exists(audio_file) else None

            return {
                'download_id': download_id,
                'video_id': info.get('id'),
                'title': info.get('title'),
                'duration': info.get('duration'),
                'file_path': audio_file,
                'file_size': file_size,
                'format': format
            }

    def get_channel_shorts(self, channel_url: str, limit: int = 30, offset: int = 0) -> dict:
        """Extract shorts from a YouTube channel URL with pagination."""
        # Ensure URL points to the /shorts tab
        url = channel_url.rstrip('/')
        if not url.endswith('/shorts'):
            url += '/shorts'

        ydl_opts = {
            'extract_flat': True,
            'quiet': True,
            'no_warnings': True,
            'playliststart': offset + 1,
            'playlistend': offset + limit,
        }
        if self.ffmpeg_dir:
            ydl_opts['ffmpeg_location'] = self.ffmpeg_dir

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            entries = info.get('entries', [])

            shorts = []
            for e in entries:
                if not e:
                    continue
                video_id = e.get('id')
                if not video_id:
                    continue
                shorts.append({
                    'video_id': video_id,
                    'title': e.get('title') or 'Untitled',
                    'url': f'https://www.youtube.com/watch?v={video_id}',
                    'duration': e.get('duration'),
                    'thumbnail': e.get('thumbnails', [{}])[-1].get('url') if e.get('thumbnails') else None,
                })

            has_more = len(shorts) >= limit
            logger.info("Found %d shorts from %s (offset=%d, limit=%d, has_more=%s)",
                        len(shorts), channel_url, offset, limit, has_more)
            return {"videos": shorts, "has_more": has_more}

    def validate_url(self, url: str) -> bool:
        try:
            with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
                info = ydl.extract_info(url, download=False, process=False)
                return info.get('extractor_key', '').lower() in ['youtube', 'youtubetab']
        except:
            return False

    def _verify_merged_streams(self, file_path: str) -> dict:
        """Verify the output file has both video and audio streams using ffprobe."""
        import subprocess

        ffprobe = 'ffprobe'
        if self.ffmpeg_dir:
            ffprobe_path = os.path.join(self.ffmpeg_dir, 'ffprobe')
            if os.path.exists(ffprobe_path) or os.path.exists(ffprobe_path + '.exe'):
                ffprobe = ffprobe_path

        result = {"has_video": False, "has_audio": False, "video_codec": None, "audio_codec": None}
        try:
            proc = subprocess.run(
                [ffprobe, '-v', 'quiet', '-show_streams', '-of', 'json', file_path],
                capture_output=True, text=True, timeout=15
            )
            if proc.returncode != 0:
                logger.warning("ffprobe failed for %s: %s", file_path, proc.stderr)
                return result

            import json
            data = json.loads(proc.stdout)
            for stream in data.get('streams', []):
                if stream.get('codec_type') == 'video':
                    result['has_video'] = True
                    result['video_codec'] = stream.get('codec_name')
                elif stream.get('codec_type') == 'audio':
                    result['has_audio'] = True
                    result['audio_codec'] = stream.get('codec_name')

            logger.info(
                "Stream verify for %s: video=%s(%s) audio=%s(%s)",
                os.path.basename(file_path),
                result['has_video'], result['video_codec'],
                result['has_audio'], result['audio_codec'],
            )
        except Exception as e:
            logger.warning("Stream verification failed: %s", e)

        return result

    def _merge_streams_fallback(self, target_dir: str, download_id: str, format: str) -> Optional[str]:
        """Manually merge separate video+audio files if yt-dlp's auto-merge failed."""
        import subprocess

        ffmpeg_bin = 'ffmpeg'
        if self.ffmpeg_dir:
            candidate = os.path.join(self.ffmpeg_dir, 'ffmpeg')
            if os.path.exists(candidate) or os.path.exists(candidate + '.exe'):
                ffmpeg_bin = candidate

        # Find separate stream files: {download_id}.f{N}.{ext}
        video_file = None
        audio_file = None
        for f in os.listdir(target_dir):
            if not f.startswith(download_id) or f.endswith('.part'):
                continue
            path = os.path.join(target_dir, f)
            parts = f[len(download_id):]  # e.g. ".f137.webm"
            if parts.count('.') <= 1:
                continue  # This is the final merged file, skip it
            # Probe this file to check if it's video or audio
            try:
                proc = subprocess.run(
                    [ffmpeg_bin.replace('ffmpeg', 'ffprobe'), '-v', 'quiet',
                     '-show_entries', 'stream=codec_type', '-of', 'csv=p=0', path],
                    capture_output=True, text=True, timeout=10
                )
                types = proc.stdout.strip().split('\n')
                if 'video' in types and not video_file:
                    video_file = path
                elif 'audio' in types and not audio_file:
                    audio_file = path
            except Exception:
                # Guess by extension
                ext_lower = os.path.splitext(f)[1].lower()
                if ext_lower in ('.m4a', '.ogg', '.opus', '.weba') and not audio_file:
                    audio_file = path
                elif ext_lower in ('.mp4', '.webm', '.mkv') and not video_file:
                    video_file = path

        if not video_file or not audio_file:
            logger.warning("Fallback merge: could not find both streams (video=%s, audio=%s)", video_file, audio_file)
            return None

        merged_path = os.path.join(target_dir, f'{download_id}.{format}')
        logger.info("Fallback merge: %s + %s -> %s", os.path.basename(video_file), os.path.basename(audio_file), os.path.basename(merged_path))

        codec_args = ['-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k'] if format == 'mp4' else ['-c', 'copy']

        try:
            subprocess.run(
                [ffmpeg_bin, '-i', video_file, '-i', audio_file] + codec_args + ['-y', merged_path],
                capture_output=True, timeout=600
            )
            if os.path.exists(merged_path) and os.path.getsize(merged_path) > 0:
                logger.info("Fallback merge succeeded: %s", os.path.basename(merged_path))
                return merged_path
            else:
                logger.error("Fallback merge produced empty file")
                return None
        except Exception as e:
            logger.error("Fallback merge failed: %s", e)
            return None

    def _cleanup_intermediate_files(self, target_dir: str, download_id: str, final_file: str):
        """Remove leftover intermediate stream files (e.g. .f137.webm, .f140.m4a)."""
        final_basename = os.path.basename(final_file)
        for f in os.listdir(target_dir):
            if f.startswith(download_id) and f != final_basename:
                path = os.path.join(target_dir, f)
                try:
                    os.remove(path)
                    logger.info("Cleaned up intermediate file: %s", f)
                except OSError as e:
                    logger.warning("Failed to clean up %s: %s", f, e)

    def _ensure_mp4_h264(self, file_path: str) -> str:
        """Check if an MP4 file has H.264 video. If not (VP9/AV1), re-encode to H.264."""
        import subprocess

        ffprobe = 'ffprobe'
        if self.ffmpeg_dir:
            ffprobe_path = os.path.join(self.ffmpeg_dir, 'ffprobe')
            if os.path.exists(ffprobe_path) or os.path.exists(ffprobe_path + '.exe'):
                ffprobe = ffprobe_path

        try:
            result = subprocess.run(
                [ffprobe, '-v', 'quiet', '-select_streams', 'v:0',
                 '-show_entries', 'stream=codec_name', '-of', 'csv=p=0', file_path],
                capture_output=True, text=True, timeout=10
            )
            codec = result.stdout.strip()
            logger.info("MP4 video codec: %s for %s", codec, os.path.basename(file_path))

            if codec in ('h264', 'avc1', ''):
                return file_path  # Already H.264 or unknown — leave it
        except Exception as e:
            logger.warning("ffprobe check failed: %s", e)
            return file_path  # Can't check — leave it

        # Re-encode VP9/AV1 to H.264
        logger.info("Re-encoding %s from %s to H.264", os.path.basename(file_path), codec)
        fixed_path = file_path.replace('.mp4', '_fixed.mp4')

        ffmpeg_bin = 'ffmpeg'
        if self.ffmpeg_dir:
            ffmpeg_candidate = os.path.join(self.ffmpeg_dir, 'ffmpeg')
            if os.path.exists(ffmpeg_candidate) or os.path.exists(ffmpeg_candidate + '.exe'):
                ffmpeg_bin = ffmpeg_candidate

        try:
            subprocess.run(
                [ffmpeg_bin, '-i', file_path, '-c:v', 'libx264', '-preset', 'fast',
                 '-crf', '23', '-c:a', 'copy', '-y', fixed_path],
                capture_output=True, timeout=600
            )
            if os.path.exists(fixed_path) and os.path.getsize(fixed_path) > 0:
                os.remove(file_path)
                os.rename(fixed_path, file_path)
                logger.info("Re-encode complete: %s", os.path.basename(file_path))
            else:
                logger.warning("Re-encode produced empty file, keeping original")
                if os.path.exists(fixed_path):
                    os.remove(fixed_path)
        except Exception as e:
            logger.error("Re-encode failed: %s", e)
            if os.path.exists(fixed_path):
                os.remove(fixed_path)

        return file_path

    def _sanitize_filename(self, name: str) -> str:
        """Sanitize a string for use as a filename."""
        name = re.sub(r'[<>:"/\\|?*]', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        if len(name) > 200:
            name = name[:200].strip()
        return name or 'untitled'

    def _rename_to_title(self, file_path: str, title: str) -> str:
        """Rename a downloaded file from UUID to the video title. Returns new path."""
        if not title or not os.path.exists(file_path):
            return file_path

        target_dir = os.path.dirname(file_path)
        ext = os.path.splitext(file_path)[1]
        safe_title = self._sanitize_filename(title)
        new_path = os.path.join(target_dir, f"{safe_title}{ext}")

        # Handle duplicates
        if os.path.exists(new_path) and os.path.abspath(new_path) != os.path.abspath(file_path):
            counter = 1
            while os.path.exists(new_path):
                new_path = os.path.join(target_dir, f"{safe_title} ({counter}){ext}")
                counter += 1

        try:
            os.rename(file_path, new_path)
            logger.info("Renamed: %s -> %s", os.path.basename(file_path), os.path.basename(new_path))
            return new_path
        except Exception as e:
            logger.warning("Failed to rename file: %s", e)
            return file_path

    def _find_output_file(self, target_dir: str, download_id: str, expected_ext: str) -> Optional[str]:
        """Find the actual output file, preferring the expected extension."""
        # First: look for the exact expected file
        expected_path = os.path.join(target_dir, f'{download_id}.{expected_ext}')
        if os.path.exists(expected_path):
            return expected_path

        # Second: look for any file matching the download_id (skip .part and intermediate files)
        candidates = []
        for f in os.listdir(target_dir):
            if f.startswith(download_id) and not f.endswith('.part'):
                # Skip intermediate stream files like {id}.f137.webm, {id}.f140.m4a
                parts = f[len(download_id):]  # e.g. ".mp4" or ".f137.webm"
                if parts.count('.') <= 1:  # final file has just one dot: ".mp4"
                    candidates.append(os.path.join(target_dir, f))

        # If no clean candidates, accept any matching file
        if not candidates:
            for f in os.listdir(target_dir):
                if f.startswith(download_id) and not f.endswith('.part'):
                    candidates.append(os.path.join(target_dir, f))

        # Return the largest file (the merged output is always the biggest)
        if candidates:
            return max(candidates, key=os.path.getsize)

        return None
