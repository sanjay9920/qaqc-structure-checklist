import argparse
import json
import re
from pathlib import Path

import openpyxl


EXCLUDED_SHEETS = {"Index", "Index-1", "Checklist status", "Sheet2"}

DISPLAY_NAMES = {
    "LA": "Lightning Arrester",
    "ERT": "Earth Resistance Test",
    "IR": "Insulation Resistance",
    "IMP": "Module Performance Test (IMP)",
    "Pre-Fab": "Pre-Fabricated Building",
    "Inverter Pre-Commisioning": "Inverter Pre-Commissioning",
    "IDT-Aux Trafo Pre-Commisioning": "IDT / Auxiliary Transformer Pre-Commissioning",
    "HT Panel Pre-Commisioning": "HT Panel Pre-Commissioning",
    "Battery Charger Commisioning": "Battery Charger Commissioning",
    "Battery Commisioning": "Battery Commissioning",
    "Commisioning Report Scada": "SCADA Commissioning",
    "Commisioning Report ACDB": "ACDB Commissioning",
    "Commisioning Report UPS DB": "UPS DB Commissioning",
    "Survillance System": "Surveillance System",
    "Fire fightening": "Fire Fighting",
    "6 sqmm DC cable": "6 sq mm DC Cable",
    "LV IR": "LV Insulation Resistance",
}

FORMAT_OVERRIDES = {
    "6 sqmm DC cable": "CH-LP-EL-003/00",
    "Trench": "Not specified",
}

POINT_OVERRIDES = {
    "IMP": [f"IMP Reading {number:02d}" for number in range(1, 21)],
    "LV IR": [f"LV IR Reading R-{number}" for number in range(1, 9)],
    "ERT": [
        f"Earth Resistance Test Point {number:02d} (EP / W.G / W.O.G)"
        for number in range(1, 22)
    ],
}

SPELLING_REPLACEMENTS = {
    "Balast": "Ballast",
    "Lighteng": "Lighting",
    "jumaer": "jumper",
    "Thtough": "Through",
    "Meggar": "Megger",
    "Verfiy": "Verify",
    "requirm": "requirem",
    "markin done": "marking done",
    "acssories": "accessories",
    "darwing": "drawing",
    "quantaity": "quantity",
    "switchyaed": "switchyard",
    "atation": "station",
    "tranformer": "transformer",
    "sysytem": "system",
    "volatge": "voltage",
    "Fittment": "Fitting",
    "Chequared": "Chequered",
    "availabe": "available",
    "connectded": "connected",
    "auxillary": "auxiliary",
    "asbuilt": "as-built",
}


def normalized_text(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def slug(value):
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def is_serial(value):
    if isinstance(value, (int, float)) and int(value) == value and value > 0:
        return True
    return bool(
        re.fullmatch(r"\d+(?:\.\d+)*\.?|\d+[a-z]?", str(value or "").strip(), re.I)
    )


def clean_point(value):
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    for old, new in SPELLING_REPLACEMENTS.items():
        text = text.replace(old, new)
    return text


def find_header(ws):
    for row in range(1, min(ws.max_row, 15) + 1):
        for column in range(1, ws.max_column + 1):
            text = normalized_text(ws.cell(row, column).value)
            if "sr no" in text or "sl no" in text or text == "s no":
                return row, column
    return None, None


def description_column(ws, header_row, serial_column):
    candidates = []
    for column in range(1, ws.max_column + 1):
        text = normalized_text(ws.cell(header_row, column).value)
        if any(
            label in text
            for label in ("description", "check points", "inspection", "identification")
        ):
            candidates.append(column)
    return max(candidates) if candidates else min(serial_column + 1, ws.max_column)


def observation_column(ws, header_row, description_col):
    for column in range(description_col + 1, ws.max_column + 1):
        text = normalized_text(ws.cell(header_row, column).value)
        if any(
            label in text
            for label in (
                "reference document",
                "acceptance criteria",
                "type of check",
                "observation",
                "result",
                "signature",
                "polarity",
                "remark",
                "cable length",
                "continuity",
                "time",
                "imp",
            )
        ):
            return column
    return ws.max_column + 1


def extract_points(ws):
    if ws.title in POINT_OVERRIDES:
        return POINT_OVERRIDES[ws.title]

    header_row, serial_column = find_header(ws)
    if not header_row:
        return []
    description_col = description_column(ws, header_row, serial_column)
    stop_col = observation_column(ws, header_row, description_col)
    points = []
    for row in range(header_row + 1, ws.max_row + 1):
        if not is_serial(ws.cell(row, serial_column).value):
            continue
        label = ""
        for column in range(description_col, stop_col):
            value = ws.cell(row, column).value
            if value is None or is_serial(value):
                continue
            candidate = clean_point(value)
            if candidate:
                label = candidate
                break
        if label:
            points.append(label)
    return points


def extract_format_number(ws):
    if ws.title in FORMAT_OVERRIDES:
        return FORMAT_OVERRIDES[ws.title]
    for row in ws.iter_rows():
        for cell in row:
            if not isinstance(cell.value, str):
                continue
            match = re.search(r"TPS-LP-[A-Z]+-\d+(?:-\d+)?", cell.value)
            if match:
                return match.group(0)
    return "Not specified"


def build_catalog(workbook):
    templates = []
    for order, ws in enumerate(
        (sheet for sheet in workbook.worksheets if sheet.title not in EXCLUDED_SHEETS),
        start=1,
    ):
        name = DISPLAY_NAMES.get(ws.title, ws.title)
        template_id = slug(ws.title)
        points = extract_points(ws)
        if not points:
            raise ValueError(f"No checklist points found in sheet: {ws.title}")
        templates.append(
            {
                "template_id": template_id,
                "name": name,
                "source_sheet": ws.title,
                "format_no": extract_format_number(ws),
                "order": order * 10,
                "points": [
                    {
                        "item_id": f"point-{index:03d}",
                        "label": label,
                        "order": index * 10,
                    }
                    for index, label in enumerate(points, start=1)
                ],
            }
        )
    return {"version": 1, "template_count": len(templates), "templates": templates}


def main():
    parser = argparse.ArgumentParser(description="Extract equipment checklists from Excel.")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    workbook = openpyxl.load_workbook(args.input, data_only=True)
    catalog = build_catalog(workbook)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Saved {catalog['template_count']} checklist templates to {args.output}")


if __name__ == "__main__":
    main()
