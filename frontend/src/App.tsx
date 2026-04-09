import { useEffect, useMemo, useRef, useState } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";

type Telemetry = {
  speed: number;
  target_speed: number;
  throttle: number;
  timestamp?: number;
  sim_time_s?: number;
};

type Control = {
  target_speed: number;
  kp: number;
  ki: number;
  kd: number;
};

type Point = {
  t: number;
  speed: number;
  target: number;
};

type AnalysisSummary = {
  sample_count: number;
  duration_s: number;
  target_ref_m_s: number | null;
  overshoot_m_s: number | null;
  settling_time_s: number | null;
  steady_state_error_m_s: number | null;
  tolerance_m_s?: number | null;
  mean_abs_error_m_s?: number | null;
};

const API_BASE = "http://127.0.0.1:8000";
const WS_BASE = "ws://127.0.0.1:8000/ws/telemetry";
const MAX_POINTS = 120;

async function fetchControl(): Promise<Control> {
  const res = await fetch(`${API_BASE}/control/`);
  if (!res.ok) {
    throw new Error(`Control request failed (${res.status})`);
  }
  return (await res.json()) as Control;
}

async function pushControl(control: Control): Promise<void> {
  const res = await fetch(`${API_BASE}/control/`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(control),
  });
  if (!res.ok) {
    throw new Error(`Control update failed (${res.status})`);
  }
}

async function resetSimulationRun(): Promise<Telemetry> {
  const res = await fetch(`${API_BASE}/simulation/reset`, { method: "POST" });
  if (!res.ok) {
    throw new Error(`Reset run failed (${res.status})`);
  }
  return (await res.json()) as Telemetry;
}

function throttleColor(percent: number): string {
  if (percent < 35) return "#10b981";
  if (percent < 70) return "#f59e0b";
  return "#ef4444";
}

