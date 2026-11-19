"""Fill the inputs of an agent from the teller's sentence, on this PC (docs/design.md, Trợ lý).

Nothing here goes to the server: the sentence and the values it holds stay in the memory of this PC. The server only ever sees the masked
sentence (`mask.prepare`). A value is filled only when exactly one input fits and exactly one value in the sentence fits it; anything
else is asked (rule 9: never guess).
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from rookie_agent.assistant import mask
from rookie_agent.assistant.catalog import fold

DEFAULT_FORMAT = "dd/mm/yyyy"
# tag -> (strftime pattern, regex of a recorded example)
FORMATS = {
    "dd/mm/yyyy": ("%d/%m/%Y", r"\d{2}/\d{2}/\d{4}"),
    "dd-mm-yyyy": ("%d-%m-%Y", r"\d{2}-\d{2}-\d{4}"),
    "dd.mm.yyyy": ("%d.%m.%Y", r"\d{2}\.\d{2}\.\d{4}"),
    "yyyy-mm-dd": ("%Y-%m-%d", r"\d{4}-\d{2}-\d{2}"),
    "yyyy/mm/dd": ("%Y/%m/%d", r"\d{4}/\d{2}/\d{2}"),
    "ddmmyyyy": ("%d%m%Y", r"\d{8}"),
    "d/m/yyyy": ("%-d/%-m/%Y", r"\d{1,2}/\d{1,2}/\d{4}"),
}

_FULL = re.compile(r"(?<![\d/.\-])(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})(?!\d)")
_ISO = re.compile(r"(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)")
_SHORT = re.compile(r"(?<![\d/.\-])(\d{1,2})/(\d{1,2})(?![\d/])")
_WORDS = re.compile(r"\b(hom nay|hom qua|thang nay|thang truoc)\b")
_PLACE = re.compile(r"§(\d+)§")
_ACCOUNT_WORD = re.compile(r"(?:\b(?:stk|tk|so tk|so tai khoan|tai khoan|account|acct)\b)\s*(?:so\s+|no\.?\s*|:\s*)?$")
_CIF_WORD = re.compile(r"\bcif\b\s*(?:so\s+|:\s*)?$")


def detect_format(value: str) -> str | None:
    """The format tag of a recorded date, or None when the value is not a date."""
    text = (value or "").strip()
    for tag, (_, pattern) in FORMATS.items():
        if tag == "d/m/yyyy":
            continue
        if re.fullmatch(pattern, text):
            return tag if _valid_example(tag, text) else None
    if re.fullmatch(FORMATS["d/m/yyyy"][1], text):
        return "d/m/yyyy" if _valid_example("d/m/yyyy", text) else None
    return None


def _valid_example(tag: str, text: str) -> bool:
    digits = re.findall(r"\d+", text) if tag != "ddmmyyyy" else [text[:2], text[2:4], text[4:]]
    a, b, c = (int(x) for x in digits)
    day, month, year = (c, b, a) if tag.startswith("yyyy") else (a, b, c)
    try:
        date(year, month, day)
    except ValueError:
        return False
    return True


def format_date(value: date, tag: str | None) -> str:
    pattern = FORMATS.get(tag or DEFAULT_FORMAT, FORMATS[DEFAULT_FORMAT])[0]
    if "%-d" in pattern:
        return pattern.replace("%-d", str(value.day)).replace("%-m", str(value.month)).replace("%Y", f"{value.year:04d}")
    return value.strftime(pattern)


def show(value: date) -> str:
    return value.strftime("%d/%m/%Y")


# ---- what a sentence holds ---------------------------------------------------------------------------------------------------------

def extract(text: str, today: date) -> dict[str, Any]:
    """{accounts: [{value, kind}], dates: [date], from_date, to_date, range, amounts: [digits], problems: [text]}.
    `kind` of an account: 'account' (a word like stk before it), 'cif' (the word cif before it) or '' (a bare number)."""
    folded = fold(text)[: mask.MAX_TEXT]
    problems: list[str] = []
    tokens: list[Any] = []                              # a date, a range (tuple of two) or None for an impossible date
    marked_parts: list[str] = []
    cursor = 0
    found: list[tuple[int, int, Any]] = []
    for pattern, order in ((_ISO, "ymd"), (_FULL, "dmy")):
        for m in pattern.finditer(folded):
            if any(a <= m.start() < b or a < m.end() <= b for a, b, _ in found):
                continue
            first, second, third = (int(x) for x in m.groups())
            day, month, year = (third, second, first) if order == "ymd" else (first, second, third)
            found.append((m.start(), m.end(), _make(year, month, day, folded[m.start():m.end()], problems)))
    for m in _SHORT.finditer(folded):
        if any(a <= m.start() < b or a < m.end() <= b for a, b, _ in found):
            continue
        day, month = int(m.group(1)), int(m.group(2))
        found.append((m.start(), m.end(), _make(today.year, month, day, folded[m.start():m.end()] + "/" + str(today.year), problems)))
    for m in _WORDS.finditer(folded):
        word = m.group(1)
        if word == "hom nay":
            value: Any = today
        elif word == "hom qua":
            value = today - timedelta(days=1)
        elif word == "thang nay":
            value = (today.replace(day=1), today)
        else:
            last_of_prev = today.replace(day=1) - timedelta(days=1)
            value = (last_of_prev.replace(day=1), last_of_prev)
        found.append((m.start(), m.end(), value))
    found.sort(key=lambda item: item[0])
    for start, end, value in found:
        marked_parts.append(folded[cursor:start])
        marked_parts.append(f"§{len(tokens)}§")
        tokens.append(value)
        cursor = end
    marked_parts.append(folded[cursor:])
    marked = "".join(marked_parts)

    used: set[int] = set()
    rng: tuple[date, date] | None = None
    from_date = to_date = None
    ranged = re.search(r"\btu\s+(?:ngay\s+)?§(\d+)§\s+(?:den|toi)\s+(?:ngay\s+)?§(\d+)§", marked)
    if ranged:
        a, b = tokens[int(ranged.group(1))], tokens[int(ranged.group(2))]
        used.update((int(ranged.group(1)), int(ranged.group(2))))
        if isinstance(a, date) and isinstance(b, date):
            if a > b:
                problems.append(f"Ngày bắt đầu {show(a)} sau ngày kết thúc {show(b)}.")
            else:
                rng = (a, b)
    else:
        for word, which in ((r"\btu\s+(?:ngay\s+)?§(\d+)§", "from"), (r"\b(?:den|toi)\s+(?:ngay\s+)?§(\d+)§", "to")):
            m = re.search(word, marked)
            if m and isinstance(tokens[int(m.group(1))], date):
                used.add(int(m.group(1)))
                if which == "from":
                    from_date = tokens[int(m.group(1))]
                else:
                    to_date = tokens[int(m.group(1))]
    singles: list[date] = []
    for index, value in enumerate(tokens):
        if index in used or value is None:
            continue
        if isinstance(value, tuple):                    # «tháng này», «tháng trước»
            if rng is None:
                rng = value
            continue
        singles.append(value)

    accounts: list[dict[str, str]] = []
    for m in re.finditer(r"(?<![\d§])\d{6,20}(?!\d)", marked):
        before = marked[max(0, m.start() - 24): m.start()]
        kind = "cif" if _CIF_WORD.search(before) else "account" if _ACCOUNT_WORD.search(before) else ""
        accounts.append({"value": m.group(0), "kind": kind})
    amounts = []
    for kind, value in _amounts(text):
        digits = mask.amount_digits(value)
        if digits:
            amounts.append(digits)
    return {"accounts": accounts, "dates": singles, "from_date": from_date, "to_date": to_date, "range": rng, "amounts": amounts,
            "problems": problems}


def _make(year: int, month: int, day: int, raw: str, problems: list[str]) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        problems.append(f"Ngày {raw} không có thật.")
        return None


def _amounts(text: str) -> list[tuple[str, str]]:
    _, slots, values = mask.extract_slots(text)
    return [("amount", values[s["id"]]) for s in slots if s["class"] == "amount"]


# ---- what an input is --------------------------------------------------------------------------------------------------------------

def _words(name: str, label: str) -> tuple[set[str], str]:
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", f"{name} {label}")
    folded = fold(spaced).replace("_", " ")
    words = set(re.findall(r"[a-z0-9]+", folded))
    return words, re.sub(r"[^a-z0-9]", "", folded)


def input_kind(item: dict[str, Any]) -> str | None:
    """'date_from', 'date_to', 'date', 'account', 'cif', 'amount' or None: from the name, the label and the recorded example."""
    words, squashed = _words(str(item.get("name") or ""), str(item.get("label") or ""))
    is_from = bool(words & {"tu", "from", "start", "begin"}) or any(k in squashed for k in ("tungay", "fromdate", "startdate", "datefrom", "ngaybatdau", "batdau"))
    is_to = bool(words & {"den", "toi", "to", "end"}) or any(k in squashed for k in ("denngay", "todate", "enddate", "dateto", "ngayketthuc", "ketthuc"))
    dated = (bool(words & {"ngay", "date", "thang"}) or item.get("type") == "date" or bool(item.get("format"))
             or any(k in squashed for k in ("fromdate", "todate", "startdate", "enddate", "tungay", "denngay")))
    if dated:
        if is_from and not is_to:
            return "date_from"
        if is_to and not is_from:
            return "date_to"
        return "date"
    if "cif" in words:
        return "cif"
    if words & {"stk", "acct", "account", "tk"} or any(k in squashed for k in ("taikhoan", "sotk", "accountno", "acctno", "accountnumber")):
        return "account"
    if re.search(r"so tien|amount|\bsotien\b", " ".join(words)) or "amount" in words or "sotien" in squashed:
        return "amount"
    return None


# ---- fill ----------------------------------------------------------------------------------------------------------------------------

def fill(found: dict[str, Any], inputs: list[dict[str, Any]], today: date) -> dict[str, Any]:
    """`inputs`: [{name, label, type, format}] still empty. Returns {values: {name: text}, asks: {name: question or ''}, used: set of digit runs}."""
    values: dict[str, str] = {}
    asks: dict[str, str] = {}
    used: set[str] = set()
    kinds = {i["name"]: input_kind(i) for i in inputs}
    by_name = {i["name"]: i for i in inputs}

    def put_date(name: str, value: date) -> None:
        values[name] = format_date(value, by_name[name].get("format") or ("yyyy-mm-dd" if by_name[name].get("type") == "date" else None))

    def of(*wanted: str) -> list[str]:
        return [n for n, k in kinds.items() if k in wanted]

    # numbers: one input that wants it and one number in the sentence that fits it
    for kind, key in (("account", "account"), ("cif", "cif")):
        names = of(kind)
        if not names:
            continue
        labelled = [a["value"] for a in found["accounts"] if a["kind"] == key]
        bare = [a["value"] for a in found["accounts"] if a["kind"] == ""] if key == "account" else []
        candidates = labelled or bare
        if len(names) == 1 and len(candidates) == 1:
            values[names[0]] = candidates[0]
            used.add(candidates[0])
        elif len(candidates) > 1 or len(names) > 1:
            asks[names[0]] = f"Trong câu có {len(candidates)} dãy số, mình không biết dãy nào là «{by_name[names[0]]['label']}». Bạn gõ lại giúp." if candidates else \
                f"Bạn cho mình «{by_name[names[0]]['label']}» nhé."
            for extra in names[1:]:
                asks[extra] = ""
    for name in of("amount"):
        if len(found["amounts"]) == 1 and len(of("amount")) == 1:
            values[name] = found["amounts"][0]
            used.add(found["amounts"][0])
        elif len(found["amounts"]) > 1:
            asks[name] = f"Trong câu có nhiều số tiền, bạn cho biết «{by_name[name]['label']}» là số nào."

    # dates
    from_in, to_in, any_in = of("date_from"), of("date_to"), of("date")
    rng, singles = found["range"], list(found["dates"])
    example = "từ " + show(today.replace(day=1)) + " đến " + show(today)
    if found["problems"] and (from_in or to_in or any_in):
        asks[(from_in + to_in + any_in)[0]] = " ".join(found["problems"]) + " Bạn gõ lại ngày giúp."
        for extra in (from_in + to_in + any_in)[1:]:
            asks[extra] = ""
        return {"values": values, "asks": asks, "used": used}
    pending = [n for n in from_in + to_in + any_in]
    if rng and len(from_in) == 1 and len(to_in) == 1 and not any_in:
        put_date(from_in[0], rng[0]); put_date(to_in[0], rng[1]); pending = []
    elif rng and pending:
        asks[pending[0]] = f"Bạn đưa một khoảng ngày nhưng việc này cần {len(pending)} ô ngày khác kiểu. Bạn cho biết «{by_name[pending[0]]['label']}» là ngày nào."
        for extra in pending[1:]:
            asks[extra] = ""
        pending = []
    else:
        if len(from_in) == 1 and found["from_date"]:
            put_date(from_in[0], found["from_date"]); pending.remove(from_in[0])
        if len(to_in) == 1 and found["to_date"]:
            put_date(to_in[0], found["to_date"]); pending.remove(to_in[0])
        if len(pending) == 1 and len(singles) == 1:
            put_date(pending[0], singles[0]); pending = []
        elif pending and singles:
            asks[pending[0]] = f"Trong câu có {len(singles)} ngày nhưng mình chưa rõ ngày nào là «{by_name[pending[0]]['label']}». Bạn gõ rõ, ví dụ {example}."
            for extra in pending[1:]:
                asks[extra] = ""
            pending = []
    if pending:
        both = len(pending) > 1
        label = " và ".join(f"«{by_name[n]['label']}»" for n in pending)
        asks[pending[0]] = (f"Bạn cho mình {label} nhé, ví dụ {example}." if both else f"Bạn cho mình {label} nhé (ví dụ {show(today)}).")
        for extra in pending[1:]:
            asks[extra] = ""
    return {"values": values, "asks": asks, "used": used}


def example_sentence(title: str, inputs: list[dict[str, Any]], today: date) -> str:
    """A sentence a teller could type for this agent, with made-up values (the first words are the agent's own name)."""
    parts = [title.strip().rstrip(".")[:1].lower() + title.strip().rstrip(".")[1:]]
    kinds = [input_kind(i) for i in inputs]
    first = today.replace(day=1)
    if "account" in kinds:
        parts.append("của stk 0123456789")
    if "cif" in kinds:
        parts.append("cif 123456")
    if "date_from" in kinds and "date_to" in kinds:
        parts.append(f"từ ngày {show(first)} đến ngày {show(today)}")
    elif "date_from" in kinds:
        parts.append(f"từ ngày {show(first)}")
    elif "date_to" in kinds:
        parts.append(f"đến ngày {show(today)}")
    elif "date" in kinds:
        parts.append(f"ngày {show(today)}")
    if "amount" in kinds:
        parts.append("5 triệu")
    return " ".join(parts)
