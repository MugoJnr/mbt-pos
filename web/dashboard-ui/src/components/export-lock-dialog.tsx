import { useState } from "react";
import { Button, Input } from "@/components/ui-kit";

const MIN_LEN = 10;

export function ExportLockDialog({
  open,
  kind,
  busy,
  error,
  onCancel,
  onConfirm,
}: {
  open: boolean;
  kind: string;
  busy?: boolean;
  error?: string;
  onCancel: () => void;
  onConfirm: (password: string) => void;
}) {
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [show, setShow] = useState(false);
  const [localError, setLocalError] = useState("");

  if (!open) return null;

  function generate() {
    const bytes = new Uint8Array(12);
    crypto.getRandomValues(bytes);
    const value = btoa(String.fromCharCode(...bytes))
      .replace(/\+/g, "")
      .replace(/\//g, "")
      .replace(/=/g, "");
    setPassword(value);
    setConfirm(value);
    setShow(true);
    setLocalError("");
  }

  function copy() {
    if (!password) return;
    void navigator.clipboard.writeText(password);
  }

  function submit() {
    if (password !== confirm) {
      setLocalError("The passwords do not match.");
      return;
    }
    if (password.trim().length < MIN_LEN || password !== password.trim()) {
      setLocalError(`Use at least ${MIN_LEN} characters, with no spaces at the ends.`);
      return;
    }
    setLocalError("");
    onConfirm(password);
  }

  const message = localError || error || "";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div
        role="dialog"
        aria-labelledby="export-lock-title"
        className="w-full max-w-md rounded-xl border border-border bg-card p-5 text-text shadow-xl"
      >
        <h2 id="export-lock-title" className="text-lg font-bold">
          Encrypt this {kind}
        </h2>
        <p className="mt-2 text-sm text-text2">
          The file itself is locked. It stays locked if you copy it, email it, or put it on a
          USB drive. This password is not your login and not the Super-Admin PIN. Send it
          separately from the file. A printout is not encrypted.
        </p>
        <p className="mt-2 text-xs font-semibold text-text2">
          {kind === "CSV"
            ? "A CSV cannot hold a password, so this download is a locked ZIP. A phone that cannot open a ZIP should use PDF or Excel instead. Those files are locked themselves and do not need a ZIP."
            : kind === "PDF"
              ? "Method: PDF AES-256. The phone PDF reader asks for this password. There is no ZIP."
              : "Method: Excel file encryption (AES). The Excel app on a phone asks for this password. There is no ZIP."}
        </p>
        <label className="mt-4 block text-xs font-semibold text-text2">
          Password
          <Input
            type={show ? "text" : "password"}
            value={password}
            autoComplete="new-password"
            onChange={(e) => setPassword(e.target.value)}
            className="mt-1 min-h-[44px]"
          />
        </label>
        <label className="mt-3 block text-xs font-semibold text-text2">
          Confirm password
          <Input
            type={show ? "text" : "password"}
            value={confirm}
            autoComplete="new-password"
            onChange={(e) => setConfirm(e.target.value)}
            className="mt-1 min-h-[44px]"
          />
        </label>
        <div className="mt-3 flex flex-wrap gap-2">
          <Button type="button" variant="secondary" className="min-h-[40px]" onClick={() => setShow((v) => !v)}>
            {show ? "Hide" : "Show"}
          </Button>
          <Button type="button" variant="secondary" className="min-h-[40px]" onClick={generate}>
            Generate
          </Button>
          <Button type="button" variant="secondary" className="min-h-[40px]" onClick={copy}>
            Copy
          </Button>
        </div>
        {message ? <p className="mt-3 text-sm text-[#E53935]">{message}</p> : null}
        <div className="mt-4 flex justify-end gap-2">
          <Button type="button" variant="secondary" className="min-h-[44px]" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
          <Button type="button" className="min-h-[44px]" onClick={submit} disabled={busy}>
            {busy ? "Encrypting…" : "Encrypt and download"}
          </Button>
        </div>
      </div>
    </div>
  );
}
