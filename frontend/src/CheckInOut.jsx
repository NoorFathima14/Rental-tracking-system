import { useState } from "react";

const EQUIPMENT_TYPES = ["Excavator", "Crane", "Bulldozer", "Grader"];
const SITES = ["S001", "S002", "S003", "S004", "S005"];

export default function CheckInOut({ onActionComplete }) {
  return (
    <section className="checkinout-grid">
      <CheckInPanel onActionComplete={onActionComplete} />
      <CheckOutPanel onActionComplete={onActionComplete} />
    </section>
  );
}

function CheckInPanel({ onActionComplete }) {
  const [form, setForm] = useState({
    equipment_type: EQUIPMENT_TYPES[0],
    site_id: SITES[0],
    check_in_date: "",
    rental_days: 7,
    operator_id: "",
  });
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);

  function update(field, value) {
    setForm((f) => ({ ...f, [field]: value }));
  }

  async function handleTap() {
    setLoading(true);
    setResult(null);
    try {
      const res = await fetch("/api/checkin", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...form,
          rental_days: Number(form.rental_days),
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Check-in failed");
      setResult({ ok: true, message: data.message });
      onActionComplete?.();
    } catch (err) {
      setResult({ ok: false, message: err.message });
    } finally {
      setLoading(false);
    }
  }

  const canSubmit = form.check_in_date && form.operator_id.trim() && Number(form.rental_days) > 0;

  return (
    <div className="panel">
      <h3>Check-In</h3>
      <p className="panel-hint">Equipment goes out to a site.</p>

      <label>
        Equipment Type
        <select value={form.equipment_type} onChange={(e) => update("equipment_type", e.target.value)}>
          {EQUIPMENT_TYPES.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
      </label>

      <label>
        Site
        <select value={form.site_id} onChange={(e) => update("site_id", e.target.value)}>
          {SITES.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
      </label>

      <label>
        Check-In Date
        <input
          type="date"
          value={form.check_in_date}
          onChange={(e) => update("check_in_date", e.target.value)}
        />
      </label>

      <label>
        Rental Days
        <input
          type="number"
          min="1"
          value={form.rental_days}
          onChange={(e) => update("rental_days", e.target.value)}
        />
      </label>

      <label>
        Operator ID
        <input
          type="text"
          placeholder="e.g. OP101"
          value={form.operator_id}
          onChange={(e) => update("operator_id", e.target.value)}
        />
      </label>

      <button className="rfid-button" disabled={!canSubmit || loading} onClick={handleTap}>
        {loading ? "Scanning..." : "📡 Simulate RFID Tap — Check In"}
      </button>

      {result && (
        <div className={result.ok ? "result-ok" : "result-error"}>{result.message}</div>
      )}
    </div>
  );
}

function CheckOutPanel({ onActionComplete }) {
  const [form, setForm] = useState({
    operator_id: "",
    equipment_type: EQUIPMENT_TYPES[0],
    site_id: SITES[0],
    check_in_date: "",
  });
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);

  function update(field, value) {
    setForm((f) => ({ ...f, [field]: value }));
  }

  async function handleTap() {
    setLoading(true);
    setResult(null);
    try {
      const res = await fetch("/api/checkout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Check-out failed");
      setResult({ ok: true, message: data.message });
      onActionComplete?.();
    } catch (err) {
      setResult({ ok: false, message: err.message });
    } finally {
      setLoading(false);
    }
  }

  const canSubmit = form.operator_id.trim() && form.check_in_date;

  return (
    <div className="panel">
      <h3>Check-Out</h3>
      <p className="panel-hint">Equipment returned. Identify it by who checked it in.</p>

      <label>
        Operator ID
        <input
          type="text"
          placeholder="e.g. OP101"
          value={form.operator_id}
          onChange={(e) => update("operator_id", e.target.value)}
        />
      </label>

      <label>
        Equipment Type
        <select value={form.equipment_type} onChange={(e) => update("equipment_type", e.target.value)}>
          {EQUIPMENT_TYPES.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
      </label>

      <label>
        Site
        <select value={form.site_id} onChange={(e) => update("site_id", e.target.value)}>
          {SITES.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
      </label>

      <label>
        Check-In Date
        <input
          type="date"
          value={form.check_in_date}
          onChange={(e) => update("check_in_date", e.target.value)}
        />
      </label>

      <button className="rfid-button" disabled={!canSubmit || loading} onClick={handleTap}>
        {loading ? "Scanning..." : "📡 Simulate RFID Tap — Check Out"}
      </button>

      {result && (
        <div className={result.ok ? "result-ok" : "result-error"}>{result.message}</div>
      )}
    </div>
  );
}