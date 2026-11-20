"""A file as the answer of a call (a report exported as PDF, a statement as Excel). Generic: nothing here knows a site.

The file is the customer's data. It is written only on the teller's PC, in a folder of their own (`%USERPROFILE%\\Downloads\\Rookie`), and is
never sent to the server, never put in a recording, a shape, an event, the model or a log. A recording keeps only that the answer was a
file: its content type, its size and a pattern of its name (digits and words masked). docs/design.md 6.4.
"""

from __future__ import annotations

import html as html_lib
import os
import re
import urllib.parse
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

MAX_BYTES = 50 * 1024 * 1024
MAX_MB = 50

# a type is a file when it is not something a page shows or a program reads (html, text, json, xml, scripts)
_FILE_TYPE = re.compile(r"^(application/(pdf|x-pdf|octet-stream|zip|x-zip-compressed|msword|rtf|excel|x-excel|x-msexcel|force-download|download|x-download|vnd\..+)"
                        r"|binary/octet-stream|text/csv|image/.+)$")
_STRUCTURED = re.compile(r"\+(json|xml)$")
_TYPE_EXT = {
    "application/pdf": "pdf", "application/x-pdf": "pdf", "application/vnd.ms-excel": "xls", "application/excel": "xls", "application/x-excel": "xls",
    "application/x-msexcel": "xls", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx", "application/msword": "doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx", "text/csv": "csv", "application/zip": "zip",
    "application/x-zip-compressed": "zip", "application/rtf": "rtf", "image/png": "png", "image/jpeg": "jpg", "image/gif": "gif",
    "image/tiff": "tif", "text/plain": "txt",
}
# what may be the extension of a saved file: nothing that runs (exe, bat, js, hta, html...); anything else is `bin`
OPENABLE = frozenset({"pdf", "xls", "xlsx", "csv", "doc", "docx", "zip", "txt", "rtf", "png", "jpg", "jpeg", "gif", "tif", "tiff"})
SAFE_EXT = OPENABLE | {"bin"}
_RESERVED = re.compile(r"^(con|prn|aux|nul|com\d|lpt\d)$", re.IGNORECASE)


def split_type(ctype: str) -> str:
    return str(ctype or "").split(";", 1)[0].strip().lower()


def is_file_answer(ctype: str, disposition: str = "") -> bool:
    """Whether an answer with these headers is a file to save: an attachment, or a type that is a document or a picture."""
    if re.search(r"attachment", str(disposition or ""), re.IGNORECASE):
        return True
    kind = split_type(ctype)
    return bool(_FILE_TYPE.match(kind)) and not _STRUCTURED.search(kind)


def disposition_name(disposition: str) -> str:
    """The file name the server proposed (`filename*=UTF-8''...` or `filename="..."`); "" when there is none."""
    text = str(disposition or "")
    found = re.search(r"filename\*\s*=\s*[\w\-]*'[^']*'([^;]+)", text, re.IGNORECASE)
    if found:
        try:
            return urllib.parse.unquote(found.group(1).strip().strip('"'))
        except ValueError:
            return ""
    found = re.search(r'filename\s*=\s*"?([^";]+)', text, re.IGNORECASE)
    return found.group(1).strip() if found else ""


_MAGIC = ((b"%PDF-", "pdf"), (b"\x89PNG\r\n\x1a\n", "png"), (b"\xff\xd8\xff", "jpg"), (b"GIF87a", "gif"), (b"GIF89a", "gif"),
          (b"II*\x00", "tif"), (b"MM\x00*", "tif"), (b"{\\rtf", "rtf"), (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "ole"))
OFFICE_ZIP = {"xl/": "xlsx", "word/": "docx"}
DOCUMENT_KINDS = frozenset({"pdf", "png", "jpg", "gif", "tif", "zip", "xlsx", "docx", "rtf", "ole"})
KIND_WORDS = {"pdf": "PDF", "png": "ảnh", "jpg": "ảnh", "gif": "ảnh", "tif": "ảnh", "zip": "file nén", "xlsx": "Excel", "docx": "Word", "rtf": "văn bản Word",
              "ole": "file Office cũ", "html": "trang web", "xml": "văn bản XML", "json": "văn bản JSON", "text": "văn bản", "gwt": "lời đáp của hệ thống",
              "": "không nhận ra"}


