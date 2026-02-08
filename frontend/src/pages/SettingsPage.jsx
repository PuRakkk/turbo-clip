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
