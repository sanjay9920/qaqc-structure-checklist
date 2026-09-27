import json
from functools import lru_cache
from pathlib import Path

from .identity_profiles import get_identity_profile


CATALOG_PATH = Path(__file__).resolve().parent / "data" / "equipment_catalog.json"


@lru_cache(maxsize=1)
def get_equipment_catalog():
    payload = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    templates = payload.get("templates", [])
    for template in templates:
        template["point_count"] = len(template.get("points", []))
        template["identity_profile"] = get_identity_profile(template)
    return sorted(templates, key=lambda item: (item.get("order", 0), item["name"]))


def get_equipment_template(template_id):
    template_id = (template_id or "").strip().lower()
    return next(
        (
            template
            for template in get_equipment_catalog()
            if template["template_id"] == template_id
        ),
        None,
    )