def sniff(data: bytes | None) -> str:
    """What the bytes really are, from their first bytes (a server may call a PDF `application/octet-stream` and give no name):
    one of the keys of KIND_WORDS. Reads at most the first 64 KB; nothing of it is kept or shown."""
    head = bytes(data or b"")[:65536]
    if not head:
        return ""
    for magic, kind in _MAGIC:
        if head.startswith(magic):
            return kind
    if head.startswith(b"PK\x03\x04"):
        try:
            import io
            import zipfile

            with zipfile.ZipFile(io.BytesIO(bytes(data)), "r") as archive:
                names = archive.namelist()
            for prefix, kind in OFFICE_ZIP.items():
                if any(n.startswith(prefix) for n in names):
                    return kind
        except Exception:  # noqa: BLE001  not a readable archive: a zip all the same
            pass
        return "zip"
    if b"\x00" in head[:4096] and not head.startswith((b"\xff\xfe", b"\xfe\xff")):
        return ""
    text = ""
    for encoding in ("utf-8-sig", "utf-16", "cp1258"):
        try:
            text = head.decode(encoding)
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
    if not text or sum(ch.isprintable() or ch in "\r\n\t" for ch in text[:2000]) < 0.95 * len(text[:2000]):
        return ""
    lead = text.lstrip().lower()
    if lead.startswith(("//ok[", "//ex[")):
        return "gwt"                                  # the answer of a GWT-RPC call (a key, a record): data of a call, never a document
    if lead.startswith(("<!doctype html", "<html", "<head", "<body", "<script", "<?php")):
        return "html"
    if lead.startswith("<?xml") or lead.startswith("<"):
        return "xml"
    if lead.startswith(("{", "[")):
        return "json"
    return "text"


def extension(ctype: str, disposition: str = "", data: bytes | None = None) -> str:
    """From the bytes when they say what they are (a PDF is a `.pdf` whatever the server called it), else from the proposed name when its
    extension is a safe one, else from the content type, else `bin`. Text a server called a file is `.txt` (never `.pdf`: it would not open)."""
    kind = sniff(data)
    if kind in DOCUMENT_KINDS and kind != "ole":
        return kind
    name = disposition_name(disposition)
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if kind == "xml":
        return "xml"                                  # data the server sent as XML (a statement as IFX): kept as it came, read through its report
    if kind in ("json", "text", "html", "gwt"):
        return ext if ext in ("txt", "csv") else ("csv" if split_type(ctype) == "text/csv" else "txt")
    if ext in SAFE_EXT:
        return ext
    return _TYPE_EXT.get(split_type(ctype), "bin")


def clean_title(title: str) -> str:
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', " ", str(title or ""))
    text = re.sub(r"\s+", " ", text).strip(" .")[:80] or "file"
    return "_" + text if _RESERVED.match(text) else text


def file_name(flow_title: str, ctype: str, disposition: str = "", now: datetime | None = None, data: bytes | None = None) -> str:
    """`<flow name>-<yyyyMMdd-HHmmss>.<ext>`; `data` (the bytes) lets the extension follow what the file really is."""
    moment = now or datetime.now()
    return f"{clean_title(flow_title)}-{moment.strftime('%Y%m%d-%H%M%S')}.{extension(ctype, disposition, data)}"


_BASE64_RUN = re.compile(rb"[A-Za-z0-9+/\r\n]{256,}={0,2}")


def embedded_document(data: bytes | str | None) -> bytes | None:
    """A SOAP service often sends a report inside its XML, as base64 in one element (`<ReportData>JVBERi0…</ReportData>`). The bytes of the
    first such run that really is a document (a PDF, Excel, Word, zip, picture: told by the first bytes after decoding), else None.
    Nothing but a known document is taken, so ordinary text, a token or a long id is never mistaken for one."""
    raw = data.encode("utf-8") if isinstance(data, str) else bytes(data or b"")
    if len(raw) < 300 or not raw.lstrip().startswith(b"<"):
        return None
    import base64

    for found in _BASE64_RUN.finditer(raw):
        blob = re.sub(rb"[\r\n]", b"", found.group(0))
        head = blob[:512 - (512 % 4)]
        try:
            kind = sniff(base64.b64decode(head, validate=True))
        except ValueError:
            continue
        if kind in DOCUMENT_KINDS:
            try:
                return base64.b64decode(blob + b"=" * (-len(blob) % 4), validate=True)
            except ValueError:
                continue
    return None


