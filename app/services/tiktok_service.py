import yt_dlp
from yt_dlp.extractor.tiktok import TikTokIE
import os
import re
import time
import logging
import uuid
import shutil
import zipfile
import urllib.request
from typing import Optional, Dict, List
from urllib.parse import urlparse
from app.settings.config import settings

logger = logging.getLogger("turboclip.tiktok")

_info_cache: Dict[str, dict] = {}
_INFO_CACHE_TTL = 600


class TikTokService:
    def __init__(self):
        self.download_dir = settings.DOWNLOAD_DIR
        os.makedirs(self.download_dir, exist_ok=True)

        self.ffmpeg_dir = None
        if settings.FFMPEG_PATH and os.path.isdir(settings.FFMPEG_PATH):
            self.ffmpeg_dir = settings.FFMPEG_PATH
        elif shutil.which('ffmpeg'):
            self.ffmpeg_dir = os.path.dirname(shutil.which('ffmpeg'))

    @staticmethod
    def _normalize_tiktok_url(url: str) -> str:
        """Rewrite /photo/ URLs to /video/ so yt-dlp can process them."""
        return re.sub(r'/photo/', '/video/', url)

    def get_video_info(self, url: str) -> Dict:
        cached = _info_cache.get(url)
        if cached and time.time() - cached["_ts"] < _INFO_CACHE_TTL:
            return cached["data"]

        norm_url = self._normalize_tiktok_url(url)

        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
        }
        if self.ffmpeg_dir:
            ydl_opts['ffmpeg_location'] = self.ffmpeg_dir

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(norm_url, download=False)

            # Detect slideshow: yt-dlp returns vcodec=none (audio only) for photo posts
            is_slideshow = False
            image_urls = []
            raw_data = None
            has_video = info.get('vcodec') not in (None, 'none')
            if not has_video:
                # No video stream — likely a slideshow; use TikTokIE for raw image data
                try:
                    ie = TikTokIE(ydl)
                    video_id = info.get('id') or norm_url.rstrip('/').split('/')[-1]
                    raw_data, _ = ie._extract_web_data_and_status(norm_url, video_id)
                    if raw_data and 'imagePost' in raw_data:
                        images = raw_data['imagePost'].get('images', [])
                        image_urls = [
                            img['imageURL']['urlList'][0]
                            for img in images
                            if img.get('imageURL', {}).get('urlList')
                        ]
                        is_slideshow = len(image_urls) > 0
                except Exception as e:
                    logger.warning("Failed to extract raw TikTok data for slideshow detection: %s", e)

            # For slideshows, extract tags from raw data (yt-dlp doesn't include them)
            tags = info.get('tags') or []
            if is_slideshow and not tags and raw_data:
                challenges = raw_data.get('challenges') or []
                tags = [c['title'] for c in challenges if c.get('title')]

            title_fallback = 'TikTok Slideshow' if is_slideshow else 'TikTok Video'
            result = {
                'video_id': info.get('id'),
                'title': info.get('title') or (info.get('description') or '')[:80] or title_fallback,
                'duration': info.get('duration'),
                'thumbnail': info.get('thumbnail'),
                'uploader': info.get('uploader') or info.get('creator'),
                'upload_date': info.get('upload_date'),
                'description': info.get('description'),
                'view_count': info.get('view_count'),
                'like_count': info.get('like_count'),
                'tags': tags,
                'is_slideshow': is_slideshow,
                'image_count': len(image_urls) if is_slideshow else 0,
                'image_urls': image_urls if is_slideshow else [],
            }

            _info_cache[url] = {"data": result, "_ts": time.time()}
            return result

    def download_video(
        self,
        url: str,
        quality: str = "best",
        progress_callback: Optional[callable] = None,
        download_dir: Optional[str] = None,
    ) -> Dict:
        url = self._normalize_tiktok_url(url)
        download_id = str(uuid.uuid4())
        target_dir = download_dir or self.download_dir
        os.makedirs(target_dir, exist_ok=True)
        output_template = os.path.join(target_dir, f'{download_id}.%(ext)s')

        ydl_opts = {
            'format': 'bestvideo[vcodec^=avc]+bestaudio/bestvideo*+bestaudio/best',
            'merge_output_format': 'mp4',
            'outtmpl': output_template,
            'quiet': True,
            'no_warnings': True,
        }

        if self.ffmpeg_dir:
            ydl_opts['ffmpeg_location'] = self.ffmpeg_dir

        if progress_callback:
            ydl_opts['progress_hooks'] = [progress_callback]

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

            downloaded_file = self._find_output_file(target_dir, download_id, 'mp4')
            if not downloaded_file:
                raise Exception("Download completed but output file not found.")

            downloaded_file = self._ensure_mp4_h264(downloaded_file)

            title = info.get('title') or (info.get('description') or '')[:80] or 'TikTok Video'
            downloaded_file = self._rename_to_title(downloaded_file, title)
            file_size = os.path.getsize(downloaded_file) if os.path.exists(downloaded_file) else None

            return {
                'download_id': download_id,
                'video_id': info.get('id'),
                'title': title,
                'duration': info.get('duration'),
                'file_path': downloaded_file,
                'file_size': file_size,
                'format': 'mp4',
                'quality': quality,
            }

    def download_audio_only(
        self,
        url: str,
        format: str = "mp3",
        download_dir: Optional[str] = None,
        progress_callback: Optional[callable] = None,
    ) -> Dict:
        url = self._normalize_tiktok_url(url)
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
                audio_file = self._find_output_file(target_dir, download_id, format)

            if not audio_file:
                raise Exception(
                    f"Audio extraction failed. FFmpeg is required. ffmpeg_dir={self.ffmpeg_dir}"
                )

            title = info.get('title') or (info.get('description') or '')[:80] or 'TikTok Audio'
            audio_file = self._rename_to_title(audio_file, title)
            file_size = os.path.getsize(audio_file) if os.path.exists(audio_file) else None

            return {
                'download_id': download_id,
                'video_id': info.get('id'),
                'title': title,
                'duration': info.get('duration'),
                'file_path': audio_file,
                'file_size': file_size,
                'format': format,
            }

    def download_slideshow(
        self,
        url: str,
        download_dir: Optional[str] = None,
        progress_callback: Optional[callable] = None,
    ) -> Dict:
        url = self._normalize_tiktok_url(url)
        download_id = str(uuid.uuid4())
        target_dir = download_dir or self.download_dir
        os.makedirs(target_dir, exist_ok=True)

        # Get info (uses cache)
        info = self.get_video_info(url)
        image_urls = info.get('image_urls', [])
        if not image_urls:
            raise Exception("No images found in this slideshow post.")

        title = info.get('title') or 'TikTok Slideshow'
        total_images = len(image_urls)
        logger.info("Downloading slideshow: %d images, title=%s", total_images, title)

        # Create temp directory for individual images
        temp_dir = os.path.join(target_dir, f'_slideshow_{download_id}')
        os.makedirs(temp_dir, exist_ok=True)

        downloaded_files = []
        try:
            for i, img_url in enumerate(image_urls):
                # Check cancellation
                if progress_callback:
                    progress_callback({
                        "status": "downloading_image",
                        "image_index": i,
                        "image_total": total_images,
                    })

                # Determine extension from URL
                ext = '.webp'
                url_path = urlparse(img_url).path.lower()
                for candidate in ('.jpg', '.jpeg', '.png', '.webp'):
                    if candidate in url_path:
                        ext = candidate
                        break

                img_filename = f'slide_{i + 1:02d}{ext}'
                img_path = os.path.join(temp_dir, img_filename)

                try:
                    req = urllib.request.Request(img_url, headers={
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                    })
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        # Check content type for extension
                        content_type = resp.headers.get('Content-Type', '')
                        if 'jpeg' in content_type or 'jpg' in content_type:
                            ext = '.jpg'
                            img_filename = f'slide_{i + 1:02d}{ext}'
                            img_path = os.path.join(temp_dir, img_filename)
                        elif 'png' in content_type:
                            ext = '.png'
                            img_filename = f'slide_{i + 1:02d}{ext}'
                            img_path = os.path.join(temp_dir, img_filename)

                        with open(img_path, 'wb') as f:
                            f.write(resp.read())

                    downloaded_files.append(img_path)
                    logger.info("Downloaded image %d/%d: %s", i + 1, total_images, img_filename)
                except Exception as e:
                    logger.warning("Failed to download image %d/%d: %s", i + 1, total_images, e)

            if not downloaded_files:
                raise Exception("Failed to download any images from the slideshow.")

            # Create ZIP
            if progress_callback:
                progress_callback({"status": "zipping"})

            safe_title = self._sanitize_filename(title)
            zip_filename = f'{safe_title}_slideshow.zip'
            zip_path = os.path.join(target_dir, zip_filename)

            # Handle duplicate filenames
            if os.path.exists(zip_path):
                counter = 1
                while os.path.exists(zip_path):
                    zip_path = os.path.join(target_dir, f'{safe_title}_slideshow ({counter}).zip')
                    counter += 1

            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_STORED) as zf:
                for img_path in downloaded_files:
                    zf.write(img_path, os.path.basename(img_path))

            file_size = os.path.getsize(zip_path)
            logger.info("Created slideshow ZIP: %s (%d images, %d bytes)", zip_path, len(downloaded_files), file_size)

            return {
                'download_id': download_id,
                'video_id': info.get('video_id'),
                'title': title,
                'duration': info.get('duration'),
                'file_path': zip_path,
                'file_size': file_size,
                'format': 'zip',
                'image_count': len(downloaded_files),
            }
        finally:
            # Clean up temp directory
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass

    def get_profile_videos(self, profile_url: str, limit: int = 30, offset: int = 0) -> dict:
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
            info = ydl.extract_info(profile_url, download=False)
            entries = info.get('entries', [])

            videos = []
            for e in entries:
                if not e:
                    continue
                video_id = e.get('id')
                if not video_id:
                    continue

                uploader = e.get('uploader') or info.get('uploader') or 'user'
                video_url = e.get('url') or e.get('webpage_url') or f'https://www.tiktok.com/@{uploader}/video/{video_id}'

                videos.append({
                    'video_id': video_id,
                    'title': e.get('title') or (e.get('description') or '')[:80] or 'TikTok Video',
                    'url': video_url,
                    'duration': e.get('duration'),
                    'thumbnail': (
                        e.get('thumbnails', [{}])[-1].get('url')
                        if e.get('thumbnails') else e.get('thumbnail')
                    ),
                })

            has_more = len(videos) >= limit
            logger.info("Found %d videos from %s (offset=%d, limit=%d, has_more=%s)",
                        len(videos), profile_url, offset, limit, has_more)
            return {"videos": videos, "has_more": has_more}

    def is_profile_url(self, url: str) -> bool:
        try:
            parsed = urlparse(url)
            host = parsed.hostname or ''
            path = parsed.path.lower().rstrip('/')

            # Short URLs always resolve to single videos
            if 'vm.tiktok.com' in host:
                return False

            # /video/ or /photo/ in path = single post
            if '/video/' in path or '/photo/' in path:
                return False

            # /@username with no further path = profile
            if re.match(r'^/@[^/]+$', path):
                return True

            return False
        except:
            return False

    def _ensure_mp4_h264(self, file_path: str) -> str:
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
            logger.info("TikTok MP4 video codec: %s for %s", codec, os.path.basename(file_path))

            if codec in ('h264', 'avc1', ''):
                return file_path
        except Exception as e:
            logger.warning("ffprobe check failed: %s", e)
            return file_path

        logger.info("Re-encoding %s from %s to H.264", os.path.basename(file_path), codec)
        fixed_path = file_path.replace('.mp4', '_fixed.mp4')

        ffmpeg_bin = 'ffmpeg'
        if self.ffmpeg_dir:
            ffmpeg_candidate = os.path.join(self.ffmpeg_dir, 'ffmpeg')
            if os.path.exists(ffmpeg_candidate) or os.path.exists(ffmpeg_candidate + '.exe'):
                ffmpeg_bin = ffmpeg_candidate

        try:
            subprocess.run(
                [ffmpeg_bin, '-i', file_path, '-c:v', 'libx264', '-preset', 'ultrafast',
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
        name = re.sub(r'[<>:"/\\|?*]', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        if len(name) > 200:
            name = name[:200].strip()
        return name or 'untitled'

    def _rename_to_title(self, file_path: str, title: str) -> str:
        if not title or not os.path.exists(file_path):
            return file_path
        target_dir = os.path.dirname(file_path)
        ext = os.path.splitext(file_path)[1]
        safe_title = self._sanitize_filename(title)
        new_path = os.path.join(target_dir, f"{safe_title}{ext}")
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
        expected_path = os.path.join(target_dir, f'{download_id}.{expected_ext}')
        if os.path.exists(expected_path):
            return expected_path
        candidates = []
        for f in os.listdir(target_dir):
            if f.startswith(download_id) and not f.endswith('.part'):
                parts = f[len(download_id):]
                if parts.count('.') <= 1:
                    candidates.append(os.path.join(target_dir, f))
        if not candidates:
            for f in os.listdir(target_dir):
                if f.startswith(download_id) and not f.endswith('.part'):
                    candidates.append(os.path.join(target_dir, f))
        if candidates:
            return max(candidates, key=os.path.getsize)
        return None
