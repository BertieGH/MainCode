"""Reading whatever a rep actually uploaded.

Prospect lists arrive as Excel. Telling every rep to save-as-CSV is a tax on
the most common input in the product, and the failure it produces is
uninformative: an `.xlsx` is a zip, `decode()` turns it into replacement
characters, `csv.DictReader` finds no columns, and the screen says "could not
read any columns from that file" — which is true and tells nobody anything.

So this dispatches on what the bytes actually are, and when it cannot read
something it says *what* it is.

**`.xlsx` with the standard library.** An `.xlsx` is a zip of XML, and a
rectangle of strings does not need `openpyxl`. What it does need is to find the
parts the way the format says to, not the way one Excel version happens to
write them:

* **Parts are found through relationships.** A sheet's `Target` may be relative
  to the workbook's folder (`worksheets/sheet1.xml`, what Excel writes) or
  absolute from the package root (`/xl/worksheets/sheet1.xml`, what many
  exporters write). Treating every target as relative turned the second into
  `xl/xl/worksheets/sheet1.xml`, and every such file failed with "could not be
  read (KeyError)" — the import screen never reached the mapping step.
* **The workbook itself is found through `_rels/.rels`**, not assumed at
  `xl/workbook.xml`; shared strings through the workbook's relationships.
* **Strict Open XML** uses different namespaces for the same elements, so
  elements are matched by local name.
* **The first tab with data**, in tab order. A cover or notes tab first made a
  workbook full of rows read as "appears to be empty".
* **Cell references, not cell order.** A sheet with an empty column C emits
  cells for B, D and E and nothing between; read positionally, every later
  value shifts one field left. Every value is placed by its own `r="B2"`.

**`.xls` (Excel 97–2003) needs `xlrd`** — a binary format no standard library
module reads. Dates arrive as serial numbers there and are written as ISO
dates.
"""

from __future__ import annotations

import csv
import io
import logging
import posixpath
import re
import zipfile
from xml.etree import ElementTree as ET

log = logging.getLogger(__name__)

#: What the first bytes say the file really is, whatever it is named. Checked
#: before anything else because a mis-named file is common and its error should
#: describe the content, not the extension.
SIGNATURES: tuple[tuple[bytes, str, str], ...] = (
    (b"PK\x03\x04", "xlsx", "a zip-based Office file (.xlsx/.docx)"),
    (b"\xd0\xcf\x11\xe0", "xls", "an old Excel file (.xls, pre-2007)"),
    (b"%PDF", "pdf", "a PDF"),
    (b"\x89PNG", "image", "a PNG image"),
    (b"\xff\xd8\xff", "image", "a JPEG image"),
)


class UnreadableUpload(ValueError):
    """The file cannot be read, with a sentence a person can act on."""


def sniff(content: bytes) -> str:
    """`csv`, `xlsx`, `xls`, or the kind of thing it turned out to be."""
    for magic, kind, _ in SIGNATURES:
        if content.startswith(magic):
            return kind
    return "csv"


def _describe(content: bytes) -> str:
    """What the bytes are, matched on the bytes.

    Looked up by signature rather than by `kind`, because several kinds share
    one label — PNG and JPEG are both `image`, and searching by kind returned
    whichever came first, so a JPEG was reported as a PNG.
    """
    for magic, _, description in SIGNATURES:
        if content.startswith(magic):
            return description
    return "not a spreadsheet"


def parse_upload(
    content: bytes, filename: str | None = None
) -> tuple[list[str], list[dict[str, str]]]:
    """Headers and rows, from a CSV, an `.xlsx` or an `.xls`.

    Raises `UnreadableUpload` for anything else, naming what arrived. The old
    behaviour — returning no columns — made a PDF and an empty spreadsheet
    indistinguishable.
    """
    if not content:
        raise UnreadableUpload("that file is empty")

    kind = sniff(content)
    if kind == "csv":
        return parse_csv(content)
    if kind == "xlsx":
        try:
            return parse_xlsx(content)
        except UnreadableUpload:
            raise
        except Exception as exc:  # noqa: BLE001 — one error type upward
            log.warning("spreadsheet.xlsx_unreadable err=%s: %s", type(exc).__name__, exc)
            raise UnreadableUpload(
                f"that .xlsx could not be read ({type(exc).__name__}). "
                "If it opens in Excel, saving it as CSV will work."
            ) from exc
    if kind == "xls":
        return parse_xls(content)

    name = f" ({filename})" if filename else ""
    raise UnreadableUpload(
        f"that looks like {_describe(content)}{name}, not a spreadsheet this "
        "can read. Upload a CSV, an .xlsx or an .xls."
    )


def parse_csv(content: bytes) -> tuple[list[str], list[dict[str, str]]]:
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    rows = [dict(r) for r in reader]
    return (reader.fieldnames or []), rows


