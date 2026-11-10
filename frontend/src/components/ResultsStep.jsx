import { api } from "../api.js";
import RecordsTable from "./RecordsTable.jsx";
import { Stat } from "./ReviewStep.jsx";

export default function ResultsStep({ job, onNew }) {
  const synced = job.created_rows + job.updated_rows;
  return (
    <section>
      <div className="section-head">
        <div>
          <h2>{job.failed_rows ? "Sync finished with some errors" : "Sync complete"}</h2>
          <p className="muted">
            Existing Leads were matched by email (or name + company) and updated instead of duplicated.
          </p>
        </div>
      </div>

      <div className="stats">
        <Stat label="New Leads created" value={job.created_rows} tone="ok" />
        <Stat label="Existing Leads updated" value={job.updated_rows} tone="info" />
        <Stat label="Failed" value={job.failed_rows} tone={job.failed_rows ? "bad" : ""} />
        <Stat label="Skipped (invalid + duplicate)" value={job.invalid_rows + job.duplicate_rows} />
      </div>

      <RecordsTable
        jobId={job.id}
        showSalesforce
        version={synced}
        tabs={[
          { label: "Synced", status: "synced", count: synced },
          { label: "Failed", status: "failed", count: job.failed_rows },
          { label: "All rows", status: null, count: job.total_rows },
        ]}
      />

      <div className="actions">
        <a className="button secondary" href={api.errorsCsvUrl(job.id)}>
          Download exceptions CSV
        </a>
        <button onClick={onNew}>Start a new import</button>
      </div>
    </section>
  );
}
