"use client";

import { useAuth } from "@clerk/nextjs";
import { useEffect, useState } from "react";
import styles from "./page.module.css";

const API_BASE = process.env.NEXT_PUBLIC_API_GATEWAY_URL ?? "http://localhost:8000";

type Me = {
  id: string;
  tenant_id: string | null;
  email: string | null;
  role: string | null;
  plan_tier: string | null;
};

type Signal = {
  id: number;
  instrument: string;
  timeframe: string;
  ts: string;
  direction: string;
  entry_price: string;
  stop_loss: string;
  take_profit_1: string | null;
  confidence: string;
};

// Distinct fetch states rather than a single boolean/error string pair: a
// 403 from /trading/signals (wrong plan tier) is a normal, expected outcome
// here -- not the same thing as a network failure -- and the page needs to
// tell those apart to show the right message (Slice 2,
// docs/post-research-vertical-slices.md).
type SignalsState =
  | { status: "loading" }
  | { status: "forbidden" }
  | { status: "error"; message: string }
  | { status: "ok"; signals: Signal[] };

function Dashboard() {
  const { getToken } = useAuth();
  const [me, setMe] = useState<Me | null>(null);
  const [signalsState, setSignalsState] = useState<SignalsState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;

    async function load() {
      const token = await getToken();
      const headers = { Authorization: `Bearer ${token}` };

      const meResp = await fetch(`${API_BASE}/me`, { headers });
      if (!cancelled && meResp.ok) {
        setMe(await meResp.json());
      }

      const signalsResp = await fetch(`${API_BASE}/trading/signals?limit=20`, { headers });
      if (cancelled) return;
      if (signalsResp.status === 403) {
        setSignalsState({ status: "forbidden" });
      } else if (!signalsResp.ok) {
        setSignalsState({ status: "error", message: `${signalsResp.status} ${signalsResp.statusText}` });
      } else {
        setSignalsState({ status: "ok", signals: await signalsResp.json() });
      }
    }

    load().catch((err) => {
      if (!cancelled) setSignalsState({ status: "error", message: String(err) });
    });

    return () => {
      cancelled = true;
    };
  }, [getToken]);

  return (
    <main className={styles.main}>
      <section>
        <h1>Signals</h1>
        {me && (
          <p className={styles.planTier}>
            Plan: <strong>{me.plan_tier ?? "no tenant"}</strong>
          </p>
        )}

        {signalsState.status === "loading" && <p>Loading...</p>}

        {signalsState.status === "forbidden" && (
          <p>
            Your current plan doesn&apos;t include signal access. Upgrade to{" "}
            <code>signal_only</code> or <code>auto_execute</code> to see signals here.
          </p>
        )}

        {signalsState.status === "error" && (
          <p role="alert">Couldn&apos;t load signals: {signalsState.message}</p>
        )}

        {signalsState.status === "ok" && (
          <table className={styles.signalsTable}>
            <thead>
              <tr>
                <th>Time</th>
                <th>Instrument</th>
                <th>TF</th>
                <th>Direction</th>
                <th>Entry</th>
                <th>Stop</th>
                <th>TP1</th>
                <th>Confidence</th>
              </tr>
            </thead>
            <tbody>
              {signalsState.signals.map((s) => (
                <tr key={s.id}>
                  <td>{new Date(s.ts).toLocaleString()}</td>
                  <td>{s.instrument}</td>
                  <td>{s.timeframe}</td>
                  <td className={s.direction === "long" ? styles.long : styles.short}>
                    {s.direction}
                  </td>
                  <td>{s.entry_price}</td>
                  <td>{s.stop_loss}</td>
                  <td>{s.take_profit_1 ?? "-"}</td>
                  <td>{s.confidence}</td>
                </tr>
              ))}
              {signalsState.signals.length === 0 && (
                <tr>
                  <td colSpan={8}>No signals yet.</td>
                </tr>
              )}
            </tbody>
          </table>
        )}
      </section>
    </main>
  );
}

export default function Home() {
  const { isLoaded, isSignedIn } = useAuth();

  if (!isLoaded) {
    return <main className={styles.main} />;
  }

  if (!isSignedIn) {
    return (
      <main className={styles.main}>
        <p>Sign in to see your signals.</p>
      </main>
    );
  }

  return <Dashboard />;
}
