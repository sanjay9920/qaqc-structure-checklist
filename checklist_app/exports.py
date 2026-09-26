import csv
from io import BytesIO, StringIO
import json

from openpyxl import Workbook

from .config import STATUS_OPTIONS
from .equipment_services import get_equipment_history, list_equipment_checklists
from .services import get_history, get_project_display_names, list_structures


def _status_label(value):
    return STATUS_OPTIONS.get(value, value)


def _project_label(display_names, project_id):
    return display_names.get(project_id, project_id or "")


def _measurement_text(item):
    values = item.get("measurements", {}) or {}
    parts = []
    for field in item.get("measurement_fields", []) or []:
        value = str(values.get(field.get("key"), "") or "").strip()
        if not value:
            continue
        unit = f" {field.get('unit')}" if field.get("unit") else ""
        parts.append(f"{field.get('label', field.get('key'))}: {value}{unit}")
    return "; ".join(parts)


def _measurement_history_text(row, key):
    values = row.get(key, {}) or {}
    return json.dumps(values, ensure_ascii=False, sort_keys=True) if values else ""


def export_structures_csv(db, project=None, block=None):
    output = StringIO()
    writer = csv.writer(output)
    project_display_names = get_project_display_names(db)
    writer.writerow(
        [
            "Project",
            "Block",
            "Structure ID",
            "Checklist Item",
            "Status",
            "Point Remark",
            "Remark Updated By",
            "Final Remark",
            "Updated By",
            "Updated At",
            "Completed Count",
            "Pending Count",
            "Not Applicable Count",
            "Progress %",
        ]
    )
    for structure in list_structures(db, project=project, block=block):
        counts = structure["counts"]
        for item in structure["checklist"]:
            writer.writerow(
                [
                    _project_label(project_display_names, structure.get("project", "")),
                    structure.get("block", ""),
                    structure["structure_id"],
                    item["label"],
                    _status_label(item["status"]),
                    item.get("remark") or "",
                    item.get("remark_updated_by") or "",
                    structure.get("final_remark") or "",
                    item.get("updated_by") or "",
                    item.get("updated_at") or "",
                    counts["completed"],
                    counts["pending"],
                    counts["na"],
                    counts["progress"],
                ]
            )
    return output.getvalue()


def export_history_csv(db, project=None, block=None):
    output = StringIO()
    writer = csv.writer(output)
    project_display_names = get_project_display_names(db)
    writer.writerow(
        [
            "Project",
            "Block",
            "Structure ID",
            "Checklist Item",
            "Previous Status",
            "New Status",
            "Change Type",
            "Previous Remark",
            "New Remark",
            "Updated By",
            "Date",
            "Time",
            "Timezone",
        ]
    )
    for row in get_history(db, project=project, block=block, limit=100000):
        writer.writerow(
            [
                _project_label(project_display_names, row.get("project", "")),
                row.get("block", ""),
                row.get("structure_id", ""),
                row.get("item_label", ""),
                _status_label(row.get("previous_status", "")),
                _status_label(row.get("new_status", "")),
                row.get("change_type", "status"),
                row.get("previous_remark", ""),
                row.get("new_remark", ""),
                row.get("updated_by", ""),
                row.get("updated_date", ""),
                row.get("updated_time", ""),
                row.get("timezone", ""),
            ]
        )
    return output.getvalue()


