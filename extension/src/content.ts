/**
 * Runs in every frame of the tab being recorded. It does nothing until the service worker says this tab
 * is being recorded, and stops as soon as recording ends.
 */
import { DomRecorder } from "./content/dom-recorder";

interface Holder {
  __rookieRecorder?: DomRecorder;
}

const holder = window as unknown as Holder;
const recorder = holder.__rookieRecorder ?? new DomRecorder(document, (event) => {
  void chrome.runtime.sendMessage({ type: "rookie-event", event }).catch(() => undefined);
});
holder.__rookieRecorder = recorder;

chrome.runtime.onMessage.addListener((message) => {
  if (message?.type === "rookie-recording") {
    if (message.recording) recorder.start();
    else recorder.stop();
  }
});

void chrome.runtime
  .sendMessage({ type: "rookie-hello" })
  .then((reply) => {
    if (reply?.recording) recorder.start();
  })
  .catch(() => undefined);
