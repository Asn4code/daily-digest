"""Derived lexical views of cited prose; originals and grounding quotes stay intact."""

import re
from dataclasses import dataclass, replace
from functools import lru_cache
from html import unescape
from unicodedata import category

from markdown_it import MarkdownIt

TOKEN = re.compile(r"(?<![^\W_])(?<!\.)[-+]?(?>\d+(?:[.,]\d+)?|\.\d+)(?:[eE][-+]?\d+)?(?!\d)")
PDB_CHAIN_ID = re.compile(r"\b[0-9][A-Za-z0-9]{3}_[A-Za-z0-9]+\b")
UNIT = re.compile(
    r"^\s*((?:[%°]?(?:[^\W\d_][^\s,;:()\[\]{}<>/]*)|%)"
    r"(?:\s*/\s*[^\s,;:()\[\]{}<>/]+)*)"
)
CONNECTORS = {
    "si",
    "mediante",
    "cuando",
    "como",
    "porque",
    "quedó",
    "quedaron",
    "terminó",
    "terminaron",
    "terminada",
    "terminado",
    "está",
    "están",
    "en",
    "de",
    "con",
    "y",
    "a",
    "para",
    "del",
    "al",
    "el",
    "la",
    "los",
    "las",
    "que",
    "o",
    "ni",
    "por",
    "según",
    "donde",
    "frente",
    "vs",
    "es",
    "son",
    "se",
    "usado",
    "usados",
    "usada",
    "usadas",
    "entre",
    "sobre",
    "hasta",
    "desde",
    "tras",
    "durante",
    "sin",
    "aunque",
    "pese",
    "mientras",
    "podría",
    "podrían",
    "sugiere",
    "sugieren",
}

COMPOUND_UNIT = re.compile(
    r"^\s+((?:(?:[YZEPTGMkhdcmuµμnpfa]?|[KMGTPEZY]i)"
    r"(?:mol|kg|byte|bit|cal|eV|cd|rad|sr|Hz|Pa|Da|m|s|g|K|A|B|L|l|J|W|N|C|V|Å)"
    r"(?:\^?[-−+]?\d+|[⁻⁺⁰¹²³⁴⁵⁶⁷⁸⁹]+)?(?=$|[\W\d_])|%|°C|°F)"
    r"[^\s,;:()\[\]{}<>/]*(?:\s*/\s*[^\s,;:()\[\]{}<>/]+)*)"
)

REFERENCE_LABEL = re.compile(
    r"\b(?:[A-Z]{2,}[A-Z0-9]*-\d+|(?i:Step|paso|proyecto|intento|lote|batch)\s+\d+)\b"
    r"(?![.,]\d)"
)
SOURCE_GIT = re.compile(
    r"\b(?:commit|sha(?:-?(?:1|256))?|hash|identificador|id|revisión)"
    r"[\s:=#\"'«»“”‘’()\[\]]+([a-fA-F0-9]{64}|[a-fA-F0-9]{40})(?!\w)",
    re.I,
)

FILE_LABELS = {"conf", "pdb", "mmcif", "npz", "csv", "json", "png", "pdf", "svg"}
QUOTES = "\"'«»“”‘’"
UNIT_PUNCTUATION = ".!?" + QUOTES


