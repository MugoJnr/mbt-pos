/** Same quantity rules as desktop/utils/quantities.py. */

const MEASURED = new Set([
  "kg", "kgs", "kilogram", "kilograms",
  "g", "gram", "grams",
  "l", "lt", "ltr", "litre", "liter", "litres", "liters",
  "ml", "millilitre", "milliliter", "millilitres", "milliliters",
  "m", "metre", "meter", "metres", "meters",
  "cm", "centimetre", "centimeter", "centimetres", "centimeters",
]);

const PIECE = new Set([
  "pcs", "pc", "piece", "pieces", "unit", "units",
  "item", "items", "each", "ea", "nos", "no",
]);

export function decimalChoice(value: unknown): boolean | null {
  if (value == null || value === "") return null;
  const text = String(value).trim().toLowerCase();
  if (text === "1" || text === "true" || text === "yes" || text === "allow") return true;
  if (text === "0" || text === "false" || text === "no" || text === "whole") return false;
  return null;
}

export function allowsFraction(unit: string | undefined | null, decimalQty?: unknown) {
  const choice = decimalChoice(decimalQty);
  if (choice === true) return true;
  if (choice === false) return false;
  return !PIECE.has(String(unit || "").trim().toLowerCase());
}

export function quantityStep(unit: string | undefined | null, wheel = 0.25, decimalQty?: unknown) {
  if (!allowsFraction(unit, decimalQty)) return 1;
  const name = String(unit || "").trim().toLowerCase();
  if (MEASURED.has(name) || decimalChoice(decimalQty) === true) return wheel > 0 ? wheel : 0.25;
  return 0.01;
}

export function parseQuantity(
  raw: string | number,
  unit?: string | null,
  options?: { allowZero?: boolean; decimalQty?: unknown },
): { quantity: number } | { error: string } {
  const text = String(raw ?? "").trim().replace(/,/g, "");
  if (!/^-?\d+(\.\d+)?$/.test(text)) return { error: "Enter a valid quantity." };
  if (text.includes(".") && text.split(".")[1].length > 4) {
    return { error: "Too many decimal places in the quantity." };
  }
  const quantity = Number(text);
  if (!Number.isFinite(quantity)) return { error: "Enter a valid quantity." };
  const kept = Math.round(quantity * 10000) / 10000;
  if (!allowsFraction(unit, options?.decimalQty) && Math.abs(kept - Math.round(kept)) > 1e-9) {
    return { error: "Quantity must be in whole units." };
  }
  if (quantity < 0) return { error: "Quantity cannot be negative." };
  if (quantity === 0 && !options?.allowZero) return { error: "Quantity must be greater than zero." };
  return { quantity: kept };
}

export function formatQuantity(value: number) {
  const n = Math.round(Number(value) * 10000) / 10000;
  if (!Number.isFinite(n)) return "0";
  return String(n);
}
