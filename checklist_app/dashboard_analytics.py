from datetime import datetime, timezone
from urllib.parse import quote, urlencode


STALE_AFTER_DAYS = 7
CRITICAL_AFTER_DAYS = 14


def _as_utc(value):
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            return None
    return None


def _age_days(record, now):
    updated_at = _as_utc(record.get("updated_at") or record.get("created_at"))
    if not updated_at:
        return None
    return max(0, int((now - updated_at).total_seconds() // 86400))


def _counts(record):
    values = record.get("counts") or {}
    return {
        "total": int(values.get("total") or 0),
        "completed": int(values.get("completed") or 0),
        "pending": int(values.get("pending") or 0),
        "na": int(values.get("na") or 0),
        "progress": int(values.get("progress") or 0),
    }


def _priority_item(record, kind, now):
    counts = _counts(record)
    if counts["pending"] <= 0:
        return None

    age_days = _age_days(record, now)
    not_started = counts["completed"] == 0
    missing_identity = kind == "equipment" and not str(
        record.get("equipment_identification") or ""
    ).strip()
    missing_vendor = kind == "equipment" and not str(
        record.get("vendor_name") or ""
    ).strip()
    stale = age_days is None or age_days >= STALE_AFTER_DAYS

    ratio = counts["pending"] / counts["total"] if counts["total"] else 1
    score = round(ratio * 35) + min(counts["pending"], 20)
    if not_started:
        score += 12
    if missing_identity:
        score += 25
    if missing_vendor:
        score += 5
    if age_days is None:
        score += 15
    elif age_days >= CRITICAL_AFTER_DAYS:
        score += 30
    elif age_days >= STALE_AFTER_DAYS:
        score += 20

    reasons = []
    if missing_identity:
        reasons.append("Equipment ID missing")
    if age_days is None:
        reasons.append("No update recorded")
    elif age_days >= STALE_AFTER_DAYS:
        reasons.append(f"No update for {age_days} days")
    if not_started:
        reasons.append("Not started")
    reasons.append(f'{counts["pending"]} points pending')
    if missing_vendor:
        reasons.append("Vendor missing")

    if age_days is None:
        age_label = "No update"
    elif age_days == 0:
        age_label = "Updated today"
    elif age_days == 1:
        age_label = "Updated 1 day ago"
    else:
        age_label = f"Updated {age_days} days ago"

    block = record.get("block") or ""
    block_display = record.get("block_display") or str(block).removeprefix("BLOCK-")
    if kind == "equipment":
        equipment_id = record.get("equipment_id") or ""
        title = str(record.get("equipment_identification") or "").strip()
        if not title:
            title = f'{record.get("template_name") or "Equipment"} #{record.get("record_number") or ""}'.strip()
        subtitle = record.get("template_name") or "Equipment checklist"
        url = f"/equipment/{quote(str(equipment_id), safe='')}" if equipment_id else ""
    else:
        structure_id = record.get("structure_id") or ""
        title = f'Structure {record.get("structure_number") or structure_id}'
        subtitle = "Structure checklist"
        url = f"/admin/structures/{quote(str(structure_id), safe='')}" if structure_id else ""

    if age_days is None or age_days >= CRITICAL_AFTER_DAYS:
        severity = "critical"
        severity_label = "Critical"
    elif stale or missing_identity:
        severity = "high"
        severity_label = "High"
    else:
        severity = "normal"
        severity_label = "Next"

    return {
        "kind": kind,
        "title": title,
        "subtitle": subtitle,
        "block": block,
        "block_display": block_display or "-",
        "completed_points": counts["completed"],
        "pending_points": counts["pending"],
        "total_points": counts["total"],
        "progress": counts["progress"],
        "not_started": not_started,
        "stale": stale,
        "age_days": age_days,
        "age_label": age_label,
        "missing_identity": missing_identity,
        "missing_vendor": missing_vendor,
        "reason": " · ".join(reasons[:3]),
        "severity": severity,
        "severity_label": severity_label,
        "priority_score": score,
        "url": url,
    }


def build_dashboard_intelligence(
    structures,
    equipment_records,
    block_rows=None,
    template_summaries=None,
    project="",
    block="",
    now=None,
):
    now = _as_utc(now) or datetime.now(timezone.utc)
    structures = structures or []
    equipment_records = equipment_records or []
    all_records = [(item, "structure") for item in structures] + [
        (item, "equipment") for item in equipment_records
    ]

    total_points = sum(_counts(item)["total"] for item, _kind in all_records)
    completed_points = sum(
        _counts(item)["completed"] for item, _kind in all_records
    )
    pending_points = sum(_counts(item)["pending"] for item, _kind in all_records)
    na_points = sum(_counts(item)["na"] for item, _kind in all_records)
    progress = (
        round((completed_points + na_points) * 100 / total_points)
        if total_points
        else 0
    )

    priority_items = []
    active_work = 0
    not_started = 0
    stale_work = 0
    updated_last_7_days = 0
    missing_identity = 0
    missing_vendor = 0
    for record, kind in all_records:
        counts = _counts(record)
        age_days = _age_days(record, now)
        if age_days is not None and age_days < STALE_AFTER_DAYS:
            updated_last_7_days += 1
        if counts["pending"] > 0 and counts["completed"] > 0:
            active_work += 1
        if counts["pending"] > 0 and counts["completed"] == 0:
            not_started += 1
        if counts["pending"] > 0 and (
            age_days is None or age_days >= STALE_AFTER_DAYS
        ):
            stale_work += 1
        if kind == "equipment":
            if not str(record.get("equipment_identification") or "").strip():
                missing_identity += 1
            if not str(record.get("vendor_name") or "").strip():
                missing_vendor += 1
        item = _priority_item(record, kind, now)
        if item:
            priority_items.append(item)

    priority_items.sort(
        key=lambda item: (
            -item["priority_score"],
            -item["pending_points"],
            item["title"],
        )
    )

    block_pressure = []
    for row in block_rows or []:
        if not row.get("block") or int(row.get("work_total_points") or 0) <= 0:
            continue
        row_progress = int(row.get("work_progress") or 0)
        row_pending = int(row.get("work_pending_points") or 0)
        if row_pending <= 0:
            state, state_label = "complete", "Complete"
        elif row_progress < 25:
            state, state_label = "critical", "Needs focus"
        elif row_progress < 75:
            state, state_label = "active", "In progress"
        else:
            state, state_label = "healthy", "On track"
        block_id = row.get("block") or ""
        block_pressure.append(
            {
                "block": block_id,
                "block_display": row.get("block_display") or block_id,
                "progress": row_progress,
                "pending_points": row_pending,
                "total_points": int(row.get("work_total_points") or 0),
                "pending_structures": int(row.get("pending_structures") or 0),
                "pending_equipment": int(
                    row.get("equipment_pending_records") or 0
                ),
                "state": state,
                "state_label": state_label,
                "url": "/admin?" + urlencode(
                    {"project": project, "block": block_id}
                ),
            }
        )
    block_pressure.sort(
        key=lambda item: (
            item["progress"],
            -item["pending_points"],
            str(item["block_display"]),
        )
    )

    bottlenecks = []
    for item in template_summaries or []:
        total_records = int(item.get("total_records") or 0)
        pending = int(item.get("pending_points") or 0)
        if total_records <= 0 or pending <= 0:
            continue
        item_blocks = list(item.get("blocks") or [])
        target_block = block or (item_blocks[0] if len(item_blocks) == 1 else "")
        url = ""
        if project and target_block and item.get("template_id"):
            url = "/admin/equipment-dashboard/{}?{}".format(
                quote(str(item["template_id"]), safe=""),
                urlencode({"project": project, "block": target_block}),
            )
        bottlenecks.append(
            {
                "template_id": item.get("template_id") or "",
                "name": item.get("name") or "Checklist",
                "format_no": item.get("format_no") or "",
                "progress": int(item.get("progress") or 0),
                "pending_points": pending,
                "total_points": int(item.get("total_points") or 0),
                "pending_records": int(item.get("pending_records") or 0),
                "not_started_records": int(item.get("not_started_records") or 0),
                "url": url,
            }
        )
    bottlenecks.sort(
        key=lambda item: (
            -item["pending_points"],
            item["progress"],
            item["name"],
        )
    )

    insights = []
    if not total_points:
        insights.append("Create the first checklist record to start live tracking.")
    else:
        if stale_work:
            insights.append(
                f"{stale_work} open record{'s' if stale_work != 1 else ''} have no update for 7+ days."
            )
        if missing_identity:
            insights.append(
                f"{missing_identity} equipment record{'s' if missing_identity != 1 else ''} need an ID for reliable tracking."
            )
        if block_pressure:
            weakest = block_pressure[0]
            insights.append(
                f'Block {weakest["block_display"]} needs the most attention at {weakest["progress"]}% progress.'
            )
        if bottlenecks:
            top = bottlenecks[0]
            insights.append(
                f'{top["name"]} is the largest checklist bottleneck with {top["pending_points"]} pending points.'
            )
        if not insights:
            insights.append("No stale records or data-quality gaps need attention.")

    return {
        "has_work": total_points > 0,
        "scope": "block" if block else "project",
        "progress": progress,
        "total_points": total_points,
        "completed_points": completed_points,
        "pending_points": pending_points,
        "open_records": sum(
            1 for item, _kind in all_records if _counts(item)["pending"] > 0
        ),
        "active_work": active_work,
        "not_started": not_started,
        "stale_work": stale_work,
        "updated_last_7_days": updated_last_7_days,
        "missing_identity": missing_identity,
        "missing_vendor": missing_vendor,
        "data_gaps": missing_identity + missing_vendor,
        "priority_items": priority_items[:8],
        "priority_total": len(priority_items),
        "block_pressure": block_pressure[:8],
        "bottlenecks": bottlenecks[:8],
        "insights": insights[:4],
        "stale_after_days": STALE_AFTER_DAYS,
    }