def _direct_unit(text: str) -> tuple[str | None, int]:
    original = text
    text = text.lstrip().lstrip(QUOTES)
    text = re.sub(r"^de\s+(?:esas|esos|estas|estos|las|los)\s+", "", text)
    classifier = re.match(r"^(?:ficheros|archivos)\s+([^\W\d_][^\s,;:()\[\]{}<>]*)", text)
    if classifier and classifier[1].rstrip(UNIT_PUNCTUATION).casefold() in FILE_LABELS:
        text = text[classifier.start(1) :]
    base = len(original) - len(text)
    matched = UNIT.match(text)
    if not matched or matched.group(1).rstrip(UNIT_PUNCTUATION) in CONNECTORS:
        return None, 0
    parts = [re.split(r"\s*/\s*(?=\d)", matched.group(1).rstrip(UNIT_PUNCTUATION))[0]]
    separator = re.search(r"\s*/\s*(?=\d)", matched.group(1))
    if separator:
        return " ".join(parts[0].split()), base + matched.start(1) + separator.start()
    end = matched.end()
    if not matched.group(1).rstrip(QUOTES).endswith((".", "!", "?")):
        tail = text[end:]
        while (suffix := COMPOUND_UNIT.match(tail)) is not None:
            parts.append(suffix.group(1).rstrip(UNIT_PUNCTUATION))
            end += suffix.end()
            if suffix.group(1).rstrip(QUOTES).endswith((".", "!", "?")):
                break
            tail = tail[suffix.end() :]
        # Preserve separated operations on dimensions, not only attached ones.
        # A numeric operand is handled by the expression binder instead.
        while (
            operation := re.match(
                r"^\s*([*/·×^+÷∕⁄=<>≤≥≠≈≃∼~:\-])\s*(?![+\-]?(?:\d|\.\d))([^\s,;:]+)", text[end:]
            )
        ) is not None:
            parts.append(operation[1] + " " + operation[2].rstrip(UNIT_PUNCTUATION))
            end += operation.end()
    return " ".join(" ".join(parts).split()), base + end


def unit_at(text: str) -> str | None:
    return _direct_unit(text)[0]


# Formatting has the same meaning in source and candidate. Code spans preserve
# their literal content, including underscores and operators. Unmatched markers
# remain text and cannot be used to hide quantities or dimensions.
MARKDOWN = MarkdownIt("commonmark", {"html": True})
OPAQUE = re.compile(r"OPAQUEREF[a-p]+")
COUNT_LABELS = {
    "estructuras",
    "pares",
    "ligandos",
    "secuencias",
    "muestras",
    "predicciones",
    "réplicas",
    "replicas",
    "residuos",
    "archivos",
    "ficheros",
    "conf",
    "partial",
    "from_scratch",
}
OPERATOR = re.compile(
    r"\s*(de|a|al|hasta|por|entre|más|menos|\.{2,}|\+/-|<=|>=|==|!=|/|[-–—+*^±·×÷∕⁄=<>≤≥≠≈≃∼~:…])\s*"
)


@lru_cache(maxsize=512)
def view(text: str) -> str:
    # A formatting marker between numeric fragments could be an operation.
    # Keep ambiguous spellings literal; never concatenate them into a value.
    # Expose both endpoints of dot ranges instead of letting the numeric
    # boundary rule silently ignore the endpoint after a decimal dot.
    text = re.sub(r"(?<=\d)(?:\s*\.){2,}\s*(?=[+\-]?\d)", " .. ", text)
    decoded = unescape(text)
    if re.search(r"\d\s*[*_]{1,2}\s*[+\-]?(?:\d|\.\d)", decoded):
        return re.sub(r"(?<=\d)(?:\s*\.){2,}\s*(?=[+\-]?\d)", " .. ", decoded).replace("−", "-")
    tokens = MARKDOWN.parseInline(text)
    children = tokens[0].children or [] if tokens else []
    # Joining token contents drops only formatting delimiters. No rendering or
    # HTML decoding is used, and nested code remains unexecuted literal text.
    plain = "".join("\n" if t.type in {"softbreak", "hardbreak"} else t.content for t in children)
    return re.sub(r"(?<=\d)(?:\s*\.){2,}\s*(?=[+\-]?\d)", " .. ", plain).replace("−", "-")


def reference_token(value: str) -> str:
    # Unique, lossless identity payload with no digits or punctuation for the
    # numeric lexer to accidentally reinterpret (including numeric PDB chains).
    encoded = value.encode().hex().translate(str.maketrans("0123456789abcdef", "abcdefghijklmnop"))
    return "OPAQUEREF" + encoded


def opaque(text: str) -> str:
    text = PDB_CHAIN_ID.sub(lambda m: reference_token(m.group()), text)

    def identity(match: re.Match[str]) -> str:
        prefix = text[: match.start()].rstrip().rstrip(QUOTES).rstrip()
        if prefix and (prefix[-1].isdigit() or prefix[-1] in "/^*·×+-"):
            return match.group()
        return reference_token(" ".join(match.group().casefold().split()))

    text = SOURCE_GIT.sub(lambda m: reference_token(m[1].casefold()), text)
    return REFERENCE_LABEL.sub(identity, text)


