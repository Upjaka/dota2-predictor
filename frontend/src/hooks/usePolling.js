import { useCallback, useEffect, useRef, useState } from "react";

export function usePolling(load, intervalMs) {
  const refreshRef = useRef(null);
  const inFlightRef = useRef(null);
  const [state, setState] = useState({
    data: null,
    loading: true,
    refreshing: false,
    error: null,
    lastUpdated: null,
  });

  useEffect(() => {
    let active = true;
    const controller = new AbortController();

    async function refresh() {
      if (inFlightRef.current || controller.signal.aborted) return;
      const requestToken = {};
      inFlightRef.current = requestToken;
      setState((current) => ({
        ...current,
        loading: current.data === null,
        refreshing: current.data !== null,
        error: null,
      }));

      try {
        const data = await load(controller.signal);
        if (active) {
          setState({
            data,
            loading: false,
            refreshing: false,
            error: null,
            lastUpdated: new Date(),
          });
        }
      } catch (error) {
        if (active && error.name !== "AbortError") {
          setState((current) => ({
            ...current,
            loading: false,
            refreshing: false,
            error: error.message,
          }));
        }
      } finally {
        if (inFlightRef.current === requestToken) {
          inFlightRef.current = null;
          if (!active && refreshRef.current) {
            Promise.resolve().then(() => refreshRef.current?.());
          }
        }
      }
    }

    refreshRef.current = refresh;
    void refresh();
    const timerId = window.setInterval(refresh, intervalMs);
    return () => {
      active = false;
      refreshRef.current = null;
      window.clearInterval(timerId);
      controller.abort();
    };
  }, [load, intervalMs]);

  const refreshNow = useCallback(() => {
    refreshRef.current?.();
  }, []);

  return { ...state, refreshNow };
}
