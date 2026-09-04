import assert from "node:assert/strict";
import test from "node:test";
import { hasStringFields, parseList } from "../src/lib/list-response.ts";

const isItem = (value) => hasStringFields(value, ["id", "name"]);
test("genuine bare and paginated empty results remain empty", () => {
  assert.deepEqual(parseList([], isItem, "Items"), []);
  assert.deepEqual(parseList({ results: [] }, isItem, "Items"), []);
});
test("missing, malformed and partially malformed results never become empty", () => {
  for (const payload of [
    null,
    {},
    { results: null },
    { results: {} },
    [{ id: "x" }],
    [
      { id: "x", name: "Valid" },
      { id: 2, name: "Invalid" },
    ],
  ]) {
    assert.throws(() => parseList(payload, isItem, "Items"), /invalid list/);
  }
});
test("valid records retain their values", () => {
  const rows = [{ id: "one", name: "Known" }];
  assert.deepEqual(parseList({ results: rows }, isItem, "Items"), rows);
});
