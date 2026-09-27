import re
from datetime import datetime

from google.cloud import firestore

from .config import STATUS_OPTIONS, settings
from .equipment_catalog import get_equipment_template
from .identity_profiles import (
    IDENTITY_DETAIL_LIMITS,
    format_work_id,
    get_identity_profile,
    identity_details_text,
)
from .qr import equipment_url
from .services import (
    calculate_counts,
    create_project,
    display_block,
    normalize_block,
    normalize_project,
    normalize_scope,
    now_local,
    now_utc,
)


def normalize_equipment_id(equipment_id):
    return re.sub(r"[^A-Z0-9-]+", "-", (equipment_id or "").strip().upper()).strip("-")


def normalize_record_number(record_number):
    cleaned = re.sub(r"[^A-Z0-9]+", "-", (record_number or "01").strip().upper()).strip("-")
    return cleaned or "01"


def _clean_detail(value, label, maximum):
    cleaned = re.sub(r"\s+", " ", str(value or "").strip())
    if len(cleaned) > maximum:
        raise ValueError(f"{label} must be {maximum} characters or less.")
    return cleaned


def normalize_equipment_details(
    vendor_name="",
    equipment_identification="",
    specification="",
    identity_details=None,
):
    supplied_identity_details = identity_details or {}
    if not isinstance(supplied_identity_details, dict):
        raise ValueError("Identity details must be supplied as fields.")
    invalid_fields = set(supplied_identity_details) - set(IDENTITY_DETAIL_LIMITS)
    if invalid_fields:
        raise ValueError("Invalid identity detail field.")
    return {
        "vendor_name": _clean_detail(vendor_name, "Vendor name", 120),
        "equipment_identification": _clean_detail(
            equipment_identification, "Equipment identification", 120
        ),
        "specification": _clean_detail(specification, "Specification", 160),
        "identity_details": {
            key: _clean_detail(
                supplied_identity_details.get(key, ""),
                key.replace("_", " ").title(),
                maximum,
            )
            for key, maximum in IDENTITY_DETAIL_LIMITS.items()
            if key in supplied_identity_details
        },
    }


def format_equipment_id(project, block, template_id, record_number="01"):
    project_id, block_id = normalize_scope(project, block)
    template_key = normalize_equipment_id(template_id)
    record_key = normalize_record_number(record_number)
    if not project_id or not block_id or not template_key:
        raise ValueError("Project, block and checklist type are required.")
    return f"{project_id}-{block_id}-EQP-{template_key}-{record_key}"


def build_default_equipment_checklist(template):
    return {
        item["item_id"]: {
            "label": item["label"],
            "status": "pending",
            "remark": "",
            "remark_updated_at": None,
            "remark_updated_by": None,
            "value": "",
            "value_updated_at": None,
            "value_updated_by": None,
            "measurements": {
                field["key"]: field.get("default", "")
                for field in item.get("measurement_fields", [])
            },
            "measurement_updated_at": None,
            "measurement_updated_by": None,
            "updated_at": None,
            "updated_by": None,
        }
        for item in template["points"]
    }


def sync_equipment_points(ref, data, template):
    checklist = data.get("checklist", {}) or {}
    updates = {}
    for item in template["points"]:
        item_id = item["item_id"]
        if item_id not in checklist:
            checklist[item_id] = {
                "label": item["label"],
                "status": "pending",
                "remark": "",
                "remark_updated_at": None,
                "remark_updated_by": None,
                "value": "",
                "value_updated_at": None,
                "value_updated_by": None,
                "measurements": {
                    field["key"]: field.get("default", "")
                    for field in item.get("measurement_fields", [])
                },
                "measurement_updated_at": None,
                "measurement_updated_by": None,
                "updated_at": None,
                "updated_by": None,
            }
            updates[f"checklist.{item_id}"] = checklist[item_id]
        elif checklist[item_id].get("label") != item["label"]:
            checklist[item_id]["label"] = item["label"]
            updates[f"checklist.{item_id}.label"] = item["label"]
    if updates:
        ref.update(updates)
        data["checklist"] = checklist
    return data


