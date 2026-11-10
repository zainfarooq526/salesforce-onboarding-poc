async function request(path, options = {}) {
  const res = await fetch(`/api${path}`, options);
  const body = res.headers.get("content-type")?.includes("json") ? await res.json() : null;
  if (!res.ok) throw new Error(body?.error || `Request failed (${res.status})`);
  return body;
}

const json = (method, data) => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(data),
});

export const api = {
  health: () => request("/health"),
  fields: () => request("/salesforce/fields"),
  listImports: () => request("/imports"),
  getImport: (id) => request(`/imports/${id}`),
  upload: (file) => {
    const form = new FormData();
    form.append("file", file);
    return request("/imports", { method: "POST", body: form });
  },
  uploadSample: () => request("/imports/sample", { method: "POST" }),
  saveMapping: (id, mapping) => request(`/imports/${id}/mapping`, json("PUT", { mapping })),
  records: (id, status, page = 1, pageSize = 50) =>
    request(`/imports/${id}/records?page=${page}&page_size=${pageSize}${status ? `&status=${status}` : ""}`),
  sync: (id) => request(`/imports/${id}/sync`, { method: "POST" }),
  errorsCsvUrl: (id) => `/api/imports/${id}/errors.csv`,
};
