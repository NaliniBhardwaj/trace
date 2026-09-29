import React, { createContext, useContext, useEffect, useState, ReactNode } from 'react';
import { api, getToken, setToken, MeResponse, onUnauthorized } from '@/api/client';
import type { Role } from '@/types';

interface AuthContextType {
  isLoading: boolean;
  isAuthenticated: boolean;
  role: Role | null;
  fullName: string | null;
  email: string | null;
  userId: string | null;
  workerId: string | null;
  zoneId: string | null;
  /** Zone code (e.g. 'pipeline') for POST /scans. Never send the UUID as zone_code. */
  zoneCode: string | null;
  /** Worker's currently assigned active strip code, if any (from /users/me). */
  activeStripCode: string | null;
  /** Re-fetches /users/me, e.g. after activating a replacement strip. */
  refreshMe: () => Promise<void>;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  error: string | null;
  /** Manager/Safety-admin/Supervisor accounts can preview the Worker view for demos. */
  viewAsWorker: boolean;
  setViewAsWorker: (v: boolean) => void;
}

const AuthContext = createContext<AuthContextType>({
  isLoading: true,
  isAuthenticated: false,
  role: null,
  fullName: null,
  email: null,
  userId: null,
  workerId: null,
  zoneId: null,
  zoneCode: null,
  activeStripCode: null,
  refreshMe: async () => {},
  login: async () => {},
  logout: async () => {},
  error: null,
  viewAsWorker: false,
  setViewAsWorker: () => {},
});

async function resolveZoneCode(zoneId: string | null): Promise<string | null> {
  if (!zoneId) return null;
  try {
    const zones = await api.zones();
    return zones.find((z) => z.id === zoneId)?.code ?? null;
  } catch {
    return null;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [isLoading, setIsLoading] = useState(true);
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [me, setMe] = useState<MeResponse | null>(null);
  const [zoneCode, setZoneCode] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [viewAsWorker, setViewAsWorker] = useState(false);

  const clearSession = () => {
    setIsAuthenticated(false);
    setMe(null);
    setZoneCode(null);
    setViewAsWorker(false);
  };

  const refreshMe = async () => {
    const meResp = await api.me();
    setMe(meResp);
    setIsAuthenticated(true);
    setZoneCode(await resolveZoneCode(meResp.zone_id));
  };

  useEffect(() => {
    const unsub = onUnauthorized(() => {
      clearSession();
    });
    return unsub;
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const token = await getToken();
        if (token) {
          try {
            await refreshMe();
          } catch {
            await setToken(null);
            clearSession();
          }
        }
      } catch {
        clearSession();
      } finally {
        setIsLoading(false);
      }
    })();
  }, []);

  const login = async (email: string, password: string) => {
    setError(null);
    try {
      const resp = await api.login(email, password);
      await setToken(resp.access_token);
      await refreshMe();
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : 'Login failed';
      setError(message);
      throw e;
    }
  };

  const logout = async () => {
    await setToken(null);
    clearSession();
  };

  return (
    <AuthContext.Provider
      value={{
        isLoading,
        isAuthenticated,
        role: (me?.role as Role) ?? null,
        fullName: me?.full_name ?? null,
        email: me?.email ?? null,
        userId: me?.id ?? null,
        workerId: me?.worker_id ?? null,
        zoneId: me?.zone_id ?? null,
        zoneCode,
        activeStripCode: me?.active_strip_code ?? null,
        refreshMe,
        login,
        logout,
        error,
        viewAsWorker,
        setViewAsWorker,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