def export_equipment_csv(db, project=None, block=None):
    output = StringIO()
    writer = csv.writer(output)
    project_display_names = get_project_display_names(db)
    writer.writerow(
        [
            "Project",
            "Block",
            "Checklist Type",
            "Format No.",
            "Record No.",
            "Equipment Checklist ID",
            "Checklist Point",
            "Activity / Section",
            "Check Type",
            "Acceptance Criteria",
            "Status",
            "Observations / Measurements",
            "Observation Updated By",
            "Point Remark",
            "Remark Updated By",
            "Final Remark",
            "Updated By",
            "Updated At",
            "Completed Count",
            "Pending Count",
            "Not Applicable Count",
            "Progress %",
        ]
    )
    for record in list_equipment_checklists(db, project=project, block=block):
        counts = record["counts"]
        for item in record["checklist"]:
            writer.writerow(
                [
                    _project_label(project_display_names, record.get("project", "")),
                    record.get("block", ""),
                    record.get("template_name", ""),
                    record.get("format_no", ""),
                    record.get("record_number", ""),
                    record.get("equipment_id", ""),
                    item.get("label", ""),
                    item.get("section", ""),
                    item.get("check_type", ""),
                    item.get("acceptance_criteria", ""),
                    _status_label(item.get("status", "")),
                    _measurement_text(item),
                    item.get("measurement_updated_by") or "",
                    item.get("remark") or "",
                    item.get("remark_updated_by") or "",
                    record.get("final_remark") or "",
                    item.get("updated_by") or "",
                    item.get("updated_at") or "",
                    counts["completed"],
                    counts["pending"],
                    counts["na"],
                    counts["progress"],
                ]
            )
    return output.getvalue()


def export_equipment_history_csv(db, project=None, block=None):
    output = StringIO()
    writer = csv.writer(output)
    project_display_names = get_project_display_names(db)
    writer.writerow(
        [
            "Project",
            "Block",
            "Checklist Type",
            "Record No.",
            "Equipment Checklist ID",
            "Checklist Point",
            "Previous Status",
            "New Status",
            "Change Type",
            "Previous Remark",
            "New Remark",
            "Previous Value",
            "New Value",
            "Previous Measurements",
            "New Measurements",
            "Updated By",
            "Date",
            "Time",
            "Timezone",
        ]
    )
    for row in get_equipment_history(db, project=project, block=block, limit=100000):
        writer.writerow(
            [
                _project_label(project_display_names, row.get("project", "")),
                row.get("block", ""),
                row.get("template_name", ""),
                row.get("record_number", ""),
                row.get("equipment_id", ""),
                row.get("item_label", ""),
                _status_label(row.get("previous_status", "")),
                _status_label(row.get("new_status", "")),
                row.get("change_type", "status"),
                row.get("previous_remark", ""),
                row.get("new_remark", ""),
                row.get("previous_value", ""),
                row.get("new_value", ""),
                _measurement_history_text(row, "previous_measurements"),
                _measurement_history_text(row, "new_measurements"),
                row.get("updated_by", ""),
                row.get("updated_date", ""),
                row.get("updated_time", ""),
                row.get("timezone", ""),
            ]
        )
    return output.getvalue()


