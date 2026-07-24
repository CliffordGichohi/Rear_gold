from datetime import UTC, date, datetime
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import httpx
import pytest

from gold_intel.providers.atlanta_fed_mpt import (
    AtlantaFedMptProvider,
    parse_atlanta_fed_mpt_workbook,
)


def _workbook(*, licensed: bool = True) -> bytes:
    values = [
        "date",
        "reference_start",
        "target_range",
        "field",
        "value",
        "2026-07-02",
        "350bps - 375bps",
        "Rate: 25th percentile",
        "350.00",
        "Rate: mean",
        "375.00",
        "Rate: mode",
        "370.00",
        "Rate: 75th percentile",
        "400.00",
        "Prob: cut",
        "25.00",
        "Prob: hike",
        "50.00",
        "Prob: 325bps - 350bps",
        "25.00",
        "Prob: 350bps - 375bps",
        "25.00",
        "Prob: 375bps - 400bps",
        "25.00",
        "Prob: 400bps - 425bps",
        "25.00",
    ]
    index = {value: position for position, value in enumerate(values)}
    shared = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        + "".join(f"<si><t>{value}</t></si>" for value in values)
        + "</sst>"
    )
    rows = [
        ("2026-07-02", "Rate: 25th percentile", "350.00"),
        ("2026-07-02", "Rate: mean", "375.00"),
        ("2026-07-02", "Rate: mode", "370.00"),
        ("2026-07-02", "Rate: 75th percentile", "400.00"),
        ("2026-07-02", "Prob: cut", "25.00"),
        ("2026-07-02", "Prob: hike", "50.00"),
        ("2026-07-02", "Prob: 325bps - 350bps", "25.00"),
        ("2026-07-02", "Prob: 350bps - 375bps", "25.00"),
        ("2026-07-02", "Prob: 375bps - 400bps", "25.00"),
        ("2026-07-02", "Prob: 400bps - 425bps", "25.00"),
    ]
    header = "".join(
        f'<c r="{column}1" t="s"><v>{index[value]}</v></c>'
        for column, value in zip("ABCDE", values[:5], strict=True)
    )
    data_rows = []
    for number, (observation_date, field, value) in enumerate(rows, start=2):
        cells = (
            f'<c r="A{number}" t="s"><v>{index[observation_date]}</v></c>'
            f'<c r="B{number}" t="n"><v>46266</v></c>'
            f'<c r="C{number}" t="s"><v>{index["350bps - 375bps"]}</v></c>'
            f'<c r="D{number}" t="s"><v>{index[field]}</v></c>'
            f'<c r="E{number}" t="s"><v>{index[value]}</v></c>'
        )
        data_rows.append(f'<row r="{number}">{cells}</row>')
    sheet = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData><row r="1">{header}</row>{"".join(data_rows)}</sheetData>'
        "</worksheet>"
    )
    license_text = (
        "Use of this data is permitted for personal and educational purposes only. "
        "CME GROUP MARKET DATA IS USED UNDER PERMISSION"
        if licensed
        else "terms changed"
    )
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "xl/workbook.xml",
            (
                '<?xml version="1.0"?>'
                '<workbook xmlns="http://schemas.openxmlformats.org/'
                'spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/'
                'officeDocument/2006/relationships"><sheets>'
                '<sheet name="DATA" sheetId="1" r:id="rId1"/>'
                "</sheets></workbook>"
            ),
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            (
                '<?xml version="1.0"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/'
                'package/2006/relationships">'
                '<Relationship Id="rId1" Target="worksheets/sheet3.xml"/>'
                "</Relationships>"
            ),
        )
        archive.writestr("xl/sharedStrings.xml", shared)
        archive.writestr("xl/worksheets/sheet3.xml", sheet)
        archive.writestr(
            "xl/drawings/drawing1.xml",
            f"<drawing>{license_text}</drawing>",
        )
    return output.getvalue()


def test_official_workbook_is_parsed_with_conservative_availability() -> None:
    windows = parse_atlanta_fed_mpt_workbook(_workbook())

    assert len(windows) == 1
    window = windows[0]
    assert window.observation_date == date(2026, 7, 2)
    assert window.reference_start == date(2026, 9, 1)
    assert window.reference_end == date(2026, 11, 30)
    assert window.rate_mean_basis_points == 375
    assert window.probability_cut == 0.25
    assert window.distribution_probability_sum == 1
    # Friday 3 July is the observed Independence Day holiday in 2026.
    assert window.available_at == datetime.max.replace(
        year=2026,
        month=7,
        day=6,
        tzinfo=UTC,
    )


def test_workbook_terms_change_fails_closed() -> None:
    with pytest.raises(ValueError, match="license text"):
        parse_atlanta_fed_mpt_workbook(_workbook(licensed=False))


async def test_provider_uses_the_explicit_download_not_a_scraped_page() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/mpt_histdata.xlsx")
        return httpx.Response(
            200,
            content=_workbook(),
            headers={"etag": '"fixture"'},
        )

    dataset = await AtlantaFedMptProvider(
        transport=httpx.MockTransport(handler),
    ).fetch(retrieved_at=datetime(2026, 7, 7, tzinfo=UTC))

    assert dataset.observation_count == 1
    assert dataset.license_class == "PERSONAL_EDUCATIONAL_ONLY"
    assert dataset.source_etag == '"fixture"'
