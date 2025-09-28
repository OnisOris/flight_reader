from __future__ import annotations

import argparse
import re
from abc import ABC, abstractmethod
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

import pandas as pd


@dataclass
class ShrMessage:
    message_type: str
    addressee: Optional[str]
    valid_from: Optional[str]
    valid_to: Optional[str]
    extra_time_codes: List[str] = field(default_factory=list)
    route_segments: List[str] = field(default_factory=list)
    fields: Dict[str, List[str]] = field(default_factory=dict)
    unparsed_segments: List[str] = field(default_factory=list)
    raw: str = ""

    def to_dict(self, flatten_fields: bool = False) -> Dict[str, object]:
        data: Dict[str, object] = {
            "message_type": self.message_type,
            "addressee": self.addressee,
            "valid_from": self.valid_from,
            "valid_to": self.valid_to,
            "extra_time_codes": list(self.extra_time_codes),
            "route_segments": list(self.route_segments),
            "raw": self.raw,
        }
        if self.unparsed_segments:
            data["unparsed_segments"] = list(self.unparsed_segments)
        if flatten_fields:
            flat_fields = {
                key: values[0] if len(values) == 1 else list(values)
                for key, values in self.fields.items()
            }
            data.update(flat_fields)
        else:
            data["fields"] = {key: list(values) for key, values in self.fields.items()}
        return data


@dataclass
class ShrRecord:
    sheet: str
    row_index: int
    flight_date: Optional[pd.Timestamp]
    message: ShrMessage

    def to_dict(self, flatten_fields: bool = False) -> Dict[str, object]:
        data = {
            "sheet": self.sheet,
            "row_index": self.row_index,
            "flight_date": self._format_date(),
        }
        data.update(self.message.to_dict(flatten_fields=flatten_fields))
        return data

    def _format_date(self) -> Optional[str]:
        if self.flight_date is None or pd.isna(self.flight_date):
            return None
        if isinstance(self.flight_date, pd.Timestamp):
            return self.flight_date.date().isoformat()
        return str(self.flight_date)


@dataclass
class ConnectorRow:
    row_index: int
    flight_date: Optional[pd.Timestamp]
    message_text: str


class BaseShrConnector(ABC):
    def __init__(
        self,
        excel_path: Path,
        excel_file: pd.ExcelFile,
        sheet_names: Optional[Iterable[str]] = None,
    ) -> None:
        self.excel_path = Path(excel_path)
        self._excel_file = excel_file
        self._sheet_names = list(sheet_names) if sheet_names is not None else None

    def iter_target_sheets(self) -> List[str]:
        if self._sheet_names is not None:
            return list(self._sheet_names)
        return list(self._excel_file.sheet_names)

    @abstractmethod
    def iter_rows(self, sheet: str) -> Iterable[ConnectorRow]:
        """Yield normalized rows for the target sheet."""


class Standard2025Connector(BaseShrConnector):
    def iter_rows(self, sheet: str) -> Iterable[ConnectorRow]:
        df = pd.read_excel(self._excel_file, sheet_name=sheet)
        column_map = {str(col).strip().lower(): col for col in df.columns}
        shr_column = column_map.get("shr")
        if shr_column is None:
            return []
        rows: List[ConnectorRow] = []
        for idx, row in df.iterrows():
            raw_message = row.get(shr_column)
            if isinstance(raw_message, str):
                cleaned = raw_message.strip()
                if cleaned:
                    rows.append(
                        ConnectorRow(
                            row_index=int(idx),
                            flight_date=None,
                            message_text=cleaned,
                        )
                    )
        return rows


