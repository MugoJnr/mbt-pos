import test from "node:test";
import assert from "node:assert/strict";
import { cleanDeviceId, deviceIdError, graceDaysFor, graceView, normalizeDeviceId } from "./licenseAdmin.ts";

test("accepts POS and Pulse device ids", () => {
  assert.equal(deviceIdError("MBT-PC-52E6"), null);
  assert.equal(deviceIdError("a".repeat(40)), null);
  assert.match(deviceIdError("till-1") || "", /MBT-PC/);
  assert.equal(normalizeDeviceId("mbt-pc-52e6"), "MBT-PC-52E6");
  assert.equal(cleanDeviceId("Ab".repeat(20)), "ab".repeat(20));
});

test("grace lock follows the product window", () => {
  const now = Date.parse("2026-10-23T00:00:00Z");
  const seen = "2026-10-10T00:00:00Z";
  assert.equal(graceDaysFor("mbt-pos"), 7);
  assert.equal(graceDaysFor("pulse"), 30);
  assert.equal(graceView(seen, now, graceDaysFor("mbt-pos")), "Grace lock");
  assert.equal(graceView(seen, now, graceDaysFor("pulse")), "Within grace");
  assert.equal(graceView(null, now, 7), "Not seen yet");
});