def _balanced(text: str) -> tuple[str, int] | None:
    stack: list[str] = []
    pairs = {"(": ")", "[": "]"}
    for i, char in enumerate(text):
        if char in pairs:
            stack.append(pairs[char])
            if len(stack) > 8:
                return None
        elif char in ")]":
            if not stack or stack.pop() != char:
                return None
            if not stack:
                return text[1:i], i + 1
    return None


def _unit(text: str) -> str | None:
    """Project adjacent annotations without discarding units inside or after them."""
    tail = text.lstrip().lstrip(QUOTES).lstrip()
    parts: list[str] = []
    head, used = _direct_unit(tail)
    if head:
        parts.append(head)
        if tail[:used].rstrip(QUOTES).endswith((".", "!", "?")):
            return head
        tail = tail[used:].lstrip().lstrip(QUOTES).lstrip()
        if not tail.startswith(("(", "[")):
            if re.match(
                r"^(?:de|a|al|hasta|por|entre|más|menos|\+/-|<=|>=|==|!=|/|[-–—+*^±·×÷∕⁄=<>≤≥≠≈≃∼~:])\s*[+\-]?(?:\d|\.\d)",
                tail,
            ):
                return head  # The next numeric operand is bound below.
            if tail and category(tail[0]) == "Sm" and tail[0] != "|":
                return "<unsupported-symbol>"
            return head
    for _ in range(8):
        if not tail.startswith(("(", "[")):
            break
        bracket = _balanced(tail)
        if bracket is None:
            return "<unbalanced>"
        body, end = bracket
        body = body.lstrip().lstrip(QUOTES)
        ident = OPAQUE.match(body)
        if ident:
            body = body[ident.end() :].lstrip().lstrip(QUOTES)
        inside = (
            "<operator>" + body.split()[0]
            if body and body[0] in "*/^·×±+-÷∕⁄=<>≤≥≠≈≃∼~"
            else unit_at(body)
        )
        if inside:
            parts.append(inside)
        tail = tail[end:].lstrip().lstrip(QUOTES).lstrip()
    else:
        return "<nested>"
    if tail and category(tail[0]) == "Sm" and tail[0] not in "|*/^·×±+-%°÷∕⁄=<>≤≥≠≈≃∼~:":
        return "<unsupported-symbol>"
    outside = unit_at(tail)
    if outside:
        parts.append(outside)
    if tail and tail[0] in "*/^·×±+-%°÷∕⁄=<>≤≥≠≈≃∼~:":
        # Operators between numbers are handled as an expression below; a
        # dangling operator must not turn an unknown dimension into no unit.
        right = unit_at(tail[1:].lstrip())
        return "<operator>" + tail[0] + (" " + right if right else "")
    if tail.startswith(("_", "`")):
        return "<literal>" + tail.split()[0]
    return " ".join(parts) or None


@dataclass(frozen=True)
class Quantity:
    value: float
    unit: str | None
    relation: tuple[tuple[float, str | None, str | None], ...] = ()
    operators: tuple[str, ...] = ()
    valid: bool = True
    annotation: str | None = None


