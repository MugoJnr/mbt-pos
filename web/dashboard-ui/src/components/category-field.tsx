import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Input } from "@/components/ui-kit";
import { GET, POST } from "@/lib/api";

export type ShopCategory = {
  id: number;
  name: string;
  description?: string;
  product_count?: number;
  error?: string;
};

export function CategoryField({
  value,
  onChange,
  canCreate,
}: {
  value: string;
  onChange: (value: string) => void;
  canCreate: boolean;
}) {
  const qc = useQueryClient();
  const catsQ = useQuery({
    queryKey: ["categories"],
    queryFn: () => GET<ShopCategory[]>("/categories"),
  });
  const cats = Array.isArray(catsQ.data) ? catsQ.data : [];
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  async function createCategory() {
    setErr("");
    setBusy(true);
    try {
      const res = await POST<ShopCategory>("/categories", { name, description });
      if (!res || res.error || !res.name) {
        const message = res?.error || "The category was not created.";
        if (message.toLowerCase().includes("already exists")) {
          await qc.invalidateQueries({ queryKey: ["categories"] });
          const wanted = name.trim().toLowerCase();
          const fresh = await GET<ShopCategory[]>("/categories");
          const match = (Array.isArray(fresh) ? fresh : []).find(
            (row) => (row.name || "").trim().toLowerCase() === wanted,
          );
          if (match?.name) {
            onChange(match.name);
            setAdding(false);
            setErr("");
            return;
          }
        }
        setErr(message);
        return;
      }
      await qc.invalidateQueries({ queryKey: ["categories"] });
      onChange(res.name);
      setName("");
      setDescription("");
      setAdding(false);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-1 space-y-2">
      <select
        aria-label="Category"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-11 w-full rounded-xl border border-border bg-input px-3 text-sm text-text"
      >
        <option value="">Uncategorised</option>
        {cats.map((row) => (
          <option key={row.id} value={row.name}>
            {row.name}
          </option>
        ))}
        {value && !cats.some((row) => row.name === value) ? (
          <option value={value}>{value}</option>
        ) : null}
      </select>
      {canCreate ? (
        <button
          type="button"
          className="text-xs font-semibold text-gold underline"
          onClick={() => setAdding((open) => !open)}
        >
          Add new category
        </button>
      ) : null}
      {adding ? (
        <div className="space-y-2 rounded-xl border border-border p-3">
          <Input
            aria-label="New category name"
            placeholder="Category name"
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
          <Input
            aria-label="New category description"
            placeholder="Optional description"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
          />
          <Button type="button" onClick={() => void createCategory()} disabled={busy}>
            {busy ? "Creating…" : "Create category"}
          </Button>
          {err ? <div className="text-xs text-err">{err}</div> : null}
        </div>
      ) : null}
    </div>
  );
}
