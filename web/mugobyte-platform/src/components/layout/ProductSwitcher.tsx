import { Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { Boxes, ArrowUpRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useAuth } from "@/lib/auth";
import { canLaunch, fetchApplications, groupAppsBySection } from "@/lib/platform";

/** Product switcher — launches apps inside the authenticated Workspace (sectioned). */
export function ProductSwitcher() {
  const { orgId } = useAuth();
  const appsQ = useQuery({
    queryKey: ["platform-apps", orgId || "default"],
    queryFn: () => fetchApplications(orgId),
  });
  const apps = appsQ.data || [];
  const sections = groupAppsBySection(apps);

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="outline"
          size="icon"
          aria-label="My Products"
          className="brand-interactive hidden h-9 w-9 sm:inline-flex"
        >
          <Boxes className="h-4 w-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="max-h-[70vh] w-80 overflow-y-auto">
        <DropdownMenuLabel>My Products</DropdownMenuLabel>
        {sections.map((group, idx) => (
          <div key={group.section}>
            {idx > 0 ? <DropdownMenuSeparator /> : <DropdownMenuSeparator />}
            <DropdownMenuLabel className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
              {group.section}
            </DropdownMenuLabel>
            {group.apps.map((app) => {
              const launchable = canLaunch(app);
              const url = (app.launch_url || "/pos").startsWith("/")
                ? app.launch_url || "/pos"
                : "/dashboard";
              return (
                <DropdownMenuItem key={app.id} asChild disabled={!launchable}>
                  {launchable ? (
                    <Link
                      to={url as "/pos"}
                      className="flex cursor-pointer items-center justify-between gap-2"
                    >
                      <span className="truncate font-medium">{app.name}</span>
                      <span className="flex items-center gap-1">
                        <Badge variant="secondary" className="text-[10px] capitalize">
                          {app.status.replace(/_/g, " ")}
                        </Badge>
                        <ArrowUpRight className="h-3.5 w-3.5 text-muted-foreground" />
                      </span>
                    </Link>
                  ) : (
                    <div className="flex w-full items-center justify-between gap-2 opacity-70">
                      <span className="truncate">{app.name}</span>
                      <Badge variant="outline" className="text-[10px]">
                        Soon
                      </Badge>
                    </div>
                  )}
                </DropdownMenuItem>
              );
            })}
          </div>
        ))}
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <Link to="/dashboard">View all in Workspace</Link>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
