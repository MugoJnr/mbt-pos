import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AppShell } from "@/components/app-shell";
import { Button, Card, Input, PageHeader, Table } from "@/components/ui-kit";
import { GET, POST } from "@/lib/api";
import { KES } from "@/lib/format";

export const Route = createFileRoute("/finance")({
  component: FinancePage,
});

function localToday() {
  const d = new Date();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${m}-${day}`;
}

function FinancePage() {
  const qc = useQueryClient();
  const today = localToday();
  const [start, setStart] = useState(today.slice(0, 8) + "01");
  const [end, setEnd] = useState(today);
  const [amount, setAmount] = useState("");
  const [description, setDescription] = useState("");
  const [vendor, setVendor] = useState("");
  const [expenseDate, setExpenseDate] = useState(today);
  const [msg, setMsg] = useState("");
  const [journalDesc, setJournalDesc] = useState("");
  const [debit, setDebit] = useState("6000");
  const [credit, setCredit] = useState("1000");
  const [journalAmount, setJournalAmount] = useState("");

  const summaryQ = useQuery({
    queryKey: ["finance-summary"],
    queryFn: () => GET<any>("/finance/summary"),
  });
  const expensesQ = useQuery({
    queryKey: ["finance-expenses", start, end],
    queryFn: () => GET<any>("/finance/expenses", { start, end }),
  });
  const journalsQ = useQuery({
    queryKey: ["finance-journals", start, end],
    queryFn: () => GET<any>("/finance/journals", { start, end }),
  });
  const pnlQ = useQuery({
    queryKey: ["finance-pnl", start, end],
    queryFn: () => GET<any>("/finance/reports/pnl", { start, end }),
  });
  const tbQ = useQuery({
    queryKey: ["finance-tb", end],
    queryFn: () => GET<any>("/finance/reports/trial-balance", { as_of: end }),
  });

  const summary = summaryQ.data?.summary || {};
  const currency = summaryQ.data?.currency || "KES";
  const expenses = Array.isArray(expensesQ.data) ? expensesQ.data : [];
  const journals = Array.isArray(journalsQ.data) ? journalsQ.data : [];
  const pnl = pnlQ.data && !pnlQ.data.error ? pnlQ.data : null;
  const trial = tbQ.data && !tbQ.data.error ? tbQ.data : null;

  async function saveExpense() {
    setMsg("");
    const res = await POST<any>("/finance/expenses", {
      amount,
      description,
      vendor_name: vendor,
      expense_date: expenseDate,
      account_code: "6000",
      pay_from_code: "1000",
    });
    if (res?.success) {
      setAmount("");
      setDescription("");
      setVendor("");
      setMsg(`Saved ${res.expense_number}.`);
      await qc.invalidateQueries({ queryKey: ["finance-expenses"] });
      await qc.invalidateQueries({ queryKey: ["finance-summary"] });
      await qc.invalidateQueries({ queryKey: ["finance-pnl"] });
      await qc.invalidateQueries({ queryKey: ["finance-journals"] });
      return;
    }
    setMsg(res?.error || "Could not save the expense.");
  }

  async function reverseExpense(id: number) {
    const reason = window.prompt("Reason for reversing this expense");
    if (!reason || !reason.trim()) return;
    const res = await POST<any>(`/finance/expenses/${id}/reverse`, { reason: reason.trim() });
    setMsg(res?.success ? "Expense reversed. The original row stays in the list." : res?.error || "Could not reverse.");
    await qc.invalidateQueries({ queryKey: ["finance-expenses"] });
    await qc.invalidateQueries({ queryKey: ["finance-summary"] });
    await qc.invalidateQueries({ queryKey: ["finance-pnl"] });
  }

  async function postJournal() {
    setMsg("");
    const value = Number(journalAmount);
    if (!journalDesc.trim() || !Number.isFinite(value) || value <= 0) {
      setMsg("Enter a description and an amount greater than zero.");
      return;
    }
    const res = await POST<any>("/finance/journals", {
      description: journalDesc.trim(),
      entry_date: end,
      lines: [
        { account_code: debit.trim(), debit: value, memo: journalDesc.trim() },
        { account_code: credit.trim(), credit: value, memo: journalDesc.trim() },
      ],
    });
    if (res?.success) {
      setJournalDesc("");
      setJournalAmount("");
      setMsg("Journal posted. Debits match credits.");
      await qc.invalidateQueries({ queryKey: ["finance-journals"] });
      await qc.invalidateQueries({ queryKey: ["finance-tb"] });
      await qc.invalidateQueries({ queryKey: ["finance-pnl"] });
      return;
    }
    setMsg(res?.error || "Could not post the journal.");
  }

  function exportExpenses() {
    const header = ["Number", "Date", "Description", "Payee", "Amount", "Status"];
    const lines = expenses.map((row: any) =>
      [row.expense_number, row.expense_date, row.description, row.vendor_name, row.amount, row.status]
        .map((cell) => `"${String(cell ?? "").replaceAll('"', '""')}"`)
        .join(","),
    );
    const blob = new Blob([[header.join(","), ...lines].join("\n")], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `expenses-${start}-to-${end}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  }

  return (
    <AppShell title="Finance">
      <PageHeader
        eyebrow="Accounts"
        title="Finance"
        description="Expenses, journals, and reports use the same books as the till. Amounts are in the shop currency."
      />
      <div className="mb-4 grid gap-3 sm:grid-cols-3">
        <Card className="p-4">
          <div className="text-xs text-text2">Month net</div>
          <div className="mt-1 text-xl font-bold text-text">{KES(Number(summary.month_net || 0), currency)}</div>
        </Card>
        <Card className="p-4">
          <div className="text-xs text-text2">Month expenses</div>
          <div className="mt-1 text-xl font-bold text-text">{KES(Number(summary.month_expenses || 0), currency)}</div>
        </Card>
        <Card className="p-4">
          <div className="text-xs text-text2">Cash position</div>
          <div className="mt-1 text-xl font-bold text-text">
            {KES(Number(summaryQ.data?.cash?.balance || summaryQ.data?.cash?.net || 0), currency)}
          </div>
        </Card>
      </div>
      {summaryQ.data?.error ? <div className="mb-3 text-sm text-err">{summaryQ.data.error}</div> : null}

      <Card className="mb-4 p-4">
        <div className="mb-3 text-sm font-semibold text-text">Record an expense</div>
        <div className="grid gap-2 sm:grid-cols-2">
          <Input value={expenseDate} onChange={(e) => setExpenseDate(e.target.value)} type="date" />
          <Input value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="Amount" />
          <Input value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Description" />
          <Input value={vendor} onChange={(e) => setVendor(e.target.value)} placeholder="Payee" />
        </div>
        <Button className="mt-3" onClick={saveExpense}>Save expense</Button>
        {msg ? <div className="mt-2 text-sm text-text2">{msg}</div> : null}
      </Card>

      <Card className="mb-4 p-4">
        <div className="mb-3 flex flex-wrap items-end gap-2">
          <Input value={start} onChange={(e) => setStart(e.target.value)} type="date" />
          <Input value={end} onChange={(e) => setEnd(e.target.value)} type="date" />
          <Button variant="ghost" onClick={exportExpenses}>Export expenses</Button>
        </div>
        <Table head={["Number", "Date", "Description", "Amount", "Status", ""]}>
          {expenses.map((row: any) => (
            <tr key={row.id}>
              <td className="px-4 py-2.5 text-text">{row.expense_number}</td>
              <td className="px-4 py-2.5 text-text2">{row.expense_date}</td>
              <td className="px-4 py-2.5 text-text">{row.description}</td>
              <td className="px-4 py-2.5 text-text">{KES(Number(row.amount || 0), currency)}</td>
              <td className="px-4 py-2.5 text-text2">{row.status}</td>
              <td className="px-4 py-2.5">
                {row.status !== "reversed" ? (
                  <Button variant="ghost" onClick={() => reverseExpense(row.id)}>Reverse</Button>
                ) : null}
              </td>
            </tr>
          ))}
        </Table>
        {expenses.length === 0 ? <div className="py-6 text-sm text-text2">No expenses in this period.</div> : null}
        {pnl ? (
          <div className="mt-3 text-sm text-text2">
            Profit and loss {start} to {end}: income {KES(Number(pnl.total_income || 0), currency)}, expenses{" "}
            {KES(Number(pnl.total_expenses || 0), currency)}, net {KES(Number(pnl.net_profit || 0), currency)}.
            {trial?.balanced === false ? " Trial balance does not balance." : " Trial balance is in balance."}
          </div>
        ) : null}
      </Card>

      <Card className="p-4">
        <div className="mb-3 text-sm font-semibold text-text">Post a balanced journal</div>
        <div className="grid gap-2 sm:grid-cols-2">
          <Input value={journalDesc} onChange={(e) => setJournalDesc(e.target.value)} placeholder="Description" />
          <Input value={journalAmount} onChange={(e) => setJournalAmount(e.target.value)} placeholder="Amount" />
          <Input value={debit} onChange={(e) => setDebit(e.target.value)} placeholder="Debit account" />
          <Input value={credit} onChange={(e) => setCredit(e.target.value)} placeholder="Credit account" />
        </div>
        <Button className="mt-3" onClick={postJournal}>Post journal</Button>
        <div className="mt-4">
          <Table head={["Number", "Date", "Description", "Status"]}>
            {journals.slice(0, 20).map((row: any) => (
              <tr key={row.id}>
                <td className="px-4 py-2.5 text-text">{row.entry_number}</td>
                <td className="px-4 py-2.5 text-text2">{row.entry_date}</td>
                <td className="px-4 py-2.5 text-text">{row.description}</td>
                <td className="px-4 py-2.5 text-text2">{row.status}</td>
              </tr>
            ))}
          </Table>
          {journals.length === 0 ? <div className="py-6 text-sm text-text2">No journals in this period.</div> : null}
        </div>
      </Card>
    </AppShell>
  );
}
