import { useEffect, useState } from "react";
import { api } from "../api.js";

const STATUS_LABEL = {
  valid: "Ready",
  invalid: "Invalid",
  duplicate: "Duplicate",
  synced: "Synced",
  failed: "Failed",
  pending: "Pending",
};

export default function RecordsTable({ jobId, tabs, showSalesforce = false, version = 0 }) {
  const [tab, setTab] = useState(tabs[0].status);
  const [page, setPage] = useState(1);
  const [data, setData] = useState({ items: [], total: 0, page_size: 25 });
  const [loading, setLoading] = useState(false);

  useEffect(() => setPage(1), [tab]);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    api
      .records(jobId, tab, page, 25)
      .then((d) => alive && setData(d))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [jobId, tab, page, version]);

  const pages = Math.max(1, Math.ceil(data.total / data.page_size));

  return (
    <div>
      <div className="tabs" role="tablist">
        {tabs.map((t) => (
          <button
            key={t.label}
            role="tab"
            aria-selected={tab === t.status}
            className={tab === t.status ? "tab active" : "tab"}
            onClick={() => setTab(t.status)}
          >
            {t.label}
            {t.count !== undefined && <span className="count">{t.count}</span>}
          </button>
        ))}
      </div>

      <div className={`table-wrap ${loading ? "loading" : ""}`}>
        <table className="records">
          <thead>
            <tr>
              <th>Row</th>
              <th>Name</th>
              <th>Email</th>
              <th>Company</th>
              <th>Status</th>
              {showSalesforce && <th>Salesforce</th>}
              <th>Notes</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((r) => {
              const m = r.mapped || {};
              const name = [m.FirstName, m.LastName].filter(Boolean).join(" ");
              return (
                <tr key={r.id}>
                  <td className="num">{r.row_number}</td>
                  <td>{name || <span className="muted">—</span>}</td>
                  <td className="mono">{m.Email || <span className="muted">—</span>}</td>
                  <td>{m.Company || <span className="muted">—</span>}</td>
                  <td>
                    <span className={`status s-${r.status}`}>{STATUS_LABEL[r.status] || r.status}</span>
                  </td>
                  {showSalesforce && (
                    <td className="mono small">
                      {r.sf_id ? (
                        <>
                          {r.sf_id}
                          <span className={`action a-${r.sf_action}`}>{r.sf_action}</span>
                        </>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                  )}
                  <td className="notes">
                    {r.errors.map((e) => (
                      <div key={e} className="note err">
                        {e}
                      </div>
                    ))}
                    {r.sf_error && <div className="note err">{r.sf_error}</div>}
                    {r.duplicate_of && <div className="note">Duplicate of row {r.duplicate_of} (merged)</div>}
                    {r.merged_from?.length > 0 && (
                      <div className="note ok">
                        Merged {r.merged_from.length === 1 ? "row" : "rows"} {r.merged_from.join(", ")} into this
                        record
                      </div>
                    )}
                    {r.warnings.map((w) => (
                      <div key={w} className="note warn">
                        {w}
                      </div>
                    ))}
                  </td>
                </tr>
              );
            })}
            {!data.items.length && (
              <tr>
                <td colSpan={showSalesforce ? 7 : 6} className="empty">
                  {loading ? "Loading…" : "Nothing here."}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {pages > 1 && (
        <div className="pager">
          <button className="ghost" disabled={page <= 1} onClick={() => setPage(page - 1)}>
            ← Prev
          </button>
          <span className="muted">
            Page {page} of {pages} · {data.total} rows
          </span>
          <button className="ghost" disabled={page >= pages} onClick={() => setPage(page + 1)}>
            Next →
          </button>
        </div>
      )}
    </div>
  );
}
