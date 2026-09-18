/**
 * Node smoke tests for profit KPI null/incomplete display rules.
 * Run: node scripts/test_profit_display.mjs
 *
 * Mirrors profitKpiFromSummary / formatCompactMoney in analytics.ts
 * (kept in sync intentionally — no vitest in this package yet).
 */
import assert from "node:assert/strict";

const PROFIT_UNAVAILABLE_HINT = "Cost data incomplete — profit unavailable";

function isMissingAmount(value) {
  return value === null || value === undefined || value === "";
}

function formatNumber(value, digits = 0) {
  const amount = Number(value || 0);
  return Number.isFinite(amount)
    ? amount.toLocaleString("en-KE", { maximumFractionDigits: digits })
    : "0";
}

function formatCompactMoney(value, currency = "KES") {
  if (isMissingAmount(value)) return "—";
  const amount = Number(value);
  const code = currency === "KES" || currency === "KSh" ? "KSh" : currency;
  if (!Number.isFinite(amount)) return "—";
  const sign = amount < 0 ? "-" : "";
  const abs = Math.abs(amount);
  if (abs >= 10_000) return `${code} ${sign}${(abs / 1_000).toFixed(1)}K`;
  if (Math.abs(abs - Math.round(abs)) < 0.005) {
    return `${code} ${sign}${Math.round(abs).toLocaleString("en-KE")}`;
  }
  return `${code} ${sign}${abs.toLocaleString("en-KE", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function profitKpiFromSummary(summary, profit, margin, currency = "KES") {
  const status = String(summary.cost_data_status || "");
  const txns = Number(summary.transactions ?? summary.sales_count ?? 0) || 0;
  const salesTotal =
    Number(summary.gross_sales ?? summary.sales_total ?? summary.revenue ?? 0) || 0;
  const hasSalesActivity = txns > 0 || salesTotal > 0;
  const flaggedIncomplete =
    Boolean(summary.cost_data_incomplete) ||
    status === "incomplete" ||
    (status === "no_items" && hasSalesActivity);
  const unavailable =
    flaggedIncomplete || (isMissingAmount(profit) && hasSalesActivity);
  const message = String(summary.cost_data_message || "").trim();
  if (unavailable) {
    return {
      amount: "—",
      hint: message || PROFIT_UNAVAILABLE_HINT,
      unavailable: true,
    };
  }
  if (isMissingAmount(profit)) {
    return {
      amount: "—",
      hint: hasSalesActivity ? PROFIT_UNAVAILABLE_HINT : "No sales in range",
      unavailable: false,
    };
  }
  return {
    amount: formatCompactMoney(profit, currency),
    hint:
      margin != null && margin !== ""
        ? `${formatNumber(margin, 1)}% margin`
        : "From sale-time costs",
    unavailable: false,
  };
}

// --- cases matching the Edmus Sep 8–9 screenshot bug ---
{
  const kpi = profitKpiFromSummary(
    {
      transactions: 37,
      gross_sales: 11400,
      cost_data_incomplete: false,
      cost_data_status: "no_items",
      inventory_value: 844200,
    },
    null, // API null profit
    null,
  );
  assert.equal(kpi.amount, "—");
  assert.match(kpi.hint, /profit unavailable/i);
  assert.equal(kpi.unavailable, true);
  assert.notEqual(kpi.amount, "KSh 0");
}

{
  // UI used to coerce null→0 when inventory existed and incomplete flag was false
  assert.equal(formatCompactMoney(null), "—");
  assert.equal(formatCompactMoney(undefined), "—");
  assert.equal(formatCompactMoney(""), "—");
  assert.equal(formatCompactMoney(0), "KSh 0"); // real zero profit still allowed
}

{
  const kpi = profitKpiFromSummary(
    {
      transactions: 1,
      gross_sales: 1000,
      cost_data_incomplete: true,
      cost_data_status: "incomplete",
      cost_data_message: PROFIT_UNAVAILABLE_HINT,
    },
    null,
    null,
  );
  assert.equal(kpi.amount, "—");
  assert.equal(kpi.hint, PROFIT_UNAVAILABLE_HINT);
}

{
  const kpi = profitKpiFromSummary(
    { transactions: 2, gross_sales: 1500, cost_data_status: "complete" },
    920,
    61.3,
  );
  assert.equal(kpi.amount, "KSh 920");
  assert.equal(kpi.hint, "61.3% margin");
  assert.equal(kpi.unavailable, false);
}

{
  // Empty range: no incomplete banner from bare null profit
  const kpi = profitKpiFromSummary(
    { transactions: 0, gross_sales: 0, cost_data_status: "no_items" },
    null,
    null,
  );
  assert.equal(kpi.amount, "—");
  assert.equal(kpi.unavailable, false);
  assert.equal(kpi.hint, "No sales in range");
}

console.log("test_profit_display.mjs: OK");
