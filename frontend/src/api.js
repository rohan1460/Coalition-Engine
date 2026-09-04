const BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

async function request(path, options = {}) {
  let resp;
  try {
    resp = await fetch(BASE + path, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
  } catch (e) {
    throw new Error(
      `Cannot reach the backend at ${BASE}. Is it running? (${e.message})`
    );
  }
  const text = await resp.text();
  let data;
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { detail: text };
  }
  if (!resp.ok) {
    throw new Error(data.detail || `Request failed (${resp.status})`);
  }
  return data;
}

export const api = {
  base: BASE,
  health: () => request("/health"),
  catalog: () => request("/catalog"),
  initiate: (product_id) =>
    request("/checkout/initiate", {
      method: "POST",
      body: JSON.stringify({ product_id }),
    }),
  confirm: (correlation_id, otp) =>
    request("/checkout/confirm", {
      method: "POST",
      body: JSON.stringify({ correlation_id, otp }),
    }),
  pay: (payload) =>
    request("/checkout/pay", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  simulate: (product_id, simulate) =>
    request("/checkout/simulate", {
      method: "POST",
      body: JSON.stringify({ product_id, simulate }),
    }),
  audit: (correlation_id) => request(`/audit/${correlation_id}`),
};

export const rupees = (n) =>
  "₹" + Number(n || 0).toLocaleString("en-IN");
