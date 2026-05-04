import { useAuth } from "../context/AuthContext";
export default function CoordinatorDashboard() {
  const { user, logout } = useAuth();
  return (
    <div className="p-8">
      <h1 className="text-2xl font-bold mb-2">Coordinator Dashboard</h1>
      <p className="text-gray-500 mb-4">Welcome, {user?.full_name}</p>
      <button onClick={logout} className="text-sm text-red-500 hover:underline">
        Sign out
      </button>
      <p className="text-sm text-gray-400 mt-8">
        Full dashboard UI coming Week 5.
      </p>
    </div>
  );
}