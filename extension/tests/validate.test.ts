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

  it("accepts a workflow the GDV named, and refuses a name that is too long or empty", () => {
    const base = structuredClone(valid["../../schemas/examples/valid/workflow-java-login.json"]) as { title?: string };
    expect(base.title).toBe("Đăng nhập");
    expect(validateWorkflow(base)).toEqual([]);
    expect(validateWorkflow({ ...base, title: "x".repeat(81) }).join()).toContain("title");
    expect(validateWorkflow({ ...base, title: "" }).join()).toContain("title");
  });

  it("accepts Enter pressed in a field, as an event and as a step", () => {
    expect(validateEvent(valid["../../schemas/examples/valid/event-java-submit.json"])).toEqual([]);
    const login = structuredClone(valid["../../schemas/examples/valid/workflow-java-login.json"]) as { steps: { target?: unknown }[] };
    delete login.steps[1]!.target;
    expect(validateWorkflow(login).join()).toContain("thiếu trường target"); // a step that acts on a field needs the field
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
