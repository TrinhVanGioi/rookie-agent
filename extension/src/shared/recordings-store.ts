/** Recordings kept in the browser on this PC until the GDV sends them to learn from, or deletes them. */
import type { WebEvent } from "./recording";

export interface SavedRecording {
  session_id: string;
  name: string;
  saved_at: string;
  host: string;
  uploaded: boolean;
  events: WebEvent[];
}

export interface StorageLike {
  get(keys: string): Promise<Record<string, unknown>>;
  set(items: Record<string, unknown>): Promise<void>;
}

const KEY = "rookie.recordings";

export async function listRecordings(storage: StorageLike): Promise<SavedRecording[]> {
  const found = (await storage.get(KEY))[KEY];
  return Array.isArray(found) ? (found as SavedRecording[]) : [];
}

export async function saveRecording(storage: StorageLike, recording: SavedRecording): Promise<void> {
  const all = await listRecordings(storage);
  await storage.set({ [KEY]: [recording, ...all.filter((item) => item.session_id !== recording.session_id)] });
}

export async function markUploaded(storage: StorageLike, ids: string[]): Promise<void> {
  const all = await listRecordings(storage);
  await storage.set({ [KEY]: all.map((item) => (ids.includes(item.session_id) ? { ...item, uploaded: true } : item)) });
}

export async function deleteRecording(storage: StorageLike, id: string): Promise<void> {
  const all = await listRecordings(storage);
  await storage.set({ [KEY]: all.filter((item) => item.session_id !== id) });
}
