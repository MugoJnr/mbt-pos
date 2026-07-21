import { createFileRoute, Link } from "@tanstack/react-router";
import { Download, FileText, MonitorSmartphone, BookOpen, Package } from "lucide-react";
import { PageShell, PageHeader } from "@/components/layout/PageShell";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useQuery } from "@tanstack/react-query";
import { GET } from "@/lib/api";
import { pageTitle, POS_CLOUD_PRODUCT } from "@/lib/brand";

export const Route = createFileRoute("/_app/downloads")({
  component: DownloadsPage,
  head: () => ({ meta: [{ title: pageTitle(POS_CLOUD_PRODUCT, "Downloads") }] }),
});

const FALLBACK_INSTALLER =
  "https://github.com/MugoJnr/mbt-pos/releases/latest/download/MBT_POS_Setup.exe";

function DownloadsPage() {
  const updatesQ = useQuery({
    queryKey: ["cloud-updates"],
    queryFn: () =>
      GET<{
        updates?: Array<{
          version: string;
          download_url: string;
          release_notes?: string;
          checksum?: string;
        }>;
        latest?: { version?: string; download_url?: string };
      }>("/cloud/updates"),
    retry: false,
  });
  const versionQ = useQuery({
    queryKey: ["app-version-dl"],
    queryFn: () =>
      GET<{ version?: string; download_url?: string; release_notes?: string; build?: string }>(
        "/version",
      ),
    retry: false,
  });

  const updates = updatesQ.data?.updates || [];
  const latestUrl =
    updatesQ.data?.latest?.download_url ||
    updates[0]?.download_url ||
    versionQ.data?.download_url ||
    FALLBACK_INSTALLER;
  const latestVer =
    updatesQ.data?.latest?.version || updates[0]?.version || versionQ.data?.version || "latest";

  return (
    <PageShell>
      <PageHeader
        eyebrow="Download Center"
        title="MBT POS Installer"
        description="One destination for installers, updates and documentation. New computers download here, install, sign in, and activate automatically via Portal licensing."
      />

      <Card className="border-primary/30 bg-primary/5">
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <CardTitle className="flex items-center gap-2 font-display text-xl">
                <Package className="h-5 w-5 text-primary" /> Desktop POS Setup
              </CardTitle>
              <CardDescription className="mt-1">
                Official Windows installer. Detects new vs upgrade automatically — you never choose.
              </CardDescription>
            </div>
            <Badge>v{latestVer}</Badge>
          </div>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          <Button asChild size="lg">
            <a href={latestUrl} target="_blank" rel="noreferrer">
              <Download className="mr-1.5 h-4 w-4" />
              Download MBT_POS_Setup.exe
            </a>
          </Button>
          <Button asChild variant="outline">
            <Link to="/license">Activate after install</Link>
          </Button>
          <Button asChild variant="outline">
            <Link to="/devices">Manage devices</Link>
          </Button>
        </CardContent>
      </Card>

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <MonitorSmartphone className="h-4 w-4 text-primary" /> New computer
            </CardTitle>
            <CardDescription>
              Download → install → Setup Wizard → Portal sign-in / create account → activate device.
            </CardDescription>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Download className="h-4 w-4 text-primary" /> Existing install
            </CardTitle>
            <CardDescription>
              Run the same Setup.exe — upgrade mode backs up the database, updates files, and
              preserves license & settings.
            </CardDescription>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <BookOpen className="h-4 w-4 text-primary" /> Docs & drivers
            </CardTitle>
            <CardDescription>
              Release notes, printer templates and support live under Documentation and Support.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button asChild variant="outline" size="sm" className="w-full">
              <Link to="/support">Open Support</Link>
            </Button>
          </CardContent>
        </Card>
      </div>

      <Card className="mt-4">
        <CardHeader>
          <CardTitle className="font-display">Published releases</CardTitle>
          <CardDescription>Verified packages from the Update Center.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {updates.length === 0 ? (
            <div className="rounded-xl border border-dashed border-border/80 p-4 text-sm text-muted-foreground">
              <p>
                No cloud releases listed yet. Use the primary download above (GitHub / latest
                published Setup).
              </p>
              <Button asChild variant="link" className="mt-2 h-auto px-0">
                <a href={FALLBACK_INSTALLER} target="_blank" rel="noreferrer">
                  <FileText className="mr-1.5 h-3.5 w-3.5" />
                  Open latest GitHub release asset
                </a>
              </Button>
            </div>
          ) : (
            updates.map((u) => (
              <div
                key={u.version}
                className="flex items-center justify-between gap-3 rounded-xl border border-border/70 p-3"
              >
                <div>
                  <div className="font-semibold">v{u.version}</div>
                  <div className="text-xs text-muted-foreground">
                    {u.release_notes || "Release package"}
                  </div>
                </div>
                {u.download_url ? (
                  <Button asChild size="sm">
                    <a href={u.download_url} target="_blank" rel="noreferrer">
                      <Download className="mr-1.5 h-4 w-4" />
                      Download
                    </a>
                  </Button>
                ) : null}
              </div>
            ))
          )}
        </CardContent>
      </Card>
    </PageShell>
  );
}