def shape_of(data: bytes | None, limit: int = 160) -> str:
    """The look of the first bytes of a file with every letter and digit masked (A a 0), for a teller to tell the team what a file that is not
    a document looks like without showing a name or a number: `size, lines, the start`. Punctuation, tags and line breaks stay (they are
    the structure: `<?xml`, `//OK[`, a BOM, base64's `=`)."""
    raw = bytes(data or b"")
    head = raw[:limit]
    prefix = "BOM " if head.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")) else ""
    text = head.decode("utf-8", "replace").lstrip("﻿￾").replace("\r\n", "\n")
    out = []
    for ch in text:
        if ch.isdigit():
            out.append("0")
        elif ch.isalpha():
            out.append("A" if ch.isupper() else "a")
        elif ch in "\r\n":
            out.append("⏎")
        elif ch == "�" or ord(ch) < 32:
            out.append("·")
        else:
            out.append(ch)
    lines = raw.count(b"\n") + (1 if raw and not raw.endswith(b"\n") else 0)
    return f"{len(raw)} byte, {lines} dòng, đầu: {prefix}{''.join(out)}"


def warning_for(kind: str) -> str:
    """A plain sentence when what was saved is not a document the teller can print as a report; "" when it is (or when it is XML, which
    has a readable report of its own)."""
    if kind in DOCUMENT_KINDS or kind in ("html", "xml", "gwt"):
        return ""
    if kind in ("json", "text"):
        return f"File này chỉ là {KIND_WORDS[kind]}, không phải PDF hay Excel nên không in được như báo cáo."
    return "Chưa nhận ra loại file này. Nếu mở không được, báo nhóm phát triển (đừng gửi nội dung file)."


# ---- XML sent as the answer (a statement as IFX): kept as it came, and read through a report made here ---------------------------------
# The report is a page of ours: every text escaped, no script, no link, no style from outside. It carries REPORT_MARK on its first line, which
# is the only reason the page may open or print it (a page from a server never is). Both files stay on this PC like any file of the teller's.

REPORT_MARK = "<!--rookie-report-->"
XML_MAX = 2 * 1024 * 1024
XML_ROWS = 2000


def xml_rows(data: bytes) -> list[tuple[int, str, str, bool]] | None:
    """The XML as `(depth, name, value, leaf)` rows, in order. A name repeated among siblings gets its number (`Row (2)`). None when it is not
    XML that is safe to read here: too large, a DOCTYPE or an entity (expansion tricks), or broken."""
    raw = bytes(data or b"")
    if not raw or len(raw) > XML_MAX or re.search(rb"<!\s*(DOCTYPE|ENTITY)", raw, re.IGNORECASE):
        return None
    try:
        root = ET.fromstring(raw)
    except (ET.ParseError, ValueError, UnicodeError):
        return None
    rows: list[tuple[int, str, str, bool]] = []

    def local(tag: Any) -> str:
        return str(tag).rsplit("}", 1)[-1]

    def walk(element: ET.Element, depth: int, label: str) -> None:
        if len(rows) >= XML_ROWS:
            return
        children = list(element)
        text = (element.text or "").strip()
        rows.append((depth, label, text, not children))
        count, seen = Counter(local(c.tag) for c in children), Counter()
        for child in children:
            name = local(child.tag)
            seen[name] += 1
            walk(child, depth + 1, f"{name} ({seen[name]})" if count[name] > 1 else name)

    walk(root, 0, local(root.tag))
    return rows


def xml_pairs(rows: list[tuple[int, str, str, bool]], limit: int = 80) -> list[list[str]]:
    """The values of the XML (`[name, value]`, the ones that hold something), for the result of a run."""
    return [[name, value[:200]] for _, name, value, leaf in rows if leaf and value][:limit]


