import { getToken } from "./api";

export async function downloadApi(pathWithQuery: string, fallbackName: string): Promise<void> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const r = await fetch("/api" + pathWithQuery, { headers });
  if (r.status === 401) {
    window.location.href = "/login";
    throw new Error("Unauthorized");
  }
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error((err as { error?: string }).error || `Export failed (${r.status})`);
  }
  const cd = r.headers.get("Content-Disposition") || "";
  const m = /filename="?([^"]+)"?/i.exec(cd);
  const name = m?.[1] || fallbackName;
  const blob = await r.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export function exportQuery(params: Record<string, string | undefined>) {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v != null && v !== "") q.set(k, v);
  }
  return q.toString();
}