# --------------------------------------------------------------------------
# a grid of cells, whichever format it came from
# --------------------------------------------------------------------------
Grid = list[dict[int, str]]


def _table(grid: Grid) -> tuple[list[str], list[dict[str, str]]] | None:
    """Headers and rows from a grid, or None when it holds nothing.

    Blank rows are dropped rather than imported as empty accounts — a
    spreadsheet's used range routinely extends past its content.
    """
    grid = list(grid)
    while grid and not grid[0]:
        grid.pop(0)  # leading blank rows above the header
    if not grid:
        return None

    header_cells = grid[0]
    columns = sorted(header_cells)
    headers = [header_cells[c] for c in columns]

    rows: list[dict[str, str]] = []
    for cells in grid[1:]:
        if not cells:
            continue
        row = {header_cells[c]: cells.get(c, "") for c in columns}
        if any(v.strip() for v in row.values()):
            rows.append(row)
    return headers, rows


# --------------------------------------------------------------------------
# xlsx
# --------------------------------------------------------------------------

_CELL_REF = re.compile(r"^([A-Z]+)(\d+)$")


def _local(tag: str) -> str:
    """`{namespace}sheetData` → `sheetData`: transitional and Strict alike."""
    return tag.rsplit("}", 1)[-1]


def _children(element: ET.Element | None, name: str) -> list[ET.Element]:
    return [c for c in (element if element is not None else []) if _local(c.tag) == name]


def _child(element: ET.Element | None, name: str) -> ET.Element | None:
    found = _children(element, name)
    return found[0] if found else None


def _column_index(ref: str) -> int:
    """`A` → 0, `B` → 1, `AA` → 26."""
    n = 0
    for char in ref:
        n = n * 26 + (ord(char) - 64)
    return n - 1


def _resolve(source_part: str, target: str) -> str:
    """Where a relationship's target lives in the zip.

    Absolute targets (`/xl/worksheets/sheet1.xml`) are from the package root;
    relative ones are from the folder of the part that declares them.
    """
    if target.startswith("/"):
        return posixpath.normpath(target.lstrip("/"))
    return posixpath.normpath(posixpath.join(posixpath.dirname(source_part), target))


def _relationships(z: zipfile.ZipFile, source_part: str) -> list[tuple[str, str, str]]:
    """(id, type, resolved target) for each relationship a part declares."""
    folder, name = posixpath.split(source_part)
    rels_path = posixpath.join(folder, "_rels", f"{name}.rels")
    try:
        root = ET.fromstring(z.read(rels_path))
    except (KeyError, ET.ParseError):
        return []
    out = []
    for rel in root:
        if _local(rel.tag) != "Relationship" or rel.get("TargetMode") == "External":
            continue
        target = rel.get("Target") or ""
        out.append((rel.get("Id") or "", rel.get("Type") or "", _resolve(source_part, target)))
    return out


def _workbook_path(z: zipfile.ZipFile) -> str:
    for _, kind, target in _relationships(z, ""):
        if kind.endswith("/officeDocument") and target in z.namelist():
            return target
    return "xl/workbook.xml"


def _sheet_paths(z: zipfile.ZipFile, workbook: str) -> list[str]:
    """Worksheet parts in tab order — the order a person sees them."""
    names = set(z.namelist())
    ordered: list[str] = []
    try:
        book = ET.fromstring(z.read(workbook))
        by_id = {
            rel_id: target
            for rel_id, kind, target in _relationships(z, workbook)
            if kind.endswith("/worksheet")
        }
        for sheet in _children(_child(book, "sheets"), "sheet"):
            rel_id = next((v for k, v in sheet.attrib.items() if _local(k) == "id"), None)
            target = by_id.get(rel_id or "")
            if target and target in names:
                ordered.append(target)
    except (KeyError, ET.ParseError):
        log.info("spreadsheet.workbook_unreadable — falling back to the worksheet parts")

    if not ordered:
        ordered = sorted(
            (n for n in names if re.match(r"^xl/worksheets/[^/]+\.xml$", n)),
            key=lambda n: [int(d) if d.isdigit() else d for d in re.split(r"(\d+)", n)],
        )
    if not ordered:
        raise UnreadableUpload("that .xlsx contains no worksheet")
    return ordered


def _shared_strings(z: zipfile.ZipFile, workbook: str) -> list[str]:
    path = next(
        (t for _, kind, t in _relationships(z, workbook) if kind.endswith("/sharedStrings")),
        "xl/sharedStrings.xml",
    )
    try:
        root = ET.fromstring(z.read(path))
    except KeyError:
        return []
    return ["".join(_text_runs(si)) for si in _children(root, "si")]


