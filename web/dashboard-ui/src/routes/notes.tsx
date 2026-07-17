import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Search, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { AppShell } from "@/components/app-shell";
import { Button, Card, Input } from "@/components/ui-kit";
import { DEL, GET, POST, PUT } from "@/lib/api";

export const Route = createFileRoute("/notes")({
  component: Notes,
});

type Note = {
  id: number;
  title?: string;
  content?: string;
  body?: string;
  updated_at?: string;
  created_at?: string;
};

function Notes() {
  const qc = useQueryClient();
  const [active, setActive] = useState<number | null>(null);
  const [q, setQ] = useState("");
  const [draftTitle, setDraftTitle] = useState("");
  const [draftBody, setDraftBody] = useState("");

  const notesQ = useQuery({
    queryKey: ["notes"],
    queryFn: () => GET<Note[]>("/notes"),
  });
  const notes = Array.isArray(notesQ.data) ? notesQ.data : [];

  const filtered = useMemo(
    () =>
      notes.filter((n) =>
        (n.title || "").toLowerCase().includes(q.toLowerCase()),
      ),
    [notes, q],
  );

  const current =
    notes.find((n) => n.id === active) ??
    (active == null && filtered[0] ? filtered[0] : null);

  useEffect(() => {
    if (!current) return;
    if (active !== current.id) setActive(current.id);
    setDraftTitle(current.title || "");
    setDraftBody(current.content || current.body || "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current?.id]);

  const create = useMutation({
    mutationFn: async () => {
      const res = await POST<{ success?: boolean; error?: string }>("/notes", {
        title: "Untitled",
        content: "",
      });
      if (!res?.success) throw new Error(res?.error || "Create failed");
      return res;
    },
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["notes"] });
      toast.success("Note created");
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const save = useMutation({
    mutationFn: async () => {
      if (!current) return;
      const res = await PUT<{ success?: boolean; error?: string }>(`/notes/${current.id}`, {
        title: draftTitle,
        content: draftBody,
      });
      if (!res?.success) throw new Error(res?.error || "Save failed");
      return res;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["notes"] });
      toast.success("Saved");
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const remove = useMutation({
    mutationFn: async (id: number) => {
      const res = await DEL<{ success?: boolean; error?: string }>(`/notes/${id}`);
      if (!res?.success) throw new Error(res?.error || "Delete failed");
      return res;
    },
    onSuccess: () => {
      setActive(null);
      qc.invalidateQueries({ queryKey: ["notes"] });
      toast.success("Deleted");
    },
    onError: (e: Error) => toast.error(e.message),
  });

  return (
    <AppShell title="Notes">
      <div className="grid grid-cols-1 md:grid-cols-[300px_1fr] gap-4 h-[calc(100vh-9rem)]">
        <Card className="flex flex-col overflow-hidden">
          <div className="p-3 border-b border-border flex items-center gap-2">
            <div className="relative flex-1">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-text2" />
              <Input
                placeholder="Search notes…"
                value={q}
                onChange={(e) => setQ(e.target.value)}
                className="pl-8"
              />
            </div>
            <Button variant="primary" size="sm" onClick={() => create.mutate()}>
              <Plus className="h-4 w-4" />
            </Button>
          </div>
          <ul className="flex-1 overflow-y-auto scrollbar-thin">
            {notesQ.isLoading ? (
              <li className="p-4 text-sm text-text2">Loading…</li>
            ) : filtered.length === 0 ? (
              <li className="p-4 text-sm text-text2">No notes yet</li>
            ) : (
              filtered.map((n) => (
                <li key={n.id}>
                  <button
                    onClick={() => {
                      setActive(n.id);
                      setDraftTitle(n.title || "");
                      setDraftBody(n.content || n.body || "");
                    }}
                    className={`w-full text-left px-4 py-3 border-b border-border/60 ${
                      n.id === current?.id
                        ? "bg-hover border-l-2 border-l-gold"
                        : "hover:bg-hover/50"
                    }`}
                  >
                    <div className="text-sm font-semibold text-text truncate">
                      {n.title || "Untitled"}
                    </div>
                    <div className="text-xs text-text2 truncate mt-0.5">
                      {(n.content || n.body || "").split("\n")[0] || "Empty note"}
                    </div>
                  </button>
                </li>
              ))
            )}
          </ul>
        </Card>

        <Card className="flex flex-col overflow-hidden">
          {!current ? (
            <div className="py-16 text-center text-sm text-text2">Select or create a note</div>
          ) : (
            <>
              <div className="p-4 border-b border-border flex items-center justify-between gap-2">
                <input
                  value={draftTitle}
                  onChange={(e) => setDraftTitle(e.target.value)}
                  onBlur={() => save.mutate()}
                  className="bg-transparent text-lg font-semibold text-text focus:outline-none flex-1"
                />
                <Button variant="ghost" size="sm" onClick={() => remove.mutate(current.id)}>
                  <Trash2 className="h-4 w-4 text-err" />
                </Button>
              </div>
              <textarea
                value={draftBody}
                onChange={(e) => setDraftBody(e.target.value)}
                onBlur={() => save.mutate()}
                placeholder="Start writing…"
                className="flex-1 p-6 bg-transparent resize-none text-text placeholder:text-muted-fg focus:outline-none text-[15px] leading-relaxed font-sans"
              />
            </>
          )}
        </Card>
      </div>
    </AppShell>
  );
}
