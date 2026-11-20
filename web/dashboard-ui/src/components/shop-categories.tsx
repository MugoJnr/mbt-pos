import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Card, Input } from "@/components/ui-kit";
import { DEL, GET, POST, PUT } from "@/lib/api";
import type { ShopCategory } from "@/components/category-field";

export function ShopCategories({
  canCreate,
  canManage,
  canDelete,
}: {
  canCreate: boolean;
  canManage: boolean;
  canDelete: boolean;
}) {
  const qc = useQueryClient();
  const catsQ = useQuery({
    queryKey: ["categories"],
    queryFn: () => GET<ShopCategory[]>("/categories"),
  });
  const cats = Array.isArray(catsQ.data) ? catsQ.data : [];
  const [q, setQ] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [editId, setEditId] = useState<number | null>(null);
  const [editName, setEditName] = useState("");
  const [editDescription, setEditDescription] = useState("");

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return cats;
    return cats.filter((row) =>
      (row.name || "").toLowerCase().includes(needle)
      || (row.description || "").toLowerCase().includes(needle),
    );
  }, [cats, q]);

  async function refresh() {
    await qc.invalidateQueries({ queryKey: ["categories"] });
  }

  async function addCategory() {
    setMsg("");
    setBusy(true);
    try {
      const res = await POST<ShopCategory>("/categories", { name, description });
      if (!res || res.error) {
        setMsg(res?.error || "The category was not created.");
        return;
      }
      setName("");
      setDescription("");
      setMsg(`${res.name} is ready to use.`);
      await refresh();
    } finally {
      setBusy(false);
    }
  }

  async function saveRename() {
    if (!editId || !canManage) return;
    setMsg("");
    setBusy(true);
    try {
      const res = await PUT<ShopCategory>(`/categories/${editId}`, {
        name: editName,
        description: editDescription,
      });
      if (!res || res.error) {
        setMsg(res?.error || "The category was not renamed.");
        return;
      }
      setEditId(null);
      setMsg(`${res.name} was saved. Products that used it now use the new name.`);
      await refresh();
    } finally {
      setBusy(false);
    }
  }

  async function remove(row: ShopCategory) {
    if (!canDelete) return;
    const count = Number(row.product_count || 0);
    const ok = window.confirm(
      count
        ? `Remove ${row.name} and leave ${count} product${count === 1 ? "" : "s"} uncategorised? The products stay in the shop.`
        : `Remove the empty category ${row.name}?`,
    );
    if (!ok) return;
    const path = count
      ? `/categories/${row.id}?leave_uncategorised=1`
      : `/categories/${row.id}`;
    const res = await DEL<ShopCategory & { success?: boolean }>(path);
    if (!res || res.error || res.success === false) {
      setMsg(res?.error || "The category was not removed.");
      return;
    }
    setMsg(`${row.name} was removed. Products were not deleted.`);
    await refresh();
  }

  return (
    <Card className="mb-3" id="shop-categories">
      <div className="space-y-3 p-4">
        <div className="text-sm font-extrabold text-text">Shop categories</div>
        <p className="text-xs text-text2">
          Only categories this shop creates are listed. Products can stay uncategorised.
          Deleting a category does not delete products.
        </p>
        <Input
          aria-label="Search categories"
          placeholder="Search categories"
          value={q}
          onChange={(event) => setQ(event.target.value)}
        />
        {canCreate ? (
          <div className="grid grid-cols-1 gap-2 md:grid-cols-[1fr_1fr_auto]">
            <Input
              aria-label="Category name"
              placeholder="Category name"
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
            <Input
              aria-label="Category description"
              placeholder="Optional description"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
            <Button type="button" onClick={() => void addCategory()} disabled={busy}>
              Add category
            </Button>
          </div>
        ) : null}
        <div className="divide-y divide-border rounded-xl border border-border">
          {shown.length === 0 ? (
            <div className="px-3 py-4 text-sm text-text2">No categories yet. Products can still be saved.</div>
          ) : shown.map((row) => (
            <div key={row.id} className="flex flex-wrap items-center gap-2 px-3 py-2">
              {editId === row.id ? (
                <>
                  <Input aria-label="Rename category" value={editName} onChange={(event) => setEditName(event.target.value)} />
                  <Input aria-label="Category description" value={editDescription} onChange={(event) => setEditDescription(event.target.value)} />
                  <Button type="button" onClick={() => void saveRename()} disabled={busy}>Save category</Button>
                  <Button type="button" variant="ghost" onClick={() => setEditId(null)}>Cancel</Button>
                </>
              ) : (
                <>
                  <div className="min-w-[10rem] flex-1">
                    <div className="text-sm font-semibold text-text">{row.name}</div>
                    <div className="text-xs text-text2">
                      {Number(row.product_count || 0)} product{Number(row.product_count || 0) === 1 ? "" : "s"}
                      {row.description ? ` · ${row.description}` : ""}
                    </div>
                  </div>
                  {canManage ? (
                    <Button
                      type="button"
                      variant="ghost"
                      onClick={() => {
                        setEditId(row.id);
                        setEditName(row.name);
                        setEditDescription(row.description || "");
                      }}
                    >
                      Rename
                    </Button>
                  ) : null}
                  {canDelete ? (
                    <Button type="button" variant="danger" onClick={() => void remove(row)}>
                      Delete category
                    </Button>
                  ) : null}
                </>
              )}
            </div>
          ))}
        </div>
        {msg ? <div className="text-sm text-text2">{msg}</div> : null}
      </div>
    </Card>
  );
}