def build_equipment_view(equipment_id, data, template):
    checklist = data.get("checklist", {}) or {}
    rows = []
    for item in template["points"]:
        existing = checklist.get(item["item_id"], {}) or {}
        measurement_fields = item.get("measurement_fields", []) or []
        measurements = {
            field["key"]: field.get("default", "") for field in measurement_fields
        }
        measurements.update(existing.get("measurements", {}) or {})
        if existing.get("value") and measurement_fields:
            first_key = measurement_fields[0]["key"]
            if not measurements.get(first_key):
                measurements[first_key] = existing["value"]
        rows.append(
            {
                "item_id": item["item_id"],
                "label": item["label"],
                "status": existing.get("status", "pending"),
                "remark": existing.get("remark", ""),
                "remark_updated_at": existing.get("remark_updated_at"),
                "remark_updated_by": existing.get("remark_updated_by"),
                "check_type": item.get("check_type", ""),
                "acceptance_criteria": item.get("acceptance_criteria", ""),
                "section": item.get("section", ""),
                "measurement_fields": measurement_fields,
                "measurements": measurements,
                "has_measurements": any(
                    str(value or "").strip() for value in measurements.values()
                ),
                "measurement_updated_at": existing.get("measurement_updated_at")
                or existing.get("value_updated_at"),
                "measurement_updated_by": existing.get("measurement_updated_by")
                or existing.get("value_updated_by"),
                "value_enabled": bool(measurement_fields),
                "value_label": item.get("value_label", "Recorded Value / Reading"),
                "value_hint": item.get("value_hint", "Enter measured value or reading"),
                "value": (
                    measurements.get(measurement_fields[0]["key"], "")
                    if measurement_fields
                    else existing.get("value", "")
                ),
                "value_updated_at": existing.get("value_updated_at"),
                "value_updated_by": existing.get("value_updated_by"),
                "updated_at": existing.get("updated_at"),
                "updated_by": existing.get("updated_by"),
            }
        )
    project_id, block_id = normalize_scope(data.get("project"), data.get("block"))
    identity_profile = get_identity_profile(template)
    identity_details = {
        field["key"]: str((data.get("identity_details") or {}).get(field["key"], ""))
        for field in identity_profile["fields"]
    }
    work_id = data.get("work_id") or format_work_id(
        template,
        project_id,
        display_block(block_id),
        data.get("record_number", "01"),
    )
    return {
        "equipment_id": equipment_id,
        "project": project_id,
        "block": block_id,
        "block_display": display_block(block_id),
        "template_id": template["template_id"],
        "template_name": template["name"],
        "format_no": template.get("format_no", ""),
        "source_sheet": template.get("source_sheet", ""),
        "record_number": data.get("record_number", "01"),
        "work_id": work_id,
        "vendor_name": data.get("vendor_name", ""),
        "equipment_identification": data.get("equipment_identification", ""),
        "specification": data.get("specification", ""),
        "identity_profile": identity_profile,
        "identity_details": identity_details,
        "identity_details_text": identity_details_text(
            identity_details, identity_profile
        ),
        "identity_search_text": " ".join(
            [
                work_id,
                data.get("equipment_identification", ""),
                data.get("specification", ""),
                data.get("vendor_name", ""),
                *identity_details.values(),
            ]
        ).strip(),
        "qr_url": data.get("qr_url") or equipment_url(equipment_id),
        "created_at": data.get("created_at"),
        "created_by": data.get("created_by"),
        "updated_at": data.get("updated_at"),
        "updated_by": data.get("updated_by"),
        "final_remark": data.get("final_remark", ""),
        "final_remark_updated_at": data.get("final_remark_updated_at"),
        "final_remark_updated_by": data.get("final_remark_updated_by"),
        "checklist": rows,
        "counts": calculate_counts(rows),
    }


