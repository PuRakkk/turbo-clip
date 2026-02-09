import { Link } from 'react-router-dom';

const PLATFORMS = [
  {
    name: 'YouTube',
    status: 'available',
    route: '/',
    color: 'red',
    icon: (
      <svg className="w-8 h-8" viewBox="0 0 24 24" fill="currentColor">
        <path d="M23.498 6.186a3.016 3.016 0 00-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 00.502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 002.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 002.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z" />
      </svg>
    ),
    features: [
      'Download videos in MP4, MKV, or WebM format',
      'Extract audio as MP3',
      'Choose quality: 360p, 480p, 720p, 1080p, or Best',
      'Batch download all Shorts from a channel',
      'View and copy video tags',
      'Custom download folder',
      'Real-time download progress with speed and ETA',
      'Files saved with original video title',
    ],
  },
  {
    name: 'Instagram',
    status: 'coming_soon',
    color: 'pink',
    icon: (
      <svg className="w-8 h-8" viewBox="0 0 24 24" fill="currentColor">
        <path d="M12 2.163c3.204 0 3.584.012 4.85.07 3.252.148 4.771 1.691 4.919 4.919.058 1.265.069 1.645.069 4.849 0 3.205-.012 3.584-.069 4.849-.149 3.225-1.664 4.771-4.919 4.919-1.266.058-1.644.07-4.85.07-3.204 0-3.584-.012-4.849-.07-3.26-.149-4.771-1.699-4.919-4.92-.058-1.265-.07-1.644-.07-4.849 0-3.204.013-3.583.07-4.849.149-3.227 1.664-4.771 4.919-4.919 1.266-.057 1.645-.069 4.849-.069zM12 0C8.741 0 8.333.014 7.053.072 2.695.272.273 2.69.073 7.052.014 8.333 0 8.741 0 12c0 3.259.014 3.668.072 4.948.2 4.358 2.618 6.78 6.98 6.98C8.333 23.986 8.741 24 12 24c3.259 0 3.668-.014 4.948-.072 4.354-.2 6.782-2.618 6.979-6.98.059-1.28.073-1.689.073-4.948 0-3.259-.014-3.667-.072-4.947-.196-4.354-2.617-6.78-6.979-6.98C15.668.014 15.259 0 12 0zm0 5.838a6.162 6.162 0 100 12.324 6.162 6.162 0 000-12.324zM12 16a4 4 0 110-8 4 4 0 010 8zm6.406-11.845a1.44 1.44 0 100 2.881 1.44 1.44 0 000-2.881z" />
      </svg>
    ),
    features: [
      'Download Reels, Posts, and Stories',
      'Save photos and carousels',
      'Download profile pictures in full resolution',
      'Batch download from profiles',
    ],
  },
  {
    name: 'TikTok & Douyin',
    status: 'available',
    route: '/tiktok',
    color: 'cyan',
    icon: (
      <svg className="w-8 h-8" viewBox="0 0 24 24" fill="currentColor">
        <path d="M12.525.02c1.31-.02 2.61-.01 3.91-.02.08 1.53.63 3.09 1.75 4.17 1.12 1.11 2.7 1.62 4.24 1.79v4.03c-1.44-.05-2.89-.35-4.2-.97-.57-.26-1.1-.59-1.62-.93-.01 2.92.01 5.84-.02 8.75-.08 1.4-.54 2.79-1.35 3.94-1.31 1.92-3.58 3.17-5.91 3.21-1.43.08-2.86-.31-4.08-1.03-2.02-1.19-3.44-3.37-3.65-5.71-.02-.5-.03-1-.01-1.49.18-1.9 1.12-3.72 2.58-4.96 1.66-1.44 3.98-2.13 6.15-1.72.02 1.48-.04 2.96-.04 4.44-.99-.32-2.15-.23-3.02.37-.63.41-1.11 1.04-1.36 1.75-.21.51-.15 1.07-.14 1.61.24 1.64 1.82 3.02 3.5 2.87 1.12-.01 2.19-.66 2.77-1.61.19-.33.4-.67.41-1.06.1-1.79.06-3.57.07-5.36.01-4.03-.01-8.05.02-12.07z" />
      </svg>
    ),
    features: [
      'Download TikTok & Douyin videos in MP4',
      'Extract audio as MP3',
      'Download slideshow images',
      'Douyin support',
      'Paste share text directly — URL auto-extracted',
      'No-watermark Douyin downloads',
      'Batch download from TikTok profiles',
      'Real-time download progress',
    ],
  },
];

