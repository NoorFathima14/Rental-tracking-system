import { useEffect, useState, useCallback } from "react";

const EQUIPMENT_TYPES = ["Excavator", "Crane", "Bulldozer", "Grader"];
const SITES = ["S001", "S002", "S003", "S004", "S005"];

const VIEWS = [
  { key: "equipment", label: "Equipment" },
  { key: "site", label: "Site" },
  { key: "operator", label: "Operator" },
  { key: "time", label: "Time Period" },
];

export default function UsageLogs() {
  const [activeView, setActiveView] = useState("equipment");
  const [granularity, setGranularity] = useState("month");
  const [filters, setFilters] = useState({
    site_id: "",
    equipment_type: "",
    start_date: "",
    end_date: "",
  });
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const fetchUsage = useCallback(() => {
    setLoading(true);
    setError("");

    const params = new URLSearchParams({ view: activeView });
    if (activeView === "time") params.set("granularity", granularity);
    if (filters.site_id) params.set("site_id", filters.site_id);
    if (filters.equipment_type) params.set("equipment_type", filters.equipment_type);
    if (filters.start_date) params.set("start_date", filters.start_date);
    if (filters.end_date) params.set("end_date", filters.end_date);

    fetch(`/api/usage?${params.toString()}`)
      .then((r) => r.json())
      .then((data) => setRows(data.rows || []))
      .catch(() => setError("Could not load usage data."))
      .finally(() => setLoading(false));
  }, [activeView, granularity, filters]);

  useEffect(() => {
    fetchUsage();
  }, [fetchUsage]);

  function updateFilter(field, value) {
    setFilters((f) => ({ ...f, [field]: value }));
  }

  function clearFilters() {
    setFilters({ site_id: "", equipment_type: "", start_date: "", end_date: "" });
  }

  return (
    <section className="panel usage-panel">
      <h3>Usage Logging</h3>
      <p className="panel-hint">
        Runtime, idle hours, and fuel are estimated from each rental's daily average x planned duration.
      </p>

      <div className="usage-tabs">
        {VIEWS.map((v) => (
          <button
            key={v.key}
            className={`usage-tab ${activeView === v.key ? "usage-tab-active" : ""}`}
            onClick={() => setActiveView(v.key)}
          >
            {v.label}
          </button>
        ))}
      </div>

      <div className="usage-filters">
        <label>
          Site
          <select value={filters.site_id} onChange={(e) => updateFilter("site_id", e.target.value)}>
            <option value="">All sites</option>
            {SITES.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </label>

        <label>
          Equipment Type
          <select value={filters.equipment_type} onChange={(e) => updateFilter("equipment_type", e.target.value)}>
            <option value="">All types</option>
            {EQUIPMENT_TYPES.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
        </label>

        <label>
          From
          <input type="date" value={filters.start_date} onChange={(e) => updateFilter("start_date", e.target.value)} />
        </label>

        <label>
          To
          <input type="date" value={filters.end_date} onChange={(e) => updateFilter("end_date", e.target.value)} />
        </label>

        {activeView === "time" && (
          <label>
            Granularity
            <select value={granularity} onChange={(e) => setGranularity(e.target.value)}>
              <option value="month">Month</option>
              <option value="week">Week</option>
            </select>
          </label>
        )}

        <button className="clear-filters-btn" onClick={clearFilters}>Clear filters</button>
      </div>

      {loading && <div className="usage-loading">Loading...</div>}
      {error && <div className="error">{error}</div>}

      {!loading && !error && <UsageTable view={activeView} rows={rows} />}
    </section>
  );
}

function UsageTable({ view, rows }) {
  if (rows.length === 0) {
    return <div className="usage-empty">No data matches the current filters.</div>;
  }

  const columnsByView = {
    equipment: [
      ["equipment_id", "Equipment"],
      ["type", "Type"],
      ["current_status", "Status"],
      ["bookings", "Bookings"],
      ["total_runtime_hours", "Runtime (hrs)"],
      ["total_idle_hours", "Idle (hrs)"],
      ["total_fuel_litres", "Fuel (L)"],
      ["late_returns", "Late Returns"],
    ],
    site: [
      ["site_id", "Site"],
      ["bookings", "Bookings"],
      ["distinct_equipment", "Distinct Equipment"],
      ["total_runtime_hours", "Runtime (hrs)"],
      ["total_idle_hours", "Idle (hrs)"],
      ["total_fuel_litres", "Fuel (L)"],
    ],
    operator: [
      ["operator_id", "Operator"],
      ["bookings", "Bookings"],
      ["total_runtime_hours", "Runtime (hrs)"],
      ["total_idle_hours", "Idle (hrs)"],
      ["late_returns", "Late Returns"],
      ["late_return_rate_pct", "Late Rate %"],
    ],
    time: [
      ["period", "Period"],
      ["bookings", "Bookings"],
      ["total_runtime_hours", "Runtime (hrs)"],
      ["total_idle_hours", "Idle (hrs)"],
      ["total_fuel_litres", "Fuel (L)"],
    ],
  };

  const columns = columnsByView[view];

  return (
    <div className="usage-table-wrapper">
      <table className="usage-table">
        <thead>
          <tr>
            {columns.map(([key, label]) => (
              <th key={key}>{label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              {columns.map(([key]) => (
                <td key={key}>{row[key] ?? "—"}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}