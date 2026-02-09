import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useState, useRef, useEffect } from 'react';

const DOWNLOAD_LINKS = [
  { to: '/', label: 'YouTube' },
  { to: '/tiktok', label: 'TikTok' },
];

export default function Navbar() {
  const { isAuthenticated, user, logout } = useAuth();
  const navigate = useNavigate();
  const [menuOpen, setMenuOpen] = useState(false);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [mobileDownloadsOpen, setMobileDownloadsOpen] = useState(false);
  const dropdownRef = useRef(null);

  function handleLogout() {
    logout();
    navigate('/login');
  }

  // Close desktop dropdown on outside click
  useEffect(() => {
    function handleClickOutside(e) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target)) {
        setDropdownOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  return (
    <nav className="bg-gray-900 border-b border-gray-800">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          {/* Logo */}
          <Link to="/" className="flex items-center gap-2">
            <span className="text-xl sm:text-2xl font-bold text-white">Turbo<span className="text-blue-500">Clip</span></span>
          </Link>

          {/* Desktop Nav */}
          <div className="hidden md:flex items-center gap-6">
            {isAuthenticated ? (
              <>
                {/* Downloads dropdown */}
                <div className="relative" ref={dropdownRef}>
                  <button
                    onClick={() => setDropdownOpen(!dropdownOpen)}
                    className="flex items-center gap-1 text-gray-300 hover:text-white transition"
                  >
                    Downloads
                    <svg className={`w-4 h-4 transition-transform ${dropdownOpen ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                    </svg>
                  </button>
                  {dropdownOpen && (
                    <div className="absolute top-full left-0 mt-2 w-44 bg-gray-800 border border-gray-700 rounded-lg shadow-xl py-1 z-50">
                      {DOWNLOAD_LINKS.map((item) => (
                        <Link
                          key={item.to}
                          to={item.to}
                          onClick={() => setDropdownOpen(false)}
                          className="block px-4 py-2 text-sm text-gray-300 hover:bg-gray-700 hover:text-white transition"
                        >
                          {item.label}
                        </Link>
                      ))}
                    </div>
                  )}
                </div>
                <Link to="/features" className="text-gray-300 hover:text-white transition">Features</Link>
                <Link to="/subscription" className="text-gray-300 hover:text-white transition">Subscription</Link>
                <Link to="/settings" className="text-gray-300 hover:text-white transition">Settings</Link>
                {user?.is_admin && (
                  <Link to="/admin" className="text-yellow-400 hover:text-yellow-300 transition">Admin</Link>
                )}
                <span className="text-gray-400 text-sm">Hi, {user?.username}</span>
                <button
                  onClick={handleLogout}
                  className="bg-red-600 hover:bg-red-700 text-white px-4 py-2 rounded-lg text-sm transition"
                >
                  Logout
                </button>
              </>
            ) : (
              <>
                <Link to="/features" className="text-gray-300 hover:text-white transition">Features</Link>
                <Link to="/login" className="text-gray-300 hover:text-white transition">Login</Link>
                <Link
                  to="/register"
                  className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg text-sm transition"
                >
                  Register
                </Link>
              </>
            )}
          </div>

          {/* Mobile menu button */}
          <button
            onClick={() => setMenuOpen(!menuOpen)}
            className="md:hidden text-gray-300 hover:text-white"
          >
            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              {menuOpen ? (
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              ) : (
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
              )}
            </svg>
          </button>
        </div>

        {/* Mobile Nav */}
        {menuOpen && (
          <div className="md:hidden pb-4 space-y-2">
            {isAuthenticated ? (
              <>
                {/* Mobile Downloads section */}
                <button
                  onClick={() => setMobileDownloadsOpen(!mobileDownloadsOpen)}
                  className="flex items-center justify-between w-full text-gray-300 hover:text-white py-2"
                >
                  Downloads
                  <svg className={`w-4 h-4 transition-transform ${mobileDownloadsOpen ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                  </svg>
                </button>
                {mobileDownloadsOpen && (
                  <div className="pl-4 space-y-1">
                    {DOWNLOAD_LINKS.map((item) => (
                      <Link
                        key={item.to}
                        to={item.to}
                        onClick={() => { setMenuOpen(false); setMobileDownloadsOpen(false); }}
                        className="block text-gray-400 hover:text-white py-1.5 text-sm"
                      >
                        {item.label}
                      </Link>
                    ))}
                  </div>
                )}
                <Link to="/features" onClick={() => setMenuOpen(false)} className="block text-gray-300 hover:text-white py-2">Features</Link>
                <Link to="/subscription" onClick={() => setMenuOpen(false)} className="block text-gray-300 hover:text-white py-2">Subscription</Link>
                <Link to="/settings" onClick={() => setMenuOpen(false)} className="block text-gray-300 hover:text-white py-2">Settings</Link>
                {user?.is_admin && (
                  <Link to="/admin" onClick={() => setMenuOpen(false)} className="block text-yellow-400 hover:text-yellow-300 py-2">Admin</Link>
                )}
                <button onClick={handleLogout} className="block text-red-400 hover:text-red-300 py-2">Logout</button>
              </>
            ) : (
              <>
                <Link to="/features" onClick={() => setMenuOpen(false)} className="block text-gray-300 hover:text-white py-2">Features</Link>
                <Link to="/login" onClick={() => setMenuOpen(false)} className="block text-gray-300 hover:text-white py-2">Login</Link>
                <Link to="/register" onClick={() => setMenuOpen(false)} className="block text-gray-300 hover:text-white py-2">Register</Link>
              </>
            )}
          </div>
        )}
      </div>
    </nav>
  );
}
