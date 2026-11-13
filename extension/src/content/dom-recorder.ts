/**
 * Watches what the GDV does on one page (or frame) and reports it as draft events. The service worker adds
 * the session, the sequence number and the time of day.
 *
 * What is kept (docs/design.md 4.2): a password field produces nothing; a sensitive field reports only the
 * class of the field; only plain fields (a date, a list choice) keep their value. The value of a sensitive
 * field is never read into a message.
 */
import { classifyField } from "../shared/field-class";
import { labelOf, selectorsFor } from "../shared/dom-selectors";
import { maskPath } from "../shared/mask";
import type { DraftEvent } from "../shared/recording";

export type { DraftEvent };

const CLICKABLE = "button, a[href], summary, input[type=button], input[type=submit], input[type=reset], input[type=checkbox], input[type=radio], [role=button], [role=link], [role=tab], [role=menuitem], [role=checkbox], [role=radio]";
// One real click is reported by the browser as a click on the control and, for a label, again on its input.
const SUBMIT_AFTER_CLICK_MS = 800;

export class DomRecorder {
  private active = false;
  private lastSubmitClick = 0;
  private readonly listeners: Array<[string, (event: Event) => void]> = [];

  constructor(
    private readonly doc: Document,
    private readonly emit: (event: DraftEvent) => void,
    private readonly now: () => number = () => Date.now(),
  ) {}

  start(): void {
    if (this.active) return;
    this.active = true;
    this.listen("click", (event) => this.onClick(event as MouseEvent));
    this.listen("change", (event) => this.onChange(event));
    this.listen("submit", (event) => this.onSubmit(event as SubmitEvent));
    this.listen("keydown", (event) => this.onKey(event as KeyboardEvent));
  }

  stop(): void {
    for (const [name, listener] of this.listeners) this.doc.removeEventListener(name, listener, true);
    this.listeners.length = 0;
    this.active = false;
  }

  private listen(name: string, listener: (event: Event) => void): void {
    this.doc.addEventListener(name, listener, true);
    this.listeners.push([name, listener]);
  }

  private url(): string {
    return maskPath(this.doc.location?.href ?? "");
  }

  /** The element the event is really about, also through shadow roots. */
  private source(event: Event): Element | null {
    const first = event.composedPath()[0];
    return first instanceof Element ? first : null;
  }

  private target(element: Element) {
    return { selectors: selectorsFor(element), label: labelOf(element), tag: element.tagName.toLowerCase() };
  }

  private onClick(event: MouseEvent): void {
    const origin = this.source(event);
    const element = origin?.closest(CLICKABLE) ?? null;
    if (!element) return;
    if (element.tagName === "LABEL") return;
    const input = element as HTMLInputElement;
    if (input.type === "password") return;
    const submits = element.matches("button:not([type=button]):not([type=reset]), input[type=submit]");
    if (submits) this.lastSubmitClick = this.now();
    this.emit({ type: "click", url: this.url(), target: this.target(element), value: null, value_class: null });
  }

  private onChange(event: Event): void {
    const element = this.source(event);
    if (!element) return;
    const tag = element.tagName.toLowerCase();
    if (!["input", "select", "textarea"].includes(tag)) return;
    const control = element as HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement;
    const type = "type" in control ? String(control.type).toLowerCase() : "";
    // Checkboxes, radios and buttons are recorded as clicks.
    if (["checkbox", "radio", "button", "submit", "reset", "file", "hidden"].includes(type)) return;
    const label = labelOf(element) ?? "";
    const field = classifyField(label, type);
    if (field.kind === "ignore") return;
    const isSelect = tag === "select";
    let value: string | null = null;
    if (field.kind === "plain") {
      value = isSelect ? ((control as HTMLSelectElement).selectedOptions[0]?.text.trim() ?? "") : control.value;
    }
    this.emit({
      type: isSelect ? "select" : "input",
      url: this.url(),
      target: this.target(element),
      value,
      value_class: field.kind === "sensitive" ? field.value_class : null,
    });
  }

  private onSubmit(event: SubmitEvent): void {
    if (this.now() - this.lastSubmitClick < SUBMIT_AFTER_CLICK_MS) return; // the click already told the story
    const form = event.target instanceof Element ? event.target : null;
    if (!form) return;
    this.emit({ type: "submit", url: this.url(), target: { ...this.target(form), tag: "form" }, value: null, value_class: null });
  }

  /** Enter in a field that is not in a form (many web apps handle it themselves). */
  private onKey(event: KeyboardEvent): void {
    if (event.key !== "Enter" || event.isComposing) return;
    const element = this.source(event);
    if (!element || element.tagName !== "INPUT") return;
    const input = element as HTMLInputElement;
    if (input.type === "password" || input.form) return;
    if (classifyField(labelOf(element) ?? "", input.type).kind === "ignore") return;
    this.emit({ type: "submit", url: this.url(), target: this.target(element), value: null, value_class: null });
  }
}
