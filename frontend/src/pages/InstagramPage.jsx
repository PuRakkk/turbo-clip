import { useState, useEffect, useRef } from 'react';
import api from '../api/axios';
import { useAuth } from '../context/AuthContext';
import VideoCard from '../components/VideoCard';
import DownloadPathPicker from '../components/DownloadPathPicker';
import { smartDownload } from '../utils/downloadHelper';

function formatSpeed(bytesPerSec) {
  if (!bytesPerSec) return '';
  if (bytesPerSec >= 1048576) return `${(bytesPerSec / 1048576).toFixed(1)} MB/s`;
  if (bytesPerSec >= 1024) return `${(bytesPerSec / 1024).toFixed(0)} KB/s`;
  return `${bytesPerSec} B/s`;
}

function formatEta(seconds) {
  if (!seconds) return '';
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}m ${s}s`;
}

const PHASE_LABELS = {
  starting: 'Starting...',
  downloading: 'Downloading',
  downloading_audio: 'Downloading audio',
  downloading_items: 'Downloading items',
  converting: 'Converting audio',
  finalizing: 'Finalizing...',
  done: 'Complete',
  error: 'Failed',
};

function extractUrl(text) {
  if (!text) return '';
  const match = text.match(
    /https?:\/\/(?:www\.)?instagram\.com\/[^\s\u4e00-\u9fff\uff00-\uffef]*/i
  );
  return match ? match[0].replace(/[,;!?）)》」』\]]+$/, '') : text.trim();
}

function proxyImg(url) {
  if (!url) return '';
  if (url.includes('instagram') || url.includes('fbcdn') || url.includes('cdninstagram')) {
    return `/api/instagram/proxy-image?url=${encodeURIComponent(url)}`;
  }
  return url;
}

export default function InstagramPage() {
  const { user } = useAuth();
  const [url, setUrl] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  // Single video / image state
  const [videoInfo, setVideoInfo] = useState(null);
  // Carousel state
  const [carouselInfo, setCarouselInfo] = useState(null);
  const [selectedItemIds, setSelectedItemIds] = useState(new Set());
  const [downloading, setDownloading] = useState(false);
  const [message, setMessage] = useState(null);
  const [progress, setProgress] = useState(null);

  // Batch (profile) state
  const [profilePosts, setProfilePosts] = useState([]);
  const [selectedIds, setSelectedIds] = useState(new Set());
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [batchDownloading, setBatchDownloading] = useState(false);
  const [batchProgress, setBatchProgress] = useState(null);
  const [postLimit, setPostLimit] = useState(30);

  const eventSourceRef = useRef(null);
  const activeDownloadId = useRef(null);
  const deliveredIdsRef = useRef(new Set());

  useEffect(() => {
    return () => {
      if (eventSourceRef.current) eventSourceRef.current.close();
    };
  }, []);

  // Auto-select all carousel items when info loads
  useEffect(() => {
    if (carouselInfo?.media_items?.length) {
      setSelectedItemIds(new Set(carouselInfo.media_items.map((_, i) => i)));
    }
  }, [carouselInfo]);

  function resetResults() {
    setVideoInfo(null);
    setCarouselInfo(null);
    setSelectedItemIds(new Set());
    setProfilePosts([]);
    setSelectedIds(new Set());
    setHasMore(false);
    setMessage(null);
    setProgress(null);
    setBatchProgress(null);
    setError('');
  }

  // Proxy all Instagram CDN thumbnail URLs in an info object
  function proxyInfoThumbnails(info) {
    const proxied = { ...info, thumbnail: proxyImg(info.thumbnail) };
    if (proxied.media_items) {
      proxied.media_items = proxied.media_items.map((item) => ({
        ...item,
        thumbnail: proxyImg(item.thumbnail),
      }));
    }
    return proxied;
  }

  // --- Smart info ---
  async function handleGetInfo(e) {
    e.preventDefault();
    resetResults();
    setLoading(true);
    const cleanUrl = extractUrl(url);
    if (cleanUrl !== url) setUrl(cleanUrl);
    try {
      const res = await api.post('/instagram/info', { url: cleanUrl, limit: postLimit, offset: 0 });
      if (res.data.type === 'profile') {
        if (res.data.count === 0) {
          setError('No posts found on this profile');
        } else if (res.data.count === 1) {
          const infoRes = await api.post('/instagram/info', { url: res.data.videos[0].url });
          if (infoRes.data.type === 'carousel') setCarouselInfo(proxyInfoThumbnails(infoRes.data.info));
          else setVideoInfo(proxyInfoThumbnails(infoRes.data.info));
        } else {
          const posts = res.data.videos.map((v) => ({ ...v, thumbnail: proxyImg(v.thumbnail) }));
          setProfilePosts(posts);
          setSelectedIds(new Set(posts.map((v) => v.video_id)));
          setHasMore(res.data.has_more);
        }
      } else if (res.data.type === 'carousel') {
        setCarouselInfo(proxyInfoThumbnails(res.data.info));
      } else {
        // video or image
        setVideoInfo(proxyInfoThumbnails(res.data.info));
      }
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to fetch Instagram info');
    } finally {
      setLoading(false);
    }
  }

  async function handleLoadMore() {
    setLoadingMore(true);
    try {
      const res = await api.post('/instagram/info', { url, limit: postLimit, offset: profilePosts.length });
      if (res.data.type === 'profile') {
        const newPosts = res.data.videos.map((v) => ({ ...v, thumbnail: proxyImg(v.thumbnail) }));
        setProfilePosts((prev) => [...prev, ...newPosts]);
        setSelectedIds((prev) => {
          const next = new Set(prev);
          newPosts.forEach((v) => next.add(v.video_id));
          return next;
        });
        setHasMore(res.data.has_more);
      }
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to load more posts');
    } finally {
      setLoadingMore(false);
    }
  }

  // --- Single download progress (SSE) ---
  function connectToProgress(downloadId) {
    if (eventSourceRef.current) eventSourceRef.current.close();
    const es = new EventSource(`/api/instagram/progress/${downloadId}`);
    eventSourceRef.current = es;

    es.onmessage = (event) => {
      const data = JSON.parse(event.data);
      setProgress(data);

      if (data.status === 'done') {
        es.close();
        eventSourceRef.current = null;
        setDownloading(false);
        if (data.download_id) {
          smartDownload(data.download_id, data.title).catch((err) =>
            console.warn('smartDownload failed:', err)
          );
        }
        setMessage({
          text: `'${data.title}' downloaded successfully`,
          downloadId: data.download_id,
        });
        setTimeout(() => setProgress(null), 1500);
      }

      if (data.status === 'error') {
        es.close();
        eventSourceRef.current = null;
        setDownloading(false);
        setError(data.error || 'Download failed');
        setProgress(null);
      }
    };

    es.onerror = () => {
      es.close();
      eventSourceRef.current = null;
      setDownloading(false);
      setError('Lost connection to download progress');
      setProgress(null);
    };
  }

  async function handleDownload(type) {
    setDownloading(true);
    setError('');
    setMessage(null);
    setProgress({ status: 'waiting', progress: 0, phase: 'starting' });

    try {
      const endpoint = type === 'audio' ? '/instagram/audio' : '/instagram/video';
      const res = await api.post(endpoint, { url });
      activeDownloadId.current = res.data.download_id;
      connectToProgress(res.data.download_id);
    } catch (err) {
      setError(err.response?.data?.detail || 'Download failed');
      setDownloading(false);
      setProgress(null);
    }
  }

  // --- Carousel download ---
  async function handleDownloadCarousel() {
    if (!carouselInfo?.media_items?.length) return;
    const allItems = carouselInfo.media_items;
    const selectedIndices = [...selectedItemIds].sort((a, b) => a - b);
    if (selectedIndices.length === 0) return;

    setDownloading(true);
    setError('');
    setMessage(null);
    setProgress({ status: 'waiting', progress: 0, phase: 'starting' });

    try {
      const selectedItems = selectedIndices.map((i) => allItems[i]);
      const res = await api.post('/instagram/carousel/items', {
        media_items: selectedItems,
        title: carouselInfo.title || 'Instagram Post',
      });
      activeDownloadId.current = res.data.download_id;
      connectToCarouselProgress(res.data.download_id);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to start carousel download');
      setDownloading(false);
      setProgress(null);
    }
  }

  function connectToCarouselProgress(downloadId) {
    if (eventSourceRef.current) eventSourceRef.current.close();
    deliveredIdsRef.current = new Set();
    const es = new EventSource(`/api/instagram/progress/${downloadId}`);
    eventSourceRef.current = es;

    es.onmessage = (event) => {
      const data = JSON.parse(event.data);
      setProgress(data);

      const downloads = data.completed_downloads || [];
      for (const dl of downloads) {
        if (dl.download_id && !deliveredIdsRef.current.has(dl.download_id)) {
          deliveredIdsRef.current.add(dl.download_id);
          smartDownload(dl.download_id, dl.title).catch((err) =>
            console.warn('Carousel smartDownload failed:', dl.title, err)
          );
        }
      }

      if (data.status === 'done') {
        es.close();
        eventSourceRef.current = null;
        setDownloading(false);
        const saved = data.saved_count || 0;
        const total = data.total_count || 0;
        const failed = total - saved;
        if (failed > 0) {
          setMessage({ text: `${saved} of ${total} items saved to your device` });
        } else {
          setMessage({ text: `${saved} items saved to your device` });
        }
        setTimeout(() => setProgress(null), 1500);
      }

      if (data.status === 'error') {
        es.close();
        eventSourceRef.current = null;
        setDownloading(false);
        setError(data.error || 'Carousel download failed');
        setProgress(null);
      }
    };

    es.onerror = () => {
      es.close();
      eventSourceRef.current = null;
      setDownloading(false);
      setError('Lost connection to download progress');
      setProgress(null);
    };
  }

  async function handleStop() {
    const id = activeDownloadId.current;
    if (id) {
      try { await api.post(`/instagram/cancel/${id}`); } catch {}
    }
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
    activeDownloadId.current = null;
    setDownloading(false);
    setBatchDownloading(false);
    setProgress(null);
    setBatchProgress(null);
  }

  // --- Batch progress (SSE) ---
  function connectToBatchProgress(batchId) {
    if (eventSourceRef.current) eventSourceRef.current.close();
    deliveredIdsRef.current = new Set();

    const es = new EventSource(`/api/instagram/batch/progress/${batchId}`);
    eventSourceRef.current = es;

    es.onmessage = (event) => {
      const data = JSON.parse(event.data);
      setBatchProgress(data);

      const downloads = data.completed_downloads || [];
      for (const dl of downloads) {
        if (dl.download_id && !deliveredIdsRef.current.has(dl.download_id)) {
          deliveredIdsRef.current.add(dl.download_id);
          smartDownload(dl.download_id, dl.title).catch((err) =>
            console.warn('Batch smartDownload failed:', dl.title, err)
          );
        }
      }

      if (data.status === 'done' || data.status === 'error') {
        es.close();
        eventSourceRef.current = null;
        setBatchDownloading(false);
      }
    };

    es.onerror = () => {
      es.close();
      eventSourceRef.current = null;
      setBatchDownloading(false);
      setError('Lost connection to batch progress');
    };
  }

  function toggleSelect(videoId) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(videoId)) next.delete(videoId);
      else next.add(videoId);
      return next;
    });
  }

  function selectAll() {
    setSelectedIds(new Set(profilePosts.map((v) => v.video_id)));
  }

  function deselectAll() {
    setSelectedIds(new Set());
  }

  const selectedCount = selectedIds.size;

  // --- Carousel item selection ---
  function toggleItemSelect(index) {
    setSelectedItemIds((prev) => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  }

  function selectAllItems() {
    if (carouselInfo?.media_items) {
      setSelectedItemIds(new Set(carouselInfo.media_items.map((_, i) => i)));
    }
  }

  function deselectAllItems() {
    setSelectedItemIds(new Set());
  }

  const selectedItemCount = selectedItemIds.size;
  const totalItemCount = carouselInfo?.media_items?.length || 0;

  async function handleDownloadAll() {
    const selected = profilePosts.filter((v) => selectedIds.has(v.video_id));
    if (selected.length === 0) return;

    setBatchDownloading(true);
    setError('');
    setBatchProgress({ status: 'waiting', total: selected.length, completed: 0 });

    try {
      const videoUrls = selected.map((v) => v.url);
      const res = await api.post('/instagram/batch/download', { video_urls: videoUrls });
      activeDownloadId.current = res.data.batch_id;
      connectToBatchProgress(res.data.batch_id);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to start batch download');
      setBatchDownloading(false);
      setBatchProgress(null);
    }
  }

  // --- Single image download (via backend carousel endpoint) ---
  async function handleDownloadImage() {
    if (!videoInfo?.media_items?.length) return;
    const item = videoInfo.media_items[0];

    setDownloading(true);
    setError('');
    setMessage(null);
    setProgress({ status: 'waiting', progress: 0, phase: 'starting' });

    try {
      const res = await api.post('/instagram/carousel/items', {
        media_items: [item],
        title: videoInfo.title || 'Instagram Image',
      });
      activeDownloadId.current = res.data.download_id;
      connectToCarouselProgress(res.data.download_id);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to download image');
      setDownloading(false);
      setProgress(null);
    }
  }

  const isBatchDone = batchProgress?.status === 'done';
  const failedCount = batchProgress?.failed?.length || 0;

  const isImageOnly = videoInfo && videoInfo.media_type === 'image';

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <div className="text-center mb-6 sm:mb-8">
        <h1 className="text-3xl sm:text-4xl font-bold mb-2">Instagram</h1>
        <p className="text-gray-400 text-sm sm:text-base">Download Reels, Posts, Carousels, or batch download from profiles</p>
      </div>

      {/* URL Input */}
      <form onSubmit={handleGetInfo} className="flex flex-col sm:flex-row gap-2 sm:gap-3">
        <input
          type="text"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          onPaste={(e) => {
            const pasted = e.clipboardData.getData('text');
            const extracted = extractUrl(pasted);
            if (extracted !== pasted.trim()) {
              e.preventDefault();
              setUrl(extracted);
            }
          }}
          required
          placeholder="Instagram URL (Reel, Post, or Profile)"
          className="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-4 py-3 text-white focus:outline-none focus:border-pink-500 transition text-sm sm:text-base"
        />
        <button
          type="submit"
          disabled={loading || downloading || batchDownloading}
          className="bg-pink-600 hover:bg-pink-700 disabled:bg-pink-800 text-white px-6 py-3 rounded-lg font-semibold transition whitespace-nowrap"
        >
          {loading ? 'Loading...' : 'Get Info'}
        </button>
      </form>

      {/* Download Location Picker */}
      <DownloadPathPicker />

      {/* Error */}
      {error && (
        <div className="bg-red-500/10 border border-red-500/50 text-red-400 px-3 sm:px-4 py-3 rounded-lg text-xs sm:text-sm wrap-break-word overflow-hidden">
          {error}
        </div>
      )}

      {/* ══════════ Single Video / Image Flow ══════════ */}

      {/* Progress */}
      {progress && (
        <div className="bg-gray-900 rounded-xl border border-gray-800 p-3 sm:p-4 space-y-3">
          <div className="flex items-center justify-between gap-2 text-xs sm:text-sm">
            <span className="text-gray-300 font-medium min-w-0 truncate">
              {PHASE_LABELS[progress.phase] || progress.phase}
            </span>
            <span className="text-white font-semibold shrink-0">{Math.round(progress.progress)}%</span>
          </div>
          <div className="w-full bg-gray-800 rounded-full h-3 overflow-hidden">
            <div
              className="h-full rounded-full transition-all duration-500 ease-out"
              style={{
                width: `${progress.progress}%`,
                background: progress.status === 'error'
                  ? '#ef4444'
                  : progress.progress >= 100
                    ? '#22c55e'
                    : 'linear-gradient(90deg, #ec4899, #a855f7)',
              }}
            />
          </div>
          <div className="flex items-center justify-between text-xs text-gray-500">
            <span>{formatSpeed(progress.speed)}</span>
            <span>{progress.eta ? `ETA: ${formatEta(progress.eta)}` : ''}</span>
          </div>
          {downloading && (
            <button
              onClick={handleStop}
              className="w-full bg-red-600 hover:bg-red-700 text-white py-2 rounded-lg text-sm font-semibold transition"
            >
              Stop Download
            </button>
          )}
        </div>
      )}

      {/* Success */}
      {message && (
        <div className="bg-green-500/10 border border-green-500/50 text-green-400 px-3 sm:px-4 py-3 rounded-lg text-xs sm:text-sm wrap-break-word overflow-hidden">
          {message.text}
        </div>
      )}

      {/* Video / Image Info + Download */}
      {videoInfo && (
        <div className="space-y-4">
          <VideoCard info={videoInfo} isPremium={!!user?.is_premium} />

          <div className="bg-gray-900 rounded-xl p-4 sm:p-6 border border-gray-800 space-y-4">
            <h3 className="text-lg font-semibold">Download Options</h3>
            <p className="text-sm text-gray-400">
              {isImageOnly
                ? 'This is a single image post.'
                : 'Instagram videos are downloaded in the best available quality as MP4.'}
            </p>
            <div className="flex flex-col sm:flex-row gap-2 sm:gap-3 pt-2">
              {isImageOnly ? (
                <button
                  onClick={handleDownloadImage}
                  disabled={downloading}
                  className="flex-1 bg-pink-600 hover:bg-pink-700 disabled:bg-pink-800 text-white py-3 rounded-lg font-semibold transition"
                >
                  Download Image
                </button>
              ) : (
                <>
                  <button
                    onClick={() => handleDownload('video')}
                    disabled={downloading}
                    className="flex-1 bg-pink-600 hover:bg-pink-700 disabled:bg-pink-800 text-white py-3 rounded-lg font-semibold transition"
                  >
                    {downloading ? 'Downloading...' : 'Download Video'}
                  </button>
                  <button
                    onClick={() => handleDownload('audio')}
                    disabled={downloading}
                    className="flex-1 bg-purple-600 hover:bg-purple-700 disabled:bg-purple-800 text-white py-3 rounded-lg font-semibold transition"
                  >
                    {downloading ? 'Downloading...' : 'Download Audio'}
                  </button>
                </>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ══════════ Carousel Flow ══════════ */}

      {carouselInfo && (
        <div className="space-y-4">
          <VideoCard info={carouselInfo} isPremium={!!user?.is_premium} />

          {/* Item selection grid */}
          <div className="bg-gray-900 rounded-xl p-4 sm:p-6 border border-gray-800 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-semibold">
                Select Items
                {selectedItemCount < totalItemCount && (
                  <span className="text-sm font-normal text-gray-400 ml-2">
                    ({selectedItemCount} selected)
                  </span>
                )}
              </h3>
            </div>

            {/* Select / Deselect controls */}
            <div className="flex items-center gap-2">
              <button
                onClick={selectAllItems}
                disabled={selectedItemCount === totalItemCount}
                className="bg-gray-800 hover:bg-gray-700 disabled:opacity-40 border border-gray-700 text-white text-xs px-3 py-1.5 rounded-lg transition"
              >
                Select All
              </button>
              <button
                onClick={deselectAllItems}
                disabled={selectedItemCount === 0}
                className="bg-gray-800 hover:bg-gray-700 disabled:opacity-40 border border-gray-700 text-white text-xs px-3 py-1.5 rounded-lg transition"
              >
                Deselect All
              </button>
              <span className="text-xs text-gray-500 ml-auto">
                Click items to toggle selection
              </span>
            </div>

            {/* Media grid */}
            <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 gap-2 sm:gap-3 max-h-80 overflow-y-auto">
              {(carouselInfo.media_items || []).map((item, i) => {
                const isSelected = selectedItemIds.has(i);
                const isVideo = item.type === 'video';
                return (
                  <div
                    key={i}
                    className="group cursor-pointer"
                    onClick={() => toggleItemSelect(i)}
                  >
                    <div className={`relative aspect-square rounded-lg overflow-hidden bg-gray-800 ring-2 transition ${isSelected ? 'ring-pink-500' : 'ring-transparent opacity-50'}`}>
                      {item.thumbnail ? (
                        <img
                          src={item.thumbnail}
                          alt={`Item ${i + 1}`}
                          loading="lazy"
                          className="w-full h-full object-cover"
                        />
                      ) : (
                        <div className="w-full h-full flex items-center justify-center text-gray-600 text-xs">
                          No preview
                        </div>
                      )}
                      {/* Video play icon overlay */}
                      {isVideo && (
                        <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
                          <svg className="w-8 h-8 text-white/80 drop-shadow-lg" fill="currentColor" viewBox="0 0 24 24">
                            <path d="M8 5v14l11-7z" />
                          </svg>
                        </div>
                      )}
                      {/* Checkbox indicator */}
                      <div className={`absolute top-1.5 left-1.5 w-5 h-5 rounded flex items-center justify-center text-xs font-bold transition ${isSelected ? 'bg-pink-500 text-white' : 'bg-black/60 text-gray-400 border border-gray-500'}`}>
                        {isSelected ? '\u2713' : ''}
                      </div>
                      {/* Type badge + number */}
                      <div className="absolute bottom-1 right-1 flex items-center gap-1">
                        <span className="bg-black/80 text-white text-xs px-1.5 py-0.5 rounded">
                          {isVideo ? 'Vid' : 'Img'} {i + 1}
                        </span>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Download button */}
            <div className="flex flex-col sm:flex-row gap-2 sm:gap-3 pt-2">
              <button
                onClick={handleDownloadCarousel}
                disabled={downloading || selectedItemCount === 0}
                className="flex-1 bg-pink-600 hover:bg-pink-700 disabled:bg-pink-800 text-white py-3 rounded-lg font-semibold transition"
              >
                {downloading
                  ? 'Downloading...'
                  : selectedItemCount === totalItemCount
                    ? `Download All ${totalItemCount} Items`
                    : `Download ${selectedItemCount} of ${totalItemCount} Items`}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ══════════ Batch (Profile) Flow ══════════ */}

      {profilePosts.length > 0 && (
        <div className="space-y-4">
          <div className="flex items-center justify-between gap-2">
            <h2 className="text-base sm:text-lg font-semibold">
              Found {profilePosts.length} posts{hasMore ? '+' : ''}
              {selectedCount < profilePosts.length && (
                <span className="text-sm font-normal text-gray-400 ml-2">
                  ({selectedCount} selected)
                </span>
              )}
            </h2>
            <div className="flex items-center gap-2 text-sm shrink-0">
              <span className="text-gray-400 hidden sm:inline">Load per page:</span>
              <select
                value={postLimit}
                onChange={(e) => setPostLimit(Number(e.target.value))}
                className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-white text-sm"
              >
                <option value={30}>30</option>
                <option value={50}>50</option>
                <option value={100}>100</option>
              </select>
            </div>
          </div>

          {/* Select / Deselect controls */}
          <div className="flex items-center gap-2">
            <button
              onClick={selectAll}
              disabled={selectedCount === profilePosts.length}
              className="bg-gray-800 hover:bg-gray-700 disabled:opacity-40 border border-gray-700 text-white text-xs px-3 py-1.5 rounded-lg transition"
            >
              Select All
            </button>
            <button
              onClick={deselectAll}
              disabled={selectedCount === 0}
              className="bg-gray-800 hover:bg-gray-700 disabled:opacity-40 border border-gray-700 text-white text-xs px-3 py-1.5 rounded-lg transition"
            >
              Deselect All
            </button>
            <span className="text-xs text-gray-500 ml-auto">
              Click thumbnails to toggle selection
            </span>
          </div>

          <div className="bg-gray-900 rounded-xl border border-gray-800 p-4 max-h-96 overflow-y-auto">
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2 sm:gap-3">
              {profilePosts.map((v) => {
                const isSelected = selectedIds.has(v.video_id);
                return (
                  <div
                    key={v.video_id}
                    className="group cursor-pointer"
                    onClick={() => toggleSelect(v.video_id)}
                  >
                    <div className={`relative aspect-square rounded-lg overflow-hidden bg-gray-800 ring-2 transition ${isSelected ? 'ring-pink-500' : 'ring-transparent opacity-50'}`}>
                      {v.thumbnail ? (
                        <img src={v.thumbnail} alt={v.title} loading="lazy" className="w-full h-full object-cover" />
                      ) : (
                        <div className="w-full h-full flex items-center justify-center text-gray-600 text-xs">
                          No thumbnail
                        </div>
                      )}
                      {/* Checkbox indicator */}
                      <div className={`absolute top-1.5 left-1.5 w-5 h-5 rounded flex items-center justify-center text-xs font-bold transition ${isSelected ? 'bg-pink-500 text-white' : 'bg-black/60 text-gray-400 border border-gray-500'}`}>
                        {isSelected ? '\u2713' : ''}
                      </div>
                      {v.duration && (
                        <span className="absolute bottom-1 right-1 bg-black/80 text-white text-xs px-1.5 py-0.5 rounded">
                          {v.duration}s
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-gray-400 mt-1 line-clamp-2">{v.title}</p>
                  </div>
                );
              })}
            </div>
          </div>

          {hasMore && (
            <button
              onClick={handleLoadMore}
              disabled={loadingMore}
              className="w-full bg-gray-800 hover:bg-gray-700 disabled:bg-gray-800 border border-gray-700 text-white py-2.5 rounded-lg text-sm font-medium transition"
            >
              {loadingMore ? 'Loading more...' : `Load ${postLimit} More Posts`}
            </button>
          )}

          <button
            onClick={handleDownloadAll}
            disabled={batchDownloading || selectedCount === 0}
            className="w-full bg-pink-600 hover:bg-pink-700 disabled:bg-pink-800 text-white py-3 rounded-lg font-semibold transition"
          >
            {batchDownloading
              ? 'Downloading...'
              : selectedCount === profilePosts.length
                ? `Download All ${profilePosts.length} Posts`
                : `Download ${selectedCount} of ${profilePosts.length} Posts`}
          </button>
        </div>
      )}

      {/* Batch Progress */}
      {batchProgress && (
        <div className="bg-gray-900 rounded-xl border border-gray-800 p-3 sm:p-4 space-y-3 overflow-hidden">
          <div className="flex items-center justify-between gap-2 text-xs sm:text-sm">
            <span className="text-gray-300 font-medium min-w-0 truncate">
              {isBatchDone
                ? 'Batch complete'
                : batchProgress.current_title
                  ? `Downloading: ${batchProgress.current_title}`
                  : `Downloading ${batchProgress.completed + 1} of ${batchProgress.total}...`}
            </span>
            <span className="text-white font-semibold shrink-0">
              {batchProgress.completed}/{batchProgress.total}
            </span>
          </div>

          <div className="w-full bg-gray-800 rounded-full h-3 overflow-hidden">
            <div
              className="h-full rounded-full transition-all duration-500 ease-out"
              style={{
                width: batchProgress.total > 0
                  ? `${(batchProgress.completed / batchProgress.total) * 100}%`
                  : '0%',
                background: isBatchDone
                  ? '#22c55e'
                  : 'linear-gradient(90deg, #ec4899, #a855f7)',
              }}
            />
          </div>

          {!isBatchDone && batchProgress.current_progress > 0 && (
            <div className="space-y-1">
              <div className="text-xs text-gray-500">
                Current post: {Math.round(batchProgress.current_progress)}%
              </div>
              <div className="w-full bg-gray-800 rounded-full h-1.5 overflow-hidden">
                <div
                  className="h-full rounded-full bg-pink-500/50 transition-all duration-300"
                  style={{ width: `${batchProgress.current_progress}%` }}
                />
              </div>
            </div>
          )}

          {batchDownloading && (
            <button
              onClick={handleStop}
              className="w-full bg-red-600 hover:bg-red-700 text-white py-2 rounded-lg text-xs sm:text-sm font-semibold transition"
            >
              Stop Batch Download
            </button>
          )}

          {isBatchDone && (
            <div className="text-xs sm:text-sm">
              <span className="text-green-400">
                Successfully downloaded {batchProgress.completed - failedCount} of {batchProgress.total} posts.
              </span>
            </div>
          )}

          {failedCount > 0 && (
            <div className="text-xs sm:text-sm overflow-hidden">
              <span className="text-red-400">{failedCount} failed:</span>
              <ul className="mt-1 space-y-1">
                {batchProgress.failed.map((f, i) => (
                  <li key={i} className="text-xs text-red-300 truncate">
                    {f.error}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
