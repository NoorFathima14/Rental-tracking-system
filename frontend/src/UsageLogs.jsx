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

      {!loading && !error && <UsageCards view={activeView} rows={rows} />}
    </section>
  );
}

function UsageCards({ view, rows }) {
  if (rows.length === 0) {
    return <div className="usage-empty">No data matches the current filters.</div>;
  }

  const cardConfig = {
    equipment: (row) => ({
      title: row.equipment_id,
      subtitle: `${row.type} · ${row.current_status}`,
      metrics: [
        ["Bookings", row.bookings],
        ["Runtime", `${row.total_runtime_hours} hrs`],
        ["Idle", `${row.total_idle_hours} hrs`],
        ["Fuel", `${row.total_fuel_litres} L`],
        ["Late Returns", row.late_returns],
      ],
    }),
    site: (row) => ({
      title: row.site_id,
      subtitle: `${row.distinct_equipment} equipment used`,
      metrics: [
        ["Bookings", row.bookings],
        ["Runtime", `${row.total_runtime_hours} hrs`],
        ["Idle", `${row.total_idle_hours} hrs`],
        ["Fuel", `${row.total_fuel_litres} L`],
      ],
    }),
    operator: (row) => ({
      title: row.operator_id,
      subtitle: `${row.late_return_rate_pct}% late-return rate`,
      metrics: [
        ["Bookings", row.bookings],
        ["Runtime", `${row.total_runtime_hours} hrs`],
        ["Idle", `${row.total_idle_hours} hrs`],
        ["Late Returns", row.late_returns],
      ],
    }),
    time: (row) => ({
      title: row.period,
      subtitle: null,
      metrics: [
        ["Bookings", row.bookings],
        ["Runtime", `${row.total_runtime_hours} hrs`],
        ["Idle", `${row.total_idle_hours} hrs`],
        ["Fuel", `${row.total_fuel_litres} L`],
      ],
    }),
  };

  const buildCard = cardConfig[view];

  return (
    <div className="usage-card-grid">
      {rows.map((row, i) => {
        const card = buildCard(row);
        return (
          <div key={i} className="usage-card">
            <div className="usage-card-title">{card.title}</div>
            {card.subtitle && <div className="usage-card-subtitle">{card.subtitle}</div>}
            <div className="usage-card-metrics">
              {card.metrics.map(([label, value]) => (
                <div key={label} className="usage-card-metric">
                  <span className="usage-card-metric-value">{value}</span>
                  <span className="usage-card-metric-label">{label}</span>
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}