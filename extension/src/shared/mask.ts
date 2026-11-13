/** Removing what must not leave the GDV's PC from the text and addresses the recorder keeps. */

const MAX_LABEL = 80;

/** Long digit runs (account, card, phone, ID numbers) and e-mail addresses are replaced; the rest is cut to length. */
export function maskText(text: string, max = MAX_LABEL): string {
  const masked = text
    .replace(/[\w.+-]+@[\w-]+(\.[\w-]+)+/g, "***")
    .replace(/\d[\d .-]{4,}\d/g, "***")
    .replace(/\s+/g, " ")
    .trim();
  return masked.length > max ? masked.slice(0, max - 1) + "…" : masked;
}

/** The address without the query string or fragment; path parts that look like ids become `{id}`. */
export function maskPath(url: string, base = "http://x"): string {
  let pathname: string;
  try {
    pathname = new URL(url, base).pathname;
  } catch {
    return "";
  }
  return pathname
    .split("/")
    .map((part) => (/^\d{5,}$/.test(part) || /^[0-9a-f]{12,}$/i.test(part) || /^[0-9a-f-]{32,}$/i.test(part) ? "{id}" : part))
    .join("/");
}
