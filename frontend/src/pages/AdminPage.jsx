import { useState, useEffect } from 'react';
import api from '../api/axios';

export default function AdminPage() {
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [toggling, setToggling] = useState(null);

  useEffect(() => {
    fetchUsers();
  }, []);

  function fetchUsers() {
    setLoading(true);
    api.get('/admin/users')
      .then((res) => setUsers(res.data))
      .catch((err) => setError(err.response?.data?.detail || 'Failed to load users'))
      .finally(() => setLoading(false));
  }

  async function togglePremium(userId, currentStatus) {
    setToggling(userId);
    try {
      await api.patch(`/admin/users/${userId}/premium`, { is_premium: !currentStatus });
      setUsers((prev) =>
        prev.map((u) => (u.id === userId ? { ...u, is_premium: !currentStatus } : u))
      );
    } catch (err) {
      alert(err.response?.data?.detail || 'Failed to update');
    } finally {
      setToggling(null);
    }
  }

  if (loading) {
    return <div className="text-center text-gray-400 py-20">Loading users...</div>;
  }

  if (error) {
    return <div className="text-center text-red-400 py-20">{error}</div>;
  }

  return (
    <div className="max-w-4xl mx-auto">
      <h1 className="text-3xl font-bold mb-2">Admin Panel</h1>
      <p className="text-gray-400 mb-6">Manage user premium status</p>

      <div className="bg-gray-900 rounded-xl border border-gray-800 overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-800 text-left text-gray-400">
              <th className="px-4 py-3">Username</th>
              <th className="px-4 py-3">Email</th>
              <th className="px-4 py-3 text-center">Premium</th>
              <th className="px-4 py-3">Joined</th>
              <th className="px-4 py-3 text-center">Action</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                <td className="px-4 py-3 font-medium">{u.username}</td>
                <td className="px-4 py-3 text-gray-400">{u.email}</td>
                <td className="px-4 py-3 text-center">
                  {u.is_premium ? (
                    <span className="inline-block bg-green-600/20 text-green-400 text-xs font-semibold px-2 py-0.5 rounded-full">
                      Active
                    </span>
                  ) : (
                    <span className="inline-block bg-gray-700/50 text-gray-400 text-xs font-semibold px-2 py-0.5 rounded-full">
                      Free
                    </span>
                  )}
                </td>
                <td className="px-4 py-3 text-gray-400">
                  {u.created_at ? new Date(u.created_at).toLocaleDateString() : '—'}
                </td>
                <td className="px-4 py-3 text-center">
                  {u.is_admin ? (
                    <span className="text-gray-500 text-xs">Admin</span>
                  ) : (
                    <button
                      onClick={() => togglePremium(u.id, u.is_premium)}
                      disabled={toggling === u.id}
                      className={`text-xs font-semibold px-3 py-1.5 rounded-lg transition ${
                        u.is_premium
                          ? 'bg-red-600/20 text-red-400 hover:bg-red-600/30'
                          : 'bg-blue-600/20 text-blue-400 hover:bg-blue-600/30'
                      } disabled:opacity-50`}
                    >
                      {toggling === u.id
                        ? '...'
                        : u.is_premium
                          ? 'Revoke'
                          : 'Activate'}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {users.length === 0 && (
          <div className="text-center text-gray-500 py-8">No users found</div>
        )}
      </div>
    </div>
  );
}