def export_all_xlsx(db, project=None, block=None):
    workbook = Workbook()
    project_display_names = get_project_display_names(db)
    structures_sheet = workbook.active
    structures_sheet.title = "Structures"
    structures_sheet.append(
        [
            "Project",
            "Block",
            "Structure ID",
            "Checklist Item",
            "Status",
            "Point Remark",
            "Remark Updated By",
            "Final Remark",
            "Updated By",
            "Updated At",
            "Completed Count",
            "Pending Count",
            "Not Applicable Count",
            "Progress %",
        ]
    )
    for structure in list_structures(db, project=project, block=block):
        counts = structure["counts"]
        for item in structure["checklist"]:
            structures_sheet.append(
                [
                    _project_label(project_display_names, structure.get("project", "")),
                    structure.get("block", ""),
                    structure["structure_id"],
                    item["label"],
                    _status_label(item["status"]),
                    item.get("remark") or "",
                    item.get("remark_updated_by") or "",
                    structure.get("final_remark") or "",
                    item.get("updated_by") or "",
                    str(item.get("updated_at") or ""),
                    counts["completed"],
                    counts["pending"],
                    counts["na"],
                    counts["progress"],
                ]
            )

    history_sheet = workbook.create_sheet("History")
    history_sheet.append(
        [
            "Project",
            "Block",
            "Structure ID",
            "Checklist Item",
            "Previous Status",
            "New Status",
            "Change Type",
            "Previous Remark",
            "New Remark",
            "Updated By",
            "Date",
            "Time",
            "Timezone",
        ]
    )
    for row in get_history(db, project=project, block=block, limit=100000):
        history_sheet.append(
            [
                _project_label(project_display_names, row.get("project", "")),
                row.get("block", ""),
                row.get("structure_id", ""),
                row.get("item_label", ""),
                _status_label(row.get("previous_status", "")),
                _status_label(row.get("new_status", "")),
                row.get("change_type", "status"),
                row.get("previous_remark", ""),
                row.get("new_remark", ""),
                row.get("updated_by", ""),
                row.get("updated_date", ""),
                row.get("updated_time", ""),
                row.get("timezone", ""),
            ]
        )

    equipment_sheet = workbook.create_sheet("Equipment Checklists")
    equipment_sheet.append(
        [
            "Project",
            "Block",
            "Checklist Type",
            "Format No.",
            "Record No.",
            "Equipment Checklist ID",
            "Checklist Point",
            "Activity / Section",
            "Check Type",
            "Acceptance Criteria",
            "Status",
            "Observations / Measurements",
            "Observation Updated By",
            "Point Remark",
            "Remark Updated By",
            "Final Remark",
            "Updated By",
            "Updated At",
            "Completed Count",
            "Pending Count",
            "Not Applicable Count",
            "Progress %",
        ]
    )
    for record in list_equipment_checklists(db, project=project, block=block):
        counts = record["counts"]
        for item in record["checklist"]:
            equipment_sheet.append(
                [
                    _project_label(project_display_names, record.get("project", "")),
                    record.get("block", ""),
                    record.get("template_name", ""),
                    record.get("format_no", ""),
                    record.get("record_number", ""),
                    record.get("equipment_id", ""),
                    item.get("label", ""),
                    item.get("section", ""),
                    item.get("check_type", ""),
                    item.get("acceptance_criteria", ""),
                    _status_label(item.get("status", "")),
                    _measurement_text(item),
                    item.get("measurement_updated_by") or "",
                    item.get("remark") or "",
                    item.get("remark_updated_by") or "",
                    record.get("final_remark") or "",
                    item.get("updated_by") or "",
                    str(item.get("updated_at") or ""),
                    counts["completed"],
                    counts["pending"],
                    counts["na"],
                    counts["progress"],
                ]
            )

    equipment_history_sheet = workbook.create_sheet("Equipment History")
    equipment_history_sheet.append(
        [
            "Project",
            "Block",
            "Checklist Type",
            "Record No.",
            "Equipment Checklist ID",
            "Checklist Point",
            "Previous Status",
            "New Status",
            "Change Type",
            "Previous Remark",
            "New Remark",
            "Previous Value",
            "New Value",
            "Previous Measurements",
            "New Measurements",
            "Updated By",
            "Date",
            "Time",
            "Timezone",
        ]
    )
    for row in get_equipment_history(db, project=project, block=block, limit=100000):
        equipment_history_sheet.append(
            [
                _project_label(project_display_names, row.get("project", "")),
                row.get("block", ""),
                row.get("template_name", ""),
                row.get("record_number", ""),
                row.get("equipment_id", ""),
                row.get("item_label", ""),
                _status_label(row.get("previous_status", "")),
                _status_label(row.get("new_status", "")),
                row.get("change_type", "status"),
                row.get("previous_remark", ""),
                row.get("new_remark", ""),
                row.get("previous_value", ""),
                row.get("new_value", ""),
                _measurement_history_text(row, "previous_measurements"),
                _measurement_history_text(row, "new_measurements"),
                row.get("updated_by", ""),
                row.get("updated_date", ""),
                row.get("updated_time", ""),
                row.get("timezone", ""),
            ]
        )

    for sheet in workbook.worksheets:
        for column_cells in sheet.columns:
            width = max(len(str(cell.value or "")) for cell in column_cells)
            sheet.column_dimensions[column_cells[0].column_letter].width = min(width + 2, 45)

    output = BytesIO()
    workbook.save(output)
    output.seek(0)
    return output