def create_equipment_checklist(
    db,
    project,
    block,
    template_id,
    record_number,
    created_by,
    base_url=None,
    vendor_name="",
    equipment_identification="",
    specification="",
    identity_details=None,
):
    project_id, block_id = normalize_scope(project, block)
    template = get_equipment_template(template_id)
    if not project_id or not block_id:
        raise ValueError("Project and block are required.")
    if not template:
        raise ValueError("Select a valid equipment checklist.")
    record_number = normalize_record_number(record_number)
    details = normalize_equipment_details(
        vendor_name,
        equipment_identification,
        specification,
        identity_details,
    )
    equipment_id = format_equipment_id(
        project_id, block_id, template["template_id"], record_number
    )
    create_project(db, project_id, created_by)
    ref = db.collection("equipment_checklists").document(equipment_id)
    snap = ref.get()
    if snap.exists:
        data = sync_equipment_points(ref, snap.to_dict() or {}, template)
        submitted_details = {key: value for key, value in details.items() if value}
        if submitted_details:
            return update_equipment_details(
                db,
                equipment_id,
                submitted_details,
                {"email": created_by, "uid": None},
                partial=True,
            )
        return build_equipment_view(equipment_id, data, template)

    timestamp = now_utc()
    data = {
        "equipment_id": equipment_id,
        "record_type": "equipment_checklist",
        "project": project_id,
        "block": block_id,
        "template_id": template["template_id"],
        "template_name": template["name"],
        "format_no": template.get("format_no", ""),
        "record_number": record_number,
        "work_id": format_work_id(
            template, project_id, display_block(block_id), record_number
        ),
        **details,
        "qr_url": equipment_url(equipment_id, base_url),
        "checklist": build_default_equipment_checklist(template),
        "final_remark": "",
        "final_remark_updated_at": None,
        "final_remark_updated_by": None,
        "created_at": timestamp,
        "created_by": created_by,
        "updated_at": timestamp,
        "updated_by": created_by,
    }
    ref.set(data)
    return build_equipment_view(equipment_id, data, template)


def update_equipment_details(db, equipment_id, details, user, partial=False):
    if not isinstance(details, dict):
        raise ValueError("Checklist details must be supplied as fields.")
    allowed = {
        "vendor_name",
        "equipment_identification",
        "specification",
        "identity_details",
    }
    if set(details) - allowed:
        raise ValueError("Invalid checklist detail field.")

    equipment_id = normalize_equipment_id(equipment_id)
    ref = db.collection("equipment_checklists").document(equipment_id)
    snap = ref.get()
    if not snap.exists:
        return None
    data = snap.to_dict() or {}
    current = {
        "vendor_name": data.get("vendor_name", ""),
        "equipment_identification": data.get("equipment_identification", ""),
        "specification": data.get("specification", ""),
        "identity_details": data.get("identity_details", {}) or {},
    }
    normalized = normalize_equipment_details(
        details.get("vendor_name", current["vendor_name"] if partial else ""),
        details.get(
            "equipment_identification",
            current["equipment_identification"] if partial else "",
        ),
        details.get("specification", current["specification"] if partial else ""),
        details.get(
            "identity_details",
            current["identity_details"] if partial else {},
        ),
    )
    if normalized == current:
        return get_equipment_checklist(db, equipment_id)

    timestamp_utc = now_utc()
    timestamp_local = now_local()
    email = user.get("email") or "unknown"
    ref.update({**normalized, "updated_at": timestamp_utc, "updated_by": email})
    db.collection("equipment_history").add(
        {
            "equipment_id": equipment_id,
            "template_id": data.get("template_id", ""),
            "template_name": data.get("template_name", ""),
            "record_number": data.get("record_number", ""),
            "project": normalize_project(data.get("project")),
            "block": normalize_block(data.get("block")),
            "item_id": "__details__",
            "item_label": "Checklist details",
            "change_type": "details",
            "previous_status": "",
            "new_status": "",
            "previous_remark": "",
            "new_remark": "",
            "previous_value": "",
            "new_value": "",
            "previous_measurements": {},
            "new_measurements": {},
            "previous_details": current,
            "new_details": normalized,
            "updated_by": email,
            "updated_by_uid": user.get("uid"),
            "updated_at": timestamp_utc,
            "updated_date": timestamp_local.strftime("%Y-%m-%d"),
            "updated_time": timestamp_local.strftime("%H:%M:%S"),
            "timezone": settings.app_timezone,
        }
    )
    return get_equipment_checklist(db, equipment_id)


