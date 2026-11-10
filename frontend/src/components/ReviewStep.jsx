import { api } from "../api.js";
import RecordsTable from "./RecordsTable.jsx";

export default function ReviewStep({ job, busy, onBack, onSync }) {
  const ready = job.valid_rows;
  return (
    <section>
      <div className="section-head">
        <div>
          <h2>Review before syncing</h2>
          <p className="muted">
            Records were cleaned (names, emails, phone numbers, websites), validated against Lead rules, and
            duplicates inside the file were merged into one record.
          </p>
        </div>
      </div>

      <div className="stats">
        <Stat label="Rows in file" value={job.total_rows} />
        <Stat label="Ready to sync" value={ready} tone="ok" />
        <Stat label="Duplicates merged" value={job.duplicate_rows} tone="info" />
        <Stat label="Need fixing" value={job.invalid_rows} tone={job.invalid_rows ? "bad" : ""} />
      </div>

      <RecordsTable
        jobId={job.id}
        version={job.valid_rows + job.invalid_rows}
        tabs={[
          { label: "All", status: null, count: job.total_rows },
          { label: "Ready", status: "valid", count: ready },
          { label: "Duplicates", status: "duplicate", count: job.duplicate_rows },
          { label: "Invalid", status: "invalid", count: job.invalid_rows },
        ]}
      />

      <div className="actions">
        <button className="ghost" onClick={onBack} disabled={busy}>
          ← Change mapping
        </button>
        <div className="row">
          {(job.invalid_rows > 0 || job.duplicate_rows > 0) && (
            <a className="button secondary" href={api.errorsCsvUrl(job.id)}>
              Download exceptions CSV
            </a>
          )}
          <button disabled={!ready || busy} onClick={onSync}>
            {busy ? "Syncing…" : `Sync ${ready} records to Salesforce →`}
          </button>
        </div>
      </div>
    </section>
  );
}

export function Stat({ label, value, tone = "" }) {
  return (
    <div className={`stat ${tone}`}>
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}
