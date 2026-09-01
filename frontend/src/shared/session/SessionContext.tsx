import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type PropsWithChildren,
} from "react";

import type { ApiAdapter, CurrentAccount, LoginRequest } from "../../platform/api/types";
import {
  setSessionAccessToken,
  setSessionUnauthorizedHandler,
} from "./sessionRuntime";

const SESSION_TOKEN_STORAGE_KEY = "auth_token";

type SessionApiAdapter = Required<
  Pick<ApiAdapter, "login" | "logout" | "getMe" | "changePassword">
>;

export type SessionStatus = "loading" | "authenticated" | "anonymous";

type SessionContextValue = {
  sessionStatus: SessionStatus;
  currentAccount: CurrentAccount | null;
  pendingTodoCount: number;
  login: (payload: LoginRequest) => Promise<void>;
  logout: () => Promise<void>;
  refreshCurrentAccount: () => Promise<CurrentAccount | null>;
};

const SessionContext = createContext<SessionContextValue | null>(null);

export function SessionProvider({
  adapter,
  children,
}: PropsWithChildren<{ adapter: SessionApiAdapter }>) {
  const [sessionStatus, setSessionStatus] = useState<SessionStatus>("loading");
  const [currentAccount, setCurrentAccount] = useState<CurrentAccount | null>(null);
  const tokenRef = useRef<string | null>(null);

  const clearSession = useCallback(() => {
    tokenRef.current = null;
    setSessionAccessToken(null);
    window.localStorage.removeItem(SESSION_TOKEN_STORAGE_KEY);
    setCurrentAccount(null);
    setSessionStatus("anonymous");
  }, []);

  const persistSession = useCallback((token: string, account: CurrentAccount) => {
    tokenRef.current = token;
    setSessionAccessToken(token);
    window.localStorage.setItem(SESSION_TOKEN_STORAGE_KEY, token);
    setCurrentAccount(account);
    setSessionStatus("authenticated");
  }, []);

  const refreshCurrentAccount = useCallback(async () => {
    if (!tokenRef.current) {
      setCurrentAccount(null);
      setSessionStatus("anonymous");
      return null;
    }

    try {
      const account = await adapter.getMe();
      setCurrentAccount(account);
      setSessionStatus("authenticated");
      return account;
    } catch (error) {
      clearSession();
      return null;
    }
  }, [adapter, clearSession]);

  const login = useCallback(
    async (payload: LoginRequest) => {
      const response = await adapter.login(payload);
      persistSession(response.token, response.account);
    },
    [adapter, persistSession],
  );

  const logout = useCallback(async () => {
    try {
      await adapter.logout();
    } finally {
      clearSession();
    }
  }, [adapter, clearSession]);

  useEffect(() => {
    setSessionUnauthorizedHandler(clearSession);
    return () => {
      setSessionUnauthorizedHandler(null);
    };
  }, [clearSession]);

  useEffect(() => {
    const persistedToken = window.localStorage.getItem(SESSION_TOKEN_STORAGE_KEY);
    if (!persistedToken) {
      clearSession();
      return;
    }

    tokenRef.current = persistedToken;
    setSessionAccessToken(persistedToken);
    setSessionStatus("loading");
    void refreshCurrentAccount();
  }, [clearSession, refreshCurrentAccount]);

  const value = useMemo<SessionContextValue>(
    () => ({
      sessionStatus,
      currentAccount,
      pendingTodoCount: currentAccount?.pendingTodoCount ?? 0,
      login,
      logout,
      refreshCurrentAccount,
    }),
    [currentAccount, login, logout, refreshCurrentAccount, sessionStatus],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession() {
  const value = useContext(SessionContext);
  if (!value) {
    throw new Error("useSession must be used within a SessionProvider.");
  }
  return value;
}