def get_equipment_checklist(db, equipment_id):
    equipment_id = normalize_equipment_id(equipment_id)
    ref = db.collection("equipment_checklists").document(equipment_id)
    snap = ref.get()
    if not snap.exists:
        return None
    data = snap.to_dict() or {}
    template = get_equipment_template(data.get("template_id"))
    if not template:
        return None
    data = sync_equipment_points(ref, data, template)
    return build_equipment_view(equipment_id, data, template)


def list_equipment_checklists(db, project=None, block=None, template_id=None):
    project_id, block_id = normalize_scope(project, block)
    normalized_template_id = str(template_id or "").strip().lower()
    rows = []
    collection = db.collection("equipment_checklists")
    docs = (
        collection.where(
            filter=firestore.FieldFilter(
                "template_id" if normalized_template_id else "project",
                "==",
                normalized_template_id if normalized_template_id else project_id,
            )
        ).stream()
        if normalized_template_id or project_id
        else collection.stream()
    )
    for snap in docs:
        data = snap.to_dict() or {}
        record_project, record_block = normalize_scope(
            data.get("project"), data.get("block")
        )
        if project_id and record_project != project_id:
            continue
        if block_id and record_block != block_id:
            continue
        if normalized_template_id and str(data.get("template_id") or "").lower() != normalized_template_id:
            continue
        template = get_equipment_template(data.get("template_id"))
        if template:
            rows.append(build_equipment_view(snap.id, data, template))
    return sorted(
        rows,
        key=lambda item: (
            item.get("project", ""),
            item.get("block", ""),
            item.get("template_name", ""),
            item.get("record_number", ""),
        ),
    )


def build_equipment_summary(records):
    records = records or []
    total_records = len(records)
    completed_records = sum(
        1 for record in records if (record.get("counts") or {}).get("pending", 0) == 0
    )
    total_points = sum((record.get("counts") or {}).get("total", 0) for record in records)
    completed_points = sum(
        (record.get("counts") or {}).get("completed", 0) for record in records
    )
    pending_points = sum(
        (record.get("counts") or {}).get("pending", 0) for record in records
    )
    na_points = sum((record.get("counts") or {}).get("na", 0) for record in records)
    progress = (
        round((completed_points + na_points) * 100 / total_points)
        if total_points
        else 0
    )
    in_progress_records = sum(
        1
        for record in records
        if (record.get("counts") or {}).get("completed", 0) > 0
        and (record.get("counts") or {}).get("pending", 0) > 0
    )
    not_started_records = sum(
        1
        for record in records
        if (record.get("counts") or {}).get("completed", 0) == 0
        and (record.get("counts") or {}).get("pending", 0) > 0
    )
    identified_records = sum(
        1
        for record in records
        if str(record.get("equipment_identification") or "").strip()
    )
    unique_equipment = {
        (
            record.get("block", ""),
            str(record.get("equipment_identification") or "").strip().upper(),
        )
        for record in records
        if str(record.get("equipment_identification") or "").strip()
    }
    return {
        "total_records": total_records,
        "completed_records": completed_records,
        "pending_records": total_records - completed_records,
        "in_progress_records": in_progress_records,
        "not_started_records": not_started_records,
        "identified_records": identified_records,
        "missing_identity_records": total_records - identified_records,
        "unique_equipment_count": len(unique_equipment),
        "active_template_count": len(
            {
                record.get("template_id")
                for record in records
                if record.get("template_id")
            }
        ),
        "total_points": total_points,
        "completed_points": completed_points,
        "pending_points": pending_points,
        "na_points": na_points,
        "progress": progress,
    }


def _equipment_family(equipment_identification):
    label = re.sub(r"\s+", " ", str(equipment_identification or "").strip())
    if not label:
        return "Unidentified"
    family = re.sub(r"[\s_\-/]*\d+[A-Z]?$", "", label, flags=re.IGNORECASE)
    return (family.strip(" -_/") or label).upper()


