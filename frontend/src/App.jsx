import { useEffect, useState, useCallback } from "react";
import CheckInOut from "./CheckInOut";

export default function App() {
  const [health, setHealth] = useState(null);
  const [pulse, setPulse] = useState(null);
  const [error, setError] = useState("");
  const [hoveredCard, setHoveredCard] = useState(null); // "overdue" | "idle" | null

  const fetchPulse = useCallback(() => {
    fetch("/api/dashboard/pulse")
      .then((r) => r.json())
      .then((data) => setPulse(data.pulse))
      .catch(() => setError("Could not load dashboard data."));
  }, []);

  useEffect(() => {
    fetch("/api/health")
      .then((r) => r.json())
      .then(setHealth)
      .catch(() => setError("Could not reach backend."));
    fetchPulse();
  }, [fetchPulse]);

  return (
    <div className="page">
      <header className="header">
        <h1>Smart Rental Tracking System</h1>
        <div className={`status ${health ? "status-ok" : "status-pending"}`}>
          {health ? `backend connected · ${health.rows_loaded} bookings loaded` : "connecting..."}
        </div>
      </header>

      {error && <div className="error">{error}</div>}

      {pulse && (
        <section className="pulse-strip">
          <PulseCard label="Total Equipment" value={pulse.total_equipment} />
          <PulseCard label="Currently Active" value={pulse.currently_active} />

          <PulseCard
            label="Available"
            value={pulse.available}
            onMouseEnter={() => setHoveredCard("available")}
            onMouseLeave={() => setHoveredCard(null)}
            tooltip={
              hoveredCard === "available" && (
                <Tooltip title="Available Equipment">
                  {pulse.available_list.length === 0 ? (
                    <div>None right now</div>
                  ) : (
                    pulse.available_list.map((eq) => (
                      <div key={eq.equipment_id}>
                        {eq.equipment_id} ({eq.type})
                      </div>
                    ))
                  )}
                </Tooltip>
              )
            }
          />

          <PulseCard
            label="Idle Right Now"
            value={pulse.idle_now}
            onMouseEnter={() => setHoveredCard("idle")}
            onMouseLeave={() => setHoveredCard(null)}
            tooltip={
              hoveredCard === "idle" && (
                <Tooltip title="Idle Equipment">
                  {pulse.idle_list.length === 0 ? (
                    <div>None right now</div>
                  ) : (
                    pulse.idle_list.map((eq) => (
                      <div key={eq.equipment_id}>
                        {eq.equipment_id} ({eq.type}) · Site {eq.site_id ?? "—"} · {eq.idle_hours_per_day}h idle/day
                      </div>
                    ))
                  )}
                </Tooltip>
              )
            }
          />

          <PulseCard
            label="Overdue"
            value={pulse.overdue}
            highlight={pulse.overdue > 0}
            onMouseEnter={() => setHoveredCard("overdue")}
            onMouseLeave={() => setHoveredCard(null)}
            tooltip={
              hoveredCard === "overdue" && (
                <Tooltip title="Overdue Equipment">
                  {pulse.overdue_list.length === 0 ? (
                    <div>None right now</div>
                  ) : (
                    pulse.overdue_list.map((eq) => (
                      <div key={eq.equipment_id}>
                        {eq.equipment_id} ({eq.type}) · Site {eq.site_id ?? "—"} · {eq.days_overdue}d overdue
                      </div>
                    ))
                  )}
                </Tooltip>
              )
            }
          />

        </section>
      )}
      <CheckInOut onActionComplete={fetchPulse} />
    </div>
  );
}

function PulseCard({ label, value, highlight, onMouseEnter, onMouseLeave, tooltip }) {
  return (
    <div
      className={`pulse-card ${highlight ? "pulse-card-alert" : ""}`}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
      style={{ position: "relative" }}
    >
      <div className="pulse-value">{value}</div>
      <div className="pulse-label">{label}</div>
      {tooltip}
    </div>
  );
}

function Tooltip({ title, children }) {
  return (
    <div className="pulse-tooltip">
      <strong>{title}</strong>
      <div className="pulse-tooltip-body">{children}</div>
    </div>
  );
}