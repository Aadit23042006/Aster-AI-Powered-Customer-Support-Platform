"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, clearTokens, getAccessToken, getRefreshToken, setTokens } from "@/lib/api";
import type { User } from "@/types/api";

interface AuthContextValue {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  signup: (fullName: string, email: string, password: string, confirmPassword: string) => Promise<void>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  const refreshUser = useCallback(async () => {
    try {
      // If the access token is missing (for example after a browser restart),
      // restore the session from the persisted refresh token before calling /me.
      if (!getAccessToken() && !getRefreshToken()) {
        setUser(null);
        return;
      }

      if (!getAccessToken() && getRefreshToken()) {
        const refreshed = await api.refreshSession();
        if (!refreshed) {
          clearTokens();
          setUser(null);
          return;
        }
      }

      const me = await api.me();
      setUser(me);
    } catch {
      // api.me() already attempts a refresh after an expired access token.
      // Only clear the local session if both access and refresh authentication fail.
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional fetch-on-mount
    refreshUser();

    // Keep the access token fresh while the user is actively using the app.
    // The refresh token is rotated server-side, so normal use does not force
    // the user back to /login.
    const refreshInterval = window.setInterval(() => {
      if (getRefreshToken()) {
        void api.refreshSession().then((ok) => {
          if (!ok) return;
          void api.me().then(setUser).catch(() => undefined);
        });
      }
    }, 10 * 60 * 1000);

    const handleFocus = () => {
      if (getRefreshToken()) {
        void api.refreshSession().then((ok) => {
          if (ok) void api.me().then(setUser).catch(() => undefined);
        });
      }
    };

    window.addEventListener("focus", handleFocus);

    return () => {
      window.clearInterval(refreshInterval);
      window.removeEventListener("focus", handleFocus);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const tokens = await api.login(email, password);
    setTokens(tokens.access_token, tokens.refresh_token);
    const me = await api.me();
    setUser(me);
  }, []);

  const signup = useCallback(async (fullName: string, email: string, password: string, confirmPassword: string) => {
    const tokens = await api.signup(fullName, email, password, confirmPassword);
    setTokens(tokens.access_token, tokens.refresh_token);
    const me = await api.me();
    setUser(me);
  }, []);

  const logout = useCallback(async () => {
    try {
      // Server-side revocation is best-effort; the user must still be
      // returned to the login screen even if the backend is unreachable.
      await api.logout();
    } finally {
      clearTokens();
      setUser(null);
      router.replace("/login");
    }
  }, [router]);

  return (
    <AuthContext.Provider value={{ user, loading, login, signup, logout, refreshUser }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
