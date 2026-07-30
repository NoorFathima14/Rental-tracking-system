import { useEffect, useState } from "react";

export default function App() {
  const [health, setHealth] = useState(null);
  const [prompt, setPrompt] = useState("");
  const [response, setResponse] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // Confirms the frontend -> backend -> AI service wiring works end to end.
  useEffect(() => {
    fetch("/api/health")
      .then((r) => r.json())
      .then(setHealth)
      .catch(() => setError("Could not reach backend. Is docker compose up?"));
  }, []);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!prompt.trim()) return;
    setLoading(true);
    setError("");
    setResponse("");
    try {
      const res = await fetch("/api/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt }),
      });
      if (!res.ok) throw new Error(`Request failed: ${res.status}`);
      const data = await res.json();
      setResponse(data.response);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="page">
      <header className="header">
        <h1>Hackathon Boilerplate</h1>
        <div className={`status ${health ? "status-ok" : "status-pending"}`}>
          {health
            ? `backend connected · provider: ${health.provider}`
            : "connecting to backend..."}
        </div>
      </header>

      <main className="card">
        <p className="hint">
          This form calls <code>POST /api/generate</code>, which routes through{" "}
          <code>ai_service.py</code> on the backend. Swap providers by editing{" "}
          <code>AI_PROVIDER</code> in <code>backend/.env</code> — no code changes needed.
        </p>

        <form onSubmit={handleSubmit} className="form">
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="Type a prompt to test the AI wiring..."
            rows={4}
          />
          <button type="submit" disabled={loading}>
            {loading ? "Generating..." : "Send"}
          </button>
        </form>

        {error && <div className="error">{error}</div>}
        {response && (
          <div className="response">
            <strong>Response:</strong>
            <p>{response}</p>
          </div>
        )}
      </main>
    </div>
  );
}
