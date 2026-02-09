import { useState, useEffect } from 'react';
import api from '../api/axios';

export default function HistoryPage() {
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [copiedId, setCopiedId] = useState(null);

  useEffect(() => {
    fetchHistory();
  }, []);

  async function fetchHistory() {
    try {
      const res = await api.get('/user/history');
      setHistory(res.data);
    } catch (err) {
      setError('Failed to load download history');
    } finally {
      setLoading(false);
    }
  }

  async function handleDelete(id) {
    try {
      await api.delete(`/user/history/${id}`);
      setHistory(history.filter((item) => item.id !== id));
    } catch {
      setError('Failed to delete item');
    }
  }

  async function handleDownload(item) {
    setError('');
    try {
      const res = await api.get(`/download/file/${item.id}`, { responseType: 'blob' });
      const disposition = res.headers['content-disposition'] || '';
      const match = disposition.match(/filename="?(.+?)"?$/);
      const filename = match ? match[1] : `download_${item.id}`;
      const blobUrl = URL.createObjectURL(res.data);
      const a = document.createElement('a');
      a.href = blobUrl;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(blobUrl);
    } catch {
      // File no longer on server — copy URL so user can re-download
      if (item.video_url && item.video_url !== 'slideshow_image') {
        handleCopyUrl(item);
        setError('File no longer on server. URL copied — paste it on the download page.');
      } else {
        setError('File no longer available.');
      }
    }
  }

  function handleCopyUrl(item) {
    if (!item.video_url || item.video_url === 'slideshow_image') return;
    navigator.clipboard.writeText(item.video_url).then(() => {
      setCopiedId(item.id);
      setTimeout(() => setCopiedId(null), 2000);
    });
  }

  function formatDate(dateStr) {
    return new Date(dateStr).toLocaleDateString('en-US', {
      year: 'numeric', month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit',
    });
  }

  function formatSize(bytes) {
    if (!bytes) return '-';
    const mb = bytes / (1024 * 1024);
    return `${mb.toFixed(1)} MB`;
  }

  if (loading) {
    return <div className="text-center text-gray-400 py-20">Loading history...</div>;
  }

  return (
    <div className="max-w-4xl mx-auto">
      <h1 className="text-2xl sm:text-3xl font-bold mb-6">Download History</h1>

      {error && (
        <div className="bg-red-500/10 border border-red-500/50 text-red-400 px-4 py-3 rounded-lg mb-6 text-sm">
          {error}
        </div>
      )}

      {history.length === 0 ? (
        <div className="text-center text-gray-500 py-20 bg-gray-900 rounded-xl border border-gray-800">
          <p className="text-lg">No downloads yet</p>
          <p className="text-sm mt-1">Your download history will appear here</p>
        </div>
      ) : (
        <>
          {/* Desktop table */}
          <div className="hidden sm:block bg-gray-900 rounded-xl border border-gray-800 overflow-hidden">
            <table className="w-full">
              <thead>
                <tr className="border-b border-gray-800 text-left text-sm text-gray-400">
                  <th className="px-4 py-3">Title</th>
                  <th className="px-4 py-3">Format</th>
                  <th className="px-4 py-3">Size</th>
                  <th className="px-4 py-3">Date</th>
                  <th className="px-4 py-3"></th>
                </tr>
              </thead>
              <tbody>
                {history.map((item) => (
                  <tr key={item.id} className="border-b border-gray-800/50 hover:bg-gray-800/50 transition">
                    <td className="px-4 py-3 text-sm max-w-xs truncate">{item.video_title}</td>
                    <td className="px-4 py-3 text-sm text-gray-400 uppercase">{item.format}</td>
                    <td className="px-4 py-3 text-sm text-gray-400">{formatSize(item.file_size)}</td>
                    <td className="px-4 py-3 text-sm text-gray-400">{formatDate(item.downloaded_at)}</td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-3">
                        <button
                          onClick={() => handleDownload(item)}
                          className="text-blue-400 hover:text-blue-300 text-sm transition"
                        >
                          Download
                        </button>
                        {item.video_url && item.video_url !== 'slideshow_image' && (
                          <button
                            onClick={() => handleCopyUrl(item)}
                            className="text-gray-400 hover:text-gray-300 text-sm transition"
                          >
                            {copiedId === item.id ? 'Copied!' : 'Copy URL'}
                          </button>
                        )}
                        <button
                          onClick={() => handleDelete(item.id)}
                          className="text-red-400 hover:text-red-300 text-sm transition"
                        >
                          Delete
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Mobile cards */}
          <div className="sm:hidden space-y-3">
            {history.map((item) => (
              <div key={item.id} className="bg-gray-900 rounded-xl border border-gray-800 p-4 space-y-2">
                <h3 className="text-sm font-medium text-white line-clamp-2">{item.video_title}</h3>
                <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-gray-400">
                  <span className="uppercase">{item.format}</span>
                  <span>{formatSize(item.file_size)}</span>
                  <span>{formatDate(item.downloaded_at)}</span>
                </div>
                <div className="flex items-center gap-3 pt-1">
                  <button
                    onClick={() => handleDownload(item)}
                    className="text-blue-400 hover:text-blue-300 text-xs font-medium transition"
                  >
                    Download
                  </button>
                  {item.video_url && item.video_url !== 'slideshow_image' && (
                    <button
                      onClick={() => handleCopyUrl(item)}
                      className="text-gray-400 hover:text-gray-300 text-xs transition"
                    >
                      {copiedId === item.id ? 'Copied!' : 'Copy URL'}
                    </button>
                  )}
                  <button
                    onClick={() => handleDelete(item.id)}
                    className="text-red-400 hover:text-red-300 text-xs transition"
                  >
                    Delete
                  </button>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
