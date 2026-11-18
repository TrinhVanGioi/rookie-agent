"""Task 6.7: the reader of a scanned document, behind one interface (docs/design.md 6.2).

`DocReader.read(data)` gives the text of the document as `Nhãn: giá trị` lines. The PoC has only `SampleReader`, which runs
offline and knows the synthetic samples in `samples/` (the picture, and next to it the text a reader would give). A real OCR
(on this PC or on the internal server) is another `DocReader`; the picture is never kept after it has been read.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Protocol

SAMPLES = Path(__file__).resolve().parent / "samples"


class UnreadableDocument(Exception):
    """The reader cannot read this picture. The message is for the teller."""


class DocReader(Protocol):
    def read(self, data: bytes) -> str: ...


class SampleReader:
    """Offline: a picture that is one of the samples gives that sample's text; any other picture is refused."""

    def __init__(self, folder: Path = SAMPLES) -> None:
        self._known: dict[str, Path] = {}
        for picture in sorted(folder.glob("*.png")):
            text = picture.with_suffix(".txt")
            if text.exists():
                self._known[hashlib.sha256(picture.read_bytes()).hexdigest()] = text

    def read(self, data: bytes) -> str:
        text = self._known.get(hashlib.sha256(data).hexdigest())
        if text is None:
            raise UnreadableDocument("Bản thử chỉ đọc được các mẫu uỷ nhiệm chi giả lập có sẵn (thư mục voucher/samples). Chưa có bộ đọc chữ thật.")
        return text.read_text(encoding="utf-8")
