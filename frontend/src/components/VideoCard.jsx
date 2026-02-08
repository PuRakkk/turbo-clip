import { memo, useState } from 'react';

function formatDuration(seconds) {
  if (!seconds) return 'Unknown';
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, '0')}`;
}

export default memo(function VideoCard({ info, isPremium = false }) {
  const [imgError, setImgError] = useState(false);
  const [showTags, setShowTags] = useState(false);
  const [copied, setCopied] = useState(false);

  const tags = info.tags || [];

  return (
    <div className="bg-gray-800 rounded-xl overflow-hidden border border-gray-700">
      {info.thumbnail && !imgError && (
        <img
          src={info.thumbnail}
          alt={info.title}
          loading="lazy"
          className="w-full h-40 sm:h-48 object-cover"
          onError={() => setImgError(true)}
        />
      )}
      {(imgError || !info.thumbnail) && (
        <div className="w-full h-40 sm:h-48 bg-gray-700 flex items-center justify-center text-gray-500">
          No thumbnail
        </div>
      )}
      <div className="p-3 sm:p-4 space-y-2">
        <h3 className="text-base sm:text-lg font-semibold text-white line-clamp-2">{info.title}</h3>
        <div className="flex flex-wrap gap-2 sm:gap-3 text-xs sm:text-sm text-gray-400">
          {info.uploader && <span>By {info.uploader}</span>}
          {info.duration && <span>Duration: {formatDuration(info.duration)}</span>}
          {info.view_count && <span>Views: {info.view_count.toLocaleString()}</span>}
        </div>

        {tags.length > 0 && (
          <div>
            <button
              onClick={() => isPremium && setShowTags(!showTags)}
              className={`text-sm font-medium transition flex items-center gap-1 ${
                isPremium
                  ? 'text-blue-400 hover:text-blue-300 cursor-pointer'
                  : 'text-gray-500 cursor-not-allowed'
              }`}
            >
              <svg
                className={`w-3.5 h-3.5 transition-transform ${showTags ? 'rotate-90' : ''}`}
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
              </svg>
              {showTags ? 'Hide Tags' : `See Tags (${tags.length})`}
              {!isPremium && (
                <span className="ml-1 text-xs bg-yellow-500/20 text-yellow-400 border border-yellow-500/30 px-1.5 py-0.5 rounded">
                  Premium
                </span>
              )}
            </button>

            {showTags && isPremium && (
              <div className="mt-2 space-y-2">
                <div className="flex flex-wrap gap-1.5">
                  {tags.map((tag) => (
                    <span
                      key={tag}
                      className="bg-gray-700 text-gray-300 text-xs px-2 py-1 rounded-md"
                    >
                      {tag}
                    </span>
                  ))}
                </div>
                <button
                  onClick={() => {
                    navigator.clipboard.writeText(tags.join(', '));
                    setCopied(true);
                    setTimeout(() => setCopied(false), 2000);
                  }}
                  className="text-xs text-gray-400 hover:text-white transition flex items-center gap-1"
                >
                  {copied ? (
                    <>
                      <svg className="w-3.5 h-3.5 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                      </svg>
                      <span className="text-green-400">Copied!</span>
                    </>
                  ) : (
                    <>
                      <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                      </svg>
                      Copy all tags
                    </>
                  )}
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
});
