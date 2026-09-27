import re


CABLE_TEMPLATE_IDS = {
    "cable-laying",
    "string-cable",
    "lt-cable-termination",
    "dc-cable-termination",
    "ht-cable-termination",
    "cable-glanding",
    "6-sqmm-dc-cable",
}

TEST_KEYWORDS = (
    "test",
    "testing",
    "commissioning",
    "pre-commissioning",
    "insulation-resistance",
    "insulation resistance",
    "earth-resistance",
    "voc",
)

PROFILE_FIELDS = {
    "cable": [
        {
            "key": "from_location",
            "label": "From Equipment / Location",
            "placeholder": "e.g. IDT-1",
            "required": True,
        },
        {
            "key": "to_location",
            "label": "To Equipment / Location",
            "placeholder": "e.g. HT PANEL-1",
            "required": True,
        },
        {
            "key": "run_number",
            "label": "Run / Feeder No.",
            "placeholder": "e.g. RUN-01 or FEEDER-02",
        },
        {
            "key": "route_reference",
            "label": "Route / Drawing Reference",
            "placeholder": "Enter route or drawing reference",
        },
    ],
    "test": [
        {
            "key": "test_reference",
            "label": "Test Reference",
            "placeholder": "e.g. IR-B01-0001",
        },
        {
            "key": "test_date",
            "label": "Test Date",
            "placeholder": "YYYY-MM-DD",
            "input_type": "date",
        },
        {
            "key": "location_reference",
            "label": "Location / Drawing Reference",
            "placeholder": "Enter location or drawing reference",
        },
    ],
    "equipment": [
        {
            "key": "make_model",
            "label": "Make / Model",
            "placeholder": "Enter make or model",
        },
        {
            "key": "rating_capacity",
            "label": "Rating / Capacity",
            "placeholder": "e.g. 5 MVA or 33 kV",
        },
        {
            "key": "location_reference",
            "label": "Location / Drawing Reference",
            "placeholder": "Enter location or drawing reference",
        },
    ],
}

IDENTITY_DETAIL_LIMITS = {
    field["key"]: 160
    for fields in PROFILE_FIELDS.values()
    for field in fields
}

TEMPLATE_CODE_OVERRIDES = {
    "smb-installation": "SMBI",
    "scada-installation": "SCI",
}


def _profile_type(template):
    template_id = str(template.get("template_id") or "").lower()
    name = str(template.get("name") or "").lower()
    if template_id in CABLE_TEMPLATE_IDS:
        return "cable"
    if any(keyword in template_id or keyword in name for keyword in TEST_KEYWORDS):
        return "test"
    return "equipment"


def _template_code(name):
    words = re.findall(r"[A-Z0-9]+", str(name or "").upper())
    code = "".join(word[0] for word in words if word not in {"OF", "AND"})
    if len(code) < 2 and words:
        code = words[0][:4]
    return (code or "WORK")[:6]


def get_identity_profile(template):
    profile_type = _profile_type(template)
    template_id = str(template.get("template_id") or "").lower()
    if profile_type == "cable":
        primary_label = "Cable / Circuit ID"
        primary_placeholder = "e.g. AC-B01-0001"
        specification_label = "Cable Size / Type"
        specification_placeholder = "e.g. 3C x 240 SQMM"
    elif profile_type == "test":
        primary_label = "Equipment / Circuit ID"
        primary_placeholder = "e.g. IDT-1 or FEEDER-01"
        specification_label = "Test Standard / Rating"
        specification_placeholder = "Enter standard, voltage or rating"
    else:
        primary_label = "Equipment / Asset ID"
        primary_placeholder = "e.g. SCB-1 or IDT-1"
        specification_label = "Size / Rating / Specification"
        specification_placeholder = "Enter size, rating or specification"
    return {
        "type": profile_type,
        "code": TEMPLATE_CODE_OVERRIDES.get(
            template_id, _template_code(template.get("name"))
        ),
        "primary_label": primary_label,
        "primary_placeholder": primary_placeholder,
        "specification_label": specification_label,
        "specification_placeholder": specification_placeholder,
        "fields": [dict(field) for field in PROFILE_FIELDS[profile_type]],
    }


def format_work_id(template, project, block_display, record_number):
    profile = get_identity_profile(template)
    project_key = re.sub(r"[^A-Z0-9]+", "-", str(project or "").upper()).strip("-")
    block_key = re.sub(r"[^A-Z0-9]+", "", str(block_display or "").upper()) or "0"
    record_key = re.sub(r"[^A-Z0-9]+", "", str(record_number or "1").upper()) or "1"
    if record_key.isdigit():
        record_key = record_key.zfill(4)
    return f"{project_key or 'PROJECT'}-{profile['code']}-B{block_key}-{record_key}"


def identity_details_text(details, profile):
    details = details or {}
    values = []
    for field in profile.get("fields", []):
        value = str(details.get(field["key"]) or "").strip()
        if value:
            values.append(f"{field['label']}: {value}")
    return " | ".join(values)