def _record_state(record):
    counts = record.get("counts") or {}
    pending = counts.get("pending", 0)
    completed = counts.get("completed", 0)
    if pending == 0 and counts.get("total", 0) > 0:
        return "completed"
    if completed > 0:
        return "in_progress"
    return "not_started"


def build_equipment_family_summaries(records):
    """Group all checklist work by physical equipment/circuit family and identity."""
    families = {}
    for record in records or []:
        identity = str(record.get("equipment_identification") or "").strip()
        profile = record.get("identity_profile") or {}
        family_name = (
            str(record.get("template_name") or "Cable circuits").upper()
            if profile.get("type") == "cable"
            else _equipment_family(identity)
        )
        family = families.setdefault(
            family_name,
            {"records": [], "equipment": {}, "blocks": set(), "templates": {}},
        )
        family["records"].append(record)
        if record.get("block"):
            family["blocks"].add(record["block"])
        if record.get("template_id"):
            family["templates"][record["template_id"]] = record.get(
                "template_name", record["template_id"]
            )

        identity_key = (
            f"{record.get('block', '')}|{identity.upper()}"
            if identity
            else f"__MISSING__{record.get('equipment_id', len(family['records']))}"
        )
        equipment = family["equipment"].setdefault(
            identity_key,
            {
                "label": identity or "ID not set",
                "block": record.get("block", ""),
                "records": [],
            },
        )
        equipment["records"].append(record)

    summaries = []
    for family_name, family in families.items():
        summary = build_equipment_summary(family["records"])
        equipment_rows = []
        for equipment in family["equipment"].values():
            equipment_summary = build_equipment_summary(equipment["records"])
            if equipment_summary["pending_records"] == 0:
                state = "completed"
            elif equipment_summary["completed_points"] > 0:
                state = "in_progress"
            else:
                state = "not_started"
            equipment_rows.append(
                {
                    "label": equipment["label"],
                    "block": equipment["block"],
                    "state": state,
                    "checklist_records": equipment_summary["total_records"],
                    "completed_points": equipment_summary["completed_points"],
                    "pending_points": equipment_summary["pending_points"],
                    "total_points": equipment_summary["total_points"],
                    "progress": equipment_summary["progress"],
                }
            )
        equipment_rows.sort(key=lambda item: item["label"])
        summaries.append(
            {
                "family": family_name,
                "equipment_count": len(equipment_rows),
                "completed_equipment": sum(
                    1 for item in equipment_rows if item["state"] == "completed"
                ),
                "in_progress_equipment": sum(
                    1 for item in equipment_rows if item["state"] == "in_progress"
                ),
                "not_started_equipment": sum(
                    1 for item in equipment_rows if item["state"] == "not_started"
                ),
                "pending_equipment": sum(
                    1 for item in equipment_rows if item["state"] != "completed"
                ),
                "block_count": len(family["blocks"]),
                "blocks": sorted(family["blocks"]),
                "checklist_type_count": len(family["templates"]),
                "checklist_types": sorted(family["templates"].values()),
                "equipment": equipment_rows[:8],
                "additional_equipment_count": max(0, len(equipment_rows) - 8),
                **summary,
            }
        )
    return sorted(
        summaries,
        key=lambda item: (item["family"] == "Unidentified", item["family"]),
    )


def get_next_equipment_record_number(records):
    used_numbers = {
        int(record.get("record_number", ""))
        for record in (records or [])
        if str(record.get("record_number", "")).isdigit()
        and int(record.get("record_number", "")) > 0
    }
    number = 1
    while number in used_numbers:
        number += 1
    return str(number).zfill(2)


