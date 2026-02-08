import { memo, useState } from 'react';

export default memo(function SlideshowCard({ info, isPremium = false }) {
  const [activeIndex, setActiveIndex] = useState(0);
  const [showTags, setShowTags] = useState(false);
  const [copied, setCopied] = useState(false);

  const images = info.image_urls || [];
  const tags = info.tags || [];

  return (
    <div className="bg-gray-800 rounded-xl overflow-hidden border border-gray-700">
      {/* Image carousel */}
      <div className="relative bg-black">
        <div className="w-full h-56 sm:h-72 flex items-center justify-center">
          {images.length > 0 ? (
            <img
              src={images[activeIndex]}
              alt={`Slide ${activeIndex + 1}`}
              className="max-w-full max-h-full object-contain"
            />
          ) : (
            <div className="text-gray-500">No images available</div>
          )}
        </div>

        {/* Image count badge */}
        <span className="absolute top-2 right-2 bg-black/70 text-white text-xs px-2.5 py-1 rounded-full flex items-center gap-1">
          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
          </svg>
          {images.length} images
        </span>

        {/* Left arrow */}
        {activeIndex > 0 && (
          <button
            onClick={() => setActiveIndex((i) => i - 1)}
            className="absolute left-2 top-1/2 -translate-y-1/2 bg-black/50 hover:bg-black/70 text-white rounded-full w-8 h-8 flex items-center justify-center transition"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          </button>
        )}

        {/* Right arrow */}
        {activeIndex < images.length - 1 && (
          <button
            onClick={() => setActiveIndex((i) => i + 1)}
            className="absolute right-2 top-1/2 -translate-y-1/2 bg-black/50 hover:bg-black/70 text-white rounded-full w-8 h-8 flex items-center justify-center transition"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
          </button>
        )}

        {/* Dot indicators */}
        {images.length > 1 && (
          <div className="absolute bottom-2 left-0 right-0 flex justify-center gap-1.5">
            {images.map((_, i) => (
              <button
                key={i}
                onClick={() => setActiveIndex(i)}
                className={`w-2 h-2 rounded-full transition ${
                  i === activeIndex ? 'bg-cyan-400 scale-125' : 'bg-white/40 hover:bg-white/60'
                }`}
              />
            ))}
          </div>
        )}
      </div>

      {/* Metadata */}
      <div className="p-3 sm:p-4 space-y-2">
        <h3 className="text-base sm:text-lg font-semibold text-white line-clamp-2">{info.title}</h3>
        <div className="flex flex-wrap gap-2 sm:gap-3 text-xs sm:text-sm text-gray-400">
          {info.uploader && <span>By {info.uploader}</span>}
          <span>{images.length} slides</span>
          {info.view_count && <span>Views: {info.view_count.toLocaleString()}</span>}
        </div>

        {/* Tags (premium-gated, same as VideoCard) */}
        {tags.length > 0 && (
          <div>
            <button
              onClick={() => isPremium && setShowTags(!showTags)}
              className={`text-sm font-medium transition flex items-center gap-1 ${
                isPremium
                  ? 'text-cyan-400 hover:text-cyan-300 cursor-pointer'
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
