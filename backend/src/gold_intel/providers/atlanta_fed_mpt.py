from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from io import BytesIO
from pathlib import PurePosixPath
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

ATLANTA_FED_MPT_HISTORY_URL = (
    "https://www.atlantafed.org/-/media/Project/Atlanta/FRBA/Documents/"
    "cenfis/market-probability-tracker/mpt_histdata.xlsx"
)
ATLANTA_FED_MPT_PROVIDER_CODE = "ATLANTA_FED_MPT"
ATLANTA_FED_MPT_DATASET_CODE = "QUARTERLY_SOFR_DISTRIBUTIONS"
ATLANTA_FED_MPT_LICENSE_CLASS = "PERSONAL_EDUCATIONAL_ONLY"
ATLANTA_FED_MPT_AVAILABILITY_QUALITY = "CONSERVATIVE_NEXT_US_BUSINESS_DAY_END"

_SPREADSHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_DOCUMENT_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_CELL_REF = re.compile(r"^([A-Z]+)[0-9]+$")
_TARGET_RANGE = re.compile(r"^\s*(-?\d+)bps\s*-\s*(-?\d+)bps\s*$")
_PROBABILITY_BIN = re.compile(r"^Prob:\s*(-?\d+)bps\s*-\s*(-?\d+)bps$")
_REQUIRED_HEADERS = ("date", "reference_start", "target_range", "field", "value")
_RATE_FIELDS = {
    "Rate: 25th percentile": "rate_p25_basis_points",
    "Rate: mean": "rate_mean_basis_points",
    "Rate: mode": "rate_mode_basis_points",
    "Rate: 75th percentile": "rate_p75_basis_points",
}


@dataclass(frozen=True, slots=True)
class AtlantaFedMptProbabilityBin:
    lower_basis_points: int
    upper_basis_points: int
    probability: float


@dataclass(frozen=True, slots=True)
class AtlantaFedMptWindow:
    observation_date: date
    snapshot_as_of: datetime
    available_at: datetime
    reference_start: date
    reference_end: date
    target_lower_basis_points: int
    target_upper_basis_points: int
    rate_p25_basis_points: float
    rate_mean_basis_points: float
    rate_mode_basis_points: float
    rate_p75_basis_points: float
    probability_cut: float | None
    probability_hike: float | None
    probability_bins: tuple[AtlantaFedMptProbabilityBin, ...]
    distribution_probability_sum: float | None
    source_record_key: str


@dataclass(frozen=True, slots=True)
class AtlantaFedMptDataset:
    retrieved_at: datetime
    source_url: str
    source_sha256: str
    source_etag: str | None
    source_last_modified: str | None
    license_class: str
    availability_quality: str
    workbook_bytes: bytes
    windows: tuple[AtlantaFedMptWindow, ...]

    @property
    def earliest_observation_date(self) -> date:
        return min(window.observation_date for window in self.windows)

    @property
    def latest_observation_date(self) -> date:
        return max(window.observation_date for window in self.windows)

    @property
    def observation_count(self) -> int:
        return len({window.observation_date for window in self.windows})


@dataclass(slots=True)
class _MutableWindow:
    observation_date: date
    reference_start: date
    target_lower_basis_points: int
    target_upper_basis_points: int
    rate_p25_basis_points: float | None = None
    rate_mean_basis_points: float | None = None
    rate_mode_basis_points: float | None = None
    rate_p75_basis_points: float | None = None
    probability_cut: float | None = None
    probability_hike: float | None = None
    probability_bins: list[AtlantaFedMptProbabilityBin] | None = None