@lru_cache(maxsize=512)
def quantities(text: str) -> tuple[Quantity, ...]:
    """Read quantities and bind contiguous operands; never evaluate expressions."""
    text = opaque(text)
    if any(category(c) == "Cf" or (category(c) == "Cc" and c not in "\n\r\t") for c in text):
        return (Quantity(0, None, valid=False),)
    if re.search(r"(?<![\w.])\d+(?:[.,]\d+){2,}(?!\w)", text):
        return (Quantity(0, None, valid=False),)
    matches = list(TOKEN.finditer(text))
    result: list[Quantity] = []
    kept: list[re.Match[str]] = []
    operand_ends: list[int] = []
    unit_end = -1
    for match in matches:
        if match.start() < unit_end:
            continue
        tail = text[match.end() :]
        unit = _unit(tail)
        # Numeric powers belong to a dimension, not to another measured value.
        # Retain their full spelling in the unit and skip their numeric token.
        _, consumed = _direct_unit(tail)
        unit_end = match.end() + consumed
        prefix = text[: match.start()].rstrip().rstrip(QUOTES).rstrip()
        prefix = prefix.rstrip("([ \t")
        valid = not (prefix and prefix[-1] in "*/^·×±+-÷∕⁄_")
        valid = valid and not re.search(r"\d\s*\.{2,}$", prefix)
        valid = valid and unit not in {"<unbalanced>", "<nested>", "<unsupported-symbol>"}
        valid = valid and not (unit and unit.startswith("<literal>"))
        annotation = None
        annotated = tail.lstrip().lstrip(QUOTES).lstrip()
        if not annotated.startswith(("(", "[")):
            annotated = tail[consumed:].lstrip().lstrip(QUOTES).lstrip()
        notes: list[str] = []
        for _ in range(8):
            if not annotated.startswith(("(", "[")):
                break
            bracket = _balanced(annotated)
            if bracket is None:
                valid = False
                break
            notes.append(" ".join(bracket[0].split()))
            annotated = annotated[bracket[1] :].lstrip().lstrip(QUOTES).lstrip()
        else:
            valid = False
        if notes:
            annotation = repr(tuple(notes))
        kept.append(match)
        operand_ends.append(unit_end)
        result.append(
            Quantity(
                float(match.group().replace(",", ".")), unit, valid=valid, annotation=annotation
            )
        )
    start = 0
    while start < len(kept):
        end = start
        ops: list[str] = []
        while end + 1 < len(kept):
            between = text[operand_ends[end] : kept[end + 1].start()]
            op = OPERATOR.fullmatch(between)
            symbols = between.strip().strip(QUOTES).strip()
            # Grouped expressions need precedence handling; fail closed rather
            # than flattening them into independently supported scalars.
            grouped = any(c in symbols for c in ")]}")
            bare_symbols = symbols.translate(str.maketrans("", "", ")]}")).strip(QUOTES).strip()
            signed = kept[end + 1].group().startswith(("+", "-"))
            if grouped and ((not bare_symbols and signed) or OPERATOR.fullmatch(bare_symbols)):
                result[end] = replace(result[end], valid=False)
                result[end + 1] = replace(result[end + 1], valid=False)
                break
            if (
                not op
                and symbols
                and all(category(c) == "Sm" or c.isspace() for c in symbols)
                and symbols != "|"
            ):
                result[end] = replace(result[end], valid=False)
                result[end + 1] = replace(result[end + 1], valid=False)
                break
            if between.strip() == "y" and re.search(r"\bentre\s*$", text[: kept[start].start()]):
                op = OPERATOR.fullmatch(" a ")
            grouped_digits = (
                not between.strip()
                and not kept[end + 1].group().startswith(("+", "-"))
                and re.match(r"\d{3}(?!\d)", kept[end + 1].group()) is not None
            )
            signed_operator = None
            if not between.strip() and kept[end + 1].group().startswith(("+", "-")):
                signed_operator = kept[end + 1].group()[0]
            if not op and signed_operator is None and not grouped_digits:
                break
            symbol = (
                signed_operator
                if signed_operator is not None
                else op[1]
                if op
                else "grouped-digits"
            )
            if (
                symbol == "/"
                and result[end].unit in COUNT_LABELS
                and result[end + 1].unit in COUNT_LABELS
            ):
                # Enumerating independently labelled counts does not divide them.
                result[end + 1] = replace(result[end + 1], valid=True)
                break
            if signed_operator is not None:
                result[end + 1] = replace(result[end + 1], value=abs(result[end + 1].value))
            ops.append(
                "/"
                if symbol == "de"
                else "-"
                if symbol in {"–", "—", "a", "al", "hasta", "…"} or symbol.startswith("..")
                else symbol
            )
            end += 1
        if end > start:
            # The operator of a following operand is a relation, not a unit.
            values = [
                replace(q, unit=None if q.unit and q.unit.startswith("<operator>") else q.unit)
                for q in result[start : end + 1]
            ]
            relation = tuple((q.value, q.unit, q.annotation) for q in values)
            for i, q in enumerate(values, start):
                result[i] = replace(
                    q, relation=relation, operators=tuple(ops), valid=values[0].valid
                )
        start = end + 1
    return tuple(result)
