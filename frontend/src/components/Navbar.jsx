import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useState } from 'react';

export default function Navbar() {
  const { isAuthenticated, user, logout } = useAuth();
  const navigate = useNavigate();
  const [menuOpen, setMenuOpen] = useState(false);

  function handleLogout() {
    logout();
    navigate('/login');
  }

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
                <Link to="/" className="text-gray-300 hover:text-white transition">YouTube</Link>
                <Link to="/tiktok" className="text-gray-300 hover:text-white transition">TikTok</Link>
                <Link to="/history" className="text-gray-300 hover:text-white transition">History</Link>
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
                <Link to="/" onClick={() => setMenuOpen(false)} className="block text-gray-300 hover:text-white py-2">YouTube</Link>
                <Link to="/tiktok" onClick={() => setMenuOpen(false)} className="block text-gray-300 hover:text-white py-2">TikTok</Link>
                <Link to="/history" onClick={() => setMenuOpen(false)} className="block text-gray-300 hover:text-white py-2">History</Link>
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
