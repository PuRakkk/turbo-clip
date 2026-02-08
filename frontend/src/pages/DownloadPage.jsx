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
  downloading_video: 'Downloading video',
  downloading_audio: 'Downloading audio',
  merging: 'Merging streams',
  converting: 'Converting audio',
  done: 'Complete',
  error: 'Failed',
};

function isChannelUrl(url) {
  try {
    const u = new URL(url);
    const path = u.pathname.toLowerCase();
    // Single short video: /shorts/VIDEO_ID — NOT a channel
    if (/^\/shorts\/[a-zA-Z0-9_-]+/.test(u.pathname)) return false;
    // Channel URLs: /@user, /channel/ID, /c/name (with or without /shorts tab)
    if (path.includes('/@') || path.includes('/channel/') || path.includes('/c/')) return true;
    return false;
  } catch {
    return false;
  }
}

export default function DownloadPage() {
  const { user } = useAuth();
  const [url, setUrl] = useState('');
  const [format, setFormat] = useState('mp4');
  const [quality, setQuality] = useState('720p');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  // Single video state
  const [videoInfo, setVideoInfo] = useState(null);
  const [downloading, setDownloading] = useState(false);
  const [message, setMessage] = useState(null);
  const [progress, setProgress] = useState(null);

  // Batch state
  const [shorts, setShorts] = useState([]);
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [batchDownloading, setBatchDownloading] = useState(false);
  const [batchProgress, setBatchProgress] = useState(null);
  const [videoLimit, setVideoLimit] = useState(30);

  const eventSourceRef = useRef(null);
  const activeDownloadId = useRef(null);

  useEffect(() => {
    return () => {
      if (eventSourceRef.current) eventSourceRef.current.close();
    };
  }, []);

  function resetResults() {
    setVideoInfo(null);
    setShorts([]);
    setHasMore(false);
    setMessage(null);
    setProgress(null);
    setBatchProgress(null);
    setError('');
  }

  // ─── Get Info (smart detection) ───
  async function handleGetInfo(e) {
    e.preventDefault();
    resetResults();
    setLoading(true);

    try {
      if (isChannelUrl(url)) {
        // Batch: load shorts from channel (paginated)
        const res = await api.post('/download/batch/info', { url, limit: videoLimit, offset: 0 });
        const videos = res.data.videos || [];
        if (videos.length === 0) {
          setError('No shorts found on this channel');
        } else if (videos.length === 1 && !res.data.has_more) {
          // Only 1 short — treat as single video
          const infoRes = await api.post('/download/info', { url: videos[0].url });
          setVideoInfo(infoRes.data);
        } else {
          setShorts(videos);
          setHasMore(res.data.has_more);
        }
      } else {
        // Single video
        const res = await api.post('/download/info', { url });
        setVideoInfo(res.data);
      }
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to fetch info');
    } finally {
      setLoading(false);
    }
  }

  async function handleLoadMore() {
    setLoadingMore(true);
    try {
      const res = await api.post('/download/batch/info', { url, limit: videoLimit, offset: shorts.length });
      const videos = res.data.videos || [];
      setShorts((prev) => [...prev, ...videos]);
      setHasMore(res.data.has_more);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to load more shorts');
    } finally {
      setLoadingMore(false);
    }
  }

  // ─── Single video progress (SSE) ───
  function connectToProgress(downloadId) {
    if (eventSourceRef.current) eventSourceRef.current.close();

    const es = new EventSource(`/api/download/progress/${downloadId}`);
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
          text: `Video '${data.title}' downloaded successfully`,
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
      const endpoint = type === 'audio' ? '/download/audio' : '/download/video';
      const res = await api.post(endpoint, { url, format, quality });
      activeDownloadId.current = res.data.download_id;
      connectToProgress(res.data.download_id);
    } catch (err) {
      setError(err.response?.data?.detail || 'Download failed');
      setDownloading(false);
      setProgress(null);
    }
  }

  async function handleStop() {
    const id = activeDownloadId.current;
    if (id) {
      try { await api.post(`/download/cancel/${id}`); } catch {}
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

  // ─── Batch progress (SSE) ───
  function connectToBatchProgress(batchId) {
    if (eventSourceRef.current) eventSourceRef.current.close();

    const es = new EventSource(`/api/download/batch/progress/${batchId}`);
    eventSourceRef.current = es;

    es.onmessage = (event) => {
      const data = JSON.parse(event.data);
      setBatchProgress(data);

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

  async function handleDownloadAll() {
    setBatchDownloading(true);
    setError('');
    setBatchProgress({ status: 'waiting', total: shorts.length, completed: 0 });

    try {
      const videoUrls = shorts.map((s) => s.url);
      const res = await api.post('/download/batch/download', {
        video_urls: videoUrls,
        format,
        quality,
      });
      activeDownloadId.current = res.data.batch_id;
      connectToBatchProgress(res.data.batch_id);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to start batch download');
      setBatchDownloading(false);
      setBatchProgress(null);
    }
  }

  const isBatchDone = batchProgress?.status === 'done';
  const failedCount = batchProgress?.failed?.length || 0;

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <div className="text-center mb-6 sm:mb-8">
        <h1 className="text-3xl sm:text-4xl font-bold mb-2">YouTube</h1>
        <p className="text-gray-400 text-sm sm:text-base">Download videos, audio, or batch download Shorts from any channel</p>
      </div>

      {/* URL Input */}
      <form onSubmit={handleGetInfo} className="flex flex-col sm:flex-row gap-2 sm:gap-3">
        <input
          type="text"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          required
          placeholder="https://www.youtube.com/watch?v=... or channel URL"
          className="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-4 py-3 text-white focus:outline-none focus:border-blue-500 transition text-sm sm:text-base"
        />
        <button
          type="submit"
          disabled={loading || downloading || batchDownloading}
          className="bg-blue-600 hover:bg-blue-700 disabled:bg-blue-800 text-white px-6 py-3 rounded-lg font-semibold transition whitespace-nowrap"
        >
          {loading ? 'Loading...' : 'Get Info'}
        </button>
      </form>

      {/* Download Location Picker */}
      <DownloadPathPicker />

      {/* Error */}
      {error && (
        <div className="bg-red-500/10 border border-red-500/50 text-red-400 px-4 py-3 rounded-lg text-sm">
          {error}
        </div>
      )}

      {/* ══════════ Single Video Flow ══════════ */}

      {/* Single video progress */}
      {progress && (
        <div className="bg-gray-900 rounded-xl border border-gray-800 p-4 space-y-3">
          <div className="flex items-center justify-between text-sm">
            <span className="text-gray-300 font-medium">
              {PHASE_LABELS[progress.phase] || progress.phase}
            </span>
            <span className="text-white font-semibold">{Math.round(progress.progress)}%</span>
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
                    : 'linear-gradient(90deg, #3b82f6, #6366f1)',
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

      {/* Success Message */}
      {message && (
        <div className="bg-green-500/10 border border-green-500/50 text-green-400 px-4 py-3 rounded-lg text-sm">
          {message.text}
        </div>
      )}

      {/* Video Info + Download Options */}
      {videoInfo && (
        <div className="space-y-4">
          <VideoCard info={videoInfo} isPremium={!!user?.is_premium} />

          <div className="bg-gray-900 rounded-xl p-4 sm:p-6 border border-gray-800 space-y-4">
            <h3 className="text-lg font-semibold">Download Options</h3>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 sm:gap-4">
              <div>
                <label className="block text-sm text-gray-400 mb-1">Format</label>
                <select
                  value={format}
                  onChange={(e) => setFormat(e.target.value)}
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:border-blue-500"
                >
                  <option value="mp4">MP4</option>
                  <option value="mkv">MKV</option>
                  <option value="webm">WebM</option>
                </select>
              </div>
              <div>
                <label className="block text-sm text-gray-400 mb-1">Quality</label>
                <select
                  value={quality}
                  onChange={(e) => setQuality(e.target.value)}
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:border-blue-500"
                >
                  <option value="360p">360p</option>
                  <option value="480p">480p</option>
                  <option value="720p">720p</option>
                  <option value="1080p">1080p</option>
                  <option value="best">Best</option>
                </select>
              </div>
            </div>

            <div className="flex flex-col sm:flex-row gap-2 sm:gap-3 pt-2">
              <button
                onClick={() => handleDownload('video')}
                disabled={downloading}
                className="flex-1 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-800 text-white py-3 rounded-lg font-semibold transition"
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
            </div>
          </div>
        </div>
      )}

      {/* ══════════ Batch Shorts Flow ══════════ */}

      {shorts.length > 0 && (
        <div className="space-y-4">
          <div className="flex items-center justify-between gap-2">
            <h2 className="text-base sm:text-lg font-semibold">
              Found {shorts.length} shorts{hasMore ? '+' : ''}
            </h2>
            <div className="flex items-center gap-2 text-sm shrink-0">
              <span className="text-gray-400 hidden sm:inline">Load per page:</span>
              <select
                value={videoLimit}
                onChange={(e) => setVideoLimit(Number(e.target.value))}
                className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-white text-sm"
              >
                <option value={30}>30</option>
                <option value={50}>50</option>
                <option value={100}>100</option>
              </select>
            </div>
          </div>

          {/* Scrollable grid */}
          <div className="bg-gray-900 rounded-xl border border-gray-800 p-4 max-h-96 overflow-y-auto">
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2 sm:gap-3">
              {shorts.map((s) => (
                <div key={s.video_id} className="group">
                  <div className="relative aspect-[9/16] rounded-lg overflow-hidden bg-gray-800">
                    {s.thumbnail ? (
                      <img
                        src={s.thumbnail}
                        alt={s.title}
                        loading="lazy"
                        className="w-full h-full object-cover"
                      />
                    ) : (
                      <div className="w-full h-full flex items-center justify-center text-gray-600 text-xs">
                        No thumbnail
                      </div>
                    )}
                    {s.duration && (
                      <span className="absolute bottom-1 right-1 bg-black/80 text-white text-xs px-1.5 py-0.5 rounded">
                        {s.duration}s
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-gray-400 mt-1 line-clamp-2">{s.title}</p>
                </div>
              ))}
            </div>
          </div>

          {hasMore && (
            <button
              onClick={handleLoadMore}
              disabled={loadingMore}
              className="w-full bg-gray-800 hover:bg-gray-700 disabled:bg-gray-800 border border-gray-700 text-white py-2.5 rounded-lg text-sm font-medium transition"
            >
              {loadingMore ? 'Loading more...' : `Load ${videoLimit} More Shorts`}
            </button>
          )}

          {/* Download Options */}
          <div className="bg-gray-900 rounded-xl p-4 sm:p-6 border border-gray-800 space-y-4">
            <h3 className="text-lg font-semibold">Download Options</h3>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 sm:gap-4">
              <div>
                <label className="block text-sm text-gray-400 mb-1">Format</label>
                <select
                  value={format}
                  onChange={(e) => setFormat(e.target.value)}
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:border-blue-500"
                >
                  <option value="mp4">MP4</option>
                  <option value="mkv">MKV</option>
                  <option value="webm">WebM</option>
                </select>
              </div>
              <div>
                <label className="block text-sm text-gray-400 mb-1">Quality</label>
                <select
                  value={quality}
                  onChange={(e) => setQuality(e.target.value)}
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:border-blue-500"
                >
                  <option value="360p">360p</option>
                  <option value="480p">480p</option>
                  <option value="720p">720p</option>
                  <option value="1080p">1080p</option>
                  <option value="best">Best</option>
                </select>
              </div>
            </div>

            <button
              onClick={handleDownloadAll}
              disabled={batchDownloading}
              className="w-full bg-blue-600 hover:bg-blue-700 disabled:bg-blue-800 text-white py-3 rounded-lg font-semibold transition"
            >
              {batchDownloading ? 'Downloading...' : `Download All ${shorts.length} Shorts`}
            </button>
          </div>
        </div>
      )}

      {/* Batch Progress */}
      {batchProgress && (
        <div className="bg-gray-900 rounded-xl border border-gray-800 p-4 space-y-3">
          <div className="flex items-center justify-between text-sm">
            <span className="text-gray-300 font-medium">
              {isBatchDone
                ? 'Batch complete'
                : batchProgress.current_title
                  ? `Downloading: ${batchProgress.current_title}`
                  : `Downloading ${batchProgress.completed + 1} of ${batchProgress.total}...`}
            </span>
            <span className="text-white font-semibold">
              {batchProgress.completed}/{batchProgress.total}
            </span>
          </div>

          {/* Overall progress bar */}
          <div className="w-full bg-gray-800 rounded-full h-3 overflow-hidden">
            <div
              className="h-full rounded-full transition-all duration-500 ease-out"
              style={{
                width: batchProgress.total > 0
                  ? `${(batchProgress.completed / batchProgress.total) * 100}%`
                  : '0%',
                background: isBatchDone
                  ? '#22c55e'
                  : 'linear-gradient(90deg, #3b82f6, #6366f1)',
              }}
            />
          </div>

          {/* Current video progress (sub-bar) */}
          {!isBatchDone && batchProgress.current_progress > 0 && (
            <div className="space-y-1">
              <div className="text-xs text-gray-500">
                Current video: {Math.round(batchProgress.current_progress)}%
              </div>
              <div className="w-full bg-gray-800 rounded-full h-1.5 overflow-hidden">
                <div
                  className="h-full rounded-full bg-blue-500/50 transition-all duration-300"
                  style={{ width: `${batchProgress.current_progress}%` }}
                />
              </div>
            </div>
          )}

          {/* Stop batch button */}
          {batchDownloading && (
            <button
              onClick={handleStop}
              className="w-full bg-red-600 hover:bg-red-700 text-white py-2 rounded-lg text-sm font-semibold transition"
            >
              Stop Batch Download
            </button>
          )}

          {/* Done message */}
          {isBatchDone && (
            <div className="text-sm">
              <span className="text-green-400">
                Successfully downloaded {batchProgress.completed - failedCount} of {batchProgress.total} shorts.
              </span>
            </div>
          )}

          {/* Failed list */}
          {failedCount > 0 && (
            <div className="text-sm">
              <span className="text-red-400">{failedCount} failed:</span>
              <ul className="mt-1 space-y-0.5">
                {batchProgress.failed.map((f, i) => (
                  <li key={i} className="text-xs text-red-300 truncate">
                    {f.url} — {f.error}
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
