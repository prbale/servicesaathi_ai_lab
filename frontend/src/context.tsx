import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api, session } from "./api";

export type User = { id: number; email: string; display_name: string; role: "customer" | "provider" | "admin" };
export type Meta = {
  banner: string;
  today: string;
  today_label: string;
  categories: { code: string; name: string; description: string }[];
  localities: { code: string; name: string }[];
  ai: { llm_enabled: boolean; llm_provider: string; embedding: { model: string | null; kind?: string } };
  charges_note: string;
};

type Ctx = {
  user: User | null;
  /** false until we know whether a saved session is still valid (avoids redirect flicker on refresh) */
  ready: boolean;
  meta: Meta | null;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => void;
  devMode: boolean;
  setDevMode: (v: boolean) => void;
  lastTrace: any;
  setLastTrace: (t: any) => void;
};

const AppCtx = createContext<Ctx>(null as unknown as Ctx);
export const useApp = () => useContext(AppCtx);

export function AppProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(!session.token);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [devMode, setDev] = useState(session.devMode);
  const [lastTrace, setLastTrace] = useState<any>(null);

  useEffect(() => {
    api<Meta>("/api/meta").then(setMeta).catch(() => setMeta(null));
    if (session.token)
      api<User>("/api/auth/me").then(setUser).catch(() => setUser(null)).finally(() => setReady(true));
    const off = session.onTrace(setLastTrace);
    const out = () => setUser(null);
    window.addEventListener("ss-signed-out", out);
    return () => {
      off();
      window.removeEventListener("ss-signed-out", out);
    };
  }, []);

  const value: Ctx = {
    user,
    ready,
    meta,
    devMode,
    lastTrace,
    setLastTrace,
    setDevMode: (v) => {
      session.setDevMode(v);
      setDev(v);
    },
    signIn: async (email, password) => {
      const r = await api<{ token: string; user: User }>("/api/auth/login", { body: { email, password } });
      session.setToken(r.token);
      setUser(r.user);
    },
    signOut: () => {
      session.setToken(null);
      setUser(null);
      setLastTrace(null);
    },
  };
  return <AppCtx.Provider value={value}>{children}</AppCtx.Provider>;
}
