import { useState, useEffect } from 'react';
import { useAuth } from '../context/AuthContext';
import api from '../api/axios';
import {
  supportsFileSystemAccess,
  isMobileDevice,
  loadDirectoryHandle,
  saveDirectoryHandle,
  clearDirectoryHandle,
} from '../utils/downloadHelper';

export default function SettingsPage() {
  const { user, updateUser } = useAuth();
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  const [hasHandle, setHasHandle] = useState(false);
  const [displayPath, setDisplayPath] = useState(user?.download_path || '');
  const [fsApiSupported] = useState(() => supportsFileSystemAccess());
  const [mobile] = useState(() => isMobileDevice());

  // Cookie states
  const [instagramCookie, setInstagramCookie] = useState('');
  const [showInstagramCookie, setShowInstagramCookie] = useState(false);
  const [savingCookie, setSavingCookie] = useState(false);


  useEffect(() => {
    if (fsApiSupported) {
      loadDirectoryHandle().then((handle) => {
        if (handle) setHasHandle(true);
      });
    }
  }, [fsApiSupported]);

  async function handleChooseFolder() {
    setError('');
    setMessage('');
    try {
      const handle = await window.showDirectoryPicker({ mode: 'readwrite' });

      await saveDirectoryHandle(handle);
      setHasHandle(true);

      const folderName = handle.name;
      setDisplayPath(folderName);

      setSaving(true);
      const res = await api.put('/user/settings', { download_path: folderName });
      updateUser(res.data);
      setMessage(`Download folder set to "${folderName}"`);
    } catch (err) {
      if (err.name === 'AbortError') return;
      setError('Failed to set download folder: ' + (err.message || 'Unknown error'));
    } finally {
      setSaving(false);
    }
  }

  async function handleClearFolder() {
    setError('');
    setMessage('');
    try {
      await clearDirectoryHandle();
      setHasHandle(false);
      setDisplayPath('');

      setSaving(true);
      const res = await api.put('/user/settings', { download_path: null });
      updateUser(res.data);
      setMessage('Download folder reset to browser default');
    } catch (err) {
      setError('Failed to reset: ' + (err.message || 'Unknown error'));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="max-w-lg mx-auto space-y-6">
      <div className="text-center mb-6 sm:mb-8">
        <h1 className="text-3xl sm:text-4xl font-bold mb-2">Settings</h1>
        <p className="text-gray-400 text-sm sm:text-base">
          Customize your TurboClip experience
        </p>
      </div>

      {/* Download Location */}
      <div className="bg-gray-900 rounded-xl p-5 sm:p-6 border border-gray-800 space-y-4">
        <h2 className="text-lg font-semibold flex items-center gap-2">
          <svg className="w-5 h-5 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
          </svg>
          Download Location
        </h2>

        {/* Chromium Desktop — full support */}
        {fsApiSupported && !mobile && (
          <div className="space-y-3">
            {hasHandle ? (
              <>
                <div className="flex items-center gap-3 bg-gray-800 rounded-lg px-4 py-3">
                  <svg className="w-5 h-5 text-green-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                      d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  <span className="text-sm text-gray-300 truncate">
                    Saving to: <span className="text-white font-medium">{displayPath || 'Custom folder'}</span>
                  </span>
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={handleChooseFolder}
                    disabled={saving}
                    className="flex-1 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-800 text-white py-2.5 rounded-lg text-sm font-semibold transition"
                  >
                    Change Folder
                  </button>
                  <button
                    onClick={handleClearFolder}
                    disabled={saving}
                    className="bg-gray-700 hover:bg-gray-600 disabled:bg-gray-800 text-white px-4 py-2.5 rounded-lg text-sm transition"
                  >
                    Reset
                  </button>
                </div>
              </>
            ) : (
              <>
                <p className="text-sm text-gray-400">
                  Choose a folder where downloaded videos will be saved directly.
                  Your browser will ask for permission to write to the folder.
                </p>
                <button
                  onClick={handleChooseFolder}
                  disabled={saving}
                  className="w-full bg-blue-600 hover:bg-blue-700 disabled:bg-blue-800 text-white py-3 rounded-lg font-semibold transition"
                >
                  {saving ? 'Saving...' : 'Choose Download Folder'}
                </button>
                <p className="text-xs text-gray-500">
                  Currently using browser default download location.
                </p>
              </>
            )}
          </div>
        )}

        {/* Firefox / Safari Desktop — no API support */}
        {!fsApiSupported && !mobile && (
          <div className="space-y-3">
            <div className="bg-gray-800 rounded-lg px-4 py-3">
              <p className="text-sm text-gray-300">
                Your browser does not support custom download folders from web apps.
              </p>
              <p className="text-sm text-gray-400 mt-2">
                To change where files are saved, update your download folder in your
                browser's settings (usually under Settings &gt; Downloads).
              </p>
            </div>
            <div className="text-xs text-gray-500">
              Tip: Chrome and Edge support choosing a custom folder directly from this page.
            </div>
          </div>
        )}

        {/* Mobile */}
        {mobile && (
          <div className="space-y-3">
            <div className="bg-gray-800 rounded-lg px-4 py-3">
              <p className="text-sm text-gray-300">
                Downloaded files are saved directly to your phone's Downloads folder.
                Videos will also appear in your Gallery / Photos app.
              </p>
              <p className="text-sm text-gray-400 mt-2">
                This is managed by your mobile browser and saves to your device, not to a server.
              </p>
            </div>
          </div>
        )}
      </div>

      {/* Instagram Cookie */}
      <div className="bg-gray-900 rounded-xl p-5 sm:p-6 border border-gray-800 space-y-4">
        <h2 className="text-lg font-semibold flex items-center gap-2">
          <svg className="w-5 h-5 text-pink-400" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 2.163c3.204 0 3.584.012 4.85.07 3.252.148 4.771 1.691 4.919 4.919.058 1.265.069 1.645.069 4.849 0 3.205-.012 3.584-.069 4.849-.149 3.225-1.664 4.771-4.919 4.919-1.266.058-1.644.07-4.85.07-3.204 0-3.584-.012-4.849-.07-3.26-.149-4.771-1.699-4.919-4.92-.058-1.265-.07-1.644-.07-4.849 0-3.204.013-3.583.07-4.849.149-3.227 1.664-4.771 4.919-4.919 1.266-.057 1.645-.069 4.849-.069zM12 0C8.741 0 8.333.014 7.053.072 2.695.272.273 2.69.073 7.052.014 8.333 0 8.741 0 12c0 3.259.014 3.668.072 4.948.2 4.358 2.618 6.78 6.98 6.98C8.333 23.986 8.741 24 12 24c3.259 0 3.668-.014 4.948-.072 4.354-.2 6.782-2.618 6.979-6.98.059-1.28.073-1.689.073-4.948 0-3.259-.014-3.667-.072-4.947-.196-4.354-2.617-6.78-6.979-6.98C15.668.014 15.259 0 12 0zm0 5.838a6.162 6.162 0 100 12.324 6.162 6.162 0 000-12.324zM12 16a4 4 0 110-8 4 4 0 010 8zm6.406-11.845a1.44 1.44 0 100 2.881 1.44 1.44 0 000-2.881z" />
          </svg>
          Instagram Cookie
          {user?.has_instagram_cookie && (
            <span className="text-xs bg-green-500/20 text-green-400 border border-green-500/30 px-2 py-0.5 rounded-full">
              Active
            </span>
          )}
        </h2>
        <p className="text-sm text-gray-400">
          Some Instagram content may require authentication. Paste your Instagram cookie to access private or restricted content.
        </p>

        {!showInstagramCookie ? (
          <button
            onClick={() => setShowInstagramCookie(true)}
            className="w-full bg-gray-800 hover:bg-gray-700 border border-gray-700 text-white py-2.5 rounded-lg text-sm font-medium transition"
          >
            {user?.has_instagram_cookie ? 'Update Cookie' : 'Add Cookie'}
          </button>
        ) : (
          <div className="space-y-3">
            <textarea
              value={instagramCookie}
              onChange={(e) => setInstagramCookie(e.target.value)}
              placeholder="Paste your Instagram cookie string here..."
              rows={3}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-4 py-3 text-white text-sm focus:outline-none focus:border-pink-500 transition resize-none"
            />
            <div className="flex gap-2">
              <button
                onClick={async () => {
                  setSavingCookie(true);
                  setError('');
                  setMessage('');
                  try {
                    const res = await api.put('/user/settings', { instagram_cookie: instagramCookie });
                    updateUser(res.data);
                    setInstagramCookie('');
                    setShowInstagramCookie(false);
                    setMessage(instagramCookie.trim() ? 'Instagram cookie saved' : 'Instagram cookie cleared');
                  } catch (err) {
                    setError('Failed to save cookie: ' + (err.response?.data?.detail || err.message));
                  } finally {
                    setSavingCookie(false);
                  }
                }}
                disabled={savingCookie}
                className="flex-1 bg-pink-600 hover:bg-pink-700 disabled:bg-pink-800 text-white py-2.5 rounded-lg text-sm font-semibold transition"
              >
                {savingCookie ? 'Saving...' : 'Save Cookie'}
              </button>
              {user?.has_instagram_cookie && (
                <button
                  onClick={async () => {
                    setSavingCookie(true);
                    setError('');
                    setMessage('');
                    try {
                      const res = await api.put('/user/settings', { instagram_cookie: '' });
                      updateUser(res.data);
                      setInstagramCookie('');
                      setShowInstagramCookie(false);
                      setMessage('Instagram cookie cleared');
                    } catch (err) {
                      setError('Failed to clear cookie');
                    } finally {
                      setSavingCookie(false);
                    }
                  }}
                  disabled={savingCookie}
                  className="bg-red-600/20 hover:bg-red-600/30 text-red-400 px-4 py-2.5 rounded-lg text-sm transition"
                >
                  Clear
                </button>
              )}
              <button
                onClick={() => { setShowInstagramCookie(false); setInstagramCookie(''); }}
                className="bg-gray-700 hover:bg-gray-600 text-white px-4 py-2.5 rounded-lg text-sm transition"
              >
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Account Info */}
      <div className="bg-gray-900 rounded-xl p-5 sm:p-6 border border-gray-800 space-y-3">
        <h2 className="text-lg font-semibold">Account</h2>
        <div className="space-y-2 text-sm">
          <div className="flex justify-between">
            <span className="text-gray-400">Username</span>
            <span className="text-white">{user?.username}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-400">Email</span>
            <span className="text-white">{user?.email}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-400">Plan</span>
            <span className={user?.is_premium ? 'text-green-400' : 'text-gray-400'}>
              {user?.is_premium ? 'Premium' : 'Free'}
            </span>
          </div>
        </div>
      </div>

      {/* Messages */}
      {message && (
        <div className="bg-green-500/10 border border-green-500/50 text-green-400 px-4 py-3 rounded-lg text-sm">
          {message}
        </div>
      )}
      {error && (
        <div className="bg-red-500/10 border border-red-500/50 text-red-400 px-4 py-3 rounded-lg text-sm">
          {error}
        </div>
      )}
    </div>
  );
}
