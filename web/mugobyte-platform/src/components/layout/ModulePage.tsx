import { useRef, type ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { Download, Plus, Printer } from "lucide-react";

import { PageShell, PageHeader, EmptyState } from "@/components/layout/PageShell";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";

/**
 * Reusable premium page shell for module screens.
 * Renders header, quick filter row, tabs, and a content slot (defaults to EmptyState).
 * Every table/form/dialog can plug in later without changing the layout.
 */
export function ModulePage({
  eyebrow,
  title,
  description,
  icon,
  tabs,
  primaryAction,
  onPrimaryAction,
  emptyTitle,
  emptyDescription,
  children,
}: {
  eyebrow: string;
  title: string;
  description: string;
  icon: LucideIcon;
  tabs?: string[];
  primaryAction?: string;
  onPrimaryAction?: () => void;
  emptyTitle?: string;
  emptyDescription?: string;
  children?: ReactNode;
}) {
  const exportRef = useRef<HTMLDivElement>(null);
  const exportPage = () => {
    const text = exportRef.current?.innerText?.trim() || `${title}\n${description}`;
    const url = URL.createObjectURL(new Blob([text], { type: "text/plain;charset=utf-8" }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${title.toLowerCase().replace(/[^a-z0-9]+/g, "-") || "export"}.txt`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  };

  return (
    <div ref={exportRef}>
      <PageShell>
      <PageHeader
        eyebrow={eyebrow}
        title={title}
        description={description}
        actions={
          <>
            <Button variant="outline" size="sm" onClick={() => window.print()}><Printer className="mr-1.5 h-3.5 w-3.5" />Print</Button>
            <Button variant="outline" size="sm" onClick={exportPage}><Download className="mr-1.5 h-3.5 w-3.5" />Export</Button>
            {primaryAction && onPrimaryAction ? (
              <Button size="sm" onClick={onPrimaryAction}><Plus className="mr-1.5 h-3.5 w-3.5" />{primaryAction}</Button>
            ) : null}
          </>
        }
      />

      <Card>
        <CardHeader className="gap-4 space-y-0">
          {tabs && tabs.length > 0 && (
            <Tabs defaultValue={tabs[0]}>
              <TabsList className="h-9">
                {tabs.map((t) => (
                  <TabsTrigger key={t} value={t} className="text-xs">{t}</TabsTrigger>
                ))}
              </TabsList>
            </Tabs>
          )}
        </CardHeader>
        <CardContent>
          {children ?? (
            <EmptyState
              icon={icon}
              title={emptyTitle ?? `No ${title.toLowerCase()} yet`}
              description={
                emptyDescription ??
                `Connect your MBT POS or add your first ${title.toLowerCase().replace(/s$/, "")} to see it here.`
              }
            />
          )}
        </CardContent>
      </Card>
      </PageShell>
    </div>
  );
}

/** Small helper card used by pages that want a lightweight info section. */
export function InfoCard({ title, description, children }: { title: string; description?: string; children?: ReactNode }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="font-display text-base">{title}</CardTitle>
        {description && <CardDescription>{description}</CardDescription>}
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}
