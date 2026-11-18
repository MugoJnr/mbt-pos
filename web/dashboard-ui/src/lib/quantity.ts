/** Same quantity rules as desktop/utils/quantities.py. */

const MEASURED = new Set([
  "kg", "kgs", "kilogram", "kilograms",
  "g", "gram", "grams",
  "l", "lt", "ltr", "litre", "liter", "litres", "liters",
  "ml", "millilitre", "milliliter", "millilitres", "milliliters",
  "m", "metre", "meter", "metres", "meters",
  "cm", "centimetre", "centimeter", "centimetres", "centimeters",
]);

export function allowsFraction(_unit: string | undefined | null) {
  return true;
}

export function quantityStep(unit: string | undefined | null, wheel = 0.25) {
  const name = String(unit || "").trim().toLowerCase();
  if (MEASURED.has(name)) return wheel > 0 ? wheel : 0.25;
  return 0.01;
}

export function parseQuantity(raw: string | number, unit?: string | null): { quantity: number } | { error: string } {
  const text = String(raw ?? "").trim().replace(/,/g, "");
  if (!/^-?\d+(\.\d+)?$/.test(text)) return { error: "Enter a valid quantity." };
  if (text.includes(".") && text.split(".")[1].length > 4) {
    return { error: "Too many decimal places in the quantity." };
  }
  const quantity = Number(text);
  if (!Number.isFinite(quantity)) return { error: "Enter a valid quantity." };
  if (quantity < 0) return { error: "Quantity cannot be negative." };
  if (quantity === 0) return { error: "Quantity must be greater than zero." };
  return { quantity: Math.round(quantity * 10000) / 10000 };
}

export function formatQuantity(value: number) {
  const n = Math.round(Number(value) * 10000) / 10000;
  if (!Number.isFinite(n)) return "0";
  return String(n);
}
