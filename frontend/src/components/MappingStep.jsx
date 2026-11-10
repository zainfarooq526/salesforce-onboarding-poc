import { useMemo, useState } from "react";

export default function MappingStep({ job, fields, busy, onBack, onSubmit }) {
  const [mapping, setMapping] = useState(() => job.mapping || job.suggested_mapping || {});
  const suggested = job.suggested_mapping || {};

  const used = useMemo(() => Object.values(mapping).filter(Boolean), [mapping]);
  const hasLast = used.includes("LastName") || used.includes("_FullName");
  const hasCompany = used.includes("Company");
  const dupes = used.filter((f, i) => used.indexOf(f) !== i);
  const ready = hasLast && hasCompany && dupes.length === 0;

  const samples = (header) =>
    (job.preview || [])
      .map((r) => r[header])
      .filter(Boolean)
      .slice(0, 3);

  return (
    <section>
      <div className="section-head">
        <div>
          <h2>Map columns to Salesforce Lead fields</h2>
          <p className="muted">
            <strong>{job.filename}</strong> · {job.total_rows} rows · {job.headers.length} columns. Suggestions are
            pre-filled; change anything that looks wrong.
          </p>
        </div>
      </div>

      <div className="checklist">
        <Check ok={hasLast} label="Last Name (or Full Name) mapped" />
        <Check ok={hasCompany} label="Company mapped" />
        <Check ok={dupes.length === 0} label="Each field used once" />
      </div>

      <div className="table-wrap">
        <table className="mapping">
          <thead>
            <tr>
              <th>CSV column</th>
              <th>Sample values</th>
              <th>Salesforce field</th>
            </tr>
          </thead>
          <tbody>
            {job.headers.map((h) => {
              const value = mapping[h] || "";
              const isSuggested = value && value === suggested[h];
              const isDupe = value && dupes.includes(value);
              return (
                <tr key={h}>
                  <td className="col-name">{h}</td>
                  <td className="samples">
                    <div>
                      {samples(h).map((s, i) => (
                        <span key={i} className="sample">
                          {s}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td>
                    <div className="select-wrap">
                      <select
                        value={value}
                        className={isDupe ? "invalid" : ""}
                        onChange={(e) => setMapping({ ...mapping, [h]: e.target.value || null })}
                        aria-label={`Salesforce field for ${h}`}
                      >
                        <option value="">— Don't import —</option>
                        {fields.map((f) => (
                          <option key={f.name} value={f.name}>
                            {f.label}
                            {f.required ? " *" : ""}
                          </option>
                        ))}
                      </select>
                      {isSuggested && <span className="chip">auto</span>}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="actions">
        <button className="ghost" onClick={onBack} disabled={busy}>
          Start over
        </button>
        <button disabled={!ready || busy} onClick={() => onSubmit(mapping)}>
          {busy ? "Validating…" : "Validate & find duplicates →"}
        </button>
      </div>
    </section>
  );
}

function Check({ ok, label }) {
  return <span className={`check ${ok ? "ok" : ""}`}>{ok ? "✓" : "○"} {label}</span>;
}