def build_equipment_template_summaries(templates, records):
    records_by_template = {}
    for record in records or []:
        records_by_template.setdefault(record.get("template_id", ""), []).append(record)

    summaries = []
    for template in templates or []:
        template_records = records_by_template.get(template.get("template_id", ""), [])
        summary = build_equipment_summary(template_records)
        equipment_labels = list(
            dict.fromkeys(
                str(record.get("equipment_identification") or "").strip()
                for record in template_records
                if str(record.get("equipment_identification") or "").strip()
            )
        )
        vendor_names = list(
            dict.fromkeys(
                str(record.get("vendor_name") or "").strip()
                for record in template_records
                if str(record.get("vendor_name") or "").strip()
            )
        )
        specifications = list(
            dict.fromkeys(
                str(record.get("specification") or "").strip()
                for record in template_records
                if str(record.get("specification") or "").strip()
            )
        )
        blocks = sorted(
            {
                record.get("block")
                for record in template_records
                if record.get("block")
            }
        )
        record_statuses = []
        for record in template_records:
            counts = record.get("counts") or {}
            record_statuses.append(
                {
                    "equipment_id": record.get("equipment_id", ""),
                    "record_number": record.get("record_number", ""),
                    "label": record.get("equipment_identification") or "ID not set",
                    "block": record.get("block", ""),
                    "state": _record_state(record),
                    "completed_points": counts.get("completed", 0),
                    "pending_points": counts.get("pending", 0),
                    "total_points": counts.get("total", 0),
                    "progress": counts.get("progress", 0),
                    "vendor_name": record.get("vendor_name", ""),
                    "specification": record.get("specification", ""),
                }
            )
        summaries.append(
            {
                **template,
                **summary,
                "equipment_labels": equipment_labels[:3],
                "additional_equipment_count": max(0, len(equipment_labels) - 3),
                "vendor_names": vendor_names[:2],
                "additional_vendor_count": max(0, len(vendor_names) - 2),
                "specifications": specifications[:2],
                "additional_specification_count": max(0, len(specifications) - 2),
                "blocks": blocks,
                "block_count": len(blocks),
                "record_statuses": record_statuses[:8],
                "additional_record_status_count": max(0, len(record_statuses) - 8),
                "next_record_number": get_next_equipment_record_number(
                    template_records
                ),
            }
        )
    return summaries


