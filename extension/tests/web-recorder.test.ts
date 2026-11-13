// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { DomRecorder, type DraftEvent } from "../src/content/dom-recorder";
import { isRandomId, labelOf, selectorsFor } from "../src/shared/dom-selectors";
import { classifyField } from "../src/shared/field-class";
import { maskPath, maskText } from "../src/shared/mask";
import { actionCount, appendDraft, appendNavigate, idleRecording, type RecordingState } from "../src/shared/recording";
import { validateEvent } from "../src/shared/validate";

function page(html: string): Document {
  document.body.innerHTML = html;
  return document;
}

function record(html: string, act: (doc: Document) => void): DraftEvent[] {
  const doc = page(html);
  const events: DraftEvent[] = [];
  const recorder = new DomRecorder(doc, (event) => events.push(event));
  recorder.start();
  act(doc);
  recorder.stop();
  return events;
}

function typeInto(input: HTMLInputElement | HTMLSelectElement, value: string): void {
  input.value = value;
  input.dispatchEvent(new Event("change", { bubbles: true }));
}

describe("field classes (same table as the Windows agent)", () => {
  it("ignores passwords whatever the label says", () => {
    expect(classifyField("Tên", "password").kind).toBe("ignore");
    expect(classifyField("Mã OTP").kind).toBe("ignore");
  });
  it("keeps only the class of sensitive fields, and treats the unknown as sensitive", () => {
    expect(classifyField("Số tài khoản")).toEqual({ kind: "sensitive", value_class: "account_number" });
    expect(classifyField("Số CIF hoặc CCCD").kind).toBe("sensitive");
    expect(classifyField("Ô lạ chưa biết").kind).toBe("sensitive");
  });
  it("keeps the value of plain fields", () => {
    expect(classifyField("Ngày báo cáo").kind).toBe("plain");
  });
});

describe("masking", () => {
  it("hides long digit runs and e-mail addresses in text", () => {
    expect(maskText("Khách 0123456789 a@b.vn")).toBe("Khách *** ***");
    expect(maskText("Tra cứu")).toBe("Tra cứu");
  });
  it("keeps only the path of an address and hides ids in it", () => {
    expect(maskPath("http://x/baocao/cuoingay?acct=0123456789#top")).toBe("/baocao/cuoingay");
    expect(maskPath("http://x/khach/12345678/chitiet")).toBe("/khach/{id}/chitiet");
  });
});

describe("selectors", () => {
  it("recognizes generated ids", () => {
    for (const id of ["ext-gen1234", ":r1:", "input-3", "a1b2c3d4e5f6", "id_20231105"]) expect(isRandomId(id)).toBe(true);
    for (const id of ["btn-search", "tf-from", "cif"]) expect(isRandomId(id)).toBe(false);
  });
  it("gives stable selectors first and none for a random id", () => {
    const doc = page(`<form><label for="tf-from">Tài khoản chuyển</label><input id="tf-from" name="from"><input id="ext-gen1234" aria-label="Số tiền"></form>`);
    const stable = selectorsFor(doc.getElementById("tf-from")!);
    expect(stable[0]).toBe("#tf-from");
    expect(stable).toContain("label=Tài khoản chuyển");
    expect(stable.some((selector) => selector.startsWith("css="))).toBe(true);
    const generated = selectorsFor(doc.getElementById("ext-gen1234")!);
    expect(generated.some((selector) => selector.includes("ext-gen"))).toBe(false);
    expect(generated).toContain("role=textbox[name='Số tiền']");
  });
  it("describes a cell of a data table by position only", () => {
    const doc = page(`<table><tr><td><a href="/k/1">Nguyễn Văn A 0123456789</a></td></tr></table>`);
    const link = doc.querySelector("a")!;
    expect(labelOf(link)).toBe("Dòng trong bảng");
    expect(selectorsFor(link).every((selector) => selector.startsWith("css="))).toBe(true);
  });
});

describe("the recorder", () => {
  const FORM = `<form id="f"><label for="acct">Số tài khoản</label><input id="acct">
    <label for="d">Ngày báo cáo</label><input id="d" type="date">
    <label for="t">Loại</label><select id="t"><option>Tất cả</option><option>Chuyển tiền</option></select>
    <input id="pw" type="password" aria-label="Mật khẩu"><button id="go" type="button">Tra cứu</button></form>`;

  it("never puts the account number into an event, only its class", () => {
    const events = record(FORM, (doc) => typeInto(doc.getElementById("acct") as HTMLInputElement, "0123456789"));
    expect(events).toHaveLength(1);
    expect(events[0]).toMatchObject({ type: "input", value: null, value_class: "account_number" });
    expect(JSON.stringify(events)).not.toContain("0123456789");
  });

  it("keeps the value of a date and a list choice", () => {
    const events = record(FORM, (doc) => {
      typeInto(doc.getElementById("d") as HTMLInputElement, "2026-11-12");
      const select = doc.getElementById("t") as HTMLSelectElement;
      select.selectedIndex = 1;
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(events.map((event) => [event.type, event.value])).toEqual([["input", "2026-11-12"], ["select", "Chuyển tiền"]]);
  });

  it("records nothing at all for a password field", () => {
    const events = record(FORM, (doc) => {
      typeInto(doc.getElementById("pw") as HTMLInputElement, "s3cret-pass");
      doc.getElementById("pw")!.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    });
    expect(events).toEqual([]);
  });

  it("records a click on a button with the label the teller sees", () => {
    const events = record(FORM, (doc) => (doc.getElementById("go") as HTMLButtonElement).click());
    expect(events).toHaveLength(1);
    expect(events[0]).toMatchObject({ type: "click", target: { label: "Tra cứu", tag: "button" } });
  });

  it("does not record a submit that a click already explained, but does record Enter in a field outside a form", () => {
    const withForm = record(`<form id="f"><button id="s">Gửi</button></form>`, (doc) => {
      doc.getElementById("f")!.addEventListener("submit", (event) => event.preventDefault());
      (doc.getElementById("s") as HTMLButtonElement).click();
    });
    expect(withForm.map((event) => event.type)).toEqual(["click"]);
    const enter = record(`<label for="q">Số CIF</label><input id="q">`, (doc) =>
      doc.getElementById("q")!.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })));
    expect(enter.map((event) => event.type)).toEqual(["submit"]);
  });

  it("stops listening when told to", () => {
    const doc = page(FORM);
    const events: DraftEvent[] = [];
    const recorder = new DomRecorder(doc, (event) => events.push(event));
    recorder.start();
    recorder.stop();
    (doc.getElementById("go") as HTMLButtonElement).click();
    expect(events).toEqual([]);
  });

  it("builds events that satisfy the contract in schemas/", () => {
    let state: RecordingState = { ...idleRecording(), recording: true, sessionId: "s-test" };
    state = appendNavigate(state, "http://x/cif?q=0123456789");
    state = appendNavigate(state, "http://x/cif"); // same screen again: one move
    for (const draft of record(FORM, (doc) => {
      typeInto(doc.getElementById("acct") as HTMLInputElement, "0123456789");
      (doc.getElementById("go") as HTMLButtonElement).click();
    })) state = appendDraft(state, draft);
    expect(state.events.map((event) => event.type)).toEqual(["navigate", "input", "click"]);
    expect(state.events.map((event) => event.seq)).toEqual([0, 1, 2]);
    expect(actionCount(state.events)).toBe(2);
    for (const event of state.events) expect(validateEvent(event)).toEqual([]);
    expect(JSON.stringify(state.events)).not.toContain("0123456789");
  });
});
