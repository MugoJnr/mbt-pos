import { useEffect, useState } from "react";

import { GET } from "@/lib/api";

/** Request queues refresh on the same 20s cadence as the Approvals page.
 * The dashboard chart interval is separate and is not used here.
 * A hidden browser tab does not keep polling.
 * A hung response becomes an error so an empty list is not left on screen.
 */

export const REQUEST_QUEUE_REFRESH_MS = 20_000;
export const REQUEST_QUEUE_TIMEOUT_MS = 8_000;

export async function loadQueue<T extends { error?: string }>(
  path: string,
  query?: Record<string, string>,
): Promise<T> {
  try {
    const data = await GET<T>(path, query, REQUEST_QUEUE_TIMEOUT_MS);
    if (!data || data.error) throw new Error(data?.error || "Could not refresh this list.");
    return data;
  } catch (err) {
    const name = err instanceof Error ? err.name : "";
    if (name === "TimeoutError" || name === "AbortError") {
      throw new Error("Could not refresh this list. Do not treat it as current.");
    }
    throw err;
  }
}

export const requestQueueQuery = {
  refetchInterval: REQUEST_QUEUE_REFRESH_MS,
  refetchIntervalInBackground: false,
  refetchOnWindowFocus: true,
};

type QueueQuery = {
  isPending: boolean;
  isError: boolean;
  isFetching: boolean;
  isSuccess: boolean;
  dataUpdatedAt: number;
};

export function queueStatusLine(query: QueueQuery, countText = ""): string {
  if (query.isError) return "Could not refresh this list. Do not treat it as current.";
  if (!query.isSuccess) return "Loading requests…";
  const count = countText ? `${countText} ` : "";
  if (query.isFetching) return `${count}Checking for new requests…`;
  if (!query.dataUpdatedAt) return count.trim();
  const ago = Math.max(0, Math.round((Date.now() - query.dataUpdatedAt) / 1000));
  const when = ago < 5 ? "Updated just now." : `Updated ${ago}s ago.`;
  return `${count}${when}`;
}

export function useQueueNotice(query: { isError: boolean; isSuccess: boolean; error: unknown }): string {
  const [notice, setNotice] = useState("");
  useEffect(() => {
    if (query.isSuccess) {
      setNotice("");
      return;
    }
    if (query.isError) {
      setNotice(query.error instanceof Error ? query.error.message : "Could not refresh this list.");
    }
  }, [query.isSuccess, query.isError, query.error]);
  return query.isSuccess ? "" : notice;
}
