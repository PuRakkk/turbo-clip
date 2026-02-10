import yt_dlp
import os
import re
import time
import logging
import uuid
import shutil
import urllib.request
from typing import Optional, Dict, List
from urllib.parse import urlparse
from app.settings.config import settings

logger = logging.getLogger("turboclip.instagram")

_info_cache: Dict[str, dict] = {}
_INFO_CACHE_TTL = 600

# Reusable requests session for Instagram web API (avoids re-visiting profile page each time)
_web_session = None
_web_session_ts = 0.0
_WEB_SESSION_TTL = 1800  # 30 minutes


class InstagramService:
    def __init__(self):
        self.download_dir = settings.DOWNLOAD_DIR
        os.makedirs(self.download_dir, exist_ok=True)

        self.ffmpeg_dir = None
        if settings.FFMPEG_PATH and os.path.isdir(settings.FFMPEG_PATH):
            self.ffmpeg_dir = settings.FFMPEG_PATH
        elif shutil.which('ffmpeg'):
            self.ffmpeg_dir = os.path.dirname(shutil.which('ffmpeg'))

    # ---- URL helpers ----

    @staticmethod
    def _extract_url_from_text(text: str) -> str:
        """Extract an Instagram URL from share text."""
        match = re.search(
            r'https?://(?:www\.)?instagram\.com/[^\s\u4e00-\u9fff\uff00-\uffef]*',
            text, re.IGNORECASE,
        )
        if match:
            return re.sub(r'[,;!?）)》」』\]]+$', '', match.group(0))
        return text.strip()

    @staticmethod
    def is_profile_url(url: str) -> bool:
        """Detect if URL is an Instagram profile."""
        try:
            parsed = urlparse(url)
            host = parsed.hostname or ''
            if 'instagram.com' not in host:
                return False
            path = parsed.path.rstrip('/')
            if not path or path == '/':
                return False
            if '/p/' in path or '/reel/' in path or '/reels/' in path or '/stories/' in path:
                return False
            if re.match(r'^/[a-zA-Z0-9_.]+$', path):
                return True
            return False
        except Exception:
            return False

    @staticmethod
    def _get_shortcode(url: str) -> Optional[str]:
        """Extract shortcode from Instagram URL."""
        match = re.search(r'/(?:p|reel|reels)/([A-Za-z0-9_-]+)', url)
        return match.group(1) if match else None

    @staticmethod
    def _get_username(url: str) -> Optional[str]:
        """Extract username from an Instagram profile URL."""
        parsed = urlparse(url)
        path = parsed.path.strip('/')
        if '/' not in path and path:
            return path
        return None

    @staticmethod
    def _shortcode_to_media_id(shortcode: str) -> int:
        """Convert an Instagram shortcode to a numeric media ID.

        Instagram uses a base64-like encoding with this alphabet:
        ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_
        """
        alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_'
        media_id = 0
        for char in shortcode:
            media_id = media_id * 64 + alphabet.index(char)
        return media_id

    # ---- Cookie management (for yt-dlp video downloads) ----

    @staticmethod
    def _cookie_string_to_file(cookie_string: str) -> Optional[str]:
        """Convert a raw Cookie header string to a Netscape cookies.txt temp file."""
        import tempfile
        pairs = []
        for part in cookie_string.split(';'):
            part = part.strip()
            if '=' not in part:
                continue
            name, _, value = part.partition('=')
            pairs.append((name.strip(), value.strip()))
        if not pairs:
            return None
        fd, path = tempfile.mkstemp(suffix='.txt', prefix='instagram_cookies_')
        try:
            with os.fdopen(fd, 'w') as f:
                f.write('# Netscape HTTP Cookie File\n')
                for name, value in pairs:
                    f.write(f'.instagram.com\tTRUE\t/\tTRUE\t0\t{name}\t{value}\n')
            return path
        except Exception as e:
            logger.warning("Failed to write temp cookie file: %s", e)
            try:
                os.close(fd)
            except Exception:
                pass
            return None

    def _get_cookie_opts(self, user_cookie: Optional[str] = None) -> dict:
        """Return yt-dlp cookie options for Instagram."""
        opts = {}
        if user_cookie and user_cookie.strip():
            tmp_path = self._cookie_string_to_file(user_cookie)
            if tmp_path:
                opts['cookiefile'] = tmp_path
                opts['_tmp_cookie_file'] = tmp_path
                return opts
        return opts

    @staticmethod
    def _cleanup_cookie_opts(opts: dict):
        tmp = opts.get('_tmp_cookie_file')
        if tmp:
            try:
                os.remove(tmp)
            except OSError:
                pass

    # ---- Info extraction ----

    @staticmethod
    def _extract_hashtags(description: str) -> list:
        if not description:
            return []
        return re.findall(r'#(\w+)', description)

    def get_post_info(self, url: str, user_cookie: Optional[str] = None) -> Dict:
        """Extract info for a single Instagram post/reel.

        Uses yt-dlp first, then web scraping as fallback.
        No cookies needed for public content.
        """
        url = self._extract_url_from_text(url)

        cached = _info_cache.get(url)
        if cached and time.time() - cached["_ts"] < _INFO_CACHE_TTL:
            return cached["data"]

        shortcode = self._get_shortcode(url)
        if not shortcode:
            raise Exception("Could not extract Instagram shortcode from URL. Check the URL format.")

        # Method 1: yt-dlp (works well for videos)
        result = self._get_post_info_ytdlp(url, shortcode, user_cookie)
        if result:
            _info_cache[url] = {"data": result, "_ts": time.time()}
            return result

        # Method 2: Web scraping (handles images/carousels that yt-dlp misses)
        logger.info("yt-dlp returned nothing, trying web scraping for %s", shortcode)
        result = self._get_post_info_web(shortcode, user_cookie)
        if result:
            _info_cache[url] = {"data": result, "_ts": time.time()}
            return result

        raise Exception(
            "Could not fetch Instagram post info. The post may be private, "
            "deleted, or temporarily unavailable. Try again later."
        )

    def _get_post_info_ytdlp(self, url: str, shortcode: str, user_cookie: Optional[str] = None) -> Optional[Dict]:
        """Try extracting post info via yt-dlp (no cookies needed for public content)."""
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
        }
        if self.ffmpeg_dir:
            ydl_opts['ffmpeg_location'] = self.ffmpeg_dir
        cookie_opts = self._get_cookie_opts(user_cookie)
        ydl_opts.update(cookie_opts)

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception as e:
            logger.info("yt-dlp failed for Instagram %s: %s", shortcode, e)
            self._cleanup_cookie_opts(ydl_opts)
            return None
        finally:
            self._cleanup_cookie_opts(ydl_opts)

        if not info:
            return None

        description = info.get('description') or ''
        title = (info.get('title') or description[:80] or 'Instagram Post').replace('\n', ' ').replace('\r', '').strip() or 'Instagram Post'
        uploader = info.get('uploader') or info.get('uploader_id') or info.get('channel') or ''
        tags = info.get('tags') or self._extract_hashtags(description)
        thumbnail = info.get('thumbnail')

        # yt-dlp may return a playlist for carousel posts
        entries = info.get('entries')
        if entries:
            entries = list(entries)

        if entries and len(entries) > 1:
            # Carousel — multiple items from yt-dlp playlist
            media_items = []
            for i, entry in enumerate(entries):
                is_video = entry.get('vcodec') not in (None, 'none')
                media_items.append({
                    'url': entry.get('webpage_url') or f'https://www.instagram.com/p/{shortcode}/',
                    'type': 'video' if is_video else 'image',
                    'thumbnail': entry.get('thumbnail') or thumbnail,
                    'direct_url': entry.get('url') or '',
                    'title': f'Item {i + 1}',
                    'duration': entry.get('duration'),
                })
            return {
                'video_id': info.get('id') or shortcode,
                'title': title,
                'thumbnail': thumbnail,
                'uploader': uploader,
                'description': description,
                'is_carousel': True,
                'media_items': media_items,
                'media_count': len(media_items),
                'tags': tags,
            }

        # Single video
        has_video = info.get('vcodec') not in (None, 'none')
        if has_video:
            return {
                'video_id': info.get('id') or shortcode,
                'title': title,
                'duration': info.get('duration'),
                'thumbnail': thumbnail,
                'uploader': uploader,
                'description': description,
                'view_count': info.get('view_count'),
                'like_count': info.get('like_count'),
                'is_carousel': False,
                'media_type': 'video',
                'media_items': [{
                    'url': info.get('webpage_url') or f'https://www.instagram.com/reel/{shortcode}/',
                    'type': 'video',
                    'thumbnail': thumbnail,
                    'direct_url': info.get('url') or '',
                }],
                'media_count': 1,
                'tags': tags,
            }

        # Single image — yt-dlp may not handle this well, return None to fallback
        if info.get('url'):
            return {
                'video_id': info.get('id') or shortcode,
                'title': title,
                'duration': None,
                'thumbnail': thumbnail or info.get('url'),
                'uploader': uploader,
                'description': description,
                'view_count': None,
                'like_count': info.get('like_count'),
                'is_carousel': False,
                'media_type': 'image',
                'media_items': [{
                    'url': f'https://www.instagram.com/p/{shortcode}/',
                    'type': 'image',
                    'thumbnail': thumbnail or info.get('url'),
                    'direct_url': info.get('url'),
                }],
                'media_count': 1,
                'tags': tags,
            }

        return None

    # ---- Web scraping fallback for single posts ----

    def _get_post_info_mobile_api(self, shortcode: str) -> Optional[Dict]:
        """Fetch post info via Instagram's mobile API (returns full carousel data)."""
        import requests as _requests

        try:
            media_id = self._shortcode_to_media_id(shortcode)
        except (ValueError, IndexError):
            logger.warning("Could not convert shortcode %s to media_id", shortcode)
            return None

        headers = {
            'User-Agent': 'Instagram 275.0.0.27.98 Android (33/13; 420dpi; 1080x2400; samsung; SM-G991B; o1s; exynos2100; en_US; 458229258)',
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.9',
            'X-IG-App-ID': '567067343352427',
            'X-IG-Capabilities': '3brTvx0=',
            'X-IG-Connection-Type': 'WIFI',
        }

        try:
            resp = _requests.get(
                f'https://i.instagram.com/api/v1/media/{media_id}/info/',
                headers=headers,
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                items = data.get('items')
                if items and len(items) > 0:
                    result = self._parse_api_v1_item(items[0], shortcode)
                    if result:
                        return result
            else:
                logger.info("Mobile API returned %d for %s (media_id=%d)", resp.status_code, shortcode, media_id)
        except _requests.RequestException as e:
            logger.warning("Mobile API request failed for %s: %s", shortcode, e)
        except (ValueError, KeyError, TypeError) as e:
            logger.warning("Failed to parse mobile API response for %s: %s", shortcode, e)

        return None

    def _get_post_info_embed(self, shortcode: str) -> Optional[Dict]:
        """Fetch post info from Instagram's embed page (public, often has carousel data)."""
        import requests as _requests
        import json as _json

        try:
            resp = _requests.get(
                f'https://www.instagram.com/p/{shortcode}/embed/captioned/',
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                                  '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.9',
                },
                timeout=15,
            )
            if resp.status_code != 200:
                logger.info("Embed page returned %d for %s", resp.status_code, shortcode)
                return None

            html = resp.text

            # Pattern 1: window.__additionalDataLoaded (contains full media object)
            match = re.search(
                r'window\.__additionalDataLoaded\s*\([^,]*,\s*(\{.+?\})\s*\)\s*;',
                html, re.DOTALL,
            )
            if match:
                try:
                    data = _json.loads(match.group(1))
                    media = data.get('shortcode_media')
                    if media:
                        result = self._parse_graphql_media(media, shortcode)
                        if result:
                            return result
                except (ValueError, KeyError):
                    pass

            # Pattern 2: Relay data in embed page
            for script_match in re.finditer(
                r'<script\s+type="application/json"[^>]*>(.*?)</script>', html, re.DOTALL
            ):
                try:
                    raw = script_match.group(1).strip()
                    if 'xdt_api__v1__media' in raw:
                        data = _json.loads(raw)
                        items = self._find_relay_media_items(data)
                        if items and len(items) > 0:
                            result = self._parse_api_v1_item(items[0], shortcode)
                            if result:
                                return result
                    elif 'shortcode_media' in raw:
                        data = _json.loads(raw)
                        media = self._find_shortcode_media(data)
                        if media:
                            result = self._parse_graphql_media(media, shortcode)
                            if result:
                                return result
                except (ValueError, KeyError):
                    continue

            # Pattern 3: Extract display_url / video_url from embed HTML
            # Carousel embeds have multiple entries
            import html as _html_mod
            display_urls = []
            for m in re.finditer(r'"display_url"\s*:\s*"([^"]+)"', html):
                try:
                    url = m.group(1).encode().decode('unicode_escape')
                    url = _html_mod.unescape(url)
                    if url not in display_urls:
                        display_urls.append(url)
                except Exception:
                    pass

            video_url_set = set()
            for m in re.finditer(r'"video_url"\s*:\s*"([^"]+)"', html):
                try:
                    url = m.group(1).encode().decode('unicode_escape')
                    url = _html_mod.unescape(url)
                    video_url_set.add(url)
                except Exception:
                    pass

            if len(display_urls) > 1:
                media_items = []
                for i, durl in enumerate(display_urls):
                    is_video = durl in video_url_set
                    media_items.append({
                        'url': f'https://www.instagram.com/p/{shortcode}/',
                        'type': 'video' if is_video else 'image',
                        'thumbnail': durl,
                        'direct_url': durl,
                        'title': f'Item {i + 1}',
                    })
                return {
                    'video_id': shortcode,
                    'title': 'Instagram Post',
                    'thumbnail': display_urls[0],
                    'uploader': '',
                    'description': '',
                    'is_carousel': True,
                    'media_items': media_items,
                    'media_count': len(media_items),
                    'tags': [],
                }

        except _requests.RequestException as e:
            logger.warning("Embed page request failed for %s: %s", shortcode, e)
        except Exception as e:
            logger.warning("Embed page parsing failed for %s: %s", shortcode, e)

        return None

    def _get_post_info_web(self, shortcode: str, user_cookie: Optional[str] = None) -> Optional[Dict]:
        """Extract post info by scraping the Instagram page (handles images/carousels)."""
        import requests as _requests
        import json as _json

        # Method 0: Instagram mobile API
        result = self._get_post_info_mobile_api(shortcode)
        if result:
            logger.info("Extracted post info from mobile API for %s", shortcode)
            return result

        session = self._make_web_session(user_cookie)
        meta_fallback = None

        # Method A: Fetch the post page and parse embedded JSON / meta tags
        try:
            resp = session.get(
                f'https://www.instagram.com/p/{shortcode}/',
                timeout=15,
                allow_redirects=True,
            )
            if resp.status_code == 200:
                result = self._extract_post_from_html(resp.text, shortcode)
                if result:
                    # If we got full data (carousel or video), return immediately
                    if result.get('is_carousel') or result.get('media_type') == 'video':
                        logger.info("Extracted post info from HTML for %s", shortcode)
                        return result
                    # Single image might be just meta tag data — save as fallback, keep trying
                    meta_fallback = result
                    logger.info("HTML returned single image for %s, trying other methods", shortcode)
        except _requests.RequestException as e:
            logger.warning("Post page fetch failed for %s: %s", shortcode, e)

        # Method A2: Embed page (public, often has carousel data)
        result = self._get_post_info_embed(shortcode)
        if result:
            logger.info("Extracted post info from embed page for %s", shortcode)
            return result

        # Method B: ?__a=1&__d=dis JSON API
        csrf = session.cookies.get('csrftoken', domain='.instagram.com') or ''
        api_headers = {
            'X-IG-App-ID': '936619743392459',
            'X-IG-WWW-Claim': '0',
            'X-Requested-With': 'XMLHttpRequest',
            'Referer': f'https://www.instagram.com/p/{shortcode}/',
            'Accept': '*/*',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
        }
        if csrf:
            api_headers['X-CSRFToken'] = csrf

        try:
            resp = session.get(
                f'https://www.instagram.com/p/{shortcode}/?__a=1&__d=dis',
                headers=api_headers,
                timeout=15,
            )
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    # Old GraphQL format
                    media = data.get('graphql', {}).get('shortcode_media')
                    if media:
                        result = self._parse_graphql_media(media, shortcode)
                        if result:
                            logger.info("Extracted post info from __a=1 (graphql) for %s", shortcode)
                            return result
                    # Newer API v1 format
                    items = data.get('items')
                    if items and len(items) > 0:
                        result = self._parse_api_v1_item(items[0], shortcode)
                        if result:
                            logger.info("Extracted post info from __a=1 (v1) for %s", shortcode)
                            return result
                except (ValueError, KeyError, TypeError) as e:
                    logger.warning("Failed to parse __a=1 for %s: %s", shortcode, e)
        except _requests.RequestException as e:
            logger.warning("__a=1 request failed for %s: %s", shortcode, e)

        # Method C: GraphQL query
        try:
            variables = _json.dumps({"shortcode": shortcode, "child_comment_count": 0, "fetch_comment_count": 0, "parent_comment_count": 0, "has_threaded_comments": False})
            resp = session.get(
                'https://www.instagram.com/graphql/query/',
                params={'query_hash': 'b3055c01b4b222b8a47dc12b090e4e64', 'variables': variables},
                headers=api_headers,
                timeout=15,
            )
            if resp.status_code == 200:
                try:
                    media = resp.json().get('data', {}).get('shortcode_media')
                    if media:
                        result = self._parse_graphql_media(media, shortcode)
                        if result:
                            logger.info("Extracted post info from GraphQL for %s", shortcode)
                            return result
                except (ValueError, KeyError, TypeError) as e:
                    logger.warning("Failed to parse GraphQL for %s: %s", shortcode, e)
        except _requests.RequestException as e:
            logger.warning("GraphQL query failed for %s: %s", shortcode, e)

        # Return meta tag fallback if we got one (single image from HTML)
        if meta_fallback:
            logger.info("Returning meta tag fallback for %s", shortcode)
            return meta_fallback

        return None

    def _extract_post_from_html(self, html: str, shortcode: str) -> Optional[Dict]:
        """Extract post data from embedded JSON in an Instagram post page."""
        import json as _json

        # Pattern 0: Modern Instagram Relay data (xdt_api__v1__media)
        # Instagram's current SSR pages embed full media data (including carousel items)
        # in <script type="application/json"> tags using Relay format.
        for script_match in re.finditer(
            r'<script\s+type="application/json"[^>]*>(.*?)</script>', html, re.DOTALL
        ):
            try:
                raw = script_match.group(1).strip()
                if 'xdt_api__v1__media' not in raw:
                    continue
                data = _json.loads(raw)
                items = self._find_relay_media_items(data)
                if items and len(items) > 0:
                    result = self._parse_api_v1_item(items[0], shortcode)
                    if result:
                        logger.info("Found media data in Relay format for %s", shortcode)
                        return result
            except (ValueError, KeyError):
                continue

        # Pattern 1: <script type="application/json"> tags with shortcode_media (GraphQL)
        for script_match in re.finditer(
            r'<script\s+type="application/json"[^>]*>(.*?)</script>', html, re.DOTALL
        ):
            try:
                raw = script_match.group(1).strip()
                if shortcode not in raw and 'shortcode_media' not in raw:
                    continue
                data = _json.loads(raw)
                media = self._find_shortcode_media(data)
                if media:
                    result = self._parse_graphql_media(media, shortcode)
                    if result:
                        return result
            except (ValueError, KeyError):
                continue

        # Pattern 2: window._sharedData
        match = re.search(r'window\._sharedData\s*=\s*(\{.+?\})\s*;\s*</script>', html, re.DOTALL)
        if match:
            try:
                data = _json.loads(match.group(1))
                media = (data.get('entry_data', {}).get('PostPage', [{}])[0]
                         .get('graphql', {}).get('shortcode_media'))
                if media:
                    result = self._parse_graphql_media(media, shortcode)
                    if result:
                        return result
            except (ValueError, KeyError, IndexError):
                pass

        # Pattern 3: Minimal fallback from OpenGraph meta tags
        return self._extract_post_from_meta(html, shortcode)

    def _extract_post_from_meta(self, html: str, shortcode: str) -> Optional[Dict]:
        """Extract minimal post info from OpenGraph meta tags."""
        import html as _html

        og_image = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', html)
        og_video = re.search(r'<meta\s+property="og:video(?::secure_url)?"\s+content="([^"]+)"', html)
        og_title = re.search(r'<meta\s+property="og:title"\s+content="([^"]*)"', html)
        og_desc = re.search(r'<meta\s+property="og:description"\s+content="([^"]*)"', html)

        # HTML meta tag values have &amp; instead of & — must unescape
        thumbnail = _html.unescape(og_image.group(1)) if og_image else ''
        if not thumbnail:
            return None

        title = og_title.group(1) if og_title else 'Instagram Post'
        title = title[:80].replace('\n', ' ').strip() or 'Instagram Post'
        description = og_desc.group(1) if og_desc else ''
        tags = self._extract_hashtags(description)

        if og_video:
            return {
                'video_id': shortcode,
                'title': title,
                'duration': None,
                'thumbnail': thumbnail,
                'uploader': '',
                'description': description,
                'view_count': None,
                'like_count': None,
                'is_carousel': False,
                'media_type': 'video',
                'media_items': [{
                    'url': f'https://www.instagram.com/reel/{shortcode}/',
                    'type': 'video',
                    'thumbnail': thumbnail,
                    'direct_url': _html.unescape(og_video.group(1)),
                }],
                'media_count': 1,
                'tags': tags,
            }

        return {
            'video_id': shortcode,
            'title': title,
            'duration': None,
            'thumbnail': thumbnail,
            'uploader': '',
            'description': description,
            'view_count': None,
            'like_count': None,
            'is_carousel': False,
            'media_type': 'image',
            'media_items': [{
                'url': f'https://www.instagram.com/p/{shortcode}/',
                'type': 'image',
                'thumbnail': thumbnail,
                'direct_url': thumbnail,
            }],
            'media_count': 1,
            'tags': tags,
        }

    @classmethod
    def _find_shortcode_media(cls, obj) -> Optional[dict]:
        """Recursively search for shortcode_media in nested JSON."""
        if isinstance(obj, dict):
            if 'shortcode_media' in obj:
                return obj['shortcode_media']
            for v in obj.values():
                result = cls._find_shortcode_media(v)
                if result is not None:
                    return result
        elif isinstance(obj, list):
            for item in obj:
                result = cls._find_shortcode_media(item)
                if result is not None:
                    return result
        return None

    @classmethod
    def _find_relay_media_items(cls, obj) -> Optional[list]:
        """Recursively search for media items in Instagram's modern Relay data format.

        Modern Instagram pages embed data under the key
        'xdt_api__v1__media__shortcode__web_info' which contains an 'items' array
        in the v1 API format (with carousel_media for carousels).
        """
        if isinstance(obj, dict):
            if 'xdt_api__v1__media__shortcode__web_info' in obj:
                web_info = obj['xdt_api__v1__media__shortcode__web_info']
                if isinstance(web_info, dict):
                    items = web_info.get('items')
                    if items and isinstance(items, list):
                        return items
            for v in obj.values():
                result = cls._find_relay_media_items(v)
                if result is not None:
                    return result
        elif isinstance(obj, list):
            for item in obj:
                result = cls._find_relay_media_items(item)
                if result is not None:
                    return result
        return None

    def _parse_graphql_media(self, media: dict, shortcode: str) -> Optional[Dict]:
        """Parse GraphQL shortcode_media into our standard format."""
        caption_edges = media.get('edge_media_to_caption', {}).get('edges', [])
        caption = caption_edges[0]['node']['text'] if caption_edges else ''
        title = caption[:80].replace('\n', ' ').replace('\r', '').strip() or 'Instagram Post'
        uploader = media.get('owner', {}).get('username', '')
        tags = self._extract_hashtags(caption)
        thumbnail = media.get('display_url') or media.get('thumbnail_src', '')

        # Carousel (GraphSidecar)
        sidecar = media.get('edge_sidecar_to_children', {})
        if sidecar and sidecar.get('edges'):
            media_items = []
            for i, edge in enumerate(sidecar['edges']):
                node = edge.get('node', {})
                is_video = node.get('is_video', False)
                media_items.append({
                    'url': f'https://www.instagram.com/p/{shortcode}/',
                    'type': 'video' if is_video else 'image',
                    'thumbnail': node.get('display_url', ''),
                    'direct_url': node.get('video_url', '') if is_video else node.get('display_url', ''),
                    'title': f'Item {i + 1}',
                    'duration': node.get('video_duration'),
                })
            return {
                'video_id': media.get('id') or shortcode,
                'title': title,
                'thumbnail': thumbnail,
                'uploader': uploader,
                'description': caption,
                'is_carousel': True,
                'media_items': media_items,
                'media_count': len(media_items),
                'tags': tags,
            }

        # Single video
        if media.get('is_video'):
            return {
                'video_id': media.get('id') or shortcode,
                'title': title,
                'duration': media.get('video_duration'),
                'thumbnail': thumbnail,
                'uploader': uploader,
                'description': caption,
                'view_count': media.get('video_view_count'),
                'like_count': media.get('edge_media_preview_like', {}).get('count'),
                'is_carousel': False,
                'media_type': 'video',
                'media_items': [{
                    'url': f'https://www.instagram.com/reel/{shortcode}/',
                    'type': 'video',
                    'thumbnail': thumbnail,
                    'direct_url': media.get('video_url', ''),
                }],
                'media_count': 1,
                'tags': tags,
            }

        # Single image
        return {
            'video_id': media.get('id') or shortcode,
            'title': title,
            'duration': None,
            'thumbnail': thumbnail,
            'uploader': uploader,
            'description': caption,
            'view_count': None,
            'like_count': media.get('edge_media_preview_like', {}).get('count'),
            'is_carousel': False,
            'media_type': 'image',
            'media_items': [{
                'url': f'https://www.instagram.com/p/{shortcode}/',
                'type': 'image',
                'thumbnail': thumbnail,
                'direct_url': thumbnail,
            }],
            'media_count': 1,
            'tags': tags,
        }

    def _parse_api_v1_item(self, item: dict, shortcode: str) -> Optional[Dict]:
        """Parse Instagram API v1 media item into our standard format."""
        caption_obj = item.get('caption') or {}
        caption = caption_obj.get('text', '') if isinstance(caption_obj, dict) else ''
        title = caption[:80].replace('\n', ' ').replace('\r', '').strip() or 'Instagram Post'
        uploader = item.get('user', {}).get('username', '')
        tags = self._extract_hashtags(caption)

        # Get best image from image_versions2
        def _best_image(item_data):
            candidates = item_data.get('image_versions2', {}).get('candidates', [])
            if candidates:
                return candidates[0].get('url', '')
            return ''

        # Get best video
        def _best_video(item_data):
            versions = item_data.get('video_versions', [])
            if versions:
                return versions[0].get('url', '')
            return ''

        media_type = item.get('media_type')
        thumbnail = _best_image(item)

        # Carousel (media_type == 8)
        if media_type == 8 and item.get('carousel_media'):
            media_items = []
            for i, cm in enumerate(item['carousel_media']):
                cm_type = cm.get('media_type')
                is_video = cm_type == 2
                media_items.append({
                    'url': f'https://www.instagram.com/p/{shortcode}/',
                    'type': 'video' if is_video else 'image',
                    'thumbnail': _best_image(cm),
                    'direct_url': _best_video(cm) if is_video else _best_image(cm),
                    'title': f'Item {i + 1}',
                    'duration': cm.get('video_duration'),
                })
            return {
                'video_id': item.get('code') or shortcode,
                'title': title,
                'thumbnail': thumbnail,
                'uploader': uploader,
                'description': caption,
                'is_carousel': True,
                'media_items': media_items,
                'media_count': len(media_items),
                'tags': tags,
            }

        # Video (media_type == 2)
        if media_type == 2:
            return {
                'video_id': item.get('code') or shortcode,
                'title': title,
                'duration': item.get('video_duration'),
                'thumbnail': thumbnail,
                'uploader': uploader,
                'description': caption,
                'view_count': item.get('view_count') or item.get('play_count'),
                'like_count': item.get('like_count'),
                'is_carousel': False,
                'media_type': 'video',
                'media_items': [{
                    'url': f'https://www.instagram.com/reel/{shortcode}/',
                    'type': 'video',
                    'thumbnail': thumbnail,
                    'direct_url': _best_video(item),
                }],
                'media_count': 1,
                'tags': tags,
            }

        # Image (media_type == 1 or fallback)
        return {
            'video_id': item.get('code') or shortcode,
            'title': title,
            'duration': None,
            'thumbnail': thumbnail,
            'uploader': uploader,
            'description': caption,
            'view_count': None,
            'like_count': item.get('like_count'),
            'is_carousel': False,
            'media_type': 'image',
            'media_items': [{
                'url': f'https://www.instagram.com/p/{shortcode}/',
                'type': 'image',
                'thumbnail': thumbnail,
                'direct_url': thumbnail,
            }],
            'media_count': 1,
            'tags': tags,
        }

    # ---- Download methods ----

    def download_video(
        self,
        url: str,
        quality: str = "best",
        progress_callback: Optional[callable] = None,
        download_dir: Optional[str] = None,
        user_cookie: Optional[str] = None,
    ) -> Dict:
        """Download a single Instagram video/reel via yt-dlp."""
        url = self._extract_url_from_text(url)
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
        cookie_opts = self._get_cookie_opts(user_cookie)
        ydl_opts.update(cookie_opts)

        if progress_callback:
            ydl_opts['progress_hooks'] = [progress_callback]

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)

                downloaded_file = self._find_output_file(target_dir, download_id, 'mp4')
                if not downloaded_file:
                    raise Exception("Download completed but output file not found.")

                streams = self._verify_merged_streams(downloaded_file)
                if not streams['has_video'] or not streams['has_audio']:
                    fallback = self._merge_streams_fallback(target_dir, download_id)
                    if fallback:
                        downloaded_file = fallback

                downloaded_file = self._ensure_mp4_h264(downloaded_file)
                self._cleanup_intermediate_files(target_dir, download_id, downloaded_file)

                title = info.get('title') or (info.get('description') or '')[:80] or 'Instagram Video'
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
        finally:
            self._cleanup_cookie_opts(cookie_opts)

    def download_audio_only(
        self,
        url: str,
        format: str = "mp3",
        download_dir: Optional[str] = None,
        progress_callback: Optional[callable] = None,
        user_cookie: Optional[str] = None,
    ) -> Dict:
        """Extract audio from Instagram video/reel."""
        url = self._extract_url_from_text(url)
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
        cookie_opts = self._get_cookie_opts(user_cookie)
        ydl_opts.update(cookie_opts)

        if progress_callback:
            ydl_opts['progress_hooks'] = [progress_callback]

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)

                audio_file = os.path.join(target_dir, f'{download_id}.{format}')
                if not os.path.exists(audio_file):
                    audio_file = self._find_output_file(target_dir, download_id, format)

                if not audio_file:
                    raise Exception("Audio extraction failed. FFmpeg is required.")

                title = info.get('title') or (info.get('description') or '')[:80] or 'Instagram Audio'
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
        finally:
            self._cleanup_cookie_opts(cookie_opts)

    def download_carousel_items(
        self,
        media_items: list,
        title: str = "Instagram Post",
        download_dir: Optional[str] = None,
        progress_callback: Optional[callable] = None,
        user_cookie: Optional[str] = None,
    ) -> Dict:
        """Download selected carousel items. Videos via yt-dlp, images via direct HTTP."""
        target_dir = download_dir or self.download_dir
        os.makedirs(target_dir, exist_ok=True)

        if not media_items:
            raise Exception("No media items provided.")

        safe_title = self._sanitize_filename(title)
        total = len(media_items)
        results = []

        for i, item in enumerate(media_items):
            item_id = str(uuid.uuid4())

            if progress_callback:
                progress_callback({
                    "status": "downloading_item",
                    "item_index": i,
                    "item_total": total,
                })

            try:
                item_type = item.get('type', 'image')
                direct_url = item.get('direct_url') or item.get('url', '')

                if item_type == 'video' and direct_url:
                    # Download video via yt-dlp (use the post URL for yt-dlp, not CDN URL)
                    video_url = item.get('url') or direct_url
                    output_template = os.path.join(target_dir, f'{item_id}.%(ext)s')
                    ydl_opts = {
                        'format': 'bestvideo[vcodec^=avc]+bestaudio/bestvideo*+bestaudio/best',
                        'merge_output_format': 'mp4',
                        'outtmpl': output_template,
                        'quiet': True,
                        'no_warnings': True,
                    }
                    if self.ffmpeg_dir:
                        ydl_opts['ffmpeg_location'] = self.ffmpeg_dir
                    cookie_opts = self._get_cookie_opts(user_cookie)
                    ydl_opts.update(cookie_opts)

                    try:
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            ydl.extract_info(video_url, download=True)
                    finally:
                        self._cleanup_cookie_opts(cookie_opts)

                    file_path = self._find_output_file(target_dir, item_id, 'mp4')
                    if not file_path:
                        # Fallback: try downloading the direct video URL via HTTP
                        file_path = self._download_direct_url(direct_url, target_dir, item_id, '.mp4')

                    if not file_path:
                        raise Exception("Video download failed.")

                    file_size = os.path.getsize(file_path)
                    display_name = f"{safe_title}_{i + 1}.mp4"

                    result = {
                        'download_id': item_id,
                        'title': display_name,
                        'file_path': file_path,
                        'file_size': file_size,
                        'format': 'mp4',
                    }
                else:
                    # Download image via direct HTTP
                    if not direct_url:
                        raise Exception("No URL for image item.")

                    file_path = self._download_direct_url(direct_url, target_dir, item_id)
                    if not file_path:
                        raise Exception("Image download failed.")

                    file_size = os.path.getsize(file_path)
                    ext = os.path.splitext(file_path)[1]
                    display_name = f"{safe_title}_{i + 1}{ext}"

                    result = {
                        'download_id': item_id,
                        'title': display_name,
                        'file_path': file_path,
                        'file_size': file_size,
                        'format': ext.lstrip('.'),
                    }

                results.append(result)
                logger.info("Saved carousel item %d/%d: %s", i + 1, total, result['title'])

                if progress_callback:
                    progress_callback({
                        "status": "item_complete",
                        "item_index": i,
                        "item_total": total,
                        "result": result,
                    })

            except Exception as e:
                logger.warning("Failed to download carousel item %d/%d: %s", i + 1, total, e)

        if not results:
            raise Exception("Failed to download any carousel items.")

        return {
            'results': results,
            'saved_count': len(results),
            'total_count': total,
        }

    def _download_direct_url(self, url: str, target_dir: str, file_id: str,
                              forced_ext: Optional[str] = None) -> Optional[str]:
        """Download a file from a direct URL via HTTP. Returns file path or None."""
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            })
            with urllib.request.urlopen(req, timeout=30) as resp:
                content_type = resp.headers.get('Content-Type', '')

                if forced_ext:
                    ext = forced_ext
                elif 'jpeg' in content_type or 'jpg' in content_type:
                    ext = '.jpg'
                elif 'png' in content_type:
                    ext = '.png'
                elif 'webp' in content_type:
                    ext = '.webp'
                elif 'mp4' in content_type or 'video' in content_type:
                    ext = '.mp4'
                else:
                    # Try from URL path
                    url_path = urlparse(url).path.lower()
                    ext = '.jpg'  # default
                    for candidate in ('.jpg', '.jpeg', '.png', '.webp', '.mp4'):
                        if candidate in url_path:
                            ext = candidate
                            break

                file_path = os.path.join(target_dir, f"{file_id}{ext}")
                with open(file_path, 'wb') as f:
                    while True:
                        chunk = resp.read(8192)
                        if not chunk:
                            break
                        f.write(chunk)

            if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
                return file_path
            return None
        except Exception as e:
            logger.warning("Direct URL download failed: %s", e)
            return None

    def get_profile_posts(self, profile_url: str, limit: int = 30, offset: int = 0,
                          user_cookie: Optional[str] = None) -> dict:
        """Fetch post list from an Instagram profile.

        Tries multiple methods to maximize reliability:
        1. yt-dlp (same approach as YouTube/TikTok)
        2. Scrape profile page HTML for embedded data
        3. web_profile_info API
        4. ?__a=1&__d=dis JSON API
        """
        profile_url = self._extract_url_from_text(profile_url)
        username = self._get_username(profile_url)
        if not username:
            raise Exception("Could not extract username from URL.")

        # Method 1: yt-dlp (most reliable, same as YouTube/TikTok)
        result = self._fetch_profile_ytdlp(username, limit, offset, user_cookie)
        if result is not None:
            return result

        # Methods 2-4: Web scraping fallbacks
        try:
            result = self._fetch_profile_multi(username, limit, offset, user_cookie)
            if result is not None:
                return result
        except Exception as e:
            err_str = str(e).lower()
            if 'not found' in err_str:
                raise
            logger.warning("Web methods failed for %s: %s", username, e)

        raise Exception(
            "Could not fetch profile posts. Instagram may be temporarily blocking requests. "
            "Try again later or use a VPN."
        )

    def _fetch_profile_ytdlp(self, username: str, limit: int = 30, offset: int = 0,
                              user_cookie: Optional[str] = None) -> Optional[dict]:
        """Fetch profile posts via yt-dlp (same approach as YouTube/TikTok)."""
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': 'in_playlist',
            'playliststart': offset + 1,
            'playlistend': offset + limit + 1,  # +1 to detect has_more
        }
        if self.ffmpeg_dir:
            ydl_opts['ffmpeg_location'] = self.ffmpeg_dir
        cookie_opts = self._get_cookie_opts(user_cookie)
        ydl_opts.update(cookie_opts)

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(
                    f'https://www.instagram.com/{username}/',
                    download=False,
                )
        except Exception as e:
            logger.info("yt-dlp profile extraction failed for %s: %s", username, e)
            self._cleanup_cookie_opts(ydl_opts)
            return None
        finally:
            self._cleanup_cookie_opts(ydl_opts)

        if not info:
            return None

        entries = info.get('entries')
        if entries is None:
            return None
        entries = list(entries)

        posts = []
        for entry in entries:
            if not entry:
                continue
            entry_url = entry.get('url') or entry.get('webpage_url') or ''
            shortcode = self._get_shortcode(entry_url) if entry_url else (entry.get('id') or '')
            if not shortcode:
                continue

            title = entry.get('title') or ''
            if not title:
                desc = entry.get('description') or ''
                title = desc[:80].replace('\n', ' ').strip() or 'Instagram Post'
            else:
                title = title[:80].replace('\n', ' ').strip()

            thumbnail = entry.get('thumbnail') or ''
            if not thumbnail:
                thumbnails = entry.get('thumbnails') or []
                if thumbnails:
                    thumbnail = thumbnails[-1].get('url', '')

            posts.append({
                'video_id': shortcode,
                'title': title or 'Instagram Post',
                'url': entry_url or f'https://www.instagram.com/p/{shortcode}/',
                'duration': entry.get('duration'),
                'thumbnail': thumbnail,
            })

        if not posts:
            return None

        has_more = len(posts) > limit
        posts = posts[:limit]
        logger.info("yt-dlp: found %d posts from %s (offset=%d, limit=%d)", len(posts), username, offset, limit)
        return {"posts": posts, "has_more": has_more}

    def _make_web_session(self, user_cookie: Optional[str] = None):
        """Create a fresh requests session mimicking a real browser."""
        import requests as _requests
        global _web_session, _web_session_ts

        if _web_session and time.time() - _web_session_ts < _WEB_SESSION_TTL:
            if user_cookie and user_cookie.strip():
                self._apply_cookie_string(_web_session, user_cookie)
            return _web_session

        session = _requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                          '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,'
                      'image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Sec-Ch-Ua': '"Chromium";v="131", "Not_A Brand";v="24"',
            'Sec-Ch-Ua-Mobile': '?0',
            'Sec-Ch-Ua-Platform': '"Windows"',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Upgrade-Insecure-Requests': '1',
        })
        if user_cookie and user_cookie.strip():
            self._apply_cookie_string(session, user_cookie)

        _web_session = session
        _web_session_ts = time.time()
        return session

    @staticmethod
    def _apply_cookie_string(session, cookie_string: str):
        for part in cookie_string.split(';'):
            part = part.strip()
            if '=' not in part:
                continue
            name, _, value = part.partition('=')
            session.cookies.set(name.strip(), value.strip(), domain='.instagram.com')

    def _fetch_profile_multi(self, username: str, limit: int = 30, offset: int = 0,
                              user_cookie: Optional[str] = None) -> Optional[dict]:
        """Try multiple methods to fetch profile posts."""
        import requests as _requests
        import json as _json

        session = self._make_web_session(user_cookie)

        # --- Method 1: Visit profile page directly (like a real browser) ---
        # This is the most natural request pattern and least likely to be blocked.
        # Also extracts embedded JSON data from the HTML.
        logger.info("Trying profile page HTML for %s", username)
        try:
            page_resp = session.get(
                f'https://www.instagram.com/{username}/',
                timeout=15,
                allow_redirects=True,
            )
            if page_resp.status_code == 404:
                raise Exception(f"Instagram profile '{username}' not found.")

            if page_resp.status_code == 200:
                # Update session cookies from this response
                csrf = session.cookies.get('csrftoken', domain='.instagram.com')

                # Try to extract posts from the HTML
                result = self._extract_posts_from_html(page_resp.text, limit, offset)
                if result is not None:
                    logger.info("Extracted %d posts from profile HTML for %s", len(result['posts']), username)
                    return result

        except _requests.RequestException as e:
            logger.warning("Profile page request failed: %s", e)

        # --- Method 2: web_profile_info API ---
        logger.info("Trying web_profile_info API for %s", username)
        csrf = session.cookies.get('csrftoken', domain='.instagram.com') or ''
        api_headers = {
            'X-IG-App-ID': '936619743392459',
            'X-IG-WWW-Claim': '0',
            'X-Requested-With': 'XMLHttpRequest',
            'Referer': f'https://www.instagram.com/{username}/',
            'Accept': '*/*',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
        }
        if csrf:
            api_headers['X-CSRFToken'] = csrf

        try:
            api_resp = session.get(
                f'https://www.instagram.com/api/v1/users/web_profile_info/?username={username}',
                headers=api_headers,
                timeout=15,
            )
            if api_resp.status_code == 200:
                try:
                    user_data = api_resp.json()['data']['user']
                    if user_data:
                        result = self._build_profile_result(user_data, limit, offset, session, api_headers)
                        if result is not None:
                            logger.info("web_profile_info returned %d posts for %s", len(result['posts']), username)
                            return result
                except (ValueError, KeyError, TypeError) as e:
                    logger.warning("Failed to parse web_profile_info: %s", e)
            else:
                logger.info("web_profile_info returned %d for %s", api_resp.status_code, username)
        except _requests.RequestException as e:
            logger.warning("web_profile_info request failed: %s", e)

        # --- Method 3: ?__a=1&__d=dis JSON shortcut ---
        logger.info("Trying ?__a=1&__d=dis for %s", username)
        try:
            json_resp = session.get(
                f'https://www.instagram.com/{username}/?__a=1&__d=dis',
                headers=api_headers,
                timeout=15,
            )
            if json_resp.status_code == 200:
                try:
                    data = json_resp.json()
                    user_data = (data.get('graphql', {}).get('user')
                                 or data.get('data', {}).get('user'))
                    if user_data:
                        result = self._build_profile_result(user_data, limit, offset, session, api_headers)
                        if result is not None:
                            logger.info("__a=1 returned %d posts for %s", len(result['posts']), username)
                            return result
                except (ValueError, KeyError, TypeError) as e:
                    logger.warning("Failed to parse __a=1 response: %s", e)
            else:
                logger.info("__a=1 returned %d for %s", json_resp.status_code, username)
        except _requests.RequestException as e:
            logger.warning("__a=1 request failed: %s", e)

        logger.warning("All web methods failed for %s", username)
        return None

    def _extract_posts_from_html(self, html: str, limit: int, offset: int) -> Optional[dict]:
        """Extract post data from embedded JSON in Instagram profile page HTML."""
        import json as _json

        # Pattern 1: window._sharedData (older pages)
        match = re.search(r'window\._sharedData\s*=\s*(\{.+?\})\s*;\s*</script>', html, re.DOTALL)
        if match:
            try:
                data = _json.loads(match.group(1))
                pages = data.get('entry_data', {}).get('ProfilePage', [])
                if pages:
                    user_data = pages[0].get('graphql', {}).get('user', {})
                    edge_media = user_data.get('edge_owner_to_timeline_media', {})
                    posts = self._parse_media_edges(edge_media.get('edges', []))
                    if posts:
                        sliced = posts[offset:offset + limit]
                        has_next = edge_media.get('page_info', {}).get('has_next_page', False)
                        return {"posts": sliced, "has_more": len(posts) > offset + limit or has_next}
            except (ValueError, KeyError, IndexError):
                pass

        # Pattern 2: Look for JSON in <script type="application/json"> tags
        for script_match in re.finditer(
            r'<script\s+type="application/json"[^>]*>(.*?)</script>', html, re.DOTALL
        ):
            try:
                raw = script_match.group(1).strip()
                if 'edge_owner_to_timeline_media' not in raw:
                    continue
                data = _json.loads(raw)
                edge_media = self._find_edge_media(data)
                if edge_media:
                    posts = self._parse_media_edges(edge_media.get('edges', []))
                    if posts:
                        sliced = posts[offset:offset + limit]
                        has_next = edge_media.get('page_info', {}).get('has_next_page', False)
                        return {"posts": sliced, "has_more": len(posts) > offset + limit or has_next}
            except (ValueError, KeyError):
                continue

        # Pattern 3: Search for edge_owner_to_timeline_media JSON blob anywhere in HTML
        match = re.search(
            r'"edge_owner_to_timeline_media"\s*:\s*(\{"count":\d+.*?"page_info":\{[^}]+\}\})',
            html, re.DOTALL
        )
        if match:
            try:
                edge_media = _json.loads(match.group(1))
                posts = self._parse_media_edges(edge_media.get('edges', []))
                if posts:
                    sliced = posts[offset:offset + limit]
                    has_next = edge_media.get('page_info', {}).get('has_next_page', False)
                    return {"posts": sliced, "has_more": len(posts) > offset + limit or has_next}
            except (ValueError, KeyError):
                pass

        return None

    @classmethod
    def _find_edge_media(cls, obj) -> Optional[dict]:
        """Recursively search a nested JSON structure for edge_owner_to_timeline_media."""
        if isinstance(obj, dict):
            if 'edge_owner_to_timeline_media' in obj:
                return obj['edge_owner_to_timeline_media']
            for v in obj.values():
                result = cls._find_edge_media(v)
                if result is not None:
                    return result
        elif isinstance(obj, list):
            for item in obj:
                result = cls._find_edge_media(item)
                if result is not None:
                    return result
        return None

    def _build_profile_result(self, user_data: dict, limit: int, offset: int,
                               session, api_headers: dict) -> Optional[dict]:
        """Build profile result from user_data dict, with optional GraphQL pagination."""
        import json as _json

        user_id = user_data.get('id')
        edge_media = user_data.get('edge_owner_to_timeline_media', {})
        all_posts = self._parse_media_edges(edge_media.get('edges', []))
        page_info = edge_media.get('page_info', {})
        has_next = page_info.get('has_next_page', False)
        end_cursor = page_info.get('end_cursor')

        # Paginate via GraphQL if needed
        while len(all_posts) < offset + limit and has_next and end_cursor and user_id:
            try:
                variables = _json.dumps({"id": str(user_id), "first": 50, "after": end_cursor})
                gql_resp = session.get(
                    'https://www.instagram.com/graphql/query/',
                    params={'query_hash': '69cba40317214236af40e7efa697781d', 'variables': variables},
                    headers=api_headers,
                    timeout=15,
                )
                if gql_resp.status_code != 200:
                    break
                gql_edge = (gql_resp.json().get('data', {})
                            .get('user', {})
                            .get('edge_owner_to_timeline_media', {}))
                new_posts = self._parse_media_edges(gql_edge.get('edges', []))
                if not new_posts:
                    break
                all_posts.extend(new_posts)
                page_info = gql_edge.get('page_info', {})
                has_next = page_info.get('has_next_page', False)
                end_cursor = page_info.get('end_cursor')
            except Exception as e:
                logger.warning("GraphQL pagination failed: %s", e)
                break

        if not all_posts:
            return None

        sliced = all_posts[offset:offset + limit]
        return {"posts": sliced, "has_more": len(all_posts) > offset + limit or has_next}

    @staticmethod
    def _parse_media_edges(edges: list) -> list:
        """Parse Instagram GraphQL media edges into post dicts."""
        posts = []
        for edge in edges:
            node = edge.get('node', {})
            shortcode = node.get('shortcode', '')
            if not shortcode:
                continue
            is_video = node.get('is_video', False)
            caption_edges = node.get('edge_media_to_caption', {}).get('edges', [])
            caption = caption_edges[0]['node']['text'] if caption_edges else ''
            posts.append({
                'video_id': shortcode,
                'title': caption[:80].replace('\n', ' ').strip() or 'Instagram Post',
                'url': f'https://www.instagram.com/p/{shortcode}/',
                'duration': node.get('video_duration') if is_video else None,
                'thumbnail': node.get('thumbnail_src') or node.get('display_url', ''),
            })
        return posts

    # ---- Utility methods ----

    def _verify_merged_streams(self, file_path: str) -> dict:
        import subprocess
        import json as _json

        ffprobe = 'ffprobe'
        if self.ffmpeg_dir:
            ffprobe_path = os.path.join(self.ffmpeg_dir, 'ffprobe')
            if os.path.exists(ffprobe_path) or os.path.exists(ffprobe_path + '.exe'):
                ffprobe = ffprobe_path

        result = {"has_video": False, "has_audio": False}
        try:
            proc = subprocess.run(
                [ffprobe, '-v', 'quiet', '-show_streams', '-of', 'json', file_path],
                capture_output=True, text=True, timeout=15
            )
            if proc.returncode != 0:
                return result
            data = _json.loads(proc.stdout)
            for stream in data.get('streams', []):
                if stream.get('codec_type') == 'video':
                    result['has_video'] = True
                elif stream.get('codec_type') == 'audio':
                    result['has_audio'] = True
        except Exception:
            pass
        return result

    def _merge_streams_fallback(self, target_dir: str, download_id: str) -> Optional[str]:
        import subprocess

        ffmpeg_bin = 'ffmpeg'
        if self.ffmpeg_dir:
            candidate = os.path.join(self.ffmpeg_dir, 'ffmpeg')
            if os.path.exists(candidate) or os.path.exists(candidate + '.exe'):
                ffmpeg_bin = candidate

        video_file = None
        audio_file = None
        for f in os.listdir(target_dir):
            if not f.startswith(download_id) or f.endswith('.part'):
                continue
            path = os.path.join(target_dir, f)
            parts = f[len(download_id):]
            if parts.count('.') <= 1:
                continue
            ext_lower = os.path.splitext(f)[1].lower()
            if ext_lower in ('.m4a', '.ogg', '.opus', '.weba') and not audio_file:
                audio_file = path
            elif ext_lower in ('.mp4', '.webm', '.mkv') and not video_file:
                video_file = path

        if not video_file or not audio_file:
            return None

        merged_path = os.path.join(target_dir, f'{download_id}.mp4')
        try:
            subprocess.run(
                [ffmpeg_bin, '-i', video_file, '-i', audio_file,
                 '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-y', merged_path],
                capture_output=True, timeout=600
            )
            if os.path.exists(merged_path) and os.path.getsize(merged_path) > 0:
                return merged_path
        except Exception:
            pass
        return None

    def _cleanup_intermediate_files(self, target_dir: str, download_id: str, final_file: str):
        final_basename = os.path.basename(final_file)
        for f in os.listdir(target_dir):
            if f.startswith(download_id) and f != final_basename:
                try:
                    os.remove(os.path.join(target_dir, f))
                except OSError:
                    pass

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
            if codec in ('h264', 'avc1', ''):
                return file_path
        except Exception:
            return file_path

        fixed_path = file_path.replace('.mp4', '_fixed.mp4')
        ffmpeg_bin = 'ffmpeg'
        if self.ffmpeg_dir:
            candidate = os.path.join(self.ffmpeg_dir, 'ffmpeg')
            if os.path.exists(candidate) or os.path.exists(candidate + '.exe'):
                ffmpeg_bin = candidate

        try:
            subprocess.run(
                [ffmpeg_bin, '-i', file_path, '-c:v', 'libx264', '-preset', 'ultrafast',
                 '-crf', '23', '-c:a', 'copy', '-y', fixed_path],
                capture_output=True, timeout=600
            )
            if os.path.exists(fixed_path) and os.path.getsize(fixed_path) > 0:
                os.remove(file_path)
                os.rename(fixed_path, file_path)
            else:
                if os.path.exists(fixed_path):
                    os.remove(fixed_path)
        except Exception:
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
            return new_path
        except Exception:
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
