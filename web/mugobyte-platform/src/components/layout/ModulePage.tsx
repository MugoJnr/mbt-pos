import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { Download, FileText, Filter, Plus, Printer, Search } from "lucide-react";

import { PageShell, PageHeader, EmptyState } from "@/components/layout/PageShell";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
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
  primaryAction = "New",
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
  emptyTitle?: string;
  emptyDescription?: string;
  children?: ReactNode;
}) {
  return (
    <PageShell>
      <PageHeader
        eyebrow={eyebrow}
        title={title}
        description={description}
        actions={
          <>
            <Button variant="outline" size="sm"><Printer className="mr-1.5 h-3.5 w-3.5" />Print</Button>
            <Button variant="outline" size="sm"><Download className="mr-1.5 h-3.5 w-3.5" />Export</Button>
            <Button size="sm"><Plus className="mr-1.5 h-3.5 w-3.5" />{primaryAction}</Button>
          </>
        }
      />

      <Card>
        <CardHeader className="gap-4 space-y-0">
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div className="relative w-full max-w-sm">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input placeholder={`Search ${title.toLowerCase()}...`} className="h-9 pl-8" />
            </div>
            <div className="flex items-center gap-2">
              <Button variant="outline" size="sm"><Filter className="mr-1.5 h-3.5 w-3.5" />Filter</Button>
              <Button variant="outline" size="sm"><FileText className="mr-1.5 h-3.5 w-3.5" />Columns</Button>
            </div>
          </div>
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
              actionLabel={`Add ${primaryAction.replace(/^New\s*/i, "") || "item"}`}
            />
          )}
        </CardContent>
      </Card>
    </PageShell>
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
