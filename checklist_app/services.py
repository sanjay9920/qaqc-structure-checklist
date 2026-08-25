import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from google.cloud import firestore

from .config import DEFAULT_CHECKLIST_ITEMS, STATUS_OPTIONS, settings
from .qr import structure_url


def slugify(value):
    cleaned = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return cleaned or "item"


def normalize_structure_id(structure_id):
    return structure_id.strip().upper()


def normalize_project(project):
    cleaned = re.sub(r"[^A-Z0-9]+", "-", (project or "").strip().upper()).strip("-")
    return cleaned


def display_project_name(project_id):
    return (project_id or "").replace("-", " ")


def clean_display_name(name):
    return re.sub(r"\s+", " ", (name or "").strip())


def normalize_block(block):
    cleaned = re.sub(r"[^A-Z0-9]+", "-", (block or "").strip().upper()).strip("-")
    if cleaned.isdigit():
        return f"BLOCK-{int(cleaned)}"
    return cleaned


def normalize_scope(project=None, block=None):
    project_id = normalize_project(project)
    block_id = normalize_block(block)
    if project_id and block_id == project_id:
        block_id = ""
    return project_id, block_id


def display_block(block):
    block_id = normalize_block(block)
    if block_id.startswith("BLOCK-"):
        return block_id.removeprefix("BLOCK-")
    return block_id


def extract_structure_number(structure_id, min_width=2):
    structure_id = normalize_structure_id(structure_id)
    match = re.search(r"(?:^|-)STR-(\d+)$", structure_id)
    if not match and re.fullmatch(r"\d+", structure_id):
        match = re.fullmatch(r"(\d+)", structure_id)
    if not match:
        return structure_id
    number = int(match.group(1))
    return f"{number:0{min_width}d}"


def infer_scope_from_structure_id(structure_id):
    match = re.match(r"^(.+)-STR-\d+$", normalize_structure_id(structure_id))
    if not match:
        return {"project": "", "block": ""}

    prefix = match.group(1)
    block_match = re.search(r"(?:^|-)(BLOCK-[A-Z0-9]+)$", prefix)
    if not block_match:
        return {"project": prefix, "block": ""}

    block_id = block_match.group(1)
    project_id = prefix[: -len(block_id)].rstrip("-")
    return {"project": project_id, "block": block_id}


def infer_block_from_structure_id(structure_id):
    return infer_scope_from_structure_id(structure_id)["block"]


def infer_project_from_structure_id(structure_id):
    return infer_scope_from_structure_id(structure_id)["project"]


def format_structure_id(number, prefix="STR", width=4, block=None, project=None):
    structure_id = f"{prefix}-{number:0{width}d}"
    project_id, block_id = normalize_scope(project, block)
    if project_id:
        structure_id = f"{project_id}-{structure_id}"
    if block_id:
        if project_id:
            return f"{project_id}-{block_id}-{prefix}-{number:0{width}d}"
        return f"{block_id}-{prefix}-{number:0{width}d}"
    return structure_id


def now_local():
    try:
        tz = ZoneInfo(settings.app_timezone)
    except Exception:
        return datetime.now(timezone.utc)
    return datetime.now(tz)


def now_utc():
    return datetime.now(timezone.utc)


def ensure_default_checklist_items(db, created_by):
    docs = list(db.collection("checklist_items").limit(1).stream())
    if docs:
        return get_active_checklist_items(db)

    batch = db.batch()
    for index, label in enumerate(DEFAULT_CHECKLIST_ITEMS, start=1):
        item_id = slugify(label)
        ref = db.collection("checklist_items").document(item_id)
        batch.set(
            ref,
            {
                "item_id": item_id,
                "label": label,
                "active": True,
                "order": index * 10,
                "created_at": now_utc(),
                "created_by": created_by,
            },
        )
    batch.commit()
    return get_active_checklist_items(db)


