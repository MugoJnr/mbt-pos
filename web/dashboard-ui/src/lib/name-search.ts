/** Product-name search. Capitalization and extra spaces do not change the match. */

export function normalizeNameQuery(value: string): string {
  return String(value || "").trim().toLowerCase().replace(/\s+/g, " ");
}

export function nameMatches(query: string, name: string): boolean {
  const q = normalizeNameQuery(query);
  if (!q) return true;
  return normalizeNameQuery(name).includes(q);
}