def _text_runs(element: ET.Element) -> list[str]:
    """The visible text of a string item — its `t` runs, not phonetic hints."""
    return [
        node.text or ""
        for node in element.iter()
        if _local(node.tag) == "t" and not _inside_phonetic(element, node)
    ]


def _inside_phonetic(root: ET.Element, node: ET.Element) -> bool:
    for rph in root.iter():
        if _local(rph.tag) == "rPh" and any(n is node for n in rph.iter()):
            return True
    return False


def _cell_text(cell: ET.Element, shared: list[str]) -> str:
    kind = cell.get("t")
    if kind == "inlineStr":
        node = _child(cell, "is")
        return "".join(_text_runs(node)).strip() if node is not None else ""
    value = _child(cell, "v")
    if value is None or value.text is None:
        return ""
    text = value.text
    if kind == "s":
        try:
            return shared[int(text)]
        except (ValueError, IndexError):
            return text
    if kind == "b":
        return "TRUE" if text == "1" else "FALSE"
    if kind == "e":
        return ""  # #N/A, #REF! — an error, not a value to import
    # Numbers arrive as floats: `12.0` for a headcount reads badly and breaks
    # an int parse downstream, so a whole number is written as one.
    if re.fullmatch(r"-?\d+\.0+", text):
        return text.split(".")[0]
    return text


def _xlsx_grid(sheet: ET.Element, shared: list[str]) -> Grid:
    grid: Grid = []
    for row in _children(_child(sheet, "sheetData"), "row"):
        cells: dict[int, str] = {}
        for index, cell in enumerate(_children(row, "c")):
            match = _CELL_REF.match(cell.get("r") or "")
            # By reference, never by position — a gap column would otherwise
            # shift every later value one field left, silently.
            column = _column_index(match.group(1)) if match else index
            text = _cell_text(cell, shared).strip()
            if text:
                cells[column] = text
        grid.append(cells)
    return grid


def parse_xlsx(content: bytes) -> tuple[list[str], list[dict[str, str]]]:
    """Headers and rows from the first worksheet that has any."""
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        workbook = _workbook_path(z)
        shared = _shared_strings(z, workbook)
        paths = _sheet_paths(z, workbook)
        for position, path in enumerate(paths):
            table = _table(_xlsx_grid(ET.fromstring(z.read(path)), shared))
            if table is not None:
                if position:
                    log.info("spreadsheet.first_tab_empty — read tab %d (%s)", position + 1, path)
                return table
    if len(paths) == 1:
        raise UnreadableUpload("that .xlsx appears to be empty")
    raise UnreadableUpload(f"that .xlsx appears to be empty — none of its {len(paths)} tabs holds data")


# --------------------------------------------------------------------------
# xls (Excel 97-2003)
# --------------------------------------------------------------------------
def parse_xls(content: bytes) -> tuple[list[str], list[dict[str, str]]]:
    """Headers and rows from the first sheet of an old binary Excel file that has any."""
    try:
        import xlrd
    except ImportError as exc:
        raise UnreadableUpload(
            "that is an old Excel file (.xls, pre-2007), and this installation cannot read "
            "one. Save it as .xlsx or CSV."
        ) from exc
    try:
        book = xlrd.open_workbook(file_contents=content, on_demand=True)
    except Exception as exc:  # noqa: BLE001 — one error type upward
        raise UnreadableUpload(
            f"that old Excel file (.xls) could not be read ({type(exc).__name__}). "
            "If it opens in Excel, saving it as .xlsx or CSV will work."
        ) from exc

    try:
        for sheet in book.sheets():
            grid: Grid = []
            for r in range(sheet.nrows):
                cells: dict[int, str] = {}
                for c in range(sheet.ncols):
                    text = _xls_text(xlrd, book, sheet.cell(r, c)).strip()
                    if text:
                        cells[c] = text
                grid.append(cells)
            table = _table(grid)
            if table is not None:
                return table
    finally:
        release = getattr(book, "release_resources", None)
        if release:
            release()
    raise UnreadableUpload("that .xls appears to be empty")


def _xls_text(xlrd, book, cell) -> str:
    kind, value = cell.ctype, cell.value
    if kind in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK, xlrd.XL_CELL_ERROR):
        return ""
    if kind == xlrd.XL_CELL_BOOLEAN:
        return "TRUE" if value else "FALSE"
    if kind == xlrd.XL_CELL_DATE:
        try:
            when = xlrd.xldate_as_datetime(value, book.datemode)
        except Exception:  # noqa: BLE001 — an unreadable date is still a number
            return str(value)
        return when.date().isoformat() if when.time() == when.time().min else when.isoformat()
    if kind == xlrd.XL_CELL_NUMBER:
        return str(int(value)) if float(value).is_integer() else str(value)
    return str(value)