class Standard2024Connector(BaseShrConnector):
    NOTES_KEY = "примечания"
    ROUTE_KEY = "маршрут"
    FLIGHT_KEY = "рейс"
    BOARD_KEY = "борт"
    DEP_TIME_KEY = "т выл. факт"
    ARR_TIME_KEY = "т пос. факт"
    DATE_KEYS = ("дата полёта", "дата")

    def iter_rows(self, sheet: str) -> Iterable[ConnectorRow]:
        df = pd.read_excel(self._excel_file, sheet_name=sheet, skiprows=1)
        column_map = {str(col).strip().lower(): col for col in df.columns}
        notes_column = column_map.get(self.NOTES_KEY)
        if notes_column is None:
            return []

        rows: List[ConnectorRow] = []
        for idx, row in df.iterrows():
            message = self._build_message(row, column_map)
            if not message:
                continue
            flight_date = self._resolve_date(row, column_map)
            rows.append(
                ConnectorRow(
                    row_index=int(idx),
                    flight_date=flight_date,
                    message_text=message,
                )
            )
        return rows

    def _build_message(self, row: pd.Series, column_map: Dict[str, str]) -> str:
        notes = self._get_cell(row, column_map.get(self.NOTES_KEY))
        if not notes:
            return ""

        addressee = self._choose_identifier(row, column_map)
        segments: List[str] = [f"SHR-{addressee}"]

        dep_time = self._extract_time(row, column_map.get(self.DEP_TIME_KEY))
        if dep_time:
            segments.append(f"-{dep_time}")

        arr_time = self._extract_time(row, column_map.get(self.ARR_TIME_KEY))
        if arr_time:
            segments.append(f"-{arr_time}")

        route = self._get_cell(row, column_map.get(self.ROUTE_KEY))
        if route:
            segments.append(f"-{route}")

        segments.append(f"-{notes}")
        return "\n".join(segments)

    def _get_cell(self, row: pd.Series, column: Optional[str]) -> Optional[str]:
        if not column:
            return None
        value = row.get(column)
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or None
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        text = str(value).strip()
        return text or None

    def _choose_identifier(self, row: pd.Series, column_map: Dict[str, str]) -> str:
        for key in (self.FLIGHT_KEY, self.BOARD_KEY):
            candidate = self._get_cell(row, column_map.get(key))
            if candidate:
                return candidate
        return "ZZZZZ"

    def _extract_time(self, row: pd.Series, column: Optional[str]) -> Optional[str]:
        value = self._get_cell(row, column)
        if not value:
            return None
        match = re.search(r"(\d{1,2})[:.](\d{2})", value)
        if match:
            hours, minutes = match.groups()
            return f"ZZZZ{hours.zfill(2)}{minutes}"
        digits_only = re.sub(r"\D", "", value)
        if len(digits_only) == 4:
            return f"ZZZZ{digits_only}"
        return None

    def _resolve_date(self, row: pd.Series, column_map: Dict[str, str]) -> Optional[pd.Timestamp]:
        for key in self.DATE_KEYS:
            column = column_map.get(key)
            if not column:
                continue
            value = row.get(column)
            if isinstance(value, pd.Timestamp):
                return value
            if value is None or (isinstance(value, float) and pd.isna(value)):
                continue
            try:
                if isinstance(value, (int, float)):
                    converted = pd.to_datetime(value, origin="1899-12-30", unit="D", errors="coerce")
                else:
                    converted = pd.to_datetime(value, dayfirst=True, errors="coerce")
            except (ValueError, TypeError):
                converted = None
            if converted is not None and not pd.isna(converted):
                return converted
        return None


_DIGIT_TO_CYRILLIC = {
    "0": "О",
    "3": "З",
    "4": "Ч",
    "6": "Б",
    "8": "В",
}

_CYRILLIC_WORD_RE = re.compile(r"[\u0400-\u04FF0-9]+")


def _contains_cyrillic(text: str) -> bool:
    return any("\u0400" <= char <= "\u04FF" for char in text)