export default function App() {
  const [telemetry, setTelemetry] = useState<Telemetry>({
    speed: 0,
    target_speed: 120,
    throttle: 0,
  });
  const [control, setControl] = useState<Control>({
    target_speed: 120,
    kp: 0.5,
    ki: 0.1,
    kd: 0.05,
  });
  const [series, setSeries] = useState<Point[]>([]);
  const [errorText, setErrorText] = useState<string>("");
  const [socketStatus, setSocketStatus] = useState<"connecting" | "live" | "reconnecting">("connecting");
  const elapsedRef = useRef(0);
  const [analysisSummary, setAnalysisSummary] = useState<AnalysisSummary | null>(null);
  const [plotNonce, setPlotNonce] = useState(0);

  useEffect(() => {
    let canceled = false;
    fetchControl()
      .then((c) => {
        if (!canceled) setControl(c);
      })
      .catch((err) => {
        if (!canceled) setErrorText(String(err));
      });
    return () => {
      canceled = true;
    };
  }, []);

  useEffect(() => {
    let active = true;
    let ws: WebSocket | null = null;
    let reconnectTimer: number | null = null;
    let startTsMs = Date.now() - elapsedRef.current * 1000;

    const connect = () => {
      if (!active) return;
      setSocketStatus((prev) => (prev === "live" ? "live" : "connecting"));
      ws = new WebSocket(WS_BASE);

      ws.onopen = () => {
        if (!active) return;
        setErrorText("");
        setSocketStatus("live");
      };

      ws.onmessage = (event) => {
        if (!active) return;
        try {
          const t = JSON.parse(event.data) as Telemetry;
          const tSec =
            typeof t.sim_time_s === "number"
              ? t.sim_time_s
              : Math.max(0, ((t.timestamp ?? Date.now() / 1000) * 1000 - startTsMs) / 1000);
          setTelemetry(t);
          setSeries((old) => {
            const point: Point = {
              t: Number(tSec.toFixed(2)),
              speed: t.speed,
              target: t.target_speed,
            };
            elapsedRef.current = point.t;
            return [...old.slice(-(MAX_POINTS - 1)), point];
          });
        } catch (err) {
          setErrorText(`WS parse error: ${String(err)}`);
        }
      };

      ws.onerror = () => {
        if (!active) return;
        setErrorText("WebSocket connection error. Retrying...");
      };

      ws.onclose = () => {
        if (!active) return;
        setSocketStatus("reconnecting");
        reconnectTimer = window.setTimeout(() => {
          startTsMs = Date.now() - elapsedRef.current * 1000;
          connect();
        }, 900);
      };
    };

    connect();
    return () => {
      active = false;
      if (reconnectTimer !== null) {
        window.clearTimeout(reconnectTimer);
      }
      if (ws) {
        ws.close();
      }
    };
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      pushControl(control).catch((err) => setErrorText(String(err)));
    }, 180);
    return () => window.clearTimeout(timer);
  }, [control]);

  const throttlePct = useMemo(
    () => Math.max(0, Math.min(100, telemetry.throttle * 100)),
    [telemetry.throttle],
  );

  async function resetAnalysisLog() {
    const res = await fetch(`${API_BASE}/analysis/log/reset`, { method: "POST" });
    if (!res.ok) throw new Error(`Reset log failed (${res.status})`);
    setAnalysisSummary(null);
    setPlotNonce((n) => n + 1);
  }

  async function refreshAnalysisSummary() {
    const res = await fetch(`${API_BASE}/analysis/summary`);
    if (!res.ok) throw new Error(`Summary failed (${res.status})`);
    const data = (await res.json()) as AnalysisSummary;
    setAnalysisSummary(data);
  }

  async function newTestRun() {
    const t = await resetSimulationRun();
    setTelemetry(t);
    setSeries([]);
    elapsedRef.current = 0;
    setAnalysisSummary(null);
    setPlotNonce((n) => n + 1);
    setErrorText("");
  }

  return (
    <main className="dashboard">
      <header>
        <h1>Pit Wall ECU Dashboard</h1>
        <p>
          Live telemetry + PID control tuning
          {" · "}
          <b>{socketStatus === "live" ? "WS LIVE" : socketStatus.toUpperCase()}</b>
        </p>
        <div className="header-actions">
          <button
            type="button"
            className="btn-new-test"
            title="Zero speed, reset PID/actuator, clear analysis log, restart chart time"
            onClick={() => newTestRun().catch((e) => setErrorText(String(e)))}
          >
            New test (reset run)
          </button>
        </div>
      </header>

      {errorText ? <div className="error-banner">{errorText}</div> : null}

      <section className="grid">
        <article className="panel chart-panel">
          <h2>Speed vs Time</h2>
          <ResponsiveContainer width="100%" height={320}>
            <LineChart data={series}>
              <CartesianGrid strokeDasharray="3 3" stroke="#2f3744" />
              <XAxis dataKey="t" stroke="#b8c3d4" />
              <YAxis stroke="#b8c3d4" />
              <Tooltip />
              <Legend />
              <Line
                type="monotone"
                dataKey="speed"
                name="Actual speed"
                dot={false}
                strokeWidth={2.2}
                stroke="#60a5fa"
                isAnimationActive={false}
              />
              <Line
                type="monotone"
                dataKey="target"
                name="Target speed"
                dot={false}
                strokeWidth={2}
                stroke="#f97316"
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </article>

        <article className="panel gauge-panel">
          <h2>Throttle</h2>
          <div className="gauge-wrap">
            <div
              className="gauge-ring"
              style={{
                background: `conic-gradient(${throttleColor(throttlePct)} ${throttlePct}%, #1f2937 ${throttlePct}% 100%)`,
              }}
            >
              <div className="gauge-inner">
                <span>{throttlePct.toFixed(0)}%</span>
              </div>
            </div>
          </div>
          <div className="readout">
            <span>Speed: {telemetry.speed.toFixed(2)} m/s</span>
            <span>Target: {telemetry.target_speed.toFixed(2)} m/s</span>
          </div>
        </article>

        <article className="panel controls-panel">
          <h2>Controls</h2>
          <label>
            Target Speed: <b>{control.target_speed.toFixed(1)} m/s</b>
            <input
              type="range"
              min={0}
              max={200}
              step={0.5}
              value={control.target_speed}
              onChange={(e) =>
                setControl((prev) => ({
                  ...prev,
                  target_speed: Number(e.target.value),
                }))
              }
            />
          </label>
          <label>
            Kp: <b>{control.kp.toFixed(2)}</b>
            <input
              type="range"
              min={0}
              max={2}
              step={0.01}
              value={control.kp}
              onChange={(e) =>
                setControl((prev) => ({
                  ...prev,
                  kp: Number(e.target.value),
                }))
              }
            />
          </label>
          <label>
            Ki: <b>{control.ki.toFixed(2)}</b>
            <input
              type="range"
              min={0}
              max={1}
              step={0.01}
              value={control.ki}
              onChange={(e) =>
                setControl((prev) => ({
                  ...prev,
                  ki: Number(e.target.value),
                }))
              }
            />
          </label>
          <label>
            Kd: <b>{control.kd.toFixed(2)}</b>
            <input
              type="range"
              min={0}
              max={1}
              step={0.01}
              value={control.kd}
              onChange={(e) =>
                setControl((prev) => ({
                  ...prev,
                  kd: Number(e.target.value),
                }))
              }
            />
          </label>
        </article>

        <article className="panel analysis-panel">
          <h2>Phase 6 — Logging &amp; analysis</h2>
          <p className="analysis-hint">
            Backend logs speed, throttle, control error, and time (s since log start). Reset before a test, run the
            sim, then refresh summary or export.
          </p>
          <div className="analysis-actions">
            <button type="button" onClick={() => resetAnalysisLog().catch((e) => setErrorText(String(e)))}>
              Reset log
            </button>
            <button type="button" onClick={() => refreshAnalysisSummary().catch((e) => setErrorText(String(e)))}>
              Refresh summary
            </button>
            <a className="analysis-link" href={`${API_BASE}/analysis/export.csv`} target="_blank" rel="noreferrer">
              Download CSV
            </a>
            <button type="button" onClick={() => setPlotNonce((n) => n + 1)}>
              Refresh plot
            </button>
          </div>
          {analysisSummary ? (
            <dl className="analysis-metrics">
              <div>
                <dt>Samples</dt>
                <dd>{analysisSummary.sample_count}</dd>
              </div>
              <div>
                <dt>Duration</dt>
                <dd>{analysisSummary.duration_s.toFixed(2)} s</dd>
              </div>
              <div>
                <dt>Target ref</dt>
                <dd>
                  {analysisSummary.target_ref_m_s != null ? `${analysisSummary.target_ref_m_s.toFixed(2)} m/s` : "—"}
                </dd>
              </div>
              <div>
                <dt>Overshoot</dt>
                <dd>
                  {analysisSummary.overshoot_m_s != null ? `${analysisSummary.overshoot_m_s.toFixed(3)} m/s` : "—"}
                </dd>
              </div>
              <div>
                <dt>Settling time</dt>
                <dd>
                  {analysisSummary.settling_time_s != null
                    ? `${analysisSummary.settling_time_s.toFixed(2)} s`
                    : "—"}
                </dd>
              </div>
              <div>
                <dt>Steady-state |error|</dt>
                <dd>
                  {analysisSummary.steady_state_error_m_s != null
                    ? `${analysisSummary.steady_state_error_m_s.toFixed(3)} m/s`
                    : "—"}
                </dd>
              </div>
              <div>
                <dt>Mean |error|</dt>
                <dd>
                  {analysisSummary.mean_abs_error_m_s != null
                    ? `${analysisSummary.mean_abs_error_m_s.toFixed(3)} m/s`
                    : "—"}
                </dd>
              </div>
            </dl>
          ) : (
            <p className="analysis-placeholder">No summary yet — click &quot;Refresh summary&quot;.</p>
          )}
          <div className="analysis-plot-wrap">
            {analysisSummary && analysisSummary.sample_count >= 2 ? (
              <img
                className="analysis-plot"
                src={`${API_BASE}/analysis/plot.png?nonce=${plotNonce}`}
                alt="Speed, target, and throttle from logged run"
              />
            ) : (
              <p className="analysis-placeholder">Plot appears after at least two logged samples (refresh plot).</p>
            )}
          </div>
        </article>
      </section>
    </main>
  );
}
