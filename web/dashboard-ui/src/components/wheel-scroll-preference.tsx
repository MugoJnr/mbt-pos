import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { GET, PUT } from "@/lib/api";
import { useAuth } from "@/lib/auth";

/** The signed-in account's mouse-wheel interval. The same value on the till and the web. */
export function WheelScrollPreference({ compact = false }: { compact?: boolean }) {
  const qc = useQueryClient();
  const { user } = useAuth();
  const scrollQ = useQuery({
    queryKey: ["account-scroll"],
    queryFn: () => GET<{ wheel_scroll_interval?: number }>("/account/scroll"),
    enabled: Boolean(user),
  });
  const [value, setValue] = useState("");
  const [ready, setReady] = useState(false);
  const [msg, setMsg] = useState("");
  const saved = scrollQ.data?.wheel_scroll_interval;
  useEffect(() => {
    if (!saved) return;
    setValue(String(saved));
    setReady(true);
  }, [saved]);

  async function save(next: string) {
    if (!ready || Number(next) === Number(saved)) return;
    setMsg("");
    const res = await PUT<{ success?: boolean; error?: string; wheel_scroll_interval?: number }>(
      "/account/scroll",
      { wheel_scroll_interval: Number(next) },
    );
    if (!res?.success) {
      setMsg(res?.error || "Not saved");
      return;
    }
    setValue(String(res.wheel_scroll_interval || next));
    setMsg("Saved for this account");
    qc.setQueryData(["account-scroll"], { wheel_scroll_interval: res.wheel_scroll_interval });
  }

  return (
    <label className={compact ? "block text-[11px] text-text2" : "block text-sm text-text2"}>
      Mouse Wheel Scroll Interval
      <span className="mt-1 flex items-center gap-2">
        <input
          aria-label="Mouse Wheel Scroll Interval"
          type="number"
          min={1}
          max={10}
          step={1}
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onWheel={(event) => event.preventDefault()}
          onBlur={() => void save(value)}
          className="h-9 w-16 rounded-md border border-border bg-card px-2 text-sm text-text"
        />
        {!compact ? <span>1 small, 10 fast. This account only.</span> : null}
      </span>
      {msg ? <span className="mt-1 block text-[11px] text-text2">{msg}</span> : null}
    </label>
  );
}
