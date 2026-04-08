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
          const tSec = Math.max(0, ((t.timestamp ?? Date.now() / 1000) * 1000 - startTsMs) / 1000);
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

  return (
    <main className="dashboard">
      <header>
        <h1>Pit Wall ECU Dashboard</h1>
        <p>
          Live telemetry + PID control tuning
          {" · "}
          <b>{socketStatus === "live" ? "WS LIVE" : socketStatus.toUpperCase()}</b>
        </p>
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
      </section>
    </main>
  );
}
