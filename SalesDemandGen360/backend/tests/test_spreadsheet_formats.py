"""Excel files as other tools write them, and old `.xls` files.

The import screen never reached the mapping step for a workbook whose sheets
are listed with absolute paths (`/xl/worksheets/sheet1.xml`) — every upload
answered "that .xlsx could not be read (KeyError)". That was found on a real
exported workbook; these build the same shapes in memory.
"""

from __future__ import annotations

import io
import sys
import zipfile
from datetime import datetime
from types import SimpleNamespace

import pytest

from app.services.spreadsheet import UnreadableUpload, parse_upload
from tests.test_spreadsheet import build_xlsx

ROWS = [
    [("A1", "Company"), ("B1", "Domain")],
    [("A2", "Meridian Cloud"), ("B2", "meridiancloud.io")],
]
EXPECTED = (["Company", "Domain"], [{"Company": "Meridian Cloud", "Domain": "meridiancloud.io"}])


def rewrite(data: bytes, *, renames=None, edit=None, add=None) -> bytes:
    """Copy a zip, renaming parts, editing their text, or adding new ones."""
    renames, edit, add = renames or {}, edit or (lambda name, text: text), add or {}
    src = zipfile.ZipFile(io.BytesIO(data))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as out:
        for name in src.namelist():
            text = edit(name, src.read(name).decode("utf-8"))
            out.writestr(renames.get(name, name), text)
        for name, text in add.items():
            out.writestr(name, text)
    return buf.getvalue()


class TestHowOtherToolsWriteAWorkbook:
    def test_absolute_sheet_paths_are_found(self):
        """The live failure: `xl/xl/worksheets/sheet1.xml` does not exist."""
        data = rewrite(
            build_xlsx(ROWS),
            edit=lambda name, text: text.replace('Target="worksheets/', 'Target="/xl/worksheets/'),
        )
        assert parse_upload(data, "export.xlsx") == EXPECTED

    def test_the_workbook_is_found_through_the_package_relationships(self):
        package_rels = (
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Target="book/main.xml" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"/>'
            "</Relationships>"
        )
        data = rewrite(
            build_xlsx(ROWS),
            renames={
                "xl/workbook.xml": "book/main.xml",
                "xl/_rels/workbook.xml.rels": "book/_rels/main.xml.rels",
                "xl/worksheets/sheet1.xml": "book/worksheets/sheet1.xml",
                "xl/sharedStrings.xml": "book/sharedStrings.xml",
            },
            edit=lambda name, text: text.replace(
                "</Relationships>",
                '<Relationship Id="rId9" Target="sharedStrings.xml" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings"/>'
                "</Relationships>",
            ) if name.endswith(".rels") else text,
            add={"_rels/.rels": package_rels},
        )
        assert parse_upload(data, "odd.xlsx") == EXPECTED

    def test_strict_open_xml_namespaces_are_read(self):
        def strict(name, text):
            return text.replace(
                "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
                "http://purl.oclc.org/ooxml/spreadsheetml/main",
            ).replace(
                "http://schemas.openxmlformats.org/officeDocument/2006/relationships\"",
                "http://purl.oclc.org/ooxml/officeDocument/relationships\"",
            )

        assert parse_upload(rewrite(build_xlsx(ROWS), edit=strict), "strict.xlsx") == EXPECTED

    def test_an_empty_first_tab_falls_through_to_the_tab_with_data(self):
        data = build_xlsx(ROWS)
        empty = (
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            "<sheetData/></worksheet>"
        )

        def two_tabs(name, text):
            if name == "xl/workbook.xml":
                return text.replace(
                    '<sheet name="Sheet1" sheetId="1" r:id="rId1"/>',
                    '<sheet name="Cover" sheetId="2" r:id="rId2"/><sheet name="Sheet1" sheetId="1" r:id="rId1"/>',
                )
            if name == "xl/_rels/workbook.xml.rels":
                return text.replace(
                    "</Relationships>",
                    '<Relationship Id="rId2" Target="worksheets/cover.xml" '
                    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"/>'
                    "</Relationships>",
                )
            return text

        data = rewrite(data, edit=two_tabs, add={"xl/worksheets/cover.xml": empty})
        assert parse_upload(data, "with-cover.xlsx") == EXPECTED

    def test_every_tab_empty_says_so(self):
        data = rewrite(
            build_xlsx([[("A1", "")]]),
        )
        with pytest.raises(UnreadableUpload, match="empty"):
            parse_upload(data, "blank.xlsx")


class FakeCell(SimpleNamespace):
    pass


class FakeSheet:
    def __init__(self, rows):
        self.rows = rows
        self.nrows = len(rows)
        self.ncols = max((len(r) for r in rows), default=0)

    def cell(self, r, c):
        row = self.rows[r]
        return row[c] if c < len(row) else FakeCell(ctype=0, value="")


class TestOldExcelFiles:
    @pytest.fixture
    def fake_xlrd(self, monkeypatch):
        def xldate_as_datetime(value, datemode):
            return datetime(2026, 9, 14) if value == 46279.0 else datetime(2026, 9, 14, 9, 30)

        module = SimpleNamespace(
            XL_CELL_EMPTY=0, XL_CELL_TEXT=1, XL_CELL_NUMBER=2, XL_CELL_DATE=3,
            XL_CELL_BOOLEAN=4, XL_CELL_ERROR=5, XL_CELL_BLANK=6,
            xldate_as_datetime=xldate_as_datetime,
        )
        monkeypatch.setitem(sys.modules, "xlrd", module)
        return module

    def book(self, module, *sheets):
        module.open_workbook = lambda file_contents, on_demand: SimpleNamespace(
            sheets=lambda: [FakeSheet(s) for s in sheets], datemode=0, release_resources=lambda: None,
        )

    def test_an_xls_is_read_with_numbers_dates_and_gaps(self, fake_xlrd):
        text = lambda v: FakeCell(ctype=1, value=v)  # noqa: E731
        self.book(
            fake_xlrd,
            [],  # an empty first sheet
            [
                [text("Company"), FakeCell(ctype=0, value=""), text("Employees"), text("Founded")],
                [text("Meridian Cloud"), FakeCell(ctype=0, value=""), FakeCell(ctype=2, value=250.0),
                 FakeCell(ctype=3, value=46279.0)],
                [FakeCell(ctype=6, value=""), FakeCell(ctype=0, value="")],
            ],
        )
        headers, rows = parse_upload(b"\xd0\xcf\x11\xe0" + b"\0" * 20, "old.xls")
        assert headers == ["Company", "Employees", "Founded"]
        assert rows == [{"Company": "Meridian Cloud", "Employees": "250", "Founded": "2026-09-14"}]

    def test_an_unreadable_xls_says_what_it_is(self, fake_xlrd):
        def broken(file_contents, on_demand):
            raise ValueError("not a BIFF file")

        fake_xlrd.open_workbook = broken
        with pytest.raises(UnreadableUpload, match="old Excel file"):
            parse_upload(b"\xd0\xcf\x11\xe0junk", "old.xls")
