/**
 * Describe an element so it can be found again: several selectors in order of how well they survive a
 * page change, plus the label the GDV sees. Text that could hold personal data is masked, and cells of a
 * data table are described by position only.
 */
import { maskText } from "./mask";

const RANDOM_ID = [
  /\d{4,}/, // generated counters and timestamps
  /^[0-9a-f]{8,}$/i,
  /^[0-9a-f]{8}-[0-9a-f]{4}-/i, // uuid
  /^:r\w*:$/, // React useId
  /^(ext-gen|gwt-uid|ember|react-select|mui-|radix-|headlessui|rc_select|ng-|ui-id)/i,
  /[-_]\d+$/, // input-3, field_12
];

export function isRandomId(id: string): boolean {
  return !id || RANDOM_ID.some((pattern) => pattern.test(id));
}

const IMPLICIT_ROLES: Record<string, string> = {
  button: "button",
  a: "link",
  select: "combobox",
  textarea: "textbox",
  summary: "button",
};

export function roleOf(element: Element): string | null {
  const explicit = element.getAttribute("role");
  if (explicit) return explicit.split(" ")[0] ?? null;
  const tag = element.tagName.toLowerCase();
  if (tag === "input") {
    const type = ((element as HTMLInputElement).type || "text").toLowerCase();
    if (type === "checkbox") return "checkbox";
    if (type === "radio") return "radio";
    if (["button", "submit", "reset"].includes(type)) return "button";
    return "textbox";
  }
  if (tag === "a") return element.hasAttribute("href") ? "link" : null;
  return IMPLICIT_ROLES[tag] ?? null;
}

/** A cell of a data table holds the customer's data; it is only described by where it is. */
export function inDataCell(element: Element): boolean {
  return element.closest("td") !== null;
}

function textOf(node: Element | null | undefined): string {
  return maskText(node?.textContent ?? "");
}

/** What the GDV reads next to or on the element. Null when there is nothing safe to say. */
export function labelOf(element: Element): string | null {
  if (inDataCell(element)) return "Dòng trong bảng";
  const doc = element.ownerDocument;
  const aria = element.getAttribute("aria-label");
  if (aria?.trim()) return maskText(aria);
  const labelledBy = element.getAttribute("aria-labelledby");
  if (labelledBy) {
    const text = labelledBy.split(/\s+/).map((id) => textOf(doc.getElementById(id))).filter(Boolean).join(" ");
    if (text) return text;
  }
  const labels = (element as HTMLInputElement).labels;
  const first = labels?.[0] ?? element.closest("label");
  const fromLabel = textOf(first);
  if (fromLabel) return fromLabel;
  const tag = element.tagName.toLowerCase();
  if (tag === "input") {
    const input = element as HTMLInputElement;
    if (["button", "submit", "reset"].includes(input.type) && input.value) return maskText(input.value);
    const placeholder = input.placeholder?.trim();
    if (placeholder) return maskText(placeholder);
  }
  if (["button", "a", "summary"].includes(tag) || element.getAttribute("role") === "button") {
    const text = textOf(element);
    if (text) return text;
    const title = element.getAttribute("title");
    if (title) return maskText(title);
    const alt = element.querySelector("img[alt]")?.getAttribute("alt");
    if (alt) return maskText(alt);
  }
  const title = element.getAttribute("title");
  if (title?.trim()) return maskText(title);
  const name = element.getAttribute("name");
  return name ? maskText(name) : null;
}

function cssEscape(value: string): string {
  const css = (globalThis as { CSS?: { escape?: (text: string) => string } }).CSS;
  return css?.escape ? css.escape(value) : value.replace(/[^\w-]/g, "\\$&");
}

/** Position from the nearest form, main area or the body: survives changes of ids and wording. */
export function positionalPath(element: Element): string {
  const parts: string[] = [];
  let node: Element | null = element;
  while (node && node.tagName.toLowerCase() !== "body" && parts.length < 6) {
    const tag = node.tagName.toLowerCase();
    const parent: Element | null = node.parentElement;
    const same = parent ? Array.from(parent.children).filter((child) => child.tagName === node!.tagName) : [];
    parts.unshift(same.length > 1 ? `${tag}:nth-of-type(${same.indexOf(node) + 1})` : tag);
    if (tag === "form" || tag === "main") break;
    node = parent;
  }
  return parts.join(" > ");
}

/** Most reliable first. A selector is only given if it finds exactly this element in its own document. */
export function selectorsFor(element: Element): string[] {
  const found: string[] = [];
  const doc = element.ownerDocument;
  const tag = element.tagName.toLowerCase();
  const cell = inDataCell(element);
  const id = element.getAttribute("id") ?? "";
  if (id && !isRandomId(id)) found.push(`#${cssEscape(id)}`);
  const name = element.getAttribute("name");
  if (name && !isRandomId(name) && !cell) found.push(`${tag}[name=${JSON.stringify(name)}]`);
  const label = cell ? null : labelOf(element);
  if (label) {
    if (["input", "select", "textarea"].includes(tag)) found.push(`label=${label}`);
    const role = roleOf(element);
    if (role) found.push(`role=${role}[name='${label.replace(/'/g, "\\'")}']`);
  }
  found.push(`css=${positionalPath(element)}`);
  const unique = [...new Set(found)];
  return unique
    .filter((selector) => {
      if (!selector.startsWith("#") && !/^[a-z]+\[name=/.test(selector)) return true;
      try {
        return doc.querySelectorAll(selector).length === 1;
      } catch {
        return false;
      }
    })
    .slice(0, 5);
}