def _clean_cyrillic_digits(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        word = match.group(0)
        if not any(char.isdigit() for char in word):
            return word
        if not _contains_cyrillic(word):
            return word
        return "".join(_DIGIT_TO_CYRILLIC.get(char, char) for char in word)

    return _CYRILLIC_WORD_RE.sub(repl, text)


def _normalize_optional_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    normalized = _clean_cyrillic_digits(value)
    return normalized if normalized else value


def _read_columns(excel_file: pd.ExcelFile, sheet: str, *, skiprows: int = 0) -> List[str]:
    try:
        df = pd.read_excel(excel_file, sheet_name=sheet, nrows=0, skiprows=skiprows)
    except ValueError:
        return []
    return [str(column).strip().lower() for column in df.columns if isinstance(column, str)]


def _detect_standard(excel_file: pd.ExcelFile, sheet_names: Optional[Iterable[str]]) -> str:
    candidate_sheets = list(sheet_names) if sheet_names is not None else list(excel_file.sheet_names)
    for sheet in candidate_sheets:
        columns = set(_read_columns(excel_file, sheet))
        if {"shr", "dep", "arr"}.issubset(columns):
            return "2025"
        columns_skip = set(_read_columns(excel_file, sheet, skiprows=1))
        if "примечания" in columns_skip:
            return "2024"
    return "2025"


def _normalize_standard_name(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    name = value.strip().lower()
    if name in {"2024", "v2024", "standard-2024"}:
        return "2024"
    if name in {"2025", "v2025", "standard-2025"}:
        return "2025"
    return None


class ShrMessageParser:
    FIELD_KEY_PATTERN = re.compile(r"(?<![A-Z0-9])([A-Z]{2,})(?=/)")
    TIME_PATTERN = re.compile(r"^[A-Z]{4}\d{4}$")
    ROUTE_PATTERN = re.compile(r"^M[A-Z0-9/ ]+", re.IGNORECASE)

    def parse(self, raw_message: str) -> ShrMessage:
        cleaned = self._strip_wrapping(raw_message)
        segments = self._split_segments(cleaned)
        if not segments:
            return ShrMessage(
                message_type="",
                addressee=None,
                valid_from=None,
                valid_to=None,
                raw=cleaned,
            )

        message_type, addressee = self._parse_header(segments[0])
        valid_from: Optional[str] = None
        valid_to: Optional[str] = None
        extra_time_codes: List[str] = []
        route_segments: List[str] = []
        field_segments: List[str] = []
        unparsed_segments: List[str] = []

        for segment in segments[1:]:
            if self.TIME_PATTERN.fullmatch(segment):
                if valid_from is None:
                    valid_from = segment
                elif valid_to is None:
                    valid_to = segment
                else:
                    extra_time_codes.append(segment)
                continue
            if self.ROUTE_PATTERN.match(segment):
                route_segments.append(segment)
                continue
            if self.FIELD_KEY_PATTERN.search(segment):
                field_segments.append(segment)
                continue
            unparsed_segments.append(segment)

        fields = self._collect_fields(field_segments)

        message = ShrMessage(
            message_type=message_type,
            addressee=addressee,
            valid_from=valid_from,
            valid_to=valid_to,
            extra_time_codes=extra_time_codes,
            route_segments=route_segments,
            fields=fields,
            unparsed_segments=unparsed_segments,
            raw=cleaned,
        )
        return self._normalize_message(message)

    def _strip_wrapping(self, raw: str) -> str:
        text = raw.strip()
        if text.startswith("(") and text.endswith(")"):
            text = text[1:-1]
        return text

    def _split_segments(self, text: str) -> List[str]:
        segments: List[str] = []
        current: Optional[str] = None
        for raw_line in text.split("\n"):
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("-"):
                if current is not None:
                    segments.append(current)
                current = line[1:].strip()
            else:
                if current is None:
                    current = line
                else:
                    current = f"{current} {line}".strip()
        if current is not None:
            segments.append(current)
        return segments

    def _parse_header(self, segment: str) -> tuple[str, Optional[str]]:
        parts = [part for part in segment.split("-") if part]
        message_type = parts[0] if parts else ""
        addressee = "-".join(parts[1:]) if len(parts) > 1 else None
        return message_type, addressee

    def _collect_fields(self, segments: List[str]) -> OrderedDict[str, List[str]]:
        fields: OrderedDict[str, List[str]] = OrderedDict()
        for segment in segments:
            for key, value in self._extract_pairs(segment):
                fields.setdefault(key, []).append(value)
        return fields

    def _extract_pairs(self, segment: str) -> List[tuple[str, str]]:
        matches = list(self.FIELD_KEY_PATTERN.finditer(segment))
        pairs: List[tuple[str, str]] = []
        for idx, match in enumerate(matches):
            key = match.group(1)
            value_start = match.end() + 1
            value_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(segment)
            value = segment[value_start:value_end].strip()
            if value:
                pairs.append((key, value))
        return pairs

    def _normalize_message(self, message: ShrMessage) -> ShrMessage:
        message.addressee = _normalize_optional_text(message.addressee)
        message.route_segments = [_clean_cyrillic_digits(segment) for segment in message.route_segments]
        normalized_fields: OrderedDict[str, List[str]] = OrderedDict()
        for key, values in message.fields.items():
            normalized_fields[key] = [_clean_cyrillic_digits(value) for value in values]
        message.fields = normalized_fields
        message.unparsed_segments = [_clean_cyrillic_digits(segment) for segment in message.unparsed_segments]
        return message


class ShrParser:
    def __init__(
        self,
        excel_path: Path | str,
        sheet_names: Optional[Iterable[str]] = None,
        standard: Optional[str] = None,
    ) -> None:
        self.excel_path = Path(excel_path)
        self.sheet_names = list(sheet_names) if sheet_names is not None else None
        self._excel_file = pd.ExcelFile(self.excel_path)
        normalized_standard = _normalize_standard_name(standard)
        detected_standard = normalized_standard or _detect_standard(self._excel_file, self.sheet_names)
        if detected_standard == "2024":
            self._connector: BaseShrConnector = Standard2024Connector(
                self.excel_path,
                self._excel_file,
                sheet_names=self.sheet_names,
            )
        else:
            self._connector = Standard2025Connector(
                self.excel_path,
                self._excel_file,
                sheet_names=self.sheet_names,
            )
        self._message_parser = ShrMessageParser()

    def parse(self) -> List[ShrRecord]:
        records: List[ShrRecord] = []
        for sheet in self._connector.iter_target_sheets():
            records.extend(self.parse_sheet(sheet))
        return records

    def parse_sheet(self, sheet: str) -> List[ShrRecord]:
        records: List[ShrRecord] = []
        for connector_row in self._connector.iter_rows(sheet):
            message = self._message_parser.parse(connector_row.message_text)
            records.append(
                ShrRecord(
                    sheet=sheet,
                    row_index=connector_row.row_index,
                    flight_date=connector_row.flight_date,
                    message=message,
                )
            )
        return records

    def parse_as_dataframe(self, flatten_fields: bool = True) -> pd.DataFrame:
        records = [record.to_dict(flatten_fields=flatten_fields) for record in self.parse()]
        return pd.DataFrame(records)

    def _iter_target_sheets(self) -> List[str]:
        return self._connector.iter_target_sheets()


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Parse SHR messages from an Excel workbook.",
    )
    parser.add_argument("excel_path", type=Path)
    parser.add_argument(
        "--sheet",
        action="append",
        help="Specific sheet name to parse (can be provided multiple times).",
    )
    parser.add_argument(
        "--standard",
        choices=["2024", "2025"],
        help="Force workbook layout standard (defaults to auto-detection).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Limit printed records for quick inspection.",
    )
    args = parser.parse_args(argv)

    shr_parser = ShrParser(args.excel_path, sheet_names=args.sheet, standard=args.standard)
    records = shr_parser.parse()
    if args.limit is not None:
        records = records[: args.limit]
    for record in records:
        print(record.to_dict(flatten_fields=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