def _equipment_item_update(
    db,
    equipment_id,
    item_id,
    user,
    status=None,
    remark=None,
    value=None,
    measurements=None,
):
    equipment_id = normalize_equipment_id(equipment_id)
    ref = db.collection("equipment_checklists").document(equipment_id)
    snap = ref.get()
    if not snap.exists:
        return None
    data = snap.to_dict() or {}
    checklist = data.get("checklist", {}) or {}
    if item_id not in checklist:
        raise ValueError("Checklist point not found.")
    item = checklist[item_id] or {}
    previous_status = item.get("status", "pending")
    previous_remark = item.get("remark", "")
    previous_value = item.get("value", "")
    previous_measurements = dict(item.get("measurements", {}) or {})
    timestamp_utc = now_utc()
    timestamp_local = now_local()
    email = user.get("email") or "unknown"
    if status is not None:
        change_type = "status"
    elif remark is not None:
        change_type = "remark"
    elif measurements is not None or value is not None:
        change_type = "measurements"
    else:
        raise ValueError("No checklist update supplied.")

    if status is not None:
        if status not in STATUS_OPTIONS:
            raise ValueError("Invalid checklist status.")
        item.update({"status": status, "updated_at": timestamp_utc, "updated_by": email})
    elif remark is not None:
        remark = (remark or "").strip()
        if len(remark) > 1000:
            raise ValueError("Remark must be 1000 characters or less.")
        item.update(
            {
                "remark": remark,
                "remark_updated_at": timestamp_utc,
                "remark_updated_by": email,
            }
        )
    else:
        template = get_equipment_template(data.get("template_id"))
        template_point = next(
            (
                point
                for point in (template or {}).get("points", [])
                if point.get("item_id") == item_id
            ),
            None,
        )
        fields = (template_point or {}).get("measurement_fields", []) or []
        if not template_point or not fields:
            raise ValueError("This checklist point does not accept observations.")
        allowed_keys = {field["key"] for field in fields}
        if measurements is None:
            measurements = {fields[0]["key"]: value or ""}
        if not isinstance(measurements, dict):
            raise ValueError("Measurements must be supplied as fields.")
        unknown_keys = set(measurements) - allowed_keys
        if unknown_keys:
            raise ValueError("Invalid measurement field.")
        cleaned_measurements = dict(previous_measurements)
        for key, field_value in measurements.items():
            cleaned_value = str(field_value or "").strip()
            if len(cleaned_value) > 500:
                raise ValueError("Each observation must be 500 characters or less.")
            cleaned_measurements[key] = cleaned_value
        if sum(len(value) for value in cleaned_measurements.values()) > 5000:
            raise ValueError("Measurement values are too long.")
        first_key = fields[0]["key"]
        value = cleaned_measurements.get(first_key, "")
        item.update(
            {
                "value": value,
                "value_updated_at": timestamp_utc,
                "value_updated_by": email,
                "measurements": cleaned_measurements,
                "measurement_updated_at": timestamp_utc,
                "measurement_updated_by": email,
            }
        )
    updates = {"updated_at": timestamp_utc, "updated_by": email}
    if status is not None:
        updates.update(
            {
                f"checklist.{item_id}.status": item["status"],
                f"checklist.{item_id}.updated_at": item["updated_at"],
                f"checklist.{item_id}.updated_by": item["updated_by"],
            }
        )
    elif remark is not None:
        updates.update(
            {
                f"checklist.{item_id}.remark": item["remark"],
                f"checklist.{item_id}.remark_updated_at": item[
                    "remark_updated_at"
                ],
                f"checklist.{item_id}.remark_updated_by": item[
                    "remark_updated_by"
                ],
            }
        )
    else:
        updates.update(
            {
                f"checklist.{item_id}.value": item["value"],
                f"checklist.{item_id}.value_updated_at": item[
                    "value_updated_at"
                ],
                f"checklist.{item_id}.value_updated_by": item[
                    "value_updated_by"
                ],
                f"checklist.{item_id}.measurements": item["measurements"],
                f"checklist.{item_id}.measurement_updated_at": item[
                    "measurement_updated_at"
                ],
                f"checklist.{item_id}.measurement_updated_by": item[
                    "measurement_updated_by"
                ],
            }
        )
    ref.update(updates)

    if status is not None:
        changed = previous_status != status
    elif remark is not None:
        changed = previous_remark != remark
    else:
        changed = previous_measurements != cleaned_measurements
    if changed:
        db.collection("equipment_history").add(
            {
                "equipment_id": equipment_id,
                "template_id": data.get("template_id", ""),
                "template_name": data.get("template_name", ""),
                "record_number": data.get("record_number", ""),
                "project": normalize_project(data.get("project")),
                "block": normalize_block(data.get("block")),
                "item_id": item_id,
                "item_label": item.get("label", item_id),
                "change_type": change_type,
                "previous_status": previous_status,
                "new_status": status if status is not None else previous_status,
                "previous_remark": previous_remark,
                "new_remark": remark if remark is not None else previous_remark,
                "previous_value": previous_value,
                "new_value": value if value is not None else previous_value,
                "previous_measurements": previous_measurements,
                "new_measurements": (
                    cleaned_measurements
                    if measurements is not None or value is not None
                    else previous_measurements
                ),
                "previous_details": {},
                "new_details": {},
                "updated_by": email,
                "updated_by_uid": user.get("uid"),
                "updated_at": timestamp_utc,
                "updated_date": timestamp_local.strftime("%Y-%m-%d"),
                "updated_time": timestamp_local.strftime("%H:%M:%S"),
                "timezone": settings.app_timezone,
            }
        )
    return get_equipment_checklist(db, equipment_id)


def update_equipment_status(db, equipment_id, item_id, status, user):
    return _equipment_item_update(db, equipment_id, item_id, user, status=status)


def update_equipment_remark(db, equipment_id, item_id, remark, user):
    return _equipment_item_update(db, equipment_id, item_id, user, remark=remark)


def update_equipment_value(db, equipment_id, item_id, value, user):
    return _equipment_item_update(db, equipment_id, item_id, user, value=value)


