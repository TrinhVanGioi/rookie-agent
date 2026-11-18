"""Task 6.7: the fields of a payment order (giấy uỷ nhiệm chi) from the text a reader gave (docs/design.md 6.2).

Pure functions. The text is lines `Nhãn: giá trị`, a line may end with ` [0.62]`, the reader's confidence for it. Every field is
returned, found or not, with its confidence; the amount in figures must equal the amount in words, else both are marked. Nothing
here keeps or sends a value: the caller shows them to the teller, who checks each one.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

THRESHOLD = 0.85   # below: the teller must correct or confirm the field on purpose

FIELDS = [   # name, label shown, words of the printed labels it is read from
    ("so_tai_khoan_chuyen", "Số tài khoản chuyển", ("tai khoan trich no", "tai khoan nguoi chuyen", "so tk trich no")),
    ("ten_nguoi_chuyen", "Tên người chuyển", ("ten nguoi chuyen", "don vi tra tien", "nguoi tra tien")),
    ("so_tai_khoan_nhan", "Số tài khoản nhận", ("tai khoan ghi co", "tai khoan nguoi huong", "so tk ghi co")),
    ("ten_nguoi_nhan", "Tên người nhận", ("ten nguoi huong", "don vi nhan tien", "nguoi huong")),
    ("ngan_hang_nhan", "Ngân hàng nhận", ("ngan hang huong", "tai ngan hang", "ngan hang nhan")),
    ("so_tien", "Số tiền", ("so tien bang so",)),
    ("so_tien_bang_chu", "Số tiền bằng chữ", ("so tien bang chu", "bang chu")),
    ("noi_dung", "Nội dung", ("noi dung",)),
    ("ngay", "Ngày", ("ngay lap", "ngay")),
]

_CONF = re.compile(r"\s*\[(0(?:\.\d+)?|1(?:\.0+)?)\]\s*$")


def plain(text: str) -> str:
    """Lower case, without Vietnamese marks (đ -> d), single spaces."""
    text = unicodedata.normalize("NFD", text.replace("Đ", "D").replace("đ", "d"))
    text = "".join(c for c in text if unicodedata.category(c) != "Mn").lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


_DIGITS = {"khong": 0, "mot": 1, "hai": 2, "ba": 3, "bon": 4, "tu": 4, "nam": 5, "lam": 5, "nham": 5, "sau": 6,
           "bay": 7, "tam": 8, "chin": 9}
_SCALES = {"nghin": 1000, "ngan": 1000, "trieu": 1_000_000, "ty": 1_000_000_000, "ti": 1_000_000_000}


def words_to_number(text: str) -> int | None:
    """«Năm triệu hai trăm linh năm nghìn đồng chẵn» -> 5205000. None when a word is not a number word."""
    total = chunk = digit = 0
    seen = False
    for word in plain(text).split():
        if word in ("dong", "chan", "vnd", "le", "linh", "va"):
            continue
        seen = True
        if word == "muoi":                     # mười (ten) or hai mươi (the digit before is the tens): the same word without marks
            chunk += (digit or 1) * 10
            digit = 0
        elif word == "tram":
            chunk += digit * 100
            digit = 0
        elif word in _SCALES:
            total += (chunk + digit) * _SCALES[word]
            chunk = digit = 0
        elif word in _DIGITS:
            digit = _DIGITS[word]
        else:
            return None
    return total + chunk + digit if seen else None


def figures_to_number(text: str) -> int | None:
    digits = re.sub(r"\D", "", text.split(",")[0])
    return int(digits) if digits else None


def extract(text: str) -> dict[str, Any]:
    """`{"fields": [{name, label, value, confidence, problem}], "ready": bool}`; problem is "" or what the teller must look at."""
    found: dict[str, tuple[str, float]] = {}
    for raw in text.splitlines():
        if ":" not in raw:
            continue
        head, _, value = raw.partition(":")
        confidence = 0.99
        mark = _CONF.search(value)
        if mark:
            confidence, value = float(mark.group(1)), value[: mark.start()]
        key = plain(head)
        for name, _, words in FIELDS:
            if name not in found and any(w in key for w in words):
                found[name] = (value.strip(), confidence)
                break
    fields = []
    for name, label, _ in FIELDS:
        value, confidence = found.get(name, ("", 0.0))
        problem = "" if value and confidence >= THRESHOLD else ("không đọc được" if not value else "chữ mờ, cần soát kỹ")
        fields.append({"name": name, "label": label, "value": value, "confidence": round(confidence, 2), "problem": problem})
    by_name = {f["name"]: f for f in fields}
    figures, words = figures_to_number(by_name["so_tien"]["value"]), words_to_number(by_name["so_tien_bang_chu"]["value"])
    if figures is not None and words is not None and figures != words:
        for name in ("so_tien", "so_tien_bang_chu"):
            by_name[name]["problem"] = "số tiền bằng số và bằng chữ không khớp"
    return {"fields": fields, "ready": not any(f["problem"] for f in fields)}


def check_confirmed(fields: list[dict[str, Any]]) -> list[str]:
    """What still stops the teller's confirmation: an empty field, or the amounts in figures and in words that differ."""
    by_name = {str(f.get("name")): str(f.get("value") or "").strip() for f in fields}
    problems = [f"«{label}» còn trống" for name, label, _ in FIELDS if not by_name.get(name)]
    figures, words = figures_to_number(by_name.get("so_tien", "")), words_to_number(by_name.get("so_tien_bang_chu", ""))
    if figures is None or words is None or figures != words:
        problems.append("Số tiền bằng số và bằng chữ không khớp")
    return problems
