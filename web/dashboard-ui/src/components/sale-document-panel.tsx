import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui-kit";
import { GET, POST } from "@/lib/api";
import { downloadApi } from "@/lib/download";
import { KES } from "@/lib/format";

const UNAVAILABLE = "Sale saved successfully. Printer unavailable. You can view, download or print the document later.";

export function SaleDocumentPanel({
  saleId,
  paymentReceipt,
  notice,
  currency,
  onClose,
}: {
  saleId?: number;
  paymentReceipt?: string;
  notice?: string;
  currency: string;
  onClose: () => void;
}) {
  const [doc, setDoc] = useState<any>(null);
  const [banner, setBanner] = useState(notice || "");
  const [kind, setKind] = useState("");

  async function load(nextKind = kind) {
    const path = paymentReceipt
      ? `/documents/payment?receipt=${encodeURIComponent(paymentReceipt)}`
      : `/sales/${saleId}/document${nextKind ? `?kind=${nextKind}` : ""}`;
    const loaded = await GET<any>(path);
    if (!loaded || loaded.error) {
      toast.error(loaded?.error || "The document could not be opened.");
      return;
    }
    setDoc(loaded);
    setKind(loaded.kind === "payment_receipt" ? "" : loaded.kind || "");
  }

  useEffect(() => {
    void load("");
  }, [saleId, paymentReceipt]);

  async function print(reprint: boolean) {
    if (paymentReceipt) {
      await browserPrint();
      return;
    }
    const outcome = await POST<any>(`/sales/${saleId}/document/print`, { reprint, automatic: false });
    setBanner(outcome?.printed ? (outcome.message || "Sent to the printer.") : (outcome?.message || UNAVAILABLE));
    if (reprint) await load(kind);
  }

  function browserPrint() {
    const html = doc?.html || `<pre>${doc?.text || ""}</pre>`;
    const frame = document.createElement("iframe");
    frame.title = "Document";
    frame.style.position = "fixed";
    frame.style.width = "0";
    frame.style.height = "0";
    frame.style.border = "0";
    frame.srcdoc = html;
    document.body.appendChild(frame);
    frame.onload = () => {
      frame.contentWindow?.focus();
      frame.contentWindow?.print();
      window.setTimeout(() => frame.remove(), 1500);
    };
  }

  async function download() {
    if (paymentReceipt) {
      await downloadApi(`/documents/payment.pdf?receipt=${encodeURIComponent(paymentReceipt)}`, `${paymentReceipt}.pdf`);
      return;
    }
    await downloadApi(`/sales/${saleId}/document.pdf?kind=${encodeURIComponent(kind || "")}`, `${doc?.number || "document"}.pdf`);
  }

  async function changeKind(next: "receipt" | "invoice") {
    const result = await POST<any>(`/sales/${saleId}/document/kind`, { kind: next });
    if (!result || result.error) {
      toast.error(result?.error || "The document type was not changed.");
      return;
    }
    setBanner(`Document type is ${result.kind}. The number stays ${result.number}.`);
    await load(next);
  }

  const outstanding = Number(doc?.outstanding || 0);
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/50 p-4" role="dialog" aria-label="Sale document">
      <div className="max-h-[90vh] w-full max-w-md overflow-auto rounded-xl border border-border bg-card p-4 text-text">
        {banner ? <p className="mb-3 rounded-lg bg-gold/15 p-3 text-sm font-semibold text-gold">{banner}</p> : null}
        <div className="text-lg font-extrabold">{doc?.title || "Document"} {doc?.number || ""}</div>
        <div className="mt-1 text-sm text-text2">{doc?.payment_status}{doc?.voided ? " · VOIDED" : ""}{doc?.reprint ? " · REPRINT" : ""}</div>
        {doc?.customer?.name ? <div className="mt-1 text-sm">{doc.customer.name} {doc.customer.phone || ""}</div> : null}
        <div className="mt-3 space-y-1 text-sm">
          {(doc?.items || []).map((line: any, index: number) => (
            <div key={index} className="flex justify-between gap-3">
              <span>{line.product_name} × {line.quantity}</span>
              <span className="tabular-nums">{KES(line.total, currency)}</span>
            </div>
          ))}
        </div>
        {doc?.kind === "payment_receipt" ? (
          <div className="mt-3 space-y-1 text-sm">
            <div className="flex justify-between"><span>Original sale</span><span>{doc.receipt_number}</span></div>
            <div className="flex justify-between"><span>Invoice</span><span>{doc.invoice_number}</span></div>
            <div className="flex justify-between"><span>Previous outstanding</span><span className="tabular-nums">{KES(doc.previous_outstanding, currency)}</span></div>
            <div className="flex justify-between font-bold"><span>Received now</span><span className="tabular-nums">{KES(doc.amount_paid, currency)}</span></div>
            <div className="flex justify-between"><span>Method</span><span>{doc.payment_method}</span></div>
          </div>
        ) : (
          <div className="mt-3 space-y-1 text-sm">
            <div className="flex justify-between font-extrabold"><span>Total</span><span className="tabular-nums">{KES(doc?.total, currency)}</span></div>
            <div className="flex justify-between"><span>Paid</span><span className="tabular-nums">{KES(doc?.amount_paid, currency)}</span></div>
            {(doc?.breakdown || []).map((row: any, index: number) => (
              <div key={index} className="flex justify-between text-xs text-text2">
                <span>{row.method}{row.reference ? ` ${row.reference}` : ""}{row.status === "outstanding" ? " outstanding" : ""}</span>
                <span className="tabular-nums">{KES(row.amount, currency)}</span>
              </div>
            ))}
          </div>
        )}
        {outstanding > 0.009 ? (
          <div className="mt-3 text-lg font-extrabold text-gold">Balance due {KES(outstanding, currency)}</div>
        ) : doc?.kind === "invoice" ? (
          <div className="mt-3 text-lg font-extrabold text-ok">PAID</div>
        ) : null}
        {doc?.footer ? <p className="mt-2 text-xs text-text2">{doc.footer}</p> : null}
        <div className="mt-4 flex flex-wrap gap-2">
          {saleId ? <Button type="button" variant="secondary" onClick={() => void load("receipt")}>View receipt</Button> : null}
          {saleId ? <Button type="button" variant="secondary" onClick={() => void load("invoice")}>View invoice</Button> : null}
          <Button type="button" onClick={() => void print(false)}>Print</Button>
          <Button type="button" variant="secondary" onClick={() => void browserPrint()}>Browser print</Button>
          <Button type="button" variant="secondary" onClick={() => void download()}>Download PDF</Button>
          {saleId ? <Button type="button" variant="secondary" onClick={() => void print(true)}>Reprint</Button> : null}
          {doc?.can_override ? <Button type="button" variant="ghost" onClick={() => void changeKind("receipt")}>Use receipt</Button> : null}
          {doc?.can_override ? <Button type="button" variant="ghost" onClick={() => void changeKind("invoice")}>Use invoice</Button> : null}
          <Button type="button" variant="ghost" onClick={onClose}>Close</Button>
        </div>
      </div>
    </div>
  );
}
