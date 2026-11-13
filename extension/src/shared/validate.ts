/**
 * Validate events and workflows against the JSON Schemas in `schemas/`.
 *
 * This is a small interpreter for the subset of JSON Schema those files use.
 * Libraries that compile schemas to code need `new Function`, which Manifest V3
 * forbids. An unknown keyword throws, so a schema change that this interpreter
 * does not understand fails the tests instead of being silently ignored.
 */
import eventSchema from "../../../schemas/event.schema.json";
import workflowSchema from "../../../schemas/workflow.schema.json";

type Schema = Record<string, unknown>;

const ANNOTATIONS = new Set(["$schema", "$id", "title", "description"]);

function typeOf(value: unknown): string {
  if (value === null) return "null";
  if (Array.isArray(value)) return "array";
  if (typeof value === "number") return Number.isInteger(value) ? "integer" : "number";
  return typeof value;
}

function matchesType(value: unknown, expected: string): boolean {
  const actual = typeOf(value);
  return actual === expected || (expected === "number" && actual === "integer");
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeOf(value) === "object";
}

function sameValue(a: unknown, b: unknown): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

function collect(schema: Schema, value: unknown, path: string, errors: string[]): void {
  const at = path || "(root)";
  for (const [keyword, rule] of Object.entries(schema)) {
    if (ANNOTATIONS.has(keyword)) continue;
    switch (keyword) {
      case "type": {
        const allowed = Array.isArray(rule) ? (rule as string[]) : [rule as string];
        if (!allowed.some((name) => matchesType(value, name))) {
          errors.push(`${at}: phải là ${allowed.join(" hoặc ")}`);
        }
        break;
      }
      case "const":
        if (!sameValue(value, rule)) errors.push(`${at}: phải bằng ${JSON.stringify(rule)}`);
        break;
      case "enum":
        if (!(rule as unknown[]).some((option) => sameValue(value, option))) {
          errors.push(`${at}: phải thuộc ${JSON.stringify(rule)}`);
        }
        break;
      case "required":
        if (isRecord(value)) {
          for (const name of rule as string[]) {
            if (!(name in value)) errors.push(`${at}: thiếu trường ${name}`);
          }
        }
        break;
      case "properties":
        if (isRecord(value)) {
          for (const [name, child] of Object.entries(rule as Record<string, Schema>)) {
            if (name in value) collect(child, value[name], path ? `${path}/${name}` : name, errors);
          }
        }
        break;
      case "additionalProperties":
        if (rule !== false) throw new Error("additionalProperties chỉ hỗ trợ giá trị false");
        if (isRecord(value)) {
          const known = (schema.properties ?? {}) as Record<string, unknown>;
          for (const name of Object.keys(value)) {
            if (!(name in known)) errors.push(`${at}: trường thừa ${name}`);
          }
        }
        break;
      case "items":
        if (Array.isArray(value)) {
          value.forEach((item, index) => collect(rule as Schema, item, `${path ? `${path}/` : ""}${index}`, errors));
        }
        break;
      case "minItems":
        if (Array.isArray(value) && value.length < (rule as number)) errors.push(`${at}: cần ít nhất ${rule} phần tử`);
        break;
      case "maxItems":
        if (Array.isArray(value) && value.length > (rule as number)) errors.push(`${at}: tối đa ${rule} phần tử`);
        break;
      case "minimum":
        if (typeof value === "number" && value < (rule as number)) errors.push(`${at}: phải lớn hơn hoặc bằng ${rule}`);
        break;
      case "minLength":
        if (typeof value === "string" && value.length < (rule as number)) errors.push(`${at}: quá ngắn`);
        break;
      case "maxLength":
        if (typeof value === "string" && value.length > (rule as number)) errors.push(`${at}: quá dài`);
        break;
      case "pattern":
        if (typeof value === "string" && !new RegExp(rule as string, "u").test(value)) {
          errors.push(`${at}: sai định dạng`);
        }
        break;
      case "allOf":
        for (const part of rule as Schema[]) collect(part, value, path, errors);
        break;
      case "if": {
        const probe: string[] = [];
        collect(rule as Schema, value, path, probe);
        if (probe.length === 0 && schema.then) collect(schema.then as Schema, value, path, errors);
        break;
      }
      case "then":
        break; // handled together with "if"
      default:
        throw new Error(`Từ khoá JSON Schema chưa hỗ trợ: ${keyword}`);
    }
  }
}

function validate(schema: Schema, document: unknown): string[] {
  const errors: string[] = [];
  collect(schema, document, "", errors);
  return errors;
}

/** Returns the list of problems; an empty list means the event is valid. */
export function validateEvent(document: unknown): string[] {
  return validate(eventSchema as Schema, document);
}

/** Returns the list of problems; an empty list means the workflow is valid. */
export function validateWorkflow(document: unknown): string[] {
  return validate(workflowSchema as Schema, document);
}
