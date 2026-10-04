"""Reading what a rep actually uploaded.

Two failures worth testing, and only one of them is loud.

The loud one is the wrong file type: an `.xlsx` used to decode into
replacement characters and produce "could not read any columns", which is
equally what a PDF, an empty file and a headerless sheet produced. Four
different problems, one useless sentence.

The quiet one is **column gaps**. A sheet with an empty column C emits cells
for B, D and E and nothing between; read positionally, every later value
shifts one field left, so names land under `domain` and the import *succeeds*.
That is the one that would reach production unnoticed, and it is the reason
cells are placed by their `r="B2"` reference rather than by their order.
"""

from __future__ import annotations

import io
import zipfile

import pytest

from app.services.spreadsheet import (
    UnreadableUpload,
    parse_upload,
    parse_xlsx,
    sniff,
)

MAIN = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
DOCREL = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'


def build_xlsx(rows: list[list[tuple[str, str]]], *, sheet_name="sheet1.xml") -> bytes:
    """A minimal but real `.xlsx`.

    `rows` is a list of `[(cell_ref, text)]`, so a test can leave a gap simply
    by not naming the column — which is exactly what Excel does.
    """
    strings: list[str] = []

    def index(text: str) -> int:
        if text not in strings:
            strings.append(text)
        return strings.index(text)

    body = []
    for n, row in enumerate(rows, start=1):
        cells = "".join(
            f'<c r="{ref}" t="s"><v>{index(text)}</v></c>' for ref, text in row
        )
        body.append(f'<row r="{n}">{cells}</row>')

    sheet = (
        f'<worksheet {MAIN}><sheetData>{"".join(body)}</sheetData></worksheet>'
    )
    shared = (
        f'<sst {MAIN} count="{len(strings)}">'
        + "".join(f"<si><t>{s}</t></si>" for s in strings)
        + "</sst>"
    )
    workbook = (
        f'<workbook {MAIN} {DOCREL}><sheets>'
        f'<sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    rels = (
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'<Relationship Id="rId1" Target="worksheets/{sheet_name}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"/>'
        "</Relationships>"
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/workbook.xml", workbook)
        z.writestr("xl/_rels/workbook.xml.rels", rels)
        z.writestr(f"xl/worksheets/{sheet_name}", sheet)
        z.writestr("xl/sharedStrings.xml", shared)
    return buf.getvalue()


class TestColumnGapsDoNotShiftValues:
    """The quiet failure: it succeeds, and every field is wrong."""

    def test_a_gap_column_leaves_the_others_in_place(self):
        data = build_xlsx([
            [("B1", "company"), ("D1", "name"), ("E1", "title")],
            [("B2", "Acme"), ("D2", "Dana"), ("E2", "CTO")],
        ])
        headers, rows = parse_xlsx(data)
        assert headers == ["company", "name", "title"]
        assert rows == [{"company": "Acme", "name": "Dana", "title": "CTO"}]

    def test_a_gap_inside_a_row_does_not_pull_later_values_left(self):
        """The row is missing D. `title` must stay `CTO`, not become blank."""
        data = build_xlsx([
            [("B1", "company"), ("D1", "name"), ("E1", "title")],
            [("B2", "Acme"), ("E2", "CTO")],
        ])
        _, rows = parse_xlsx(data)
        assert rows == [{"company": "Acme", "name": "", "title": "CTO"}]

    def test_columns_past_z_are_placed_correctly(self):
        data = build_xlsx([
            [("A1", "first"), ("AA1", "twentyseventh")],
            [("A2", "x"), ("AA2", "y")],
        ])
        headers, rows = parse_xlsx(data)
        assert headers == ["first", "twentyseventh"]
        assert rows[0]["twentyseventh"] == "y"


class TestWhatGetsDropped:
    def test_blank_rows_are_not_imported_as_empty_accounts(self):
        """A used range routinely runs past the content, and Excel emits it."""
        data = build_xlsx([
            [("A1", "company")],
            [("A2", "Acme")],
            [],
            [],
        ])
        _, rows = parse_xlsx(data)
        assert rows == [{"company": "Acme"}]

    def test_blank_rows_above_the_header_are_skipped(self):
        data = build_xlsx([
            [],
            [("A2", "company")],
            [("A3", "Acme")],
        ])
        headers, rows = parse_xlsx(data)
        assert headers == ["company"]
        assert rows == [{"company": "Acme"}]


class TestUnreadableFilesSayWhatTheyAre:
    """One sentence a person can act on, instead of four problems sharing one."""

    @pytest.mark.parametrize(
        "content,expected",
        [
            (b"%PDF-1.7 ...", "PDF"),
            (b"\xd0\xcf\x11\xe0junk", "old Excel"),
            (b"\x89PNG\r\n\x1a\n", "PNG"),
            (b"\xff\xd8\xff\xe0", "JPEG"),
        ],
    )
    def test_the_kind_is_named(self, content, expected):
        with pytest.raises(UnreadableUpload) as caught:
            parse_upload(content, "whatever.csv")
        assert expected in str(caught.value)

    def test_an_empty_file_says_so(self):
        with pytest.raises(UnreadableUpload, match="empty"):
            parse_upload(b"", "x.csv")

    def test_a_corrupt_xlsx_suggests_the_way_out(self):
        """It starts with the zip magic but is not a workbook."""
        with pytest.raises(UnreadableUpload) as caught:
            parse_upload(b"PK\x03\x04 not really a zip", "broken.xlsx")
        assert "saving it as CSV" in str(caught.value)

    def test_the_content_decides_not_the_extension(self):
        """A renamed file is common; the error should describe what arrived."""
        assert sniff(b"%PDF-1.7") == "pdf"
        with pytest.raises(UnreadableUpload, match="PDF"):
            parse_upload(b"%PDF-1.7", "definitely-a-list.csv")


class TestCsvStillWorks:
    def test_a_plain_csv_round_trips(self):
        headers, rows = parse_upload(b"company,name\nAcme,Dana\n", "x.csv")
        assert headers == ["company", "name"]
        assert rows == [{"company": "Acme", "name": "Dana"}]

    def test_a_utf8_bom_is_stripped(self):
        """Excel's own CSV export writes one, and it corrupts the first header."""
        headers, _ = parse_upload(b"\xef\xbb\xbfcompany,name\nAcme,Dana\n", "x.csv")
        assert headers[0] == "company"


class TestCellTypes:
    def test_a_whole_number_does_not_arrive_as_a_float(self):
        """`250.0` for a headcount reads badly and breaks an int parse."""
        sheet = (
            f'<worksheet {MAIN}><sheetData>'
            '<row r="1"><c r="A1" t="inlineStr"><is><t>employees</t></is></c></row>'
            '<row r="2"><c r="A2"><v>250.0</v></c></row>'
            "</sheetData></worksheet>"
        )
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("xl/worksheets/sheet1.xml", sheet)
        _, rows = parse_xlsx(buf.getvalue())
        assert rows == [{"employees": "250"}]

    def test_inline_strings_are_read(self):
        sheet = (
            f'<worksheet {MAIN}><sheetData>'
            '<row r="1"><c r="A1" t="inlineStr"><is><t>company</t></is></c></row>'
            '<row r="2"><c r="A2" t="inlineStr"><is><t>Acme</t></is></c></row>'
            "</sheetData></worksheet>"
        )
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("xl/worksheets/sheet1.xml", sheet)
        headers, rows = parse_xlsx(buf.getvalue())
        assert headers == ["company"]
        assert rows == [{"company": "Acme"}]
