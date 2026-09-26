import re

from google.cloud import firestore

from .config import STATUS_OPTIONS, settings
from .equipment_catalog import get_equipment_template
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
            "updated_at": None,
            "updated_by": None,
        }
        for item in template["points"]
    }


def sync_equipment_points(ref, data, template):
    checklist = data.get("checklist", {}) or {}
    changed = False
    for item in template["points"]:
        item_id = item["item_id"]
        if item_id not in checklist:
            checklist[item_id] = {
                "label": item["label"],
                "status": "pending",
                "remark": "",
                "remark_updated_at": None,
                "remark_updated_by": None,
                "updated_at": None,
                "updated_by": None,
            }
            changed = True
        elif checklist[item_id].get("label") != item["label"]:
            checklist[item_id]["label"] = item["label"]
            changed = True
    if changed:
        ref.update({"checklist": checklist})
        data["checklist"] = checklist
    return data


def build_equipment_view(equipment_id, data, template):
    checklist = data.get("checklist", {}) or {}
    rows = []
    for item in template["points"]:
        existing = checklist.get(item["item_id"], {}) or {}
        rows.append(
            {
                "item_id": item["item_id"],
                "label": item["label"],
                "status": existing.get("status", "pending"),
                "remark": existing.get("remark", ""),
                "remark_updated_at": existing.get("remark_updated_at"),
                "remark_updated_by": existing.get("remark_updated_by"),
                "updated_at": existing.get("updated_at"),
                "updated_by": existing.get("updated_by"),
            }
        )
    project_id, block_id = normalize_scope(data.get("project"), data.get("block"))
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
    db, project, block, template_id, record_number, created_by, base_url=None
):
    project_id, block_id = normalize_scope(project, block)
    template = get_equipment_template(template_id)
    if not project_id or not block_id:
        raise ValueError("Project and block are required.")
    if not template:
        raise ValueError("Select a valid equipment checklist.")
    record_number = normalize_record_number(record_number)
    equipment_id = format_equipment_id(
        project_id, block_id, template["template_id"], record_number
    )
    create_project(db, project_id, created_by)
    ref = db.collection("equipment_checklists").document(equipment_id)
    snap = ref.get()
    if snap.exists:
        data = sync_equipment_points(ref, snap.to_dict() or {}, template)
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


def list_equipment_checklists(db, project=None, block=None):
    project_id, block_id = normalize_scope(project, block)
    rows = []
    for snap in db.collection("equipment_checklists").stream():
        data = snap.to_dict() or {}
        record_project, record_block = normalize_scope(
            data.get("project"), data.get("block")
        )
        if project_id and record_project != project_id:
            continue
        if block_id and record_block != block_id:
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
    progress = round(completed_points * 100 / total_points) if total_points else 0
    return {
        "total_records": total_records,
        "completed_records": completed_records,
        "pending_records": total_records - completed_records,
        "total_points": total_points,
        "completed_points": completed_points,
        "pending_points": pending_points,
        "na_points": na_points,
        "progress": progress,
    }


def _equipment_item_update(db, equipment_id, item_id, user, status=None, remark=None):
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
    timestamp_utc = now_utc()
    timestamp_local = now_local()
    email = user.get("email") or "unknown"
    change_type = "status" if status is not None else "remark"

    if status is not None:
        if status not in STATUS_OPTIONS:
            raise ValueError("Invalid checklist status.")
        item.update({"status": status, "updated_at": timestamp_utc, "updated_by": email})
    else:
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
    checklist[item_id] = item
    ref.update(
        {"checklist": checklist, "updated_at": timestamp_utc, "updated_by": email}
    )

    changed = previous_status != status if status is not None else previous_remark != remark
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
                "new_remark": remark if status is None else previous_remark,
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
            item.get("updated_date", ""),
            item.get("updated_time", ""),
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
