from __future__ import annotations

import argparse
import re
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

        return ShrMessage(
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


class ShrParser:
    def __init__(self, excel_path: Path | str, sheet_names: Optional[Iterable[str]] = None):
        self.excel_path = Path(excel_path)
        self.sheet_names = list(sheet_names) if sheet_names is not None else None
        self._message_parser = ShrMessageParser()

    def parse(self) -> List[ShrRecord]:
        records: List[ShrRecord] = []
        for sheet in self._iter_target_sheets():
            records.extend(self.parse_sheet(sheet))
        return records

    def parse_sheet(self, sheet: str) -> List[ShrRecord]:
        df = pd.read_excel(self.excel_path, sheet_name=sheet, skiprows=1)
        records: List[ShrRecord] = []
        for idx, row in df.iterrows():
            raw_message = row.get("Сообщение SHR")
            if not isinstance(raw_message, str) or not raw_message.strip():
                continue
            message = self._message_parser.parse(raw_message)
            flight_date = row.get("Дата полёта")
            records.append(
                ShrRecord(
                    sheet=sheet,
                    row_index=int(idx),
                    flight_date=flight_date,
                    message=message,
                )
            )
        return records

    def parse_as_dataframe(self, flatten_fields: bool = True) -> pd.DataFrame:
        records = [record.to_dict(flatten_fields=flatten_fields) for record in self.parse()]
        return pd.DataFrame(records)

    def _iter_target_sheets(self) -> List[str]:
        if self.sheet_names is not None:
            return self.sheet_names
        excel_file = pd.ExcelFile(self.excel_path)
        return excel_file.sheet_names


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
        "--limit",
        type=int,
        help="Limit printed records for quick inspection.",
    )
    args = parser.parse_args(argv)

    shr_parser = ShrParser(args.excel_path, sheet_names=args.sheet)
    records = shr_parser.parse()
    if args.limit is not None:
        records = records[: args.limit]
    for record in records:
        print(record.to_dict(flatten_fields=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
