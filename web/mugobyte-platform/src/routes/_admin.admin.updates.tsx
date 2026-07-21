import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CloudUpload, Plus, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { PageShell, PageHeader } from "@/components/layout/PageShell";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { GET, POST } from "@/lib/api";

export const Route = createFileRoute("/_admin/admin/updates")({
  component: Page,
  head: () => ({ meta: [{ title: "Updates | MugoByte" }] }),
});

type UpdateRow = {
  version: string;
  download_url?: string;
  release_notes?: string;
  is_mandatory?: boolean;
  is_active?: boolean;
  published_at?: string;
};

function Page() {
  const qc = useQueryClient();
  const [version, setVersion] = useState("");
  const [url, setUrl] = useState("");
  const [notes, setNotes] = useState("");
  const [checksum, setChecksum] = useState("");

  const listQ = useQuery({
    queryKey: ["admin-updates"],
    queryFn: () => GET<{ updates?: UpdateRow[] }>("/cloud/updates"),
  });
  const updates = listQ.data?.updates || [];

  const publishMut = useMutation({
    mutationFn: () =>
      POST("/cloud/updates", {
        version,
        download_url: url,
        checksum,
        release_notes: notes,
        is_mandatory: false,
      }),
    onSuccess: () => {
      toast.success("Update published");
      setVersion("");
      setUrl("");
      setNotes("");
      setChecksum("");
      qc.invalidateQueries({ queryKey: ["admin-updates"] });
    },
    onError: (e: Error) => toast.error(e.message || "Publish failed"),
  });

  return (
    <PageShell>
      <PageHeader
        eyebrow="Admin"
        title="Update Center"
        description="Publish desktop POS versions. Devices check Portal, download, verify, install, and report status."
        actions={
          <Button variant="outline" onClick={() => listQ.refetch()}>
            <RefreshCw className="mr-1.5 h-4 w-4" />Refresh
          </Button>
        }
      />

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 font-display">
              <Plus className="h-4 w-4" /> New release
            </CardTitle>
            <CardDescription>Requires admin role. Checksum recommended (SHA-256).</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <Input placeholder="Version e.g. 2.4.1" value={version} onChange={(e) => setVersion(e.target.value)} />
            <Input placeholder="Download URL" value={url} onChange={(e) => setUrl(e.target.value)} />
            <Input placeholder="SHA-256 checksum (optional)" value={checksum} onChange={(e) => setChecksum(e.target.value)} />
            <Input placeholder="Release notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
            <Button
              disabled={!version || !url || publishMut.isPending}
              onClick={() => publishMut.mutate()}
            >
              <CloudUpload className="mr-1.5 h-4 w-4" />
              Publish
            </Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="font-display">Published versions</CardTitle>
            <CardDescription>History of active and past releases.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            {updates.length === 0 ? (
              <p className="text-sm text-muted-foreground">No updates in Supabase yet.</p>
            ) : (
              updates.map((u) => (
                <div key={u.version} className="flex items-center justify-between rounded-xl border border-border/70 p-3">
                  <div>
                    <div className="font-semibold">v{u.version}</div>
                    <div className="text-xs text-muted-foreground">{(u.release_notes || "").slice(0, 80)}</div>
                  </div>
                  <Badge variant={u.is_active ? "default" : "secondary"}>
                    {u.is_active ? "active" : "inactive"}
                  </Badge>
                </div>
              ))
            )}
          </CardContent>
        </Card>
      </div>
    </PageShell>
  );
}
