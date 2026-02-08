import { useState, useEffect } from 'react';
import api from '../api/axios';

const FEATURES = [
  'Unlimited downloads',
  'Best quality available',
  'All video formats',
  'Audio downloads (MP3)',
  'Priority processing',
];

export default function SubscriptionPage() {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get('/user/me')
      .then((res) => setUser(res.data))
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, []);

  const isPremium = user?.is_premium || false;

  if (loading) {
    return <div className="text-center text-gray-400 py-20">Loading...</div>;
  }

  return (
    <div className="max-w-md mx-auto">
      <h1 className="text-3xl font-bold mb-2 text-center">Subscription</h1>
      <p className="text-gray-400 mb-8 text-center">
        {isPremium
          ? 'You have full access to TurboClip.'
          : 'Upgrade to unlock all features.'}
      </p>

      <div
        className={`rounded-xl p-5 sm:p-8 border transition ${
          isPremium
            ? 'bg-green-600/10 border-green-500'
            : 'bg-gray-900 border-gray-800'
        }`}
      >
        <div className="text-center mb-6">
          <span className="inline-block bg-blue-600 text-white text-xs font-bold px-3 py-1 rounded-full mb-3 uppercase tracking-wider">
            Premium
          </span>
          <p className="text-4xl font-bold">
            $5<span className="text-base text-gray-400 font-normal">/month</span>
          </p>
          <p className="text-gray-400 text-sm mt-1">No limits. Download anything.</p>
        </div>

        <ul className="space-y-3 mb-8">
          {FEATURES.map((feature) => (
            <li key={feature} className="flex items-center gap-3 text-sm text-gray-300">
              <svg className="w-5 h-5 text-green-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
              {feature}
            </li>
          ))}
        </ul>

        {isPremium ? (
          <div className="text-center">
            <div className="inline-flex items-center gap-2 text-green-400 font-semibold text-sm py-2">
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              Active — You're all set!
            </div>
          </div>
        ) : (
          <div className="text-center space-y-3">
            <p className="text-gray-400 text-sm">
              Contact us to subscribe and get instant access.
            </p>
            <a
              href="https://t.me/Sarak_chon"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-block w-full bg-blue-600 hover:bg-blue-500 text-white py-3 rounded-lg text-sm font-semibold transition"
            >
              Contact Us to Subscribe
            </a>
          </div>
        )}
      </div>
    </div>
  );
}
