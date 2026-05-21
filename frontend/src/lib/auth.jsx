import { createContext, useContext, useEffect, useState, useCallback } from "react";
import { apiFetch } from "@/lib/api";

const AuthCtx = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    try { return JSON.parse(localStorage.getItem("ate_user") || "null"); } catch { return null; }
  });
  const [loading, setLoading] = useState(false);

  // ── Clear session helper ────────────────────────────────────────────
  const clearSession = useCallback(() => {
    localStorage.removeItem("token");
    localStorage.removeItem("ate_user");
    setUser(null);
  }, []);

  // ── On mount: validate stored token against /api/auth/me ────────────
  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) {
      // No token at all — clear any stale user data
      clearSession();
      return;
    }
    // Verify token is still valid; silently log out if it isn't
    apiFetch("/api/auth/me")
      .then((r) => {
        // Token valid — refresh stored user data and issue a fresh token
        localStorage.setItem("ate_user", JSON.stringify(r));
        setUser(r);
        // Silently refresh token so it doesn't expire mid-session
        apiFetch("/api/auth/refresh")
          .then((res) => {
            if (res.token) localStorage.setItem("token", res.token);
          })
          .catch(() => {}); // non-critical
      })
      .catch(() => {
        // Token invalid or expired — log out immediately
        clearSession();
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Listen for the global auth:expired event fired by apiFetch ──────
  useEffect(() => {
    const handleExpired = () => clearSession();
    window.addEventListener("auth:expired", handleExpired);
    return () => window.removeEventListener("auth:expired", handleExpired);
  }, [clearSession]);

  const login = async (email, password) => {
    setLoading(true);
    try {
      const data = await apiFetch("/api/auth/login", {
        method: "POST", body: JSON.stringify({ email, password }),
      });
      localStorage.setItem("token", data.token);
      localStorage.setItem("ate_user", JSON.stringify(data.user));
      setUser(data.user);
      return data.user;
    } finally { setLoading(false); }
  };

  const register = async (email, password, name) => {
    setLoading(true);
    try {
      const data = await apiFetch("/api/auth/register", {
        method: "POST", body: JSON.stringify({ email, password, name }),
      });
      localStorage.setItem("token", data.token);
      localStorage.setItem("ate_user", JSON.stringify(data.user));
      setUser(data.user);
      return data.user;
    } finally { setLoading(false); }
  };

  const logout = () => clearSession();

  return (
    <AuthCtx.Provider value={{ user, loading, login, register, logout }}>
      {children}
    </AuthCtx.Provider>
  );
}

export const useAuth = () => useContext(AuthCtx);
