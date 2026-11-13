/**
 * How a field's value may be stored (docs/design.md 4.2). Same table and same rules as the Windows agent
 * (`config/field-classes.json`): the first rule that matches the label wins, and anything unknown is sensitive.
 */
import config from "../../../config/field-classes.json";

export type FieldKind = "ignore" | "sensitive" | "plain";

export interface FieldClass {
  kind: FieldKind;
  value_class: string | null;
}

interface Rule {
  kind: FieldKind;
  value_class?: string;
  pattern: string;
}

const RULES = (config.rules as Rule[]).map((rule) => ({
  kind: rule.kind,
  value_class: rule.value_class ?? null,
  pattern: new RegExp(rule.pattern, "i"),
}));
const IGNORED_INPUT_TYPES = new Set<string>(config.ignore_input_types);

export function normalizeLabel(label: string): string {
  return label.normalize("NFC").toLowerCase().split(/\s+/).filter(Boolean).join(" ");
}

/** `inputType` is the HTML type of the control (`password` is never stored, whatever the label says). */
export function classifyField(label: string, inputType = ""): FieldClass {
  if (IGNORED_INPUT_TYPES.has(inputType.toLowerCase())) return { kind: "ignore", value_class: null };
  const text = normalizeLabel(label);
  for (const rule of RULES) {
    if (rule.pattern.test(text)) return { kind: rule.kind, value_class: rule.value_class };
  }
  return { kind: config.default.kind as FieldKind, value_class: config.default.value_class };
}
