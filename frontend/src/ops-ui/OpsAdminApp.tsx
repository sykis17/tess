import { useEffect, useState } from "react";
import {
  clearChaos,
  clearOpsToken,
  fetchProviders,
  fetchRouting,
  forceActive,
  getOpsToken,
  OpsApiError,
  probeNow,
  setOpsToken,
  simulateUnhealthy,
  type OpsProvider,
  type OpsRoutingPayload,
} from "./opsApi";

function formatResult(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

export function OpsAdminApp() {
  const [tokenInput, setTokenInput] = useState(() => getOpsToken() ?? "");
  const [hasToken, setHasToken] = useState(() => Boolean(getOpsToken()));
  const [routing, setRouting] = useState<OpsRoutingPayload | null>(null);
  const [providers, setProviders] = useState<OpsProvider[]>([]);
  const [busy, setBusy] = useState(false);
  const [lastResult, setLastResult] = useState<string>("");
  const [error, setError] = useState<string>("");

  const activeId = routing?.routing.active_provider_id ?? null;

  async function loadStatus(): Promise<{ active_provider_id: string | null; providers: number }> {
    const [nextRouting, nextProviders] = await Promise.all([
      fetchRouting(),
      fetchProviders(),
    ]);
    setRouting(nextRouting);
    setProviders(nextProviders);
    return {
      active_provider_id: nextRouting.routing.active_provider_id,
      providers: nextProviders.length,
    };
  }

  async function runAction(label: string, action: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try {
      const result = await action();
      setLastResult(`${label}\n${formatResult(result)}`);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
      setLastResult("");
      if (err instanceof OpsApiError && (err.status === 401 || err.status === 403)) {
        clearOpsToken();
        setHasToken(false);
      }
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (!hasToken) {
      return;
    }
    let cancelled = false;
    setBusy(true);
    setError("");
    void loadStatus()
      .then(() => {
        if (!cancelled) {
          setLastResult("");
        }
      })
      .catch((err: unknown) => {
        if (cancelled) {
          return;
        }
        const message = err instanceof Error ? err.message : String(err);
        setError(message);
        if (err instanceof OpsApiError && (err.status === 401 || err.status === 403)) {
          clearOpsToken();
          setHasToken(false);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setBusy(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [hasToken]);

  function saveToken() {
    const trimmed = tokenInput.trim();
    if (!trimmed) {
      setError("Enter an admin Bearer token");
      return;
    }
    setOpsToken(trimmed);
    setHasToken(true);
    setError("");
  }

  function onClearToken() {
    clearOpsToken();
    setTokenInput("");
    setHasToken(false);
    setRouting(null);
    setProviders([]);
    setLastResult("");
    setError("");
  }

  return (
    <main className="ops-page">
      <header className="ops-header">
        <h1>TESS Ops</h1>
        <p className="ops-sub">Take offline / force active (demo controls)</p>
      </header>

      <section className="ops-card">
        <h2>Admin token</h2>
        <p className="ops-hint">
          Stored in this browser only (<code>localStorage</code>). Not embedded in the
          build.
        </p>
        <div className="ops-row">
          <input
            type="password"
            autoComplete="off"
            placeholder="Bearer token"
            value={tokenInput}
            onChange={(e) => setTokenInput(e.target.value)}
            disabled={busy}
          />
          <button type="button" onClick={saveToken} disabled={busy}>
            Save
          </button>
          <button
            type="button"
            className="ops-secondary"
            onClick={onClearToken}
            disabled={busy}
          >
            Clear
          </button>
        </div>
      </section>

      {hasToken && (
        <>
          <section className="ops-card">
            <div className="ops-row ops-row-between">
              <h2>Routing</h2>
              <button
                type="button"
                className="ops-secondary"
                disabled={busy}
                onClick={() => void runAction("Refresh", () => loadStatus())}
              >
                Refresh
              </button>
            </div>
            <p>
              Active: <strong>{activeId ?? "(none)"}</strong>
            </p>
            {routing?.active?.ws_base_url && (
              <p className="ops-muted">WS: {routing.active.ws_base_url}</p>
            )}
            <div className="ops-row">
              <button
                type="button"
                disabled={busy || !activeId}
                onClick={() =>
                  void runAction("Take offline", async () => {
                    const result = await simulateUnhealthy(activeId!, true);
                    await loadStatus();
                    return result;
                  })
                }
              >
                Take offline (active)
              </button>
              <button
                type="button"
                className="ops-secondary"
                disabled={busy || !activeId}
                onClick={() =>
                  void runAction("Bring online", async () => {
                    const cleared = await simulateUnhealthy(activeId!, false);
                    await clearChaos(activeId!);
                    await loadStatus();
                    return cleared;
                  })
                }
              >
                Bring online
              </button>
              <button
                type="button"
                className="ops-secondary"
                disabled={busy}
                onClick={() =>
                  void runAction("Probe now", async () => {
                    const result = await probeNow();
                    await loadStatus();
                    return result;
                  })
                }
              >
                Probe now
              </button>
            </div>
          </section>

          <section className="ops-card">
            <h2>Providers</h2>
            <ul className="ops-provider-list">
              {providers.map((p) => {
                const isActive = p.id === activeId;
                const offline =
                  p.simulate_unhealthy ||
                  (p.chaos?.enabled === true && p.chaos.kind === "mark_unhealthy");
                return (
                  <li key={p.id} className={isActive ? "is-active" : undefined}>
                    <div>
                      <strong>{p.name}</strong>{" "}
                      <span className="ops-muted">({p.id})</span>
                      {isActive && <span className="ops-badge">active</span>}
                      {offline && (
                        <span className="ops-badge ops-badge-warn">simulated off</span>
                      )}
                    </div>
                    <button
                      type="button"
                      disabled={busy || isActive}
                      onClick={() =>
                        void runAction(`Force active ${p.id}`, async () => {
                          const result = await forceActive(p.id);
                          await loadStatus();
                          return result;
                        })
                      }
                    >
                      Force active
                    </button>
                  </li>
                );
              })}
            </ul>
          </section>
        </>
      )}

      {error && (
        <section className="ops-card ops-error">
          <h2>Error</h2>
          <pre>{error}</pre>
        </section>
      )}

      {lastResult && (
        <section className="ops-card">
          <h2>Last action</h2>
          <pre>{lastResult}</pre>
        </section>
      )}
    </main>
  );
}