def get_active_checklist_items(db, include_inactive=False):
    query = db.collection("checklist_items").order_by("order")
    docs = list(query.stream())
    if not docs:
        ensure_default_checklist_items(db, "system")
        docs = list(query.stream())

    items = []
    for snap in docs:
        data = snap.to_dict()
        data["item_id"] = snap.id
        if include_inactive or data.get("active", True):
            items.append(data)
    return items


def build_default_checklist(items):
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
        for item in items
        if item.get("active", True)
    }


def calculate_counts(checklist_rows):
    total = len(checklist_rows)
    completed = sum(1 for item in checklist_rows if item["status"] == "completed")
    pending = sum(1 for item in checklist_rows if item["status"] == "pending")
    na = sum(1 for item in checklist_rows if item["status"] == "na")
    progress = round((completed / total) * 100) if total else 0
    return {
        "total": total,
        "completed": completed,
        "pending": pending,
        "na": na,
        "progress": progress,
    }


def build_structure_view(structure_id, data, items):
    checklist = data.get("checklist", {})
    scope = infer_scope_from_structure_id(structure_id)
    project_id, block_id = normalize_scope(
        data.get("project") or scope["project"],
        data.get("block") or scope["block"],
    )
    rows = []
    for item in items:
        if not item.get("active", True):
            continue
        item_id = item["item_id"]
        existing = checklist.get(item_id, {})
        rows.append(
            {
                "item_id": item_id,
                "label": item["label"],
                "status": existing.get("status", "pending"),
                "remark": existing.get("remark", ""),
                "remark_updated_at": existing.get("remark_updated_at"),
                "remark_updated_by": existing.get("remark_updated_by"),
                "updated_at": existing.get("updated_at"),
                "updated_by": existing.get("updated_by"),
            }
        )

    counts = calculate_counts(rows)
    return {
        "structure_id": structure_id,
        "structure_number": extract_structure_number(structure_id),
        "project": project_id,
        "block": block_id,
        "block_display": display_block(block_id),
        "qr_url": data.get("qr_url") or structure_url(structure_id),
        "created_at": data.get("created_at"),
        "created_by": data.get("created_by"),
        "updated_at": data.get("updated_at"),
        "updated_by": data.get("updated_by"),
        "final_remark": data.get("final_remark", ""),
        "final_remark_updated_at": data.get("final_remark_updated_at"),
        "final_remark_updated_by": data.get("final_remark_updated_by"),
        "checklist": rows,
        "counts": counts,
    }


def sync_missing_checklist_items(db, structure_id, data, items):
    checklist = data.get("checklist", {}) or {}
    changed = False
    for item in items:
        item_id = item["item_id"]
        if item.get("active", True) and item_id not in checklist:
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
    if changed:
        db.collection("structures").document(structure_id).update({"checklist": checklist})
        data["checklist"] = checklist
    return data


def create_project(db, project, created_by):
    project_id = normalize_project(project)
    if not project_id:
        raise ValueError("Project name is required.")

    timestamp = now_utc()
    ref = db.collection("projects").document(project_id)
    snap = ref.get()
    raw_display_name = clean_display_name(project)
    display_name = (
        display_project_name(project_id)
        if raw_display_name == project_id
        else raw_display_name or display_project_name(project_id)
    )
    project_data = {
        "project_id": project_id,
        "name": project_id,
        "display_name": display_name,
        "block_count": 0,
        "block_structure_counts": {},
        "active": True,
    }
    if snap.exists:
        existing = snap.to_dict() or {}
        ref.update(
            {
                "active": True,
                "display_name": existing.get("display_name") or display_name,
                "updated_at": timestamp,
                "updated_by": created_by,
            }
        )
        existing.update(
            {
                "project_id": project_id,
                "name": project_id,
                "display_name": existing.get("display_name") or display_name,
                "block_count": int(existing.get("block_count") or 0),
                "block_structure_counts": existing.get("block_structure_counts") or {},
                "active": True,
            }
        )
        existing["updated_at"] = timestamp
        existing["updated_by"] = created_by
        return existing

    project_data.update(
        {
            "created_at": timestamp,
            "created_by": created_by,
            "updated_at": timestamp,
            "updated_by": created_by,
        }
    )
    ref.set(project_data)
    return project_data


