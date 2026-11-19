import assert from "node:assert/strict";
import {
  normalizeBackdateReason,
  otherReasonDraft,
  reasonFromOtherDraft,
  showsOtherReasonField,
} from "./backdate-reason.ts";

assert.equal(showsOtherReasonField("Other"), true);
assert.equal(showsOtherReasonField("Transaction entered late"), false);
assert.equal(otherReasonDraft("Other"), "");

let draft = "";
for (const piece of ["the", " ", "shop", " ", "was", " ", "closed"]) {
  draft += piece;
  const stored = reasonFromOtherDraft(draft);
  assert.equal(otherReasonDraft(stored), draft);
}
assert.equal(normalizeBackdateReason(reasonFromOtherDraft("the shop was closed")), "Other: the shop was closed");
assert.equal(normalizeBackdateReason("Other:    "), "Other");
assert.equal(normalizeBackdateReason("Transaction entered late"), "Transaction entered late");
console.log("backdate other reason ok");
