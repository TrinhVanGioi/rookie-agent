import { describe, expect, it } from "vitest";
import { ACTION_LABELS, SCHEMA_VERSION } from "../src/shared/constants";

describe("shared constants", () => {
  it("exposes the schema version used by the contracts", () => {
    expect(SCHEMA_VERSION).toBe(1);
  });

  it("uses the agreed Vietnamese action names", () => {
    expect(Object.values(ACTION_LABELS)).toEqual(["Ghi", "Học", "Duyệt", "Chạy", "Dừng khẩn"]);
  });
});
