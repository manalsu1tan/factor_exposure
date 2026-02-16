import { useMemo, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from "recharts";

type Holding = { ticker: string; weight: number };

type AnalyticsResponse = {
  as_of: string;
  factor_exposures: Record<string, number>;
  risk: {
    annualized_vol: number;
    daily_vol: number;
    variance: { total: number; factor: number; specific: number };
    factor_variance_contrib: Record<string, number>;
  };
};

type ScenarioResponse = {
  scenario: {
    template?: string | null;
    factor_shocks: Record<string, number>;
    calibration?: { mode: string; sigma_multiplier: number; percentile: number };
  };
  pnl: {
    factor: number;
    specific: number;
    total: number;
    factor_contrib: Record<string, number>;
  };
};

type AttributionResponse = {
  quality: {
    available: boolean;
    days_compared: number;
    mean_residual?: number;
    mae_residual?: number;
    rmse_residual?: number;
    corr_explained_vs_realized?: number;
    r2_explained_vs_realized?: number;
  };
  daily?: Array<{
    date: string;
    quality?: {
      explained_return: number;
      realized_return: number;
      residual_return: number;
      comparable_holdings: number;
    };
  }>;
};

const DEFAULT_HOLDINGS: Holding[] = [
  { ticker: "AAPL", weight: 0.3 },
  { ticker: "MSFT", weight: 0.3 },
  { ticker: "NVDA", weight: 0.2 },
  { ticker: "JPM", weight: 0.2 }
];

const TEMPLATES = ["market_down_5", "momentum_crash", "liquidity_crunch", "low_vol_unwind"];

async function postJson<T>(baseUrl: string, path: string, payload: unknown): Promise<T> {
  const resp = await fetch(`${baseUrl}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(text || `${resp.status} ${resp.statusText}`);
  }
  return (await resp.json()) as T;
}

function number(v: number | undefined, digits = 4): string {
  if (v === undefined || Number.isNaN(v)) return "—";
  return v.toFixed(digits);
}

export default function App() {
  const [apiBase, setApiBase] = useState("http://127.0.0.1:8000");
  const [asOf, setAsOf] = useState("2025-12-31");
  const [startDate, setStartDate] = useState("2025-01-01");
  const [endDate, setEndDate] = useState("2025-12-31");
  const [holdings, setHoldings] = useState<Holding[]>(DEFAULT_HOLDINGS);
  const [template, setTemplate] = useState("momentum_crash");
  const [calibrationMode, setCalibrationMode] = useState("none");
  const [sigmaMultiplier, setSigmaMultiplier] = useState(1.5);
  const [percentile, setPercentile] = useState(0.1);
  const [customShocks, setCustomShocks] = useState("{}");

  const [analytics, setAnalytics] = useState<AnalyticsResponse | null>(null);
  const [scenario, setScenario] = useState<ScenarioResponse | null>(null);
  const [attribution, setAttribution] = useState<AttributionResponse | null>(null);
  const [loading, setLoading] = useState<"" | "analytics" | "scenario" | "attribution">("");
  const [error, setError] = useState("");

  const normalizedHoldings = useMemo(() => {
    const cleaned = holdings
      .map((h) => ({ ticker: h.ticker.trim().toUpperCase(), weight: Number(h.weight) }))
      .filter((h) => h.ticker && Number.isFinite(h.weight));
    return cleaned;
  }, [holdings]);

  const qualitySeries = useMemo(() => {
    if (!attribution?.daily) return [];
    return attribution.daily
      .filter((d) => d.quality)
      .map((d) => ({
        date: d.date.slice(5),
        explained: d.quality!.explained_return,
        realized: d.quality!.realized_return,
        residual: d.quality!.residual_return
      }));
  }, [attribution]);

  const setHolding = (idx: number, key: keyof Holding, value: string) => {
    setHoldings((prev) =>
      prev.map((h, i) => (i === idx ? { ...h, [key]: key === "weight" ? Number(value) : value } : h))
    );
  };

  const runAnalytics = async () => {
    setError("");
    setLoading("analytics");
    try {
      const res = await postJson<AnalyticsResponse>(apiBase, "/portfolio/analytics", {
        as_of: asOf,
        holdings: normalizedHoldings
      });
      setAnalytics(res);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading("");
    }
  };

  const runScenario = async () => {
    setError("");
    setLoading("scenario");
    try {
      const parsedShocks = JSON.parse(customShocks || "{}") as Record<string, number>;
      const res = await postJson<ScenarioResponse>(apiBase, "/portfolio/scenario", {
        as_of: asOf,
        template,
        calibration_mode: calibrationMode,
        sigma_multiplier: sigmaMultiplier,
        percentile,
        factor_shocks: parsedShocks,
        holdings: normalizedHoldings
      });
      setScenario(res);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading("");
    }
  };

  const runAttribution = async () => {
    setError("");
    setLoading("attribution");
    try {
      const res = await postJson<AttributionResponse>(apiBase, "/portfolio/attribution", {
        start_date: startDate,
        end_date: endDate,
        include_daily: true,
        limit: 300,
        offset: 0,
        compact: true,
        include_quality: true,
        holdings: normalizedHoldings
      });
      setAttribution(res);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading("");
    }
  };

  return (
    <main className="container">
      <h1>Factor Exposure Dashboard</h1>

      <section className="card">
        <h2>Inputs</h2>
        <div className="grid two">
          <label>
            API Base
            <input value={apiBase} onChange={(e) => setApiBase(e.target.value)} />
          </label>
          <label>
            As Of
            <input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} />
          </label>
          <label>
            Start Date
            <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
          </label>
          <label>
            End Date
            <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
          </label>
        </div>

        <h3>Holdings</h3>
        <table>
          <thead>
            <tr>
              <th>Ticker</th>
              <th>Weight</th>
            </tr>
          </thead>
          <tbody>
            {holdings.map((h, i) => (
              <tr key={`${h.ticker}-${i}`}>
                <td>
                  <input value={h.ticker} onChange={(e) => setHolding(i, "ticker", e.target.value)} />
                </td>
                <td>
                  <input
                    type="number"
                    step="0.01"
                    value={h.weight}
                    onChange={(e) => setHolding(i, "weight", e.target.value)}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <button type="button" onClick={() => setHoldings((v) => [...v, { ticker: "", weight: 0 }])}>
          Add Row
        </button>
      </section>

      <section className="card">
        <h2>Analytics</h2>
        <button type="button" disabled={loading !== ""} onClick={runAnalytics}>
          {loading === "analytics" ? "Running..." : "Run Analytics"}
        </button>
        {analytics && (
          <>
            <p>
              Annualized Vol: <strong>{number(analytics.risk.annualized_vol, 4)}</strong>
            </p>
            <h3>Factor Exposures</h3>
            <ul>
              {Object.entries(analytics.factor_exposures)
                .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
                .map(([f, v]) => (
                  <li key={f}>
                    {f}: {number(v, 4)}
                  </li>
                ))}
            </ul>
          </>
        )}
      </section>

      <section className="card">
        <h2>Scenario</h2>
        <div className="grid three">
          <label>
            Template
            <select value={template} onChange={(e) => setTemplate(e.target.value)}>
              {TEMPLATES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </label>
          <label>
            Calibration
            <select value={calibrationMode} onChange={(e) => setCalibrationMode(e.target.value)}>
              <option value="none">none</option>
              <option value="sigma">sigma</option>
              <option value="percentile">percentile</option>
            </select>
          </label>
          <label>
            Sigma Multiplier
            <input type="number" step="0.1" value={sigmaMultiplier} onChange={(e) => setSigmaMultiplier(Number(e.target.value))} />
          </label>
          <label>
            Percentile
            <input type="number" step="0.01" value={percentile} onChange={(e) => setPercentile(Number(e.target.value))} />
          </label>
        </div>
        <label>
          Custom Shock Overrides (JSON)
          <textarea value={customShocks} onChange={(e) => setCustomShocks(e.target.value)} rows={4} />
        </label>
        <button type="button" disabled={loading !== ""} onClick={runScenario}>
          {loading === "scenario" ? "Running..." : "Run Scenario"}
        </button>
        {scenario && (
          <>
            <p>
              Scenario Total PnL: <strong>{number(scenario.pnl.total, 4)}</strong>
            </p>
            <h3>Factor PnL Contribution</h3>
            <ul>
              {Object.entries(scenario.pnl.factor_contrib)
                .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
                .map(([f, v]) => (
                  <li key={f}>
                    {f}: {number(v, 5)}
                  </li>
                ))}
            </ul>
          </>
        )}
      </section>

      <section className="card">
        <h2>Attribution Quality</h2>
        <button type="button" disabled={loading !== ""} onClick={runAttribution}>
          {loading === "attribution" ? "Running..." : "Run Attribution Quality"}
        </button>
        {attribution?.quality && (
          <>
            <p>Days Compared: {attribution.quality.days_compared}</p>
            <p>Mean Residual: {number(attribution.quality.mean_residual, 6)}</p>
            <p>RMSE Residual: {number(attribution.quality.rmse_residual, 6)}</p>
            <p>Corr Explained vs Realized: {number(attribution.quality.corr_explained_vs_realized, 4)}</p>
          </>
        )}
        {qualitySeries.length > 0 && (
          <div style={{ width: "100%", height: 280 }}>
            <ResponsiveContainer>
              <LineChart data={qualitySeries}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="date" minTickGap={24} />
                <YAxis />
                <Tooltip />
                <Line dataKey="explained" stroke="#1976d2" dot={false} />
                <Line dataKey="realized" stroke="#2e7d32" dot={false} />
                <Line dataKey="residual" stroke="#d32f2f" dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </section>

      {error && <pre className="error">{error}</pre>}
    </main>
  );
}