def update_project_display_name(db, project_id, display_name, updated_by):
    project_id = normalize_project(project_id)
    display_name = clean_display_name(display_name)
    if not project_id:
        raise ValueError("Project is required.")
    if not display_name:
        raise ValueError("Project name is required.")
    if len(display_name) > 120:
        raise ValueError("Project name must be 120 characters or less.")

    timestamp = now_utc()
    ref = db.collection("projects").document(project_id)
    snap = ref.get()
    data = {
        "project_id": project_id,
        "name": project_id,
        "display_name": display_name,
        "active": True,
        "updated_at": timestamp,
        "updated_by": updated_by,
    }
    if snap.exists:
        ref.update(data)
    else:
        data["created_at"] = timestamp
        data["created_by"] = updated_by
        ref.set(data)
    return data


def update_project_block_count(db, project_id, block_count, updated_by):
    project_id = normalize_project(project_id)
    if not project_id:
        raise ValueError("Project is required.")
    try:
        block_count = int(block_count)
    except (TypeError, ValueError):
        raise ValueError("Total blocks must be a number.")
    if block_count < 0 or block_count > 999:
        raise ValueError("Total blocks must be between 0 and 999.")

    timestamp = now_utc()
    ref = db.collection("projects").document(project_id)
    snap = ref.get()
    data = {
        "project_id": project_id,
        "name": project_id,
        "display_name": display_project_name(project_id),
        "block_count": block_count,
        "block_structure_counts": {},
        "active": True,
        "updated_at": timestamp,
        "updated_by": updated_by,
    }
    if snap.exists:
        existing = snap.to_dict() or {}
        data["display_name"] = existing.get("display_name") or data["display_name"]
        ref.update(
            {
                "block_count": block_count,
                "updated_at": timestamp,
                "updated_by": updated_by,
            }
        )
    else:
        data["created_at"] = timestamp
        data["created_by"] = updated_by
        ref.set(data)
    return data


def update_project_block_structure_count(
    db, project_id, block_id, structure_count, updated_by
):
    project_id, block_id = normalize_scope(project_id, block_id)
    if not project_id:
        raise ValueError("Project is required.")
    if not block_id:
        raise ValueError("Block is required.")
    try:
        structure_count = int(structure_count)
    except (TypeError, ValueError):
        raise ValueError("Total structures must be a number.")
    if structure_count < 0 or structure_count > 999999:
        raise ValueError("Total structures must be between 0 and 999999.")

    timestamp = now_utc()
    ref = db.collection("projects").document(project_id)
    snap = ref.get()
    counts = {}
    if snap.exists:
        existing = snap.to_dict() or {}
        counts = existing.get("block_structure_counts") or {}
        if not isinstance(counts, dict):
            counts = {}
    counts[block_id] = structure_count
    block_number = display_block(block_id)

    update_data = {
        "block_structure_counts": counts,
        "updated_at": timestamp,
        "updated_by": updated_by,
    }
    if snap.exists:
        ref.update(update_data)
    else:
        update_data.update(
            {
                "project_id": project_id,
                "name": project_id,
                "display_name": display_project_name(project_id),
                "block_count": int(block_number) if block_number.isdigit() else 0,
                "active": True,
                "created_at": timestamp,
                "created_by": updated_by,
            }
        )
        ref.set(update_data)

    return {
        "project_id": project_id,
        "block": block_id,
        "structure_count": structure_count,
    }


def delete_project(db, project_id):
    project_id = normalize_project(project_id)
    if not project_id:
        raise ValueError("Project is required.")

    structure_count = 0
    for snap in db.collection("structures").stream():
        data = snap.to_dict() or {}
        scope = infer_scope_from_structure_id(snap.id)
        structure_project, _structure_block = normalize_scope(
            data.get("project") or scope["project"],
            data.get("block") or scope["block"],
        )
        if structure_project == project_id:
            structure_count += 1

    if structure_count:
        raise ValueError(
            f"Project has {structure_count} structures. Delete those structures first."
        )

    ref = db.collection("projects").document(project_id)
    if ref.get().exists:
        ref.delete()
    return {"project_id": project_id}


