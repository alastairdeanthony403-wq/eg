/**
 * src/utils/api.js
 *
 * Central API configuration.
 * Set VITE_API_URL (Vite) or REACT_APP_API_URL (CRA) in your Render env vars
 * to point at the Flask backend.
 *
 * Example: VITE_API_URL=https://your-flask-app.onrender.com
 *
 * In development with a proxy configured in vite.config.js or package.json
 * you can leave these unset (falls back to same-origin "").
 */

export const API_BASE =
  (typeof import.meta !== "undefined" && import.meta.env?.VITE_API_URL) ||
  (typeof process !== "undefined" && process.env?.REACT_APP_API_URL) ||
  "";

/**
 * Wrapper around fetch that:
 * 1. Prepends API_BASE to the URL
 * 2. Attaches the auth token header automatically
 * 3. Reads the body ONCE (fixes "body stream already read" error)
 * 4. Throws a proper Error if the response is not JSON or not ok
 *
 * Usage:
 *   const data = await apiFetch("/api/signals?strategy=bot");
 *   const data = await apiFetch("/api/backtest", { method: "POST", body: JSON.stringify(payload) });
 */
export async function apiFetch(path, options = {}) {
  const token = localStorage.getItem("token");
  const headers = {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(options.headers || {}),
  };

  const url = `${API_BASE}${path}`;

  let response;
  try {
    response = await fetch(url, { ...options, headers });
  } catch (networkError) {
    throw new Error(`Network error — is the backend running? (${networkError.message})`);
  }

  // Read body exactly once
  const contentType = response.headers.get("content-type") || "";
  let data;

  if (contentType.includes("application/json")) {
    data = await response.json();
  } else {
    // If we get HTML back, the backend URL is wrong — give a helpful error
    const text = await response.text();
    if (text.trim().startsWith("<")) {
      throw new Error(
        `API returned HTML instead of JSON. ` +
        `Check that VITE_API_URL is set correctly in Render environment variables ` +
        `and points to your Flask backend. URL tried: ${url}`
      );
    }
    try {
      data = JSON.parse(text);
    } catch {
      throw new Error(`Unexpected response from server: ${text.slice(0, 120)}`);
    }
  }

  if (!response.ok) {
    throw new Error(data?.error || data?.message || `HTTP ${response.status}`);
  }

  return data;
}
