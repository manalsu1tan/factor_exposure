import { useEffect, useMemo, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from "recharts";

type HoldingInput = {
  id: number;
  ticker: string;
  weight: number;
  shares: number;
  price: number;
};

type InputMode = "weight" | "shares";

type AnalyticsResponse = {
  as_of: string;
  coverage: {
    requested: number;
    covered: number;
    missing: string[];
  };
  factor_exposures: Record<string, number>;
  risk: {
    annualized_vol: number;
    daily_vol: number;
    variance: { total: number; factor: number; specific: number };
    factor_variance_contrib: Record<string, number>;
  };
};

type ExposureTimeseriesResponse = {
  start_date: string | null;
  end_date: string | null;
  rows: Array<
    {
      date: string;
      covered_holdings: number;
      requested_holdings: number;
    } & Record<string, number | string>
  >;
};

type UniverseTickersResponse = {
  as_of: string;
  count: number;
  tickers: string[];
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

type PositionEventsResponse = {
  portfolio_id: string;
  count: number;
  events: Array<{
    event_id: string;
    event_time: string;
    ticker: string;
    event_type: string;
    quantity: number;
    side?: string | null;
    price?: number | null;
    fees?: number;
  }>;
};

type PositionSnapshotResponse = {
  portfolio_id: string;
  as_of: string | null;
  event_count: number;
  totals: {
    tickers: number;
    open_positions: number;
    long_positions: number;
    short_positions: number;
    priced_rows: number;
    unpriced_tickers: string[];
    market_value: number;
    realized_pnl: number;
    dividends_pnl: number;
    total_pnl: number;
    unrealized_pnl: number;
    economic_total_pnl: number;
  };
  rows: Array<{
    ticker: string;
    quantity: number;
    avg_cost: number;
    market_price?: number | null;
    price_as_of?: string | null;
    market_value?: number | null;
    realized_pnl: number;
    dividends_pnl: number;
    total_pnl: number;
    unrealized_pnl?: number | null;
    economic_total_pnl?: number | null;
    last_event_time: string;
  }>;
};

type ExplainResponse = {
  report: {
    as_of: string;
    views_expressed: Array<{ factor: string; exposure: number }>;
    top_risk_contributors: Array<{ factor: string; variance_contrib: number }>;
    drift_window: { start_date: string | null; end_date: string | null; rows: number };
    drift_top_factors: Array<{ factor: string; delta: number }>;
  };
  explanation: {
    mode: string;
    model?: string;
    overview: string;
    key_views: string[];
    risk_watchouts: string[];
    drift_story: string[];
    scenario_implications: string[];
    limitations: string[];
  };
};

type QualityRow = {
  date: string;
  explained: number;
  realized: number;
  residual: number;
  comparableHoldings: number;
};

const DEFAULT_HOLDINGS: HoldingInput[] = [
  { id: 1, ticker: "AAPL", weight: 0.3, shares: 0, price: 0 },
  { id: 2, ticker: "MSFT", weight: 0.3, shares: 0, price: 0 },
  { id: 3, ticker: "NVDA", weight: 0.2, shares: 0, price: 0 },
  { id: 4, ticker: "JPM", weight: 0.2, shares: 0, price: 0 }
];

const TEMPLATES = ["market_down_5", "momentum_crash", "liquidity_crunch", "low_vol_unwind"];

const LS_KEY = "factor_exposure_web_state_v1";

function parseErrorBody(text: string): string {
  if (!text) return "Request failed with empty response.";
  try {
    const parsed = JSON.parse(text);
    if (typeof parsed?.detail === "string") return parsed.detail;
    if (Array.isArray(parsed?.detail)) return JSON.stringify(parsed.detail);
    return JSON.stringify(parsed);
  } catch {
    return text;
  }
}

function toErrorMessage(err: unknown): string {
  if (err instanceof Error) return err.message;
  return String(err);
}

async function postJson<T>(
  baseUrl: string,
  path: string,
  payload: unknown,
  timeoutMs = 12_000,
  maxAttempts = 2
): Promise<T> {
  let lastError: unknown = null;
  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const resp = await fetch(`${baseUrl}${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        signal: controller.signal
      });
      clearTimeout(timer);
      if (!resp.ok) {
        const text = await resp.text();
        const message = parseErrorBody(text) || `${resp.status} ${resp.statusText}`;
        if (resp.status >= 500 && attempt < maxAttempts) {
          lastError = new Error(message);
          continue;
        }
        throw new Error(message);
      }
      return (await resp.json()) as T;
    } catch (err) {
      clearTimeout(timer);
      const aborted = err instanceof DOMException && err.name === "AbortError";
      if (aborted) {
        lastError = new Error(`Request timed out after ${timeoutMs}ms (${path})`);
      } else {
        lastError = err;
      }
      if (attempt < maxAttempts) {
        continue;
      }
    }
  }
  throw lastError instanceof Error ? lastError : new Error(String(lastError));
}

async function getJson<T>(
  baseUrl: string,
  path: string,
  timeoutMs = 8_000
): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const resp = await fetch(`${baseUrl}${path}`, { signal: controller.signal });
    clearTimeout(timer);
    if (!resp.ok) {
      const text = await resp.text();
      throw new Error(parseErrorBody(text) || `${resp.status} ${resp.statusText}`);
    }
    return (await resp.json()) as T;
  } catch (err) {
    clearTimeout(timer);
    const aborted = err instanceof DOMException && err.name === "AbortError";
    if (aborted) {
      throw new Error(`Request timed out after ${timeoutMs}ms (${path})`);
    }
    throw err;
  }
}

function number(v: number | undefined, digits = 4): string {
  if (v === undefined || Number.isNaN(v)) return "—";
  return v.toFixed(digits);
}

function percentileRank(series: number[], value: number): number | undefined {
  const clean = series.filter((x) => Number.isFinite(x));
  if (clean.length === 0) return undefined;
  const count = clean.filter((x) => x <= value).length;
  return (count / clean.length) * 100;
}

function parseCsvRows(text: string): Array<Record<string, string>> {
  const lines = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
  if (lines.length === 0) return [];

  const first = lines[0].toLowerCase();
  const hasHeader = first.includes("ticker");
  const headers = hasHeader
    ? lines[0].split(",").map((h) => h.trim().toLowerCase())
    : ["ticker", "weight", "shares", "price"];
  const dataLines = hasHeader ? lines.slice(1) : lines;

  return dataLines.map((line) => {
    const cols = line.split(",").map((c) => c.trim());
    const row: Record<string, string> = {};
    headers.forEach((h, i) => {
      row[h] = cols[i] ?? "";
    });
    return row;
  });
}

export default function App() {
  const [inputMode, setInputMode] = useState<InputMode>("weight");
  const [apiBase, setApiBase] = useState("http://127.0.0.1:8000");
  const [asOf, setAsOf] = useState("2025-12-31");
  const [startDate, setStartDate] = useState("2025-01-01");
  const [endDate, setEndDate] = useState("2025-12-31");
  const [holdings, setHoldings] = useState<HoldingInput[]>(DEFAULT_HOLDINGS);
  const [csvText, setCsvText] = useState("");
  const [template, setTemplate] = useState("momentum_crash");
  const [calibrationMode, setCalibrationMode] = useState("none");
  const [sigmaMultiplier, setSigmaMultiplier] = useState(1.5);
  const [percentile, setPercentile] = useState(0.1);
  const [customShocks, setCustomShocks] = useState("{}");
  const [explainMode, setExplainMode] = useState("auto");
  const [llmModel, setLlmModel] = useState("gpt-4.1-mini");
  const [explainTopN, setExplainTopN] = useState(5);
  const [portfolioId, setPortfolioId] = useState("demo_book");
  const [snapshotAsOf, setSnapshotAsOf] = useState("");

  const [analytics, setAnalytics] = useState<AnalyticsResponse | null>(null);
  const [exposureTs, setExposureTs] = useState<ExposureTimeseriesResponse | null>(null);
  const [scenario, setScenario] = useState<ScenarioResponse | null>(null);
  const [attribution, setAttribution] = useState<AttributionResponse | null>(null);
  const [explain, setExplain] = useState<ExplainResponse | null>(null);
  const [positionEvents, setPositionEvents] = useState<PositionEventsResponse | null>(null);
  const [positionSnapshot, setPositionSnapshot] = useState<PositionSnapshotResponse | null>(null);
  const [universeTickers, setUniverseTickers] = useState<string[]>([]);
  const [loading, setLoading] = useState<
    "" | "analytics" | "scenario" | "attribution" | "explain" | "positions"
  >("");
  const [error, setError] = useState("");
  const [tickerLoadError, setTickerLoadError] = useState("");

  const universeSet = useMemo(() => new Set(universeTickers), [universeTickers]);

  const refreshUniverseTickers = async () => {
    try {
      const res = await getJson<UniverseTickersResponse>(apiBase, "/universe/tickers");
      setUniverseTickers(res.tickers || []);
      setTickerLoadError("");
    } catch (e) {
      setUniverseTickers([]);
      setTickerLoadError(`Ticker reference unavailable: ${toErrorMessage(e)}`);
    }
  };

  const holdingRows = useMemo(() => {
    return holdings.map((h) => {
      const ticker = h.ticker.trim().toUpperCase();
      const errors: string[] = [];
      const warnings: string[] = [];
      if (!ticker) errors.push("ticker required");
      if (ticker && !/^[A-Z][A-Z0-9.\-]*$/.test(ticker)) errors.push("ticker format");
      if (ticker && universeSet.size > 0 && !universeSet.has(ticker)) warnings.push("unknown ticker");

      const weight = Number(h.weight);
      const shares = Number(h.shares);
      const price = Number(h.price);
      const marketValue = Number.isFinite(shares) && Number.isFinite(price) ? shares * price : NaN;
      if (inputMode === "weight") {
        if (!Number.isFinite(weight)) errors.push("weight invalid");
      } else {
        if (!Number.isFinite(shares)) errors.push("shares invalid");
        if (!Number.isFinite(price)) errors.push("price invalid");
      }

      return {
        ...h,
        ticker,
        weight,
        shares,
        price,
        marketValue,
        errors,
        warnings
      };
    });
  }, [holdings, inputMode, universeSet]);

  const normalizedHoldings = useMemo(() => {
    const active = holdingRows.filter((row) => row.errors.length === 0 && row.ticker);
    if (inputMode === "weight") {
      const denom = active.reduce((acc, row) => acc + Math.abs(row.weight), 0);
      if (denom <= 0) return [];
      return active.map((row) => ({ ticker: row.ticker, weight: row.weight / denom }));
    }
    const valued = active.filter((row) => Number.isFinite(row.marketValue));
    const denom = valued.reduce((acc, row) => acc + Math.abs(row.marketValue), 0);
    if (denom <= 0) return [];
    return valued.map((row) => ({ ticker: row.ticker, weight: row.marketValue / denom }));
  }, [holdingRows, inputMode]);

  const holdingsStats = useMemo(() => {
    const validCount = holdingRows.filter((row) => row.errors.length === 0 && row.ticker).length;
    const total = holdingRows.length;
    const blockingIssues = holdingRows
      .filter((row) => row.errors.length > 0)
      .map((row) => `${row.ticker || "(blank)"}: ${row.errors.join(", ")}`);
    const warnings = holdingRows
      .filter((row) => row.errors.length === 0 && row.warnings.length > 0)
      .map((row) => `${row.ticker}: ${row.warnings.join(", ")}`);

    const absWeights = normalizedHoldings.map((row) => Math.abs(row.weight)).sort((a, b) => b - a);
    const top1 = absWeights[0] ?? 0;
    const top5 = absWeights.slice(0, 5).reduce((a, b) => a + b, 0);
    const effectiveN = absWeights.length > 0 ? 1 / absWeights.reduce((a, b) => a + b * b, 0) : 0;

    const rawGross =
      inputMode === "weight"
        ? holdingRows
            .filter((row) => row.errors.length === 0)
            .reduce((acc, row) => acc + Math.abs(row.weight), 0)
        : holdingRows
            .filter((row) => row.errors.length === 0 && Number.isFinite(row.marketValue))
            .reduce((acc, row) => acc + Math.abs(row.marketValue), 0);
    const rawNet =
      inputMode === "weight"
        ? holdingRows
            .filter((row) => row.errors.length === 0)
            .reduce((acc, row) => acc + row.weight, 0)
        : holdingRows
            .filter((row) => row.errors.length === 0 && Number.isFinite(row.marketValue))
            .reduce((acc, row) => acc + row.marketValue, 0);

    return {
      validCount,
      total,
      blockingIssues,
      warnings,
      top1,
      top5,
      effectiveN,
      rawGross,
      rawNet
    };
  }, [holdingRows, normalizedHoldings, inputMode]);

  const qualityRows = useMemo<QualityRow[]>(() => {
    if (!attribution?.daily) return [];
    return attribution.daily
      .filter((d) => d.quality)
      .map((d) => ({
        date: d.date,
        explained: d.quality!.explained_return,
        realized: d.quality!.realized_return,
        residual: d.quality!.residual_return,
        comparableHoldings: d.quality!.comparable_holdings
      }));
  }, [attribution]);

  const qualitySeries = useMemo(
    () => qualityRows.map((row) => ({ ...row, label: row.date.slice(5) })),
    [qualityRows]
  );

  const exposureContext = useMemo(() => {
    if (!analytics || !exposureTs || exposureTs.rows.length === 0) return [];
    const latestRow = exposureTs.rows[exposureTs.rows.length - 1];
    return Object.entries(analytics.factor_exposures)
      .map(([factor, current]) => {
        const series = exposureTs.rows
          .map((row) => row[factor])
          .filter((v): v is number => typeof v === "number" && Number.isFinite(v));
        const rank = percentileRank(series, current);
        const latest = latestRow[factor];
        return {
          factor,
          current,
          latest: typeof latest === "number" ? latest : undefined,
          percentile: rank
        };
      })
      .sort((a, b) => Math.abs(b.current) - Math.abs(a.current));
  }, [analytics, exposureTs]);

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(LS_KEY);
      if (!raw) return;
      const parsed = JSON.parse(raw) as Partial<{
        inputMode: InputMode;
        apiBase: string;
        asOf: string;
        startDate: string;
        endDate: string;
        holdings: HoldingInput[] | Array<{ ticker: string; weight: number }>;
        csvText: string;
        template: string;
        calibrationMode: string;
        sigmaMultiplier: number;
        percentile: number;
        customShocks: string;
        explainMode: string;
        llmModel: string;
        explainTopN: number;
        portfolioId: string;
        snapshotAsOf: string;
      }>;
      if (parsed.inputMode) setInputMode(parsed.inputMode);
      if (parsed.apiBase) setApiBase(parsed.apiBase);
      if (parsed.asOf) setAsOf(parsed.asOf);
      if (parsed.startDate) setStartDate(parsed.startDate);
      if (parsed.endDate) setEndDate(parsed.endDate);
      if (Array.isArray(parsed.holdings) && parsed.holdings.length > 0) {
        const coerced = parsed.holdings.map((h, idx) => ({
          id: idx + 1,
          ticker: String(h.ticker ?? "").toUpperCase(),
          weight: Number(h.weight ?? 0),
          shares: Number((h as HoldingInput).shares ?? 0),
          price: Number((h as HoldingInput).price ?? 0)
        }));
        setHoldings(coerced);
      }
      if (typeof parsed.csvText === "string") setCsvText(parsed.csvText);
      if (parsed.template) setTemplate(parsed.template);
      if (parsed.calibrationMode) setCalibrationMode(parsed.calibrationMode);
      if (typeof parsed.sigmaMultiplier === "number") setSigmaMultiplier(parsed.sigmaMultiplier);
      if (typeof parsed.percentile === "number") setPercentile(parsed.percentile);
      if (typeof parsed.customShocks === "string") setCustomShocks(parsed.customShocks);
      if (typeof parsed.explainMode === "string") setExplainMode(parsed.explainMode);
      if (typeof parsed.llmModel === "string") setLlmModel(parsed.llmModel);
      if (typeof parsed.explainTopN === "number") setExplainTopN(parsed.explainTopN);
      if (typeof parsed.portfolioId === "string") setPortfolioId(parsed.portfolioId);
      if (typeof parsed.snapshotAsOf === "string") setSnapshotAsOf(parsed.snapshotAsOf);
    } catch {
      // ignore malformed local state
    }
  }, []);

  useEffect(() => {
    const payload = {
      inputMode,
      apiBase,
      asOf,
      startDate,
      endDate,
      holdings,
      csvText,
      template,
      calibrationMode,
      sigmaMultiplier,
      percentile,
      customShocks,
      explainMode,
      llmModel,
      explainTopN,
      portfolioId,
      snapshotAsOf
    };
    window.localStorage.setItem(LS_KEY, JSON.stringify(payload));
  }, [inputMode, apiBase, asOf, startDate, endDate, holdings, csvText, template, calibrationMode, sigmaMultiplier, percentile, customShocks, explainMode, llmModel, explainTopN, portfolioId, snapshotAsOf]);

  useEffect(() => {
    void refreshUniverseTickers();
  }, [apiBase]);

  const setHolding = (idx: number, key: keyof HoldingInput, value: string) => {
    setHoldings((prev) =>
      prev.map((h, i) =>
        i === idx
          ? {
              ...h,
              [key]:
                key === "ticker" ? value : Number(value)
            }
          : h
      )
    );
  };

  const removeHolding = (id: number) => {
    setHoldings((prev) => {
      if (prev.length <= 1) {
        return [{ id: 1, ticker: "", weight: 0, shares: 0, price: 0 }];
      }
      return prev.filter((row) => row.id !== id);
    });
  };

  const loadCsv = () => {
    try {
      const parsed = parseCsvRows(csvText);
      if (parsed.length === 0) {
        setError("CSV input is empty.");
        return;
      }
      const rows: HoldingInput[] = parsed.map((row, idx) => ({
        id: idx + 1,
        ticker: String(row.ticker ?? "").toUpperCase(),
        weight: Number(row.weight ?? 0),
        shares: Number(row.shares ?? 0),
        price: Number(row.price ?? 0)
      }));
      setHoldings(rows);
      setError("");
    } catch (e) {
      setError(`CSV parse error: ${toErrorMessage(e)}`);
    }
  };

  const downloadQualityCsv = () => {
    if (qualityRows.length === 0) return;
    const header = "date,explained_return,realized_return,residual_return,comparable_holdings";
    const rows = qualityRows.map((row) =>
      [row.date, row.explained, row.realized, row.residual, row.comparableHoldings].join(",")
    );
    const csv = [header, ...rows].join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "attribution_quality_daily.csv";
    anchor.click();
    URL.revokeObjectURL(url);
  };

  const runAnalytics = async () => {
    if (normalizedHoldings.length === 0) {
      setError("No valid holdings. Fix input errors first.");
      return;
    }
    setError("");
    setLoading("analytics");
    try {
      const [analyticsRes, tsRes] = await Promise.all([
        postJson<AnalyticsResponse>(apiBase, "/portfolio/analytics", {
          as_of: asOf,
          holdings: normalizedHoldings
        }),
        postJson<ExposureTimeseriesResponse>(apiBase, "/portfolio/exposure-timeseries", {
          start_date: startDate,
          end_date: endDate,
          holdings: normalizedHoldings
        })
      ]);
      setAnalytics(analyticsRes);
      setExposureTs(tsRes);
    } catch (e) {
      setError(toErrorMessage(e));
    } finally {
      setLoading("");
    }
  };

  const runScenario = async () => {
    if (normalizedHoldings.length === 0) {
      setError("No valid holdings. Fix input errors first.");
      return;
    }
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
      setError(toErrorMessage(e));
    } finally {
      setLoading("");
    }
  };

  const runAttribution = async () => {
    if (normalizedHoldings.length === 0) {
      setError("No valid holdings. Fix input errors first.");
      return;
    }
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
      setError(toErrorMessage(e));
    } finally {
      setLoading("");
    }
  };

  const runExplain = async () => {
    if (normalizedHoldings.length === 0) {
      setError("No valid holdings. Fix input errors first.");
      return;
    }
    setError("");
    setLoading("explain");
    try {
      const res = await postJson<ExplainResponse>(apiBase, "/portfolio/explain", {
        as_of: asOf,
        start_date: startDate,
        end_date: endDate,
        top_n: explainTopN,
        mode: explainMode,
        llm_model: llmModel,
        holdings: normalizedHoldings
      });
      setExplain(res);
    } catch (e) {
      setError(toErrorMessage(e));
    } finally {
      setLoading("");
    }
  };

  const runPositions = async () => {
    if (!portfolioId.trim()) {
      setError("Portfolio ID is required for positions.");
      return;
    }
    setError("");
    setLoading("positions");
    try {
      const query = new URLSearchParams({ portfolio_id: portfolioId.trim() });
      const events = await getJson<PositionEventsResponse>(
        apiBase,
        `/positions/events?${query.toString()}`
      );
      const snapshot = await postJson<PositionSnapshotResponse>(apiBase, "/positions/snapshot", {
        portfolio_id: portfolioId.trim(),
        as_of: snapshotAsOf || undefined,
        include_closed: false
      });
      setPositionEvents(events);
      setPositionSnapshot(snapshot);
    } catch (e) {
      setError(toErrorMessage(e));
    } finally {
      setLoading("");
    }
  };

  const syncHoldingsToPositions = async () => {
    if (!portfolioId.trim()) {
      setError("Portfolio ID is required for positions.");
      return;
    }
    const candidates = holdingRows
      .filter((row) => row.ticker && Number.isFinite(row.shares) && Number.isFinite(row.price))
      .filter((row) => row.shares !== 0 && row.price > 0);
    if (candidates.length === 0) {
      setError("No share/price rows to sync. Switch to shares mode and enter non-zero shares + price.");
      return;
    }

    setError("");
    setLoading("positions");
    try {
      const now = new Date().toISOString();
      await postJson<{ appended: number }>(apiBase, "/positions/events", {
        portfolio_id: portfolioId.trim(),
        events: candidates.map((row, idx) => ({
          event_id: `ui-${Date.now()}-${idx}-${row.ticker}`,
          event_time: now,
          ticker: row.ticker,
          event_type: "TRADE",
          side: row.shares > 0 ? "BUY" : "SELL",
          quantity: Math.abs(row.shares),
          price: row.price,
          fees: 0,
          source: "web-holdings-sync"
        }))
      });
      await runPositions();
    } catch (e) {
      setError(toErrorMessage(e));
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
        <div className="actions">
          <label>
            Input Mode
            <select value={inputMode} onChange={(e) => setInputMode(e.target.value as InputMode)}>
              <option value="weight">weight</option>
              <option value="shares">shares × price</option>
            </select>
          </label>
          <div className="badge">Universe: {universeTickers.length || "—"}</div>
          <div className="badge ok">Valid: {holdingsStats.validCount}/{holdingsStats.total}</div>
          <div className="badge">Normalized rows: {normalizedHoldings.length}</div>
          <button type="button" onClick={() => void refreshUniverseTickers()}>
            Refresh Tickers
          </button>
        </div>
        {tickerLoadError && <div className="warnBox">{tickerLoadError}</div>}
        <datalist id="ticker-options">
          {universeTickers.map((ticker) => (
            <option key={ticker} value={ticker} />
          ))}
        </datalist>

        <table>
          <thead>
            <tr>
              <th>Ticker</th>
              <th>Weight</th>
              <th>Shares</th>
              <th>Price</th>
              <th>Market Value</th>
              <th>Status</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {holdingRows.map((h, i) => (
              <tr key={h.id}>
                <td>
                  <input
                    list="ticker-options"
                    value={h.ticker}
                    onChange={(e) => setHolding(i, "ticker", e.target.value)}
                  />
                  {h.ticker && universeTickers.length > 0 && (
                    <div className="hintRow">
                      {universeTickers
                        .filter((t) => t.startsWith(h.ticker.toUpperCase()) && t !== h.ticker.toUpperCase())
                        .slice(0, 5)
                        .map((t) => (
                          <button key={t} type="button" className="chip" onClick={() => setHolding(i, "ticker", t)}>
                            {t}
                          </button>
                        ))}
                    </div>
                  )}
                </td>
                <td>
                  <input
                    type="number"
                    step="0.01"
                    value={h.weight}
                    disabled={inputMode === "shares"}
                    onChange={(e) => setHolding(i, "weight", e.target.value)}
                  />
                </td>
                <td>
                  <input
                    type="number"
                    step="1"
                    value={h.shares}
                    disabled={inputMode === "weight"}
                    onChange={(e) => setHolding(i, "shares", e.target.value)}
                  />
                </td>
                <td>
                  <input
                    type="number"
                    step="0.01"
                    value={h.price}
                    disabled={inputMode === "weight"}
                    onChange={(e) => setHolding(i, "price", e.target.value)}
                  />
                </td>
                <td>{Number.isFinite(h.marketValue) ? number(h.marketValue, 2) : "—"}</td>
                <td>
                  {h.errors.length === 0 ? (
                    h.warnings.length === 0 ? (
                      <span className="badge ok">ok</span>
                    ) : (
                      <span className="badge warn">{h.warnings.join("; ")}</span>
                    )
                  ) : (
                    <span className="badge bad">{h.errors.join("; ")}</span>
                  )}
                </td>
                <td>
                  <button type="button" className="dangerBtn" onClick={() => removeHolding(h.id)}>
                    Remove
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {holdingsStats.blockingIssues.length > 0 && (
          <div className="warnBox">
            {holdingsStats.blockingIssues.slice(0, 5).map((line) => (
              <div key={line}>{line}</div>
            ))}
            {holdingsStats.blockingIssues.length > 5 && <div>...and {holdingsStats.blockingIssues.length - 5} more</div>}
          </div>
        )}
        {holdingsStats.warnings.length > 0 && (
          <div className="warnBox soft">
            {holdingsStats.warnings.slice(0, 5).map((line) => (
              <div key={line}>{line}</div>
            ))}
            {holdingsStats.warnings.length > 5 && <div>...and {holdingsStats.warnings.length - 5} more</div>}
          </div>
        )}

        <h3>Import CSV</h3>
        <textarea
          rows={4}
          value={csvText}
          onChange={(e) => setCsvText(e.target.value)}
          placeholder="ticker,weight,shares,price&#10;AAPL,0.3,,&#10;MSFT,0.3,,"
        />
        <div className="actions">
          <button type="button" onClick={loadCsv}>
            Load CSV
          </button>
        </div>

        <h3>Portfolio Metrics</h3>
        <div className="grid three">
          <div className="metric">Raw Gross: {number(holdingsStats.rawGross, 4)}</div>
          <div className="metric">Raw Net: {number(holdingsStats.rawNet, 4)}</div>
          <div className="metric">Top-1 Concentration: {number(holdingsStats.top1 * 100, 2)}%</div>
          <div className="metric">Top-5 Concentration: {number(holdingsStats.top5 * 100, 2)}%</div>
          <div className="metric">Effective N: {number(holdingsStats.effectiveN, 2)}</div>
        </div>

        <button
          type="button"
          onClick={() =>
            setHoldings((v) => [
              ...v,
              {
                id: (v.reduce((mx, row) => Math.max(mx, row.id), 0) || 0) + 1,
                ticker: "",
                weight: 0,
                shares: 0,
                price: 0
              }
            ])
          }
        >
          Add Row
        </button>
        <button
          type="button"
          disabled={inputMode === "shares"}
          onClick={() => {
            const denom = holdingRows.reduce((acc, h) => acc + (h.errors.length === 0 ? Math.abs(h.weight) : 0), 0);
            if (denom <= 0) return;
            setHoldings((prev) =>
              prev.map((h) => ({
                ...h,
                weight: h.ticker ? h.weight / denom : h.weight
              }))
            );
          }}
        >
          Normalize
        </button>
      </section>

      <section className="card">
        <h2>Positions</h2>
        <div className="grid three">
          <label>
            Portfolio ID
            <input value={portfolioId} onChange={(e) => setPortfolioId(e.target.value)} />
          </label>
          <label>
            Snapshot As Of (optional)
            <input
              type="datetime-local"
              value={snapshotAsOf}
              onChange={(e) => setSnapshotAsOf(e.target.value)}
            />
          </label>
        </div>
        <div className="actions">
          <button type="button" disabled={loading !== ""} onClick={syncHoldingsToPositions}>
            {loading === "positions" ? "Running..." : "Sync Holdings -> Events"}
          </button>
          <button type="button" disabled={loading !== ""} onClick={runPositions}>
            {loading === "positions" ? "Running..." : "Refresh Positions Snapshot"}
          </button>
        </div>

        {positionSnapshot && (
          <>
            <h3>Snapshot Totals</h3>
            <div className="grid three">
              <div className="metric">Rows: {positionSnapshot.totals.tickers}</div>
              <div className="metric">Priced Rows: {positionSnapshot.totals.priced_rows}</div>
              <div className="metric">Market Value: {number(positionSnapshot.totals.market_value, 2)}</div>
              <div className="metric">Realized PnL: {number(positionSnapshot.totals.total_pnl, 2)}</div>
              <div className="metric">Unrealized PnL: {number(positionSnapshot.totals.unrealized_pnl, 2)}</div>
              <div className="metric">Economic PnL: {number(positionSnapshot.totals.economic_total_pnl, 2)}</div>
            </div>
            {positionSnapshot.totals.unpriced_tickers.length > 0 && (
              <div className="warnBox soft">
                Unpriced tickers: {positionSnapshot.totals.unpriced_tickers.join(", ")}
              </div>
            )}
            <div className="tableWrap">
              <table>
                <thead>
                  <tr>
                    <th>Ticker</th>
                    <th>Qty</th>
                    <th>Avg Cost</th>
                    <th>Mkt Px</th>
                    <th>Mkt Value</th>
                    <th>Unrealized</th>
                    <th>Total PnL</th>
                    <th>Price Date</th>
                  </tr>
                </thead>
                <tbody>
                  {positionSnapshot.rows.map((row) => (
                    <tr key={row.ticker}>
                      <td>{row.ticker}</td>
                      <td>{number(row.quantity, 2)}</td>
                      <td>{number(row.avg_cost, 4)}</td>
                      <td>{number(row.market_price ?? undefined, 4)}</td>
                      <td>{number(row.market_value ?? undefined, 2)}</td>
                      <td>{number(row.unrealized_pnl ?? undefined, 2)}</td>
                      <td>{number(row.economic_total_pnl ?? undefined, 2)}</td>
                      <td>{row.price_as_of ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}

        {positionEvents && (
          <>
            <h3>Recent Events ({positionEvents.count})</h3>
            <div className="tableWrap">
              <table>
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>Ticker</th>
                    <th>Type</th>
                    <th>Side</th>
                    <th>Qty</th>
                    <th>Price</th>
                  </tr>
                </thead>
                <tbody>
                  {positionEvents.events
                    .slice(-20)
                    .reverse()
                    .map((event) => (
                      <tr key={event.event_id}>
                        <td>{event.event_time}</td>
                        <td>{event.ticker}</td>
                        <td>{event.event_type}</td>
                        <td>{event.side ?? "—"}</td>
                        <td>{number(event.quantity, 2)}</td>
                        <td>{number(event.price ?? undefined, 4)}</td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>

      <section className="card">
        <h2>Analytics</h2>
        <button type="button" disabled={loading !== "" || normalizedHoldings.length === 0} onClick={runAnalytics}>
          {loading === "analytics" ? "Running..." : "Run Analytics"}
        </button>
        {analytics && (
          <>
            <h3>Coverage</h3>
            <p>
              Covered {analytics.coverage.covered}/{analytics.coverage.requested}
              {analytics.coverage.missing.length > 0
                ? ` (missing: ${analytics.coverage.missing.join(", ")})`
                : ""}
            </p>
            <p>
              Annualized Vol: <strong>{number(analytics.risk.annualized_vol, 4)}</strong>
            </p>
            <h3>Risk Decomposition</h3>
            <div className="riskBars">
              {([
                ["Factor", analytics.risk.variance.factor],
                ["Specific", analytics.risk.variance.specific]
              ] as const).map(([label, value]) => {
                const total = analytics.risk.variance.total || 1;
                const pct = Math.max(0, (value / total) * 100);
                return (
                  <div key={label} className="riskRow">
                    <div className="riskLabel">
                      {label}: {number(value, 6)} ({number(pct, 1)}%)
                    </div>
                    <div className="riskTrack">
                      <div className="riskFill" style={{ width: `${Math.min(100, pct)}%` }} />
                    </div>
                  </div>
                );
              })}
            </div>
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
            {exposureContext.length > 0 && (
              <>
                <h3>Exposure Context (History Percentile)</h3>
                <div className="tableWrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Factor</th>
                        <th>Current</th>
                        <th>Percentile</th>
                      </tr>
                    </thead>
                    <tbody>
                      {exposureContext.map((row) => (
                        <tr key={row.factor}>
                          <td>{row.factor}</td>
                          <td>{number(row.current, 4)}</td>
                          <td>{row.percentile === undefined ? "—" : `${number(row.percentile, 1)}%`}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {exposureTs?.start_date && exposureTs?.end_date && (
                  <p className="muted">
                    Context window: {exposureTs.start_date} to {exposureTs.end_date} ({exposureTs.rows.length} rows)
                  </p>
                )}
              </>
            )}
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
        <button type="button" disabled={loading !== "" || normalizedHoldings.length === 0} onClick={runScenario}>
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
        <div className="actions">
          <button type="button" disabled={loading !== "" || normalizedHoldings.length === 0} onClick={runAttribution}>
          {loading === "attribution" ? "Running..." : "Run Attribution Quality"}
          </button>
          <button type="button" disabled={qualityRows.length === 0} onClick={downloadQualityCsv}>
            Download Quality CSV
          </button>
        </div>
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
                <XAxis dataKey="label" minTickGap={24} />
                <YAxis />
                <Tooltip />
                <Line dataKey="explained" stroke="#1976d2" dot={false} />
                <Line dataKey="realized" stroke="#2e7d32" dot={false} />
                <Line dataKey="residual" stroke="#d32f2f" dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
        {qualityRows.length > 0 && (
          <div className="tableWrap">
            <table>
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Explained</th>
                  <th>Realized</th>
                  <th>Residual</th>
                  <th>Comparable Holdings</th>
                </tr>
              </thead>
              <tbody>
                {qualityRows.slice(-60).reverse().map((row) => (
                  <tr key={row.date}>
                    <td>{row.date}</td>
                    <td>{number(row.explained, 6)}</td>
                    <td>{number(row.realized, 6)}</td>
                    <td>{number(row.residual, 6)}</td>
                    <td>{row.comparableHoldings}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="card">
        <h2>LLM Explainer</h2>
        <div className="grid three">
          <label>
            Mode
            <select value={explainMode} onChange={(e) => setExplainMode(e.target.value)}>
              <option value="auto">auto</option>
              <option value="heuristic">heuristic</option>
              <option value="llm">llm</option>
            </select>
          </label>
          <label>
            LLM Model
            <input value={llmModel} onChange={(e) => setLlmModel(e.target.value)} />
          </label>
          <label>
            Top N
            <input
              type="number"
              min={1}
              max={10}
              value={explainTopN}
              onChange={(e) => setExplainTopN(Number(e.target.value))}
            />
          </label>
        </div>
        <button type="button" disabled={loading !== "" || normalizedHoldings.length === 0} onClick={runExplain}>
          {loading === "explain" ? "Running..." : "Run Explainer"}
        </button>
        {explain && (
          <div className="explainBlock">
            <p>
              Mode: <strong>{explain.explanation.mode}</strong>
              {explain.explanation.model ? ` (${explain.explanation.model})` : ""}
            </p>
            <h3>Overview</h3>
            <p>{explain.explanation.overview}</p>
            <h3>Key Views</h3>
            <ul>{explain.explanation.key_views.map((x, i) => <li key={`kv-${i}`}>{x}</li>)}</ul>
            <h3>Risk Watchouts</h3>
            <ul>{explain.explanation.risk_watchouts.map((x, i) => <li key={`rw-${i}`}>{x}</li>)}</ul>
            <h3>Drift Story</h3>
            <ul>{explain.explanation.drift_story.map((x, i) => <li key={`ds-${i}`}>{x}</li>)}</ul>
            <h3>Scenario Implications</h3>
            <ul>{explain.explanation.scenario_implications.map((x, i) => <li key={`si-${i}`}>{x}</li>)}</ul>
            <h3>Limitations</h3>
            <ul>{explain.explanation.limitations.map((x, i) => <li key={`lm-${i}`}>{x}</li>)}</ul>
          </div>
        )}
      </section>

      {error && <pre className="error">{error}</pre>}
    </main>
  );
}
