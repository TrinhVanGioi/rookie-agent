"""A file as the answer of a call (a report exported as PDF, a statement as Excel). Generic: nothing here knows a site.

The file is the customer's data. It is written only on the teller's PC, in a folder of their own (`%USERPROFILE%\\Downloads\\Rookie`), and is
never sent to the server, never put in a recording, a shape, an event, the model or a log. A recording keeps only that the answer was a
file: its content type, its size and a pattern of its name (digits and words masked). docs/design.md 6.4.
"""

from __future__ import annotations

import os
import re
import urllib.parse
from datetime import datetime
from pathlib import Path

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


def extension(ctype: str, disposition: str = "") -> str:
    """From the proposed name when its extension is a safe one, else from the content type, else `bin`."""
    name = disposition_name(disposition)
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext in SAFE_EXT:
        return ext
    return _TYPE_EXT.get(split_type(ctype), "bin")


def clean_title(title: str) -> str:
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', " ", str(title or ""))
    text = re.sub(r"\s+", " ", text).strip(" .")[:80] or "file"
    return "_" + text if _RESERVED.match(text) else text


def file_name(flow_title: str, ctype: str, disposition: str = "", now: datetime | None = None) -> str:
    """`<flow name>-<yyyyMMdd-HHmmss>.<ext>`."""
    moment = now or datetime.now()
    return f"{clean_title(flow_title)}-{moment.strftime('%Y%m%d-%H%M%S')}.{extension(ctype, disposition)}"


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
