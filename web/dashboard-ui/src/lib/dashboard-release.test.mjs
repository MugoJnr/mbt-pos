import assert from "node:assert/strict";
import test from "node:test";
import {
  dashboardMismatch,
  releaseNeedsRefresh,
  scriptsMatch,
} from "./dashboard-release.ts";

const servedBuild = {
  version: "3.1.77",
  build: "RC-2026-11-03-v3.1.77",
  entry_script: "/assets/index-DyTKToKH.js",
  asset_ready: true,
};

test("the same dashboard file is current even when its baked version is older", () => {
  assert.equal(
    dashboardMismatch("/assets/index-DyTKToKH.js", "3.1.76", servedBuild),
    false,
  );
  const decision = releaseNeedsRefresh(
    "http://127.0.0.1:5050/assets/index-DyTKToKH.js",
    "3.1.76",
    servedBuild,
    "/assets/index-DyTKToKH.js",
  );
  assert.equal(decision.show, false);
  assert.equal(decision.landed, true);
  assert.equal(decision.missed, false);
});

test("a refresh that loaded the served file keeps the button hidden", () => {
  const decision = releaseNeedsRefresh(
    "/assets/index-DyTKToKH.js?dashboard=RC-2026-11-03-v3.1.77",
    "3.1.76",
    servedBuild,
    "",
  );
  assert.equal(decision.show, false);
  assert.equal(decision.landed, false);
});

test("a different dashboard file still asks for a refresh", () => {
  assert.equal(scriptsMatch("/assets/index-OLD.js", "/assets/index-DyTKToKH.js"), false);
  const decision = releaseNeedsRefresh(
    "/assets/index-OLD.js",
    "3.1.77",
    servedBuild,
    "/assets/index-DyTKToKH.js",
  );
  assert.equal(decision.show, true);
  assert.equal(decision.missed, true);
  assert.equal(decision.landed, false);
});

test("a missing served file asks for a refresh until that file is the open page", () => {
  const missing = { ...servedBuild, asset_ready: false };
  assert.equal(dashboardMismatch("/assets/index-OLD.js", "3.1.77", missing), true);
  assert.equal(dashboardMismatch("/assets/index-DyTKToKH.js", "3.1.76", missing), false);
});