const STATUS_BADGE = {
  available: { label: 'Available', className: 'bg-green-500/20 text-green-400 border-green-500/30' },
  coming_soon: { label: 'Coming Soon', className: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30' },
};

const COLOR_MAP = {
  red: { border: 'border-red-500/30', bg: 'bg-red-500/10', text: 'text-red-400', dot: 'bg-red-400' },
  pink: { border: 'border-pink-500/30', bg: 'bg-pink-500/10', text: 'text-pink-400', dot: 'bg-pink-400' },
  cyan: { border: 'border-cyan-500/30', bg: 'bg-cyan-500/10', text: 'text-cyan-400', dot: 'bg-cyan-400' },
};

export default function FeaturesPage() {
  return (
    <div className="max-w-4xl mx-auto space-y-8">
      <div className="text-center mb-10">
        <h1 className="text-3xl sm:text-4xl font-bold mb-3">
          What's inside <span className="text-blue-500">TurboClip</span>
        </h1>
        <p className="text-gray-400 max-w-lg mx-auto">
          One subscription, multiple platforms. Download content from your favorite social media — all in one place.
        </p>
      </div>

      {/* Pricing highlight */}
      <div className="bg-gradient-to-r from-blue-600/20 to-purple-600/20 border border-blue-500/30 rounded-xl p-5 text-center">
        <p className="text-lg font-semibold text-white">
          All features included for <span className="text-blue-400">$5/month</span>
        </p>
        <p className="text-sm text-gray-400 mt-1">Unlimited downloads across all platforms</p>
        <Link
          to="/subscription"
          className="inline-block mt-3 bg-blue-600 hover:bg-blue-700 text-white px-6 py-2 rounded-lg text-sm font-semibold transition"
        >
          Subscribe Now
        </Link>
      </div>

      {/* Platform cards */}
      <div className="space-y-6">
        {PLATFORMS.map((platform) => {
          const colors = COLOR_MAP[platform.color];
          const badge = STATUS_BADGE[platform.status];

          return (
            <div
              key={platform.name}
              className={`bg-gray-900 rounded-xl border ${colors.border} overflow-hidden`}
            >
              {/* Header */}
              <div className={`${colors.bg} px-4 sm:px-6 py-4 flex items-center justify-between`}>
                <div className="flex items-center gap-3">
                  <span className={colors.text}>{platform.icon}</span>
                  <h2 className="text-xl font-bold text-white">{platform.name}</h2>
                </div>
                <span className={`text-xs font-medium px-2.5 py-1 rounded-full border ${badge.className}`}>
                  {badge.label}
                </span>
              </div>

              {/* Features */}
              <div className="px-4 sm:px-6 py-5">
                <ul className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                  {platform.features.map((feature) => (
                    <li key={feature} className="flex items-start gap-2 text-sm">
                      <span className={`w-1.5 h-1.5 rounded-full ${colors.dot} mt-1.5 shrink-0`} />
                      <span className="text-gray-300">{feature}</span>
                    </li>
                  ))}
                </ul>

                {platform.status === 'available' && platform.route && (
                  <Link
                    to={platform.route}
                    className={`inline-flex items-center gap-1.5 mt-4 text-sm font-medium ${colors.text} hover:underline`}
                  >
                    Go to {platform.name}
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                    </svg>
                  </Link>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
