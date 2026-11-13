/// <reference types="vite/client" />
import { describe, expect, it } from "vitest";
import { validateEvent, validateWorkflow } from "../src/shared/validate";

// Same example files the server and Windows agent tests use.
const valid = import.meta.glob("../../schemas/examples/valid/*.json", { eager: true, import: "default" });
const invalid = import.meta.glob("../../schemas/examples/invalid/*.json", { eager: true, import: "default" });

function check(path: string, document: unknown): string[] {
  const name = path.split("/").pop() ?? "";
  return name.startsWith("event-") ? validateEvent(document) : validateWorkflow(document);
}

describe("schema validation", () => {
  it("finds examples for both engines", () => {
    const names = Object.keys(valid).map((path) => path.split("/").pop());
    expect(names).toEqual(expect.arrayContaining(["event-web-click.json", "event-java-click.json"]));
    expect(names).toEqual(expect.arrayContaining(["workflow-web.json", "workflow-java.json"]));
    expect(Object.keys(invalid).length).toBeGreaterThanOrEqual(10);
  });

  it.each(Object.entries(valid))("accepts %s", (path, document) => {
    expect(check(path, document)).toEqual([]);
  });

  it.each(Object.entries(invalid))("rejects %s", (path, document) => {
    expect(check(path, document).length).toBeGreaterThan(0);
  });

  it("names the failing field", () => {
    const workflow = structuredClone(valid["../../schemas/examples/valid/workflow-web.json"]) as {
      steps: { risk: string }[];
    };
    workflow.steps[0]!.risk = "danger";
    expect(validateWorkflow(workflow).join("\n")).toContain("steps/0/risk");
  });

  it("rejects a money step set to auto", () => {
    const workflow = structuredClone(valid["../../schemas/examples/valid/workflow-java.json"]) as {
      steps: { risk: string; mode: string }[];
    };
    const money = workflow.steps.find((step) => step.risk === "money")!;
    money.mode = "auto";
    expect(validateWorkflow(workflow).length).toBeGreaterThan(0);
  });
});
