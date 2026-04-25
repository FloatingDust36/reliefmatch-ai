// frontend/src/App.jsx
// Temporary landing page — will be replaced with proper routing in Week 4.
// This just confirms React + Tailwind + Vite are all wired up correctly.

function App() {
  return (
    <div className="min-h-screen bg-gray-950 text-white flex items-center justify-center">
      <div className="text-center space-y-4">
        <div className="text-5xl">🌀</div>
        <h1 className="text-4xl font-bold text-blue-400">ReliefMatch AI</h1>
        <p className="text-gray-400 text-lg">
          AI-Powered Disaster Relief Allocation for Philippine LGUs
        </p>
        <div className="inline-block bg-green-500/20 border border-green-500 text-green-400 px-4 py-2 rounded-full text-sm">
          ✅ Frontend running
        </div>
      </div>
    </div>
  )
}

export default App