class AtlantaFedMptProvider:
    """Official Atlanta Fed historical Market Probability Tracker adapter.

    This adapter downloads the historical workbook through the explicit link
    published by the Atlanta Fed. It does not scrape page markup or call an
    undocumented website endpoint.
    """

    def __init__(
        self,
        *,
        timeout_seconds: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
        history_url: str = ATLANTA_FED_MPT_HISTORY_URL,
    ) -> None:
        self._timeout = httpx.Timeout(timeout_seconds, connect=15.0)
        self._transport = transport
        self._history_url = history_url

    @retry(
        retry=retry_if_exception_type(httpx.HTTPError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        reraise=True,
    )
    async def fetch(
        self,
        *,
        retrieved_at: datetime | None = None,
    ) -> AtlantaFedMptDataset:
        retrieval_clock = (retrieved_at or datetime.now(UTC)).astimezone(UTC)
        async with httpx.AsyncClient(
            timeout=self._timeout,
            follow_redirects=True,
            transport=self._transport,
        ) as client:
            response = await client.get(
                self._history_url,
                headers={
                    "Accept": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                    "User-Agent": "gold-market-intelligence-engine/0.1.0",
                },
            )
            response.raise_for_status()
        workbook = response.content
        windows = parse_atlanta_fed_mpt_workbook(workbook)
        return AtlantaFedMptDataset(
            retrieved_at=retrieval_clock,
            source_url=self._history_url,
            source_sha256=hashlib.sha256(workbook).hexdigest(),
            source_etag=response.headers.get("etag"),
            source_last_modified=response.headers.get("last-modified"),
            license_class=ATLANTA_FED_MPT_LICENSE_CLASS,
            availability_quality=ATLANTA_FED_MPT_AVAILABILITY_QUALITY,
            workbook_bytes=workbook,
            windows=windows,
        )


def parse_atlanta_fed_mpt_workbook(
    workbook: bytes,
) -> tuple[AtlantaFedMptWindow, ...]:
    """Parse and validate the official historical workbook without Excel."""

    if not workbook:
        raise ValueError("Atlanta Fed MPT workbook is empty.")
    try:
        with ZipFile(BytesIO(workbook)) as archive:
            _validate_workbook_license(archive)
            shared_strings = _read_shared_strings(archive)
            data_sheet_path = _data_sheet_path(archive)
            rows = _read_data_rows(
                archive,
                data_sheet_path=data_sheet_path,
                shared_strings=shared_strings,
            )
    except (BadZipFile, ElementTree.ParseError, KeyError) as exc:
        raise ValueError("Atlanta Fed MPT response is not a valid historical workbook.") from exc

    groups: dict[tuple[date, date], _MutableWindow] = {}
    for row_number, row in rows:
        try:
            observation_date = date.fromisoformat(row["date"].strip())
            reference_start = _excel_date(row["reference_start"])
            target_lower, target_upper = _basis_point_range(row["target_range"])
            field = row["field"].strip()
            value = float(row["value"].strip())
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Invalid Atlanta Fed MPT DATA row {row_number}.") from exc
        if not value == value or value in {float("inf"), float("-inf")}:
            raise ValueError(f"Atlanta Fed MPT DATA row {row_number} has a non-finite value.")

        key = (observation_date, reference_start)
        group = groups.get(key)
        if group is None:
            group = _MutableWindow(
                observation_date=observation_date,
                reference_start=reference_start,
                target_lower_basis_points=target_lower,
                target_upper_basis_points=target_upper,
                probability_bins=[],
            )
            groups[key] = group
        elif (
            group.target_lower_basis_points != target_lower
            or group.target_upper_basis_points != target_upper
        ):
            raise ValueError(
                "Atlanta Fed MPT target range changed within one observation/reference window."
            )

        if field in _RATE_FIELDS:
            attribute = _RATE_FIELDS[field]
            if getattr(group, attribute) is not None:
                raise ValueError(f"Duplicate Atlanta Fed MPT metric at DATA row {row_number}.")
            setattr(group, attribute, value)
            continue
        if field == "Prob: cut":
            group.probability_cut = _percent_probability(value, row_number)
            continue
        if field == "Prob: hike":
            group.probability_hike = _percent_probability(value, row_number)
            continue
        bin_match = _PROBABILITY_BIN.fullmatch(field)
        if bin_match is None:
            raise ValueError(f"Unsupported Atlanta Fed MPT field {field!r}.")
        lower, upper = (int(item) for item in bin_match.groups())
        if upper <= lower:
            raise ValueError(f"Invalid Atlanta Fed MPT probability bin at DATA row {row_number}.")
        if group.probability_bins is None:
            group.probability_bins = []
        if any(
            item.lower_basis_points == lower and item.upper_basis_points == upper
            for item in group.probability_bins
        ):
            raise ValueError(f"Duplicate Atlanta Fed MPT probability bin at row {row_number}.")
        group.probability_bins.append(
            AtlantaFedMptProbabilityBin(
                lower_basis_points=lower,
                upper_basis_points=upper,
                probability=_percent_probability(value, row_number),
            )
        )

    if not groups:
        raise ValueError("Atlanta Fed MPT workbook contains no DATA records.")

    windows: list[AtlantaFedMptWindow] = []
    for group in sorted(
        groups.values(),
        key=lambda item: (item.observation_date, item.reference_start),
    ):
        required_rates = (
            group.rate_p25_basis_points,
            group.rate_mean_basis_points,
            group.rate_mode_basis_points,
            group.rate_p75_basis_points,
        )
        if any(value is None for value in required_rates):
            raise ValueError(
                "Atlanta Fed MPT window lacks one or more required rate-distribution metrics: "
                f"{group.observation_date}/{group.reference_start}."
            )
        assert group.rate_p25_basis_points is not None
        assert group.rate_mean_basis_points is not None
        assert group.rate_mode_basis_points is not None
        assert group.rate_p75_basis_points is not None
        bins = tuple(
            sorted(
                group.probability_bins or [],
                key=lambda item: (item.lower_basis_points, item.upper_basis_points),
            )
        )
        probability_sum = sum(item.probability for item in bins) if bins else None
        if probability_sum is not None and not 0.95 <= probability_sum <= 1.01:
            raise ValueError(
                "Atlanta Fed MPT reported probability bins outside the accepted mass range "
                f"for {group.observation_date}/{group.reference_start}: {probability_sum:.6f}."
            )
        snapshot_as_of = datetime.combine(group.observation_date, time.max, UTC)
        windows.append(
            AtlantaFedMptWindow(
                observation_date=group.observation_date,
                snapshot_as_of=snapshot_as_of,
                available_at=_conservative_available_at(group.observation_date),
                reference_start=group.reference_start,
                reference_end=_add_months(group.reference_start, 3) - timedelta(days=1),
                target_lower_basis_points=group.target_lower_basis_points,
                target_upper_basis_points=group.target_upper_basis_points,
                rate_p25_basis_points=float(group.rate_p25_basis_points),
                rate_mean_basis_points=float(group.rate_mean_basis_points),
                rate_mode_basis_points=float(group.rate_mode_basis_points),
                rate_p75_basis_points=float(group.rate_p75_basis_points),
                probability_cut=group.probability_cut,
                probability_hike=group.probability_hike,
                probability_bins=bins,
                distribution_probability_sum=probability_sum,
                source_record_key=(
                    f"MPT:{group.observation_date.isoformat()}:{group.reference_start.isoformat()}"
                ),
            )
        )
    return tuple(windows)


def _validate_workbook_license(archive: ZipFile) -> None:
    drawing_text = " ".join(
        archive.read(name).decode("utf-8", errors="replace")
        for name in archive.namelist()
        if name.startswith("xl/drawings/") and name.endswith(".xml")
    )
    required = (
        "personal and educational purposes only",
        "CME GROUP MARKET DATA IS USED UNDER PERMISSION",
    )
    if not all(phrase in drawing_text for phrase in required):
        raise ValueError(
            "Atlanta Fed MPT workbook license text is missing or changed; ingestion "
            "is stopped pending terms review."
        )


def _read_shared_strings(archive: ZipFile) -> tuple[str, ...]:
    try:
        root = ElementTree.parse(archive.open("xl/sharedStrings.xml")).getroot()
    except KeyError:
        return ()
    return tuple(
        "".join(node.text or "" for node in item.iter(f"{{{_SPREADSHEET_NS}}}t"))
        for item in root.findall(f"{{{_SPREADSHEET_NS}}}si")
    )


def _data_sheet_path(archive: ZipFile) -> str:
    workbook = ElementTree.parse(archive.open("xl/workbook.xml")).getroot()
    relations = ElementTree.parse(archive.open("xl/_rels/workbook.xml.rels")).getroot()
    targets = {
        relation.attrib["Id"]: relation.attrib["Target"]
        for relation in relations.findall(f"{{{_PACKAGE_REL_NS}}}Relationship")
    }
    sheets = workbook.find(f"{{{_SPREADSHEET_NS}}}sheets")
    if sheets is None:
        raise ValueError("Atlanta Fed MPT workbook has no sheets.")
    for sheet in sheets.findall(f"{{{_SPREADSHEET_NS}}}sheet"):
        if sheet.attrib.get("name") != "DATA":
            continue
        relation_id = sheet.attrib.get(f"{{{_DOCUMENT_REL_NS}}}id")
        if relation_id is None or relation_id not in targets:
            break
        return str(PurePosixPath("xl") / targets[relation_id])
    raise ValueError("Atlanta Fed MPT workbook has no DATA sheet.")


def _read_data_rows(
    archive: ZipFile,
    *,
    data_sheet_path: str,
    shared_strings: tuple[str, ...],
) -> list[tuple[int, dict[str, str]]]:
    rows: list[tuple[int, dict[str, str]]] = []
    headers: dict[str, str] | None = None
    with archive.open(data_sheet_path) as stream:
        for _, element in ElementTree.iterparse(stream, events=("end",)):
            if element.tag != f"{{{_SPREADSHEET_NS}}}row":
                continue
            row_number = int(element.attrib.get("r", "0"))
            cells: dict[str, str] = {}
            for cell in element.findall(f"{{{_SPREADSHEET_NS}}}c"):
                reference = cell.attrib.get("r", "")
                match = _CELL_REF.fullmatch(reference)
                if match is None:
                    continue
                column = match.group(1)
                value_node = cell.find(f"{{{_SPREADSHEET_NS}}}v")
                if value_node is None:
                    cells[column] = ""
                    continue
                raw_value = value_node.text or ""
                if cell.attrib.get("t") == "s":
                    try:
                        cells[column] = shared_strings[int(raw_value)]
                    except (IndexError, ValueError) as exc:
                        raise ValueError(
                            f"Invalid shared-string index in DATA row {row_number}."
                        ) from exc
                else:
                    cells[column] = raw_value
            if headers is None:
                ordered_headers = tuple(
                    cells.get(column, "") for column in ("A", "B", "C", "D", "E")
                )
                if ordered_headers != _REQUIRED_HEADERS:
                    raise ValueError(
                        "Atlanta Fed MPT DATA headers changed: " + repr(ordered_headers)
                    )
                headers = {
                    column: header
                    for column, header in zip(
                        ("A", "B", "C", "D", "E"),
                        _REQUIRED_HEADERS,
                        strict=True,
                    )
                }
            elif any(cells.get(column, "") for column in headers):
                rows.append(
                    (
                        row_number,
                        {header: cells.get(column, "") for column, header in headers.items()},
                    )
                )
            element.clear()
    if headers is None:
        raise ValueError("Atlanta Fed MPT DATA sheet is empty.")
    return rows


def _excel_date(value: str) -> date:
    serial = float(value)
    if serial != int(serial):
        raise ValueError("reference_start must be an Excel whole-day serial")
    parsed = date(1899, 12, 30) + timedelta(days=int(serial))
    if not 2000 <= parsed.year <= 2100:
        raise ValueError("reference_start is outside the supported range")
    return parsed


def _basis_point_range(value: str) -> tuple[int, int]:
    match = _TARGET_RANGE.fullmatch(value)
    if match is None:
        raise ValueError("target_range is not a basis-point range")
    lower, upper = (int(item) for item in match.groups())
    if upper < lower:
        raise ValueError("target_range upper bound precedes lower bound")
    return lower, upper


def _percent_probability(value: float, row_number: int) -> float:
    if not 0 <= value <= 100:
        raise ValueError(f"Probability outside 0-100 percent at DATA row {row_number}.")
    return value / 100


def _add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, value.day)


