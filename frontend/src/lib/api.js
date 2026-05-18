/**
 * src/utils/api.js — NexusBot
 * CRA / craco compatible. No import.meta (Vite-only).
 * Set REACT_APP_API_URL in Vercel/Render env vars.
 * Example: REACT_APP_API_URL=https://your-flask.onrender.com
 */
export const API_BASE = process.env.REACT_APP_API_URL || "";

/**
 * Fetch wrapper — attaches auth token, reads body ONCE, throws on error.
 * Returns parsed JSON. Never returns a Response object.
 */
export async function apiFetch(path, options = {}) {
  const token = localStorage.getItem("token");
  const headers = {
    "Content-Type": "application/json",
    ...(token ? { Authorization: "Bearer " + token } : {}),
    ...(options.headers || {}),
  };

  const url = API_BASE + path;
  let response;
  try {
    response = await fetch(url, { ...options, headers });
  } catch (err) {
    throw new Error("Network error — is the backend reachable? (" + err.message + ")");
  }

  const ct = response.headers.get("content-type") || "";
  let data;
  if (ct.includes("application/json")) {
    data = await response.json();
  } else {
    const text = await response.text();
    if (text.trim().startsWith("<")) {
      throw new Error(
        "API returned HTML — set REACT_APP_API_URL in your Vercel environment variables " +
        "to point at your Flask backend. Tried: " + url
      );
    }
    try { data = JSON.parse(text); }
    catch { throw new Error("Unexpected response: " + text.slice(0, 100)); }
  }

  if (!response.ok) {
    throw new Error((data && (data.error || data.message)) || "HTTP " + response.status);
  }
  return data;
}
