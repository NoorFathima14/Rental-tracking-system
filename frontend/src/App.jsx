import { useEffect, useState } from "react";

export default function App() {
  const [health, setHealth] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    fetch("/api/health")
      .then((r) => r.json())
      .then(setHealth)
      .catch(() => setError("Could not reach backend. Is the backend running?"));
  }, []);

  return (
    <div className="page">
      <header className="header">
        <h1>Smart Rental Tracking System</h1>
        <div className={`status ${health ? "status-ok" : "status-pending"}`}>
          {health
            ? `backend connected · ${health.rows_loaded} bookings loaded`
            : "connecting to backend..."}
        </div>
      </header>

      <main className="card">
        <p className="hint">
          Base stack is wired. Dashboard, check-in/check-out, and usage
          analytics screens go here next.
        </p>
        {error && <div className="error">{error}</div>}
      </main>
    </div>
  );
}