def _conservative_available_at(observation_date: date) -> datetime:
    candidate = observation_date + timedelta(days=1)
    while candidate.weekday() >= 5 or candidate in _us_federal_holidays(candidate.year):
        candidate += timedelta(days=1)
    return datetime.combine(candidate, time.max, UTC)


def _us_federal_holidays(year: int) -> set[date]:
    holidays = {
        _observed(date(year, 1, 1)),
        _nth_weekday(year, 1, 0, 3),
        _nth_weekday(year, 2, 0, 3),
        _last_weekday(year, 5, 0),
        _observed(date(year, 6, 19)),
        _observed(date(year, 7, 4)),
        _nth_weekday(year, 9, 0, 1),
        _nth_weekday(year, 10, 0, 2),
        _observed(date(year, 11, 11)),
        _nth_weekday(year, 11, 3, 4),
        _observed(date(year, 12, 25)),
    }
    # A New Year's Day falling on Saturday is observed in the prior year.
    next_new_year = _observed(date(year + 1, 1, 1))
    if next_new_year.year == year:
        holidays.add(next_new_year)
    return holidays


def _observed(value: date) -> date:
    if value.weekday() == 5:
        return value - timedelta(days=1)
    if value.weekday() == 6:
        return value + timedelta(days=1)
    return value


def _nth_weekday(year: int, month: int, weekday: int, occurrence: int) -> date:
    candidate = date(year, month, 1)
    candidate += timedelta(days=(weekday - candidate.weekday()) % 7)
    return candidate + timedelta(weeks=occurrence - 1)


def _last_weekday(year: int, month: int, weekday: int) -> date:
    candidate = _add_months(date(year, month, 1), 1) - timedelta(days=1)
    return candidate - timedelta(days=(candidate.weekday() - weekday) % 7)