def update_equipment_measurements(db, equipment_id, item_id, measurements, user):
    return _equipment_item_update(
        db, equipment_id, item_id, user, measurements=measurements
    )


def update_equipment_final_remark(db, equipment_id, remark, user):
    equipment_id = normalize_equipment_id(equipment_id)
    remark = (remark or "").strip()
    if len(remark) > 2000:
        raise ValueError("Final remark must be 2000 characters or less.")
    ref = db.collection("equipment_checklists").document(equipment_id)
    snap = ref.get()
    if not snap.exists:
        return None
    data = snap.to_dict() or {}
    previous_remark = data.get("final_remark", "")
    timestamp_utc = now_utc()
    timestamp_local = now_local()
    email = user.get("email") or "unknown"
    ref.update(
        {
            "final_remark": remark,
            "final_remark_updated_at": timestamp_utc,
            "final_remark_updated_by": email,
            "updated_at": timestamp_utc,
            "updated_by": email,
        }
    )
    if previous_remark != remark:
        db.collection("equipment_history").add(
            {
                "equipment_id": equipment_id,
                "template_id": data.get("template_id", ""),
                "template_name": data.get("template_name", ""),
                "record_number": data.get("record_number", ""),
                "project": normalize_project(data.get("project")),
                "block": normalize_block(data.get("block")),
                "item_id": "__final_remark__",
                "item_label": "Final remark",
                "change_type": "final_remark",
                "previous_status": "",
                "new_status": "",
                "previous_remark": previous_remark,
                "new_remark": remark,
                "previous_value": "",
                "new_value": "",
                "previous_measurements": {},
                "new_measurements": {},
                "previous_details": {},
                "new_details": {},
                "updated_by": email,
                "updated_by_uid": user.get("uid"),
                "updated_at": timestamp_utc,
                "updated_date": timestamp_local.strftime("%Y-%m-%d"),
                "updated_time": timestamp_local.strftime("%H:%M:%S"),
                "timezone": settings.app_timezone,
            }
        )
    return get_equipment_checklist(db, equipment_id)


def get_equipment_history(db, equipment_id=None, project=None, block=None, limit=100):
    project_id, block_id = normalize_scope(project, block)
    if equipment_id:
        docs = db.collection("equipment_history").where(
            filter=firestore.FieldFilter(
                "equipment_id", "==", normalize_equipment_id(equipment_id)
            )
        ).stream()
    elif project_id:
        docs = db.collection("equipment_history").where(
            filter=firestore.FieldFilter("project", "==", project_id)
        ).stream()
    else:
        docs = db.collection("equipment_history").stream()
    rows = []
    for snap in docs:
        data = snap.to_dict() or {}
        data["history_id"] = snap.id
        data["project"], data["block"] = normalize_scope(
            data.get("project"), data.get("block")
        )
        if project_id and data["project"] != project_id:
            continue
        if block_id and data["block"] != block_id:
            continue
        rows.append(data)
    rows.sort(
        key=lambda item: (
            item["updated_at"].timestamp()
            if isinstance(item.get("updated_at"), datetime)
            else 0
        ),
        reverse=True,
    )
    return rows[:limit]


def delete_equipment_checklist(db, equipment_id, delete_history=True):
    equipment_id = normalize_equipment_id(equipment_id)
    ref = db.collection("equipment_checklists").document(equipment_id)
    snap = ref.get()
    if not snap.exists:
        return None
    data = snap.to_dict() or {}
    if delete_history:
        batch = db.batch()
        count = 0
        for history in db.collection("equipment_history").where(
            filter=firestore.FieldFilter("equipment_id", "==", equipment_id)
        ).stream():
            batch.delete(history.reference)
            count += 1
            if count % 450 == 0:
                batch.commit()
                batch = db.batch()
        if count % 450:
            batch.commit()
    ref.delete()
    return {
        "equipment_id": equipment_id,
        "project": normalize_project(data.get("project")),
        "block": normalize_block(data.get("block")),
        "template_name": data.get("template_name", "Equipment checklist"),
        "record_number": data.get("record_number", ""),
    }