def create_structure(db, structure_id, created_by, base_url=None, block=None, project=None):
    structure_id = normalize_structure_id(structure_id)
    scope = infer_scope_from_structure_id(structure_id)
    project_id, block_id = normalize_scope(
        normalize_project(project) or scope["project"],
        normalize_block(block) or scope["block"],
    )
    if project_id:
        create_project(db, project_id, created_by)
    number_match = re.match(r"^(?:STR-)?(\d+)$", structure_id)
    if number_match:
        structure_id = format_structure_id(
            int(number_match.group(1)),
            block=block_id,
            project=project_id,
        )
    elif project_id and block_id and re.match(
        rf"^{re.escape(project_id)}-STR-\d+$", structure_id
    ):
        number_part = structure_id.split("-STR-")[-1]
        structure_id = f"{project_id}-{block_id}-STR-{number_part}"
    elif project_id and block_id and re.match(
        rf"^{re.escape(block_id)}-STR-\d+$", structure_id
    ):
        structure_id = f"{project_id}-{structure_id}"
    elif project_id and not block_id and re.match(r"^STR-\d+$", structure_id):
        structure_id = f"{project_id}-{structure_id}"
    items = ensure_default_checklist_items(db, created_by)
    ref = db.collection("structures").document(structure_id)
    snap = ref.get()
    if snap.exists:
        data = snap.to_dict()
        updates = {}
        if project_id and data.get("project") != project_id:
            updates["project"] = project_id
        if block_id and data.get("block") != block_id:
            updates["block"] = block_id
        if updates:
            updates.update(
                {
                    "updated_at": now_utc(),
                    "updated_by": created_by,
                }
            )
            ref.update(
                updates
            )
            data.update(updates)
        data = sync_missing_checklist_items(db, structure_id, data, items)
        return build_structure_view(structure_id, data, items)

    data = {
        "structure_id": structure_id,
        "project": project_id,
        "block": block_id,
        "qr_url": structure_url(structure_id, base_url),
        "checklist": build_default_checklist(items),
        "final_remark": "",
        "final_remark_updated_at": None,
        "final_remark_updated_by": None,
        "created_at": now_utc(),
        "created_by": created_by,
        "updated_at": now_utc(),
        "updated_by": created_by,
    }
    ref.set(data)
    return build_structure_view(structure_id, data, items)


def create_structures_bulk(
    db, start, end, created_by, base_url=None, block=None, project=None
):
    project_id, block_id = normalize_scope(project, block)
    return [
        create_structure(
            db,
            format_structure_id(number, block=block_id, project=project_id),
            created_by,
            base_url=base_url,
            block=block_id,
            project=project_id,
        )
        for number in range(start, end + 1)
    ]


def get_next_structure_id(db, block=None, project=None):
    project_id, block_id = normalize_scope(project, block)
    prefix_parts = [item for item in [project_id, block_id] if item]
    id_prefix = "-".join(prefix_parts)
    pattern = (
        rf"^{re.escape(id_prefix)}-STR-(\d+)$"
        if id_prefix
        else r"^STR-(\d+)$"
    )
    max_number = 0
    for snap in db.collection("structures").stream():
        match = re.match(pattern, snap.id.upper())
        if match:
            max_number = max(max_number, int(match.group(1)))
    return format_structure_id(max_number + 1, block=block_id, project=project_id)


def get_structure(db, structure_id):
    structure_id = normalize_structure_id(structure_id)
    items = get_active_checklist_items(db)
    snap = db.collection("structures").document(structure_id).get()
    if not snap.exists:
        return None
    data = sync_missing_checklist_items(db, structure_id, snap.to_dict(), items)
    return build_structure_view(structure_id, data, items)


