import { useState, useEffect } from 'react';
import {
  supportsFileSystemAccess,
  isMobileDevice,
  loadDirectoryHandle,
  saveDirectoryHandle,
  clearDirectoryHandle,
} from '../utils/downloadHelper';

export default function DownloadPathPicker() {
  const [hasHandle, setHasHandle] = useState(false);
  const [folderName, setFolderName] = useState('');
  const [fsSupported] = useState(() => supportsFileSystemAccess());
  const [mobile] = useState(() => isMobileDevice());

  useEffect(() => {
    if (fsSupported) {
      loadDirectoryHandle().then((handle) => {
        if (handle) {
          setHasHandle(true);
          setFolderName(handle.name || 'Custom folder');
        }
      });
    }
  }, [fsSupported]);

  async function handleChoose() {
    try {
      const handle = await window.showDirectoryPicker({ mode: 'readwrite' });
      await saveDirectoryHandle(handle);
      setHasHandle(true);
      setFolderName(handle.name || 'Custom folder');
    } catch (err) {
      if (err.name === 'AbortError') return;
      console.warn('Failed to pick folder:', err);
    }
  }

  async function handleClear() {
    await clearDirectoryHandle();
    setHasHandle(false);
    setFolderName('');
  }

  // PC with File System Access API support
  if (fsSupported && !mobile) {
    return (
      <div className="flex items-center gap-2 bg-gray-900 border border-gray-800 rounded-lg px-3 py-2.5">
        <svg className="w-4 h-4 text-gray-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
        </svg>

        {hasHandle ? (
          <>
            <span className="text-sm text-gray-300 truncate flex-1">
              Save to: <span className="text-white font-medium">{folderName}</span>
            </span>
            <button
              onClick={handleChoose}
              className="text-xs text-blue-400 hover:text-blue-300 font-medium shrink-0 transition"
            >
              Change
            </button>
            <span className="text-gray-600">|</span>
            <button
              onClick={handleClear}
              className="text-xs text-gray-400 hover:text-gray-300 font-medium shrink-0 transition"
            >
              Reset
            </button>
          </>
        ) : (
          <>
            <span className="text-sm text-gray-500 flex-1">Save to: Browser default</span>
            <button
              onClick={handleChoose}
              className="text-xs bg-blue-600 hover:bg-blue-700 text-white px-3 py-1 rounded font-medium shrink-0 transition"
            >
              Choose Folder
            </button>
          </>
        )}
      </div>
    );
  }

  // Mobile or unsupported browser — just show info
  return (
    <div className="flex items-center gap-2 bg-gray-900 border border-gray-800 rounded-lg px-3 py-2.5">
      <svg className="w-4 h-4 text-gray-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
          d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
      </svg>
      <span className="text-sm text-gray-500 flex-1">
        {mobile ? 'Save to: Your phone\'s Downloads' : 'Save to: Browser default folder'}
      </span>
      {mobile && (
        <span className="text-xs text-gray-600 shrink-0">Videos appear in Gallery</span>
      )}
    </div>
  );
}
