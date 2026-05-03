import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider, useAuth } from "@/lib/auth";
import Login from "@/pages/Login";
import AppShell from "@/pages/AppShell";
import Dashboard from "@/pages/Dashboard";
import Backtester from "@/pages/Backtester";
import Settings from "@/pages/Settings";
import Journal from "@/pages/Journal";

function Protected({ children }) {
  const { user } = useAuth();
    if (!user) return <Navigate to="/login" replace />;
      return children;
      }

      function PublicOnly({ children }) {
        const { user } = useAuth();
          if (user) return <Navigate to="/dashboard" replace />;
            return children;
            }

            export default function App() {
              return (
                  <AuthProvider>
                        <BrowserRouter>
                                <Routes>
                                          <Route path="/login" element={<PublicOnly><Login mode="login" /></PublicOnly>} />
                                                    <Route path="/register" element={<PublicOnly><Login mode="register" /></PublicOnly>} />
                                                              <Route element={<Protected><AppShell /></Protected>}>
                                                                          <Route path="/" element={<Navigate to="/dashboard" replace />} />
                                                                                      <Route path="/dashboard" element={<Dashboard />} />
                                                                                                  <Route path="/backtester" element={<Backtester />} />
                                                                                                              <Route path="/journal" element={<Journal />} />
                                                                                                                          <Route path="/settings" element={<Settings />} />
                                                                                                                                    </Route>
                                                                                                                                              <Route path="*" element={<Navigate to="/dashboard" replace />} />
                                                                                                                                                      </Routes>
                                                                                                                                                            </BrowserRouter>
                                                                                                                                                                </AuthProvider>
                                                                                                                                                                  );
                                                                                                                                                                  }
                                                                                                                                                                  