def list_structures(db, search="", block=None, project=None):
    search = normalize_structure_id(search) if search else ""
    project_id, block_id = normalize_scope(project, block)
    items = get_active_checklist_items(db)
    structures = []
    for snap in db.collection("structures").stream():
        structure_id = snap.id
        data = snap.to_dict()
        scope = infer_scope_from_structure_id(structure_id)
        structure_project, structure_block = normalize_scope(
            data.get("project") or scope["project"],
            data.get("block") or scope["block"],
        )
        if project_id and structure_project != project_id:
            continue
        if block_id and structure_block != block_id:
            continue
        if (
            search
            and search not in structure_id
            and search not in structure_project
            and search not in structure_block
        ):
            continue
        structures.append(build_structure_view(structure_id, data, items))
    return sorted(
        structures,
        key=lambda item: (
            item.get("project") or "",
            item.get("block") or "",
            item["structure_id"],
        ),
    )


def list_project_records(db):
    projects = {}
    for snap in db.collection("projects").stream():
        data = snap.to_dict() or {}
        if data.get("active", True) is False:
            continue
        project_id = normalize_project(data.get("project_id") or snap.id)
        if project_id:
            projects[project_id] = {
                "project_id": project_id,
                "display_name": data.get("display_name") or display_project_name(project_id),
                "block_count": int(data.get("block_count") or 0),
                "block_structure_counts": data.get("block_structure_counts") or {},
            }

    for snap in db.collection("structures").stream():
        data = snap.to_dict() or {}
        scope = infer_scope_from_structure_id(snap.id)
        project_id, _block_id = normalize_scope(
            data.get("project") or scope["project"],
            data.get("block") or scope["block"],
        )
        if project_id and project_id not in projects:
            projects[project_id] = {
                "project_id": project_id,
                "display_name": display_project_name(project_id),
                "block_count": 0,
                "block_structure_counts": {},
            }
    return sorted(
        projects.values(),
        key=lambda item: (item["display_name"].upper(), item["project_id"]),
    )


def list_projects(db):
    return [item["project_id"] for item in list_project_records(db)]


def get_project_display_names(db):
    return {
        item["project_id"]: item["display_name"]
        for item in list_project_records(db)
    }


def get_project_display_name(db, project_id):
    project_id = normalize_project(project_id)
    if not project_id:
        return ""
    snap = db.collection("projects").document(project_id).get()
    if snap.exists:
        data = snap.to_dict() or {}
        return data.get("display_name") or display_project_name(project_id)
    return display_project_name(project_id)


def _percent(part, total):
    return round((part / total) * 100) if total else 0


def _empty_block_summary(block_id):
    return {
        "block": block_id,
        "block_display": display_block(block_id) if block_id else "No block",
        "total_structures": 0,
        "completed_structures": 0,
        "pending_structures": 0,
        "checklist_total": 0,
        "checklist_completed": 0,
        "checklist_pending": 0,
        "checklist_na": 0,
        "completed_percent": 0,
        "pending_percent": 0,
        "structure_percent": 0,
        "pending_structure_percent": 0,
        "selected": False,
    }


def build_project_summary(structures, selected_block=None, block_count=0):
    selected_block_id = normalize_block(selected_block)
    try:
        block_count = max(0, int(block_count or 0))
    except (TypeError, ValueError):
        block_count = 0
    totals = {
        "total_blocks": 0,
        "total_structures": len(structures),
        "completed_structures": 0,
        "pending_structures": 0,
        "checklist_total": 0,
        "checklist_completed": 0,
        "checklist_pending": 0,
        "checklist_na": 0,
        "completed_percent": 0,
        "pending_percent": 0,
        "structure_percent": 0,
        "pending_structure_percent": 0,
        "blocks": [],
    }
    blocks = {}

    for structure in structures:
        counts = structure.get("counts", {}) or {}
        checklist_total = int(counts.get("total") or 0)
        checklist_completed = int(counts.get("completed") or 0)
        checklist_pending = int(counts.get("pending") or 0)
        checklist_na = int(counts.get("na") or 0)
        is_completed = checklist_pending == 0 and checklist_total > 0

        totals["checklist_total"] += checklist_total
        totals["checklist_completed"] += checklist_completed
        totals["checklist_pending"] += checklist_pending
        totals["checklist_na"] += checklist_na
        if is_completed:
            totals["completed_structures"] += 1
        else:
            totals["pending_structures"] += 1

        block_id = normalize_block(structure.get("block") or "")
        block_key = block_id or "__NO_BLOCK__"
        block_row = blocks.setdefault(
            block_key,
            _empty_block_summary(block_id),
        )
        block_row["total_structures"] += 1
        block_row["checklist_total"] += checklist_total
        block_row["checklist_completed"] += checklist_completed
        block_row["checklist_pending"] += checklist_pending
        block_row["checklist_na"] += checklist_na
        if is_completed:
            block_row["completed_structures"] += 1
        else:
            block_row["pending_structures"] += 1

    for number in range(1, block_count + 1):
        block_id = normalize_block(str(number))
        blocks.setdefault(block_id, _empty_block_summary(block_id))

    block_rows = []
    for block_row in blocks.values():
        block_row["completed_percent"] = _percent(
            block_row["checklist_completed"], block_row["checklist_total"]
        )
        block_row["pending_percent"] = _percent(
            block_row["checklist_pending"], block_row["checklist_total"]
        )
        block_row["structure_percent"] = _percent(
            block_row["completed_structures"], block_row["total_structures"]
        )
        block_row["pending_structure_percent"] = _percent(
            block_row["pending_structures"], block_row["total_structures"]
        )
        block_row["selected"] = bool(
            selected_block_id and block_row["block"] == selected_block_id
        )
        block_rows.append(block_row)

    selected_block_exists = any(
        item["block"] == selected_block_id for item in block_rows
    )
    if selected_block_id and not selected_block_exists:
        selected_row = _empty_block_summary(selected_block_id)
        selected_row["selected"] = True
        block_rows.append(selected_row)
    else:
        selected_row = next(
            (item for item in block_rows if item["block"] == selected_block_id),
            _empty_block_summary(selected_block_id),
        )

    block_rows.sort(
        key=lambda item: (
            1 if not item["block"] else 0,
            0 if str(item["block_display"]).isdigit() else 1,
            int(item["block_display"]) if str(item["block_display"]).isdigit() else 0,
            str(item["block_display"]),
        )
    )

    totals["total_blocks"] = sum(1 for item in block_rows if item["block"])
    totals["completed_percent"] = _percent(
        totals["checklist_completed"], totals["checklist_total"]
    )
    totals["pending_percent"] = _percent(
        totals["checklist_pending"], totals["checklist_total"]
    )
    totals["structure_percent"] = _percent(
        totals["completed_structures"], totals["total_structures"]
    )
    totals["pending_structure_percent"] = _percent(
        totals["pending_structures"], totals["total_structures"]
    )
    totals["blocks"] = block_rows
    totals["configured_block_count"] = block_count
    totals["selected_block"] = selected_block_id
    totals["selected_block_exists"] = selected_block_exists
    totals["selected_block_summary"] = selected_row
    return totals


def get_item_label(db, item_id):
    snap = db.collection("checklist_items").document(item_id).get()
    if snap.exists:
        return snap.to_dict().get("label", item_id)
    return item_id


def update_checklist_status(db, structure_id, item_id, new_status, user):
    structure_id = normalize_structure_id(structure_id)
    if new_status not in STATUS_OPTIONS:
        raise ValueError("Invalid checklist status.")

    ref = db.collection("structures").document(structure_id)
    snap = ref.get()
    if not snap.exists:
        return None

    data = snap.to_dict()
    scope = infer_scope_from_structure_id(structure_id)
    project_id, block_id = normalize_scope(
        data.get("project") or scope["project"],
        data.get("block") or scope["block"],
    )
    checklist = data.get("checklist", {}) or {}
    item_data = checklist.get(item_id, {}) or {}
    previous_status = item_data.get("status", "pending")
    item_label = item_data.get("label") or get_item_label(db, item_id)
    timestamp_utc = now_utc()
    timestamp_local = now_local()
    email = user.get("email") or "unknown"

    item_data.update(
        {
            "label": item_label,
            "status": new_status,
            "updated_at": timestamp_utc,
            "updated_by": email,
        }
    )
    checklist[item_id] = item_data
    ref.update(
        {
            "checklist": checklist,
            "updated_at": timestamp_utc,
            "updated_by": email,
        }
    )

    if previous_status != new_status:
        db.collection("history").add(
            {
                "structure_id": structure_id,
                "project": project_id,
                "block": block_id,
                "item_id": item_id,
                "item_label": item_label,
                "change_type": "status",
                "previous_status": previous_status,
                "new_status": new_status,
                "updated_by": email,
                "updated_by_uid": user.get("uid"),
                "updated_at": timestamp_utc,
                "updated_date": timestamp_local.strftime("%Y-%m-%d"),
                "updated_time": timestamp_local.strftime("%H:%M:%S"),
                "timezone": settings.app_timezone,
            }
        )

    return get_structure(db, structure_id)


def update_checklist_remark(db, structure_id, item_id, remark, user):
    structure_id = normalize_structure_id(structure_id)
    remark = (remark or "").strip()
    if len(remark) > 1000:
        raise ValueError("Remark must be 1000 characters or less.")

    ref = db.collection("structures").document(structure_id)
    snap = ref.get()
    if not snap.exists:
        return None

    data = snap.to_dict()
    scope = infer_scope_from_structure_id(structure_id)
    project_id, block_id = normalize_scope(
        data.get("project") or scope["project"],
        data.get("block") or scope["block"],
    )
    checklist = data.get("checklist", {}) or {}
    item_data = checklist.get(item_id, {}) or {}
    previous_remark = item_data.get("remark", "")
    item_label = item_data.get("label") or get_item_label(db, item_id)
    timestamp_utc = now_utc()
    timestamp_local = now_local()
    email = user.get("email") or "unknown"

    item_data.update(
        {
            "label": item_label,
            "status": item_data.get("status", "pending"),
            "remark": remark,
            "remark_updated_at": timestamp_utc,
            "remark_updated_by": email,
        }
    )
    checklist[item_id] = item_data
    ref.update(
        {
            "checklist": checklist,
            "updated_at": timestamp_utc,
            "updated_by": email,
        }
    )

    if previous_remark != remark:
        db.collection("history").add(
            {
                "structure_id": structure_id,
                "project": project_id,
                "block": block_id,
                "item_id": item_id,
                "item_label": item_label,
                "change_type": "remark",
                "previous_status": item_data.get("status", "pending"),
                "new_status": item_data.get("status", "pending"),
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

    return get_structure(db, structure_id)


def update_final_remark(db, structure_id, remark, user):
    structure_id = normalize_structure_id(structure_id)
    remark = (remark or "").strip()
    if len(remark) > 2000:
        raise ValueError("Final remark must be 2000 characters or less.")

    ref = db.collection("structures").document(structure_id)
    snap = ref.get()
    if not snap.exists:
        return None

    data = snap.to_dict()
    scope = infer_scope_from_structure_id(structure_id)
    project_id, block_id = normalize_scope(
        data.get("project") or scope["project"],
        data.get("block") or scope["block"],
    )
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
        db.collection("history").add(
            {
                "structure_id": structure_id,
                "project": project_id,
                "block": block_id,
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

    return get_structure(db, structure_id)


def add_checklist_item(db, label, created_by):
    base_id = slugify(label)
    item_id = base_id
    suffix = 2
    while db.collection("checklist_items").document(item_id).get().exists:
        item_id = f"{base_id}_{suffix}"
        suffix += 1

    existing = list(db.collection("checklist_items").stream())
    max_order = max((doc.to_dict().get("order", 0) for doc in existing), default=0)
    db.collection("checklist_items").document(item_id).set(
        {
            "item_id": item_id,
            "label": label,
            "active": True,
            "order": max_order + 10,
            "created_at": now_utc(),
            "created_by": created_by,
        }
    )
    return item_id


def deactivate_checklist_item(db, item_id, updated_by):
    db.collection("checklist_items").document(item_id).update(
        {
            "active": False,
            "updated_at": now_utc(),
            "updated_by": updated_by,
        }
    )


def update_checklist_item_label(db, item_id, label, updated_by):
    label = clean_display_name(label)
    if not label:
        raise ValueError("Checklist item name is required.")
    if len(label) > 160:
        raise ValueError("Checklist item name must be 160 characters or less.")

    timestamp = now_utc()
    item_ref = db.collection("checklist_items").document(item_id)
    snap = item_ref.get()
    if not snap.exists:
        raise ValueError("Checklist item not found.")

    item_ref.update(
        {
            "label": label,
            "updated_at": timestamp,
            "updated_by": updated_by,
        }
    )

    batch = db.batch()
    count = 0
    for structure in db.collection("structures").stream():
        data = structure.to_dict() or {}
        checklist = data.get("checklist", {}) or {}
        if item_id not in checklist:
            continue
        checklist[item_id]["label"] = label
        batch.update(
            structure.reference,
            {
                "checklist": checklist,
                "updated_at": timestamp,
                "updated_by": updated_by,
            },
        )
        count += 1
        if count % 450 == 0:
            batch.commit()
            batch = db.batch()
    if count % 450:
        batch.commit()

    history_batch = db.batch()
    history_count = 0
    for history in db.collection("history").where(
        filter=firestore.FieldFilter("item_id", "==", item_id)
    ).stream():
        history_batch.update(history.reference, {"item_label": label})
        history_count += 1
        if history_count % 450 == 0:
            history_batch.commit()
            history_batch = db.batch()
    if history_count % 450:
        history_batch.commit()

    return {
        "item_id": item_id,
        "label": label,
        "updated_structures": count,
        "updated_history": history_count,
    }


def get_history(db, structure_id=None, project=None, block=None, limit=300):
    project_id, block_id = normalize_scope(project, block)
    if structure_id:
        docs = db.collection("history").where(
            filter=firestore.FieldFilter(
                "structure_id", "==", normalize_structure_id(structure_id)
            )
        ).stream()
    else:
        docs = db.collection("history").stream()

    rows = []
    for snap in docs:
        data = snap.to_dict()
        data["history_id"] = snap.id
        scope = infer_scope_from_structure_id(data.get("structure_id", ""))
        data["project"], data["block"] = normalize_scope(
            data.get("project") or scope["project"],
            data.get("block") or scope["block"],
        )
        if project_id and data["project"] != project_id:
            continue
        if block_id and data["block"] != block_id:
            continue
        rows.append(data)

    rows.sort(key=lambda item: item.get("updated_at") or datetime.min, reverse=True)
    return rows[:limit]


def delete_structure(db, structure_id, delete_history=True):
    structure_id = normalize_structure_id(structure_id)
    ref = db.collection("structures").document(structure_id)
    snap = ref.get()
    if not snap.exists:
        return None

    data = snap.to_dict() or {}
    scope = infer_scope_from_structure_id(structure_id)
    project_id, block_id = normalize_scope(
        data.get("project") or scope["project"],
        data.get("block") or scope["block"],
    )
    deleted = {
        "structure_id": structure_id,
        "project": project_id,
        "block": block_id,
    }

    if delete_history:
        batch = db.batch()
        count = 0
        for history in db.collection("history").where(
            filter=firestore.FieldFilter("structure_id", "==", structure_id)
        ).stream():
            batch.delete(history.reference)
            count += 1
            if count % 450 == 0:
                batch.commit()
                batch = db.batch()
        if count % 450:
            batch.commit()

    ref.delete()
    return deleted
