import { createContext, useContext, useEffect, useState } from "react";
import api from "@/lib/api";

const AuthCtx = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    try { return JSON.parse(localStorage.getItem("ate_user") || "null"); } catch { return null; }
  });
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const token = localStorage.getItem("ate_token");
    if (token && !user) {
      api.get("/auth/me").then((r) => {
        localStorage.setItem("ate_user", JSON.stringify(r.data));
        setUser(r.data);
      }).catch(() => {});
    }
  }, []); // eslint-disable-line

  const login = async (email, password) => {
    setLoading(true);
    try {
      const { data } = await api.post("/auth/login", { email, password });
      localStorage.setItem("ate_token", data.token);
      localStorage.setItem("ate_user", JSON.stringify(data.user));
      setUser(data.user);
      return data.user;
    } finally { setLoading(false); }
  };

  const register = async (email, password, name) => {
    setLoading(true);
    try {
      const { data } = await api.post("/auth/register", { email, password, name });
      localStorage.setItem("ate_token", data.token);
      localStorage.setItem("ate_user", JSON.stringify(data.user));
      setUser(data.user);
      return data.user;
    } finally { setLoading(false); }
  };

  const logout = () => {
    localStorage.removeItem("ate_token");
    localStorage.removeItem("ate_user");
    setUser(null);
  };

  return (
    <AuthCtx.Provider value={{ user, loading, login, register, logout }}>
      {children}
    </AuthCtx.Provider>
  );
}

export const useAuth = () => useContext(AuthCtx);
