import { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";
import Stepper from "./components/Stepper.jsx";
import UploadStep from "./components/UploadStep.jsx";
import MappingStep from "./components/MappingStep.jsx";
import ReviewStep from "./components/ReviewStep.jsx";
import ResultsStep from "./components/ResultsStep.jsx";
import History from "./components/History.jsx";

const STEP_FOR_STATUS = { uploaded: 1, mapped: 2, synced: 3, partial: 3 };

export default function App() {
  const [health, setHealth] = useState(null);
  const [fields, setFields] = useState([]);
  const [job, setJob] = useState(null);
  const [step, setStep] = useState(0);
  const [history, setHistory] = useState([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const refreshHistory = useCallback(() => api.listImports().then((r) => setHistory(r.items)).catch(() => {}), []);

  useEffect(() => {
    api.health().then(setHealth).catch((e) => setError(e.message));
    api.fields().then((r) => setFields(r.fields));
    refreshHistory();
  }, [refreshHistory]);

  // Wraps an API call: shows a spinner, surfaces errors, and moves the wizard on success.
  const run = async (fn, nextStep) => {
    setBusy(true);
    setError("");
    try {
      const result = await fn();
      if (result) setJob((prev) => ({ ...prev, ...result }));
      if (nextStep !== undefined) setStep(nextStep);
      refreshHistory();
      return result;
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const openJob = (id) =>
    run(async () => {
      const j = await api.getImport(id);
      setJob(j);
      setStep(STEP_FOR_STATUS[j.status] ?? 1);
    });

  const reset = () => {
    setJob(null);
    setStep(0);
    setError("");
  };

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <div className="logo" aria-hidden>
            ⇪
          </div>
          <div>
            <h1>Lead Onboarding</h1>
            <p>CSV → field mapping → dedupe → Salesforce</p>
          </div>
        </div>
        {health && (
          <div className="badges">
            <span className={`badge ${health.salesforce === "live" ? "badge-live" : ""}`}>
              {health.salesforce === "live" ? "Live Salesforce org" : "Mock Salesforce org"}
            </span>
            <span className="badge">{health.database === "postgres" ? "PostgreSQL" : "SQLite"}</span>
          </div>
        )}
      </header>

      <div className="layout">
        <main className="panel">
          <Stepper step={step} />
          {error && (
            <div className="alert" role="alert">
              {error}
              <button className="link" onClick={() => setError("")}>
                Dismiss
              </button>
            </div>
          )}
          {step === 0 && (
            <UploadStep
              busy={busy}
              onUpload={(file) => run(() => api.upload(file), 1)}
              onSample={() => run(() => api.uploadSample(), 1)}
            />
          )}
          {step === 1 && job && (
            <MappingStep
              job={job}
              fields={fields}
              busy={busy}
              onBack={reset}
              onSubmit={(mapping) => run(() => api.saveMapping(job.id, mapping), 2)}
            />
          )}
          {step === 2 && job && (
            <ReviewStep
              job={job}
              busy={busy}
              onBack={() => setStep(1)}
              onSync={() => run(() => api.sync(job.id), 3)}
            />
          )}
          {step === 3 && job && <ResultsStep job={job} onNew={reset} />}
        </main>

        <aside className="panel side">
          <History items={history} activeId={job?.id} onOpen={openJob} />
        </aside>
      </div>
    </div>
  );
}
