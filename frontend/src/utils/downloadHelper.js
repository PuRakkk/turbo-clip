// ─── Feature Detection ───

export function supportsFileSystemAccess() {
  return typeof window.showDirectoryPicker === 'function';
}

export function isMobileDevice() {
  return /Android|iPhone|iPad|iPod|Opera Mini|IEMobile|WPDesktop/i.test(
    navigator.userAgent
  );
}

// ─── IndexedDB Handle Storage ───

const DB_NAME = 'TurboClipSettings';
const DB_VERSION = 1;
const STORE_NAME = 'handles';
const HANDLE_KEY = 'downloadDir';

function openDB() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME);
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

export async function saveDirectoryHandle(handle) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readwrite');
    tx.objectStore(STORE_NAME).put(handle, HANDLE_KEY);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

export async function loadDirectoryHandle() {
  try {
    const db = await openDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, 'readonly');
      const req = tx.objectStore(STORE_NAME).get(HANDLE_KEY);
      req.onsuccess = () => resolve(req.result || null);
      req.onerror = () => reject(req.error);
    });
  } catch {
    return null;
  }
}

export async function clearDirectoryHandle() {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readwrite');
    tx.objectStore(STORE_NAME).delete(HANDLE_KEY);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

export async function verifyHandlePermission(handle) {
  try {
    const opts = { mode: 'readwrite' };
    if ((await handle.queryPermission(opts)) === 'granted') return true;
    if ((await handle.requestPermission(opts)) === 'granted') return true;
    return false;
  } catch {
    return false;
  }
}

// ─── Smart Download ───

export async function smartDownload(downloadId, suggestedName) {
  if (supportsFileSystemAccess()) {
    const handle = await loadDirectoryHandle();
    if (handle) {
      try {
        const hasPermission = await verifyHandlePermission(handle);
        if (hasPermission) {
          await streamToDirectory(handle, downloadId, suggestedName);
          return { method: 'fs-api' };
        }
      } catch (err) {
        console.warn('File System Access download failed, falling back:', err);
      }
    }
  }

  triggerBrowserDownload(downloadId);
  return { method: 'browser' };
}

export function triggerBrowserDownload(downloadId) {
  const a = document.createElement('a');
  a.href = `/api/download/file/${downloadId}`;
  a.download = '';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

async function streamToDirectory(dirHandle, downloadId, suggestedName) {
  const response = await fetch(`/api/download/file/${downloadId}`);

  if (!response.ok) {
    throw new Error(`Server returned ${response.status}`);
  }

  const filename = parseFilenameFromResponse(response, suggestedName, downloadId);

  const fileHandle = await dirHandle.getFileHandle(filename, { create: true });
  const writable = await fileHandle.createWritable();

  // Stream directly to disk — no memory buffering for large files
  await response.body.pipeTo(writable);
}

function parseFilenameFromResponse(response, suggestedName, downloadId) {
  const disposition = response.headers.get('Content-Disposition');
  if (disposition) {
    const utf8Match = disposition.match(/filename\*=UTF-8''(.+)/i);
    if (utf8Match) return decodeURIComponent(utf8Match[1]);

    const match = disposition.match(/filename="?([^";\n]+)"?/i);
    if (match) return match[1].trim();
  }

  if (suggestedName) {
    // Sanitize and add extension from content-type
    const safe = suggestedName.replace(/[<>:"/\\|?*]/g, '').trim();
    const ct = response.headers.get('Content-Type') || '';
    const extMap = {
      'video/mp4': '.mp4',
      'video/webm': '.webm',
      'video/x-matroska': '.mkv',
      'audio/mpeg': '.mp3',
      'audio/mp4': '.m4a',
      'application/zip': '.zip',
      'image/jpeg': '.jpg',
      'image/png': '.png',
      'image/webp': '.webp',
    };
    const ext = extMap[ct] || '.mp4';
    if (safe && !safe.endsWith(ext)) return safe + ext;
    if (safe) return safe;
  }

  const ct = response.headers.get('Content-Type') || '';
  const extMap = {
    'video/mp4': '.mp4',
    'video/webm': '.webm',
    'video/x-matroska': '.mkv',
    'audio/mpeg': '.mp3',
    'audio/mp4': '.m4a',
    'application/zip': '.zip',
    'image/jpeg': '.jpg',
    'image/png': '.png',
    'image/webp': '.webp',
  };
  const ext = extMap[ct] || '.mp4';
  return `${downloadId}${ext}`;
}
