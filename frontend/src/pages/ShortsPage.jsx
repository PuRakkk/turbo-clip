import { useState, useEffect, useRef } from 'react';
import api from '../api/axios';
import FolderPicker from '../components/FolderPicker';

export default function ShortsPage() {
  const [url, setUrl] = useState('');
  const [shorts, setShorts] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [format, setFormat] = useState('mp4');
  const [quality, setQuality] = useState('720p');

  // Batch download state
  const [downloading, setDownloading] = useState(false);
  const [batchProgress, setBatchProgress] = useState(null);
  const eventSourceRef = useRef(null);

  // Download path
  const [savedPath, setSavedPath] = useState('');
  const [showFolderPicker, setShowFolderPicker] = useState(false);

  useEffect(() => {
    api.get('/user/settings')
      .then((res) => setSavedPath(res.data.download_path || ''))
      .catch(() => {});
    return () => {
      if (eventSourceRef.current) eventSourceRef.current.close();
    };
  }, []);

  async function handleLoadShorts(e) {
    e.preventDefault();
    setError('');
    setShorts([]);
    setBatchProgress(null);
    setLoading(true);

    try {
      const res = await api.post('/download/batch/info', { url });
      setShorts(res.data.videos || []);
      if (res.data.count === 0) {
        setError('No shorts found on this channel');
      }
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to load shorts');
    } finally {
      setLoading(false);
    }
  }

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
        setDownloading(false);
      }
    };

    es.onerror = () => {
      es.close();
      eventSourceRef.current = null;
      setDownloading(false);
      setError('Lost connection to batch progress');
    };
  }

  async function handleDownloadAll() {
    setDownloading(true);
    setError('');
    setBatchProgress({ status: 'waiting', total: shorts.length, completed: 0 });

    try {
      const videoUrls = shorts.map((s) => s.url);
      const res = await api.post('/download/batch/download', {
        video_urls: videoUrls,
        format,
        quality,
      });
      connectToBatchProgress(res.data.batch_id);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to start batch download');
      setDownloading(false);
      setBatchProgress(null);
    }
  }

  const isDone = batchProgress?.status === 'done';
  const failedCount = batchProgress?.failed?.length || 0;

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <div className="text-center mb-8">
        <h1 className="text-4xl font-bold mb-2">Batch Shorts</h1>
        <p className="text-gray-400">Download all shorts from a YouTube channel at once</p>
      </div>

      {/* Download Path */}
      <div className="bg-gray-900 rounded-xl border border-gray-800 px-4 py-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-sm min-w-0">
            <svg className="w-4 h-4 text-yellow-500 shrink-0" fill="currentColor" viewBox="0 0 24 24">
              <path d="M10 4H4a2 2 0 00-2 2v12a2 2 0 002 2h16a2 2 0 002-2V8a2 2 0 00-2-2h-8l-2-2z" />
            </svg>
            {savedPath ? (
              <span className="text-gray-300 truncate" title={savedPath}>
                Save to: <span className="text-white font-medium">{savedPath}</span>
              </span>
            ) : (
              <span className="text-gray-500">Save to: Default server directory</span>
            )}
          </div>
          <button
            onClick={() => setShowFolderPicker(true)}
            className="bg-gray-800 hover:bg-gray-700 border border-gray-700 text-white px-3 py-1.5 rounded-lg text-sm transition shrink-0 ml-3"
          >
            Browse
          </button>
        </div>
      </div>

      {showFolderPicker && (
        <FolderPicker
          onSelect={(path) => { setSavedPath(path); setShowFolderPicker(false); }}
          onClose={() => setShowFolderPicker(false)}
        />
      )}

      {/* URL Input */}
      <form onSubmit={handleLoadShorts} className="flex gap-3">
        <input
          type="text"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          required
          placeholder="https://www.youtube.com/@channel/shorts"
          className="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-4 py-3 text-white focus:outline-none focus:border-blue-500 transition"
        />
        <button
          type="submit"
          disabled={loading}
          className="bg-blue-600 hover:bg-blue-700 disabled:bg-blue-800 text-white px-6 py-3 rounded-lg font-semibold transition whitespace-nowrap"
        >
          {loading ? 'Loading...' : 'Load Shorts'}
        </button>
      </form>

      {error && (
        <div className="bg-red-500/10 border border-red-500/50 text-red-400 px-4 py-3 rounded-lg text-sm">
          {error}
        </div>
      )}

      {/* Shorts List */}
      {shorts.length > 0 && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold">
              Found {shorts.length} shorts
            </h2>
          </div>

          {/* Scrollable grid */}
          <div className="bg-gray-900 rounded-xl border border-gray-800 p-4 max-h-80 overflow-y-auto">
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
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

          {/* Download Options */}
          <div className="bg-gray-900 rounded-xl p-6 border border-gray-800 space-y-4">
            <h3 className="text-lg font-semibold">Download Options</h3>

            <div className="grid grid-cols-2 gap-4">
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
              disabled={downloading}
              className="w-full bg-blue-600 hover:bg-blue-700 disabled:bg-blue-800 text-white py-3 rounded-lg font-semibold transition"
            >
              {downloading ? 'Downloading...' : `Download All ${shorts.length} Shorts`}
            </button>
          </div>
        </div>
      )}

      {/* Batch Progress */}
      {batchProgress && (
        <div className="bg-gray-900 rounded-xl border border-gray-800 p-4 space-y-3">
          <div className="flex items-center justify-between text-sm">
            <span className="text-gray-300 font-medium">
              {isDone
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
                background: isDone
                  ? '#22c55e'
                  : 'linear-gradient(90deg, #3b82f6, #6366f1)',
              }}
            />
          </div>

          {/* Current video progress (sub-bar) */}
          {!isDone && batchProgress.current_progress > 0 && (
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

          {/* Done message */}
          {isDone && (
            <div className="text-sm">
              <span className="text-green-400">
                Successfully downloaded {batchProgress.completed - failedCount} of {batchProgress.total} shorts.
              </span>
              {savedPath && (
                <p className="text-xs text-green-300 mt-1">Saved to: {savedPath}</p>
              )}
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
