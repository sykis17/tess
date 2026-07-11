import { useMemo } from "react";

const STORAGE_KEY = "tess_session_id";

export function useSessionId(): string {
  return useMemo(() => {
    const existing = sessionStorage.getItem(STORAGE_KEY);
    if (existing) {
      return existing;
    }

    const id = crypto.randomUUID();
    sessionStorage.setItem(STORAGE_KEY, id);
    return id;
  }, []);
}