def xml_report_html(title: str, rows: list[tuple[int, str, str, bool]], when: datetime | None = None) -> str:
    """A readable and printable page of the XML: sections for the elements that hold others, one row for each value."""
    esc = html_lib.escape
    moment = (when or datetime.now()).strftime("%d/%m/%Y %H:%M")
    body = []
    for depth, name, value, leaf in rows:
        pad = f"padding-left:{8 + depth * 18}px"
        if leaf:
            body.append(f'<tr><td style="{pad}">{esc(name)}</td><td>{esc(value)}</td></tr>')
        else:
            body.append(f'<tr class="h"><th colspan="2" style="{pad}">{esc(name)}</th></tr>')
    return (f"{REPORT_MARK}\n<!DOCTYPE html>\n<html lang=\"vi\"><head><meta charset=\"utf-8\"><title>{esc(title)}</title>\n"
            "<style>body{font:14px Arial,sans-serif;margin:24px;color:#111}h1{font-size:20px;margin:0 0 4px}p{margin:0 0 14px;color:#555}"
            "table{border-collapse:collapse;width:100%}td,th{border:1px solid #bbb;padding:4px 8px;text-align:left;vertical-align:top}"
            "tr.h th{background:#e8edf4}td:first-child{width:34%;color:#333}@media print{body{margin:8mm}}</style></head><body>\n"
            f"<h1>{esc(title)}</h1><p>Bản đọc từ dữ liệu XML, lập lúc {esc(moment)}. File gốc nằm cạnh file này.</p>\n"
            f"<table>\n{chr(10).join(body)}\n</table></body></html>\n")


def pairs_report_html(title: str, pairs: list[tuple[str, str]], when: datetime | None = None) -> str:
    """A printable page of `label: value` rows, made from the data a call returned (a screen the page fills in, not a file). A page of ours
    like the XML report: every text escaped, no script, no link, REPORT_MARK on its first line."""
    esc = html_lib.escape
    moment = (when or datetime.now()).strftime("%d/%m/%Y %H:%M")
    rows = "\n".join(f"<tr><td>{esc(label)}</td><td>{esc(value)}</td></tr>" for label, value in pairs)
    return (f"{REPORT_MARK}\n<!DOCTYPE html>\n<html lang=\"vi\"><head><meta charset=\"utf-8\"><title>{esc(title)}</title>\n"
            "<style>body{font:14px Arial,sans-serif;margin:24px;color:#111}h1{font-size:20px;margin:0 0 4px}p{margin:0 0 14px;color:#555}"
            "table{border-collapse:collapse;width:100%}td{border:1px solid #bbb;padding:5px 9px;vertical-align:top}td:first-child{width:34%;"
            "background:#f1f4f8;color:#333}@media print{body{margin:8mm}}</style></head><body>\n"
            f"<h1>{esc(title)}</h1><p>Dựng từ dữ liệu hệ thống trả về lúc {esc(moment)}. Đây là bản trình bày của Rookie Agent, "
            "không phải chứng từ chính thức của hệ thống.</p>\n"
            f"<table>\n{rows}\n</table></body></html>\n")


def is_report(path: Path) -> bool:
    """A page this agent made (its first line is REPORT_MARK): the only `.html` the page may open or print."""
    try:
        if path.suffix.lower() != ".html":
            return False
        with open(path, "rb") as handle:
            return handle.read(len(REPORT_MARK)) == REPORT_MARK.encode("ascii")
    except OSError:
        return False


def downloads_dir(override: str | None = None) -> Path:
    """`%USERPROFILE%\\Downloads\\Rookie`, or the folder the teller set (an absolute path)."""
    if override and Path(str(override)).is_absolute():
        return Path(str(override))
    return Path(os.environ.get("USERPROFILE") or Path.home()) / "Downloads" / "Rookie"


def inside(folder: Path, path: Path) -> bool:
    """Whether `path` is in `folder` (after resolving `..` and links; the case of a Windows path does not matter)."""
    try:
        base = os.path.normcase(str(folder.resolve()))
        target = os.path.normcase(str(path.resolve()))
        return os.path.commonpath([base, target]) == base and target != base
    except (OSError, ValueError):
        return False


def save(folder: Path, name: str, data: bytes) -> Path:
    """Write the bytes as they came. A name already taken gets ` (2)`, ` (3)`: a file of the teller is never overwritten."""
    folder.mkdir(parents=True, exist_ok=True)
    stem, dot, ext = name.rpartition(".")
    for count in range(1, 1000):
        path = folder / (name if count == 1 else f"{stem} ({count}){dot}{ext}")
        try:
            with open(path, "xb") as handle:
                handle.write(data)
            return path
        except FileExistsError:
            continue
    raise OSError("Không đặt được tên cho file.")


def placeholder() -> bytes:
    """A tiny PDF the twin answers with. Synthetic: it holds no data of anyone."""
    return (b"%PDF-1.1\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
            b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 50]>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n")


def size_text(size: int) -> str:
    return f"{max(1, round(size / 1024))} KB" if size < 1024 * 1024 else f"{size / (1024 * 1024):.1f} MB"
