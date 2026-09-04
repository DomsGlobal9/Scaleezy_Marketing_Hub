import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";

export interface PlatformPageInfo {
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
  next_page: number | null;
  previous_page: number | null;
  status_counts?: Record<string, number>;
  kind_counts?: Record<string, number>;
}

type Page<T> = PlatformPageInfo & { items: T[] };

/** Bounded console reads. A changed filter can never display an older page. */
export function usePlatformPage<T>(
  path: string,
  rowKey: string,
  filters: Record<string, string> = {},
) {
  const [query, setQuery] = useState("");
  const filterKey = JSON.stringify({ ...filters, q: query });
  const [selection, setSelection] = useState({ key: filterKey, page: 1 });
  const page = selection.key === filterKey ? selection.page : 1;
  const requestKey = `${filterKey}:${page}`;
  const [result, setResult] = useState<{ key: string; data: Page<T> | null }>({
    key: "",
    data: null,
  });
  const [pending, setPending] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const version = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const load = useCallback(async () => {
    const current = ++version.current;
    controller.current?.abort();
    const abort = new AbortController();
    controller.current = abort;
    setPending(true);
    setError(null);
    try {
      const params = new URLSearchParams({
        ...JSON.parse(filterKey),
        page: String(page),
        page_size: "25",
      });
      const payload = await api<PlatformPageInfo & Record<string, unknown>>(`${path}?${params}`, {
        signal: abort.signal,
      });
      if (
        !Array.isArray(payload[rowKey]) ||
        typeof payload.total !== "number" ||
        typeof payload.page !== "number"
      ) {
        throw new Error("The server returned an invalid page. Please retry.");
      }
      if (current === version.current)
        setResult({ key: requestKey, data: { ...payload, items: payload[rowKey] as T[] } });
    } catch (reason) {
      if (current === version.current && !abort.signal.aborted) {
        setError(reason instanceof Error ? reason.message : "Could not load this page.");
        setResult({ key: requestKey, data: null });
      }
    } finally {
      if (current === version.current) setPending(false);
    }
  }, [path, rowKey, filterKey, page, requestKey]);

  useEffect(() => {
    void load();
    return () => {
      version.current += 1;
      controller.current?.abort();
    };
  }, [load]);

  const data = result.key === requestKey ? result.data : null;
  return {
    items: data?.items ?? null,
    pageInfo: data,
    error,
    load,
    loading: pending || result.key !== requestKey,
    query,
    setQuery,
    setPage: (next: number) => setSelection({ key: filterKey, page: next }),
  };
}
