import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Sparkles, Send, Lightbulb, AlertTriangle } from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { Badge, Button, Card, Input, PageHeader, SectionTitle } from "@/components/ui-kit";
import { GET, POST } from "@/lib/api";

export const Route = createFileRoute("/ai")({
  component: AiPage,
});

type Msg = { role: "user" | "assistant"; text: string; source?: string };

function AiPage() {
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Msg[]>([
    {
      role: "assistant",
      text: "Ask about today's sales, stock, debt, or backups. Uses live AI when configured; otherwise local heuristics.",
      source: "local",
    },
  ]);

  const insightsQ = useQuery({
    queryKey: ["ai-insights"],
    queryFn: () =>
      GET<{
        summary: string;
        alerts: string[];
        recommendations: string[];
        source: string;
      }>("/ai/insights"),
    refetchInterval: 60_000,
  });

  const chatM = useMutation({
    mutationFn: (message: string) =>
      POST<{ reply: string; source: string }>("/ai/chat", { message, module: "dashboard" }),
    onSuccess: (data, message) => {
      setMessages((m) => [
        ...m,
        { role: "user", text: message },
        {
          role: "assistant",
          text: data?.reply || "No reply",
          source: data?.source || "local",
        },
      ]);
    },
  });

  const insights = insightsQ.data;

  function send() {
    const msg = input.trim();
    if (!msg || chatM.isPending) return;
    setInput("");
    chatM.mutate(msg);
  }

  return (
    <AppShell title="AI Command Center">
      <PageHeader
        eyebrow="Command"
        title="AI Command Center"
        icon={<Sparkles className="h-4 w-4" />}
        description="Insights and chat for remote operators"
      />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card className="p-4">
          <SectionTitle
            action={
              <Badge tone={insights?.source === "ai" ? "ok" : "muted"}>
                {insights?.source || "…"}
              </Badge>
            }
          >
            Business Insights
          </SectionTitle>
          <p className="text-sm text-text mb-4 leading-relaxed">
            {insightsQ.isLoading ? "Loading…" : insights?.summary || "—"}
          </p>
          <div className="space-y-3">
            <div>
              <div className="flex items-center gap-1.5 text-[10px] tracking-[0.16em] uppercase font-semibold text-text2 mb-1.5">
                <AlertTriangle className="h-3 w-3 text-warn" /> Alerts
              </div>
              <ul className="space-y-1">
                {(insights?.alerts || []).map((a, i) => (
                  <li key={i} className="text-sm text-text2 pl-2 border-l-2 border-warn/40">
                    {a}
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <div className="flex items-center gap-1.5 text-[10px] tracking-[0.16em] uppercase font-semibold text-text2 mb-1.5">
                <Lightbulb className="h-3 w-3 text-gold" /> Recommendations
              </div>
              <ul className="space-y-1">
                {(insights?.recommendations || []).map((a, i) => (
                  <li key={i} className="text-sm text-text2 pl-2 border-l-2 border-gold/40">
                    {a}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </Card>

        <Card className="flex flex-col min-h-[420px] overflow-hidden">
          <div className="p-4 border-b border-border">
            <SectionTitle>Chat</SectionTitle>
          </div>
          <div className="flex-1 overflow-y-auto scrollbar-thin p-4 space-y-3">
            {messages.map((m, i) => (
              <div
                key={i}
                className={`max-w-[90%] rounded-lg px-3 py-2 text-sm ${
                  m.role === "user"
                    ? "ml-auto bg-gold/20 text-text"
                    : "mr-auto bg-panel text-text2"
                }`}
              >
                {m.text}
                {m.source ? (
                  <div className="mt-1 text-[10px] uppercase tracking-wide text-muted-fg">
                    {m.source}
                  </div>
                ) : null}
              </div>
            ))}
            {chatM.isPending ? (
              <div className="text-xs text-text2">Thinking…</div>
            ) : null}
          </div>
          <div className="p-3 border-t border-border flex gap-2">
            <Input
              placeholder="Ask about sales, stock, debt…"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") send();
              }}
              className="min-h-[44px]"
            />
            <Button
              variant="primary"
              className="min-h-[44px] min-w-[44px] shrink-0"
              disabled={chatM.isPending || !input.trim()}
              onClick={send}
            >
              <Send className="h-4 w-4" />
            </Button>
          </div>
        </Card>
      </div>
    </AppShell>
  );
}
