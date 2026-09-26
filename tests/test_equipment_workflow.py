import copy
import sys
import unittest

from openpyxl import load_workbook

import checklist_app as app_module
from checklist_app.equipment_catalog import get_equipment_catalog, get_equipment_template
from checklist_app.equipment_services import (
    create_equipment_checklist,
    delete_equipment_checklist,
    get_equipment_history,
    list_equipment_checklists,
    update_equipment_final_remark,
    update_equipment_measurements,
    update_equipment_remark,
    update_equipment_status,
)
from checklist_app.exports import export_all_xlsx, export_equipment_csv


class FakeSnapshot:
    def __init__(self, reference, data):
        self.reference = reference
        self.id = reference.id
        self._data = copy.deepcopy(data)
        self.exists = data is not None

    def to_dict(self):
        return copy.deepcopy(self._data)


class FakeDocument:
    def __init__(self, database, collection_name, document_id):
        self.database = database
        self.collection_name = collection_name
        self.id = document_id

    def get(self):
        return FakeSnapshot(
            self, self.database.data[self.collection_name].get(self.id)
        )

    def set(self, data):
        self.database.data[self.collection_name][self.id] = copy.deepcopy(data)

    def update(self, data):
        self.database.data[self.collection_name][self.id].update(copy.deepcopy(data))

    def delete(self):
        self.database.data[self.collection_name].pop(self.id, None)


class FakeQuery:
    def __init__(self, collection, field=None, value=None, maximum=None):
        self.collection = collection
        self.field = field
        self.value = value
        self.maximum = maximum

    def stream(self):
        rows = self.collection.stream()
        if self.field:
            rows = [
                row
                for row in rows
                if (row.to_dict() or {}).get(self.field) == self.value
            ]
        return rows[: self.maximum] if self.maximum else rows

    def order_by(self, *_args, **_kwargs):
        return self

    def limit(self, maximum):
        self.maximum = maximum
        return self


class FakeCollection:
    def __init__(self, database, name):
        self.database = database
        self.name = name
        database.data.setdefault(name, {})

    def document(self, document_id):
        return FakeDocument(self.database, self.name, document_id)

    def stream(self):
        return [
            FakeSnapshot(FakeDocument(self.database, self.name, key), value)
            for key, value in self.database.data[self.name].items()
        ]

    def add(self, data):
        reference = self.document(f"auto-{len(self.database.data[self.name]) + 1}")
        reference.set(data)
        return None, reference

    def where(self, filter=None, **_kwargs):
        return FakeQuery(
            self,
            getattr(filter, "field_path", None),
            getattr(filter, "value", None),
        )

    def order_by(self, *_args, **_kwargs):
        return FakeQuery(self)

    def limit(self, maximum):
        return FakeQuery(self, maximum=maximum)


class FakeBatch:
    def __init__(self):
        self.operations = []

    def delete(self, reference):
        self.operations.append(("delete", reference, None))

    def set(self, reference, data):
        self.operations.append(("set", reference, data))

    def commit(self):
        for action, reference, data in self.operations:
            if action == "delete":
                reference.delete()
            else:
                reference.set(data)
        self.operations = []


class FakeFirestore:
    def __init__(self):
        self.data = {}

    def collection(self, name):
        return FakeCollection(self, name)

    def batch(self):
        return FakeBatch()


def build_fixture():
    database = FakeFirestore()
    database.collection("checklist_items").document("dummy").set(
        {"label": "Dummy", "order": 10, "active": True}
    )
    user = {"uid": "admin", "email": "admin@example.com"}
    cable_laying = create_equipment_checklist(
        database,
        "100 MW AKOLA SITE",
        "1",
        "cable-laying",
        "01",
        user["email"],
        base_url="https://quality.example.com",
    )
    transformer = create_equipment_checklist(
        database,
        "100 MW AKOLA SITE",
        "1",
        "transformer-installation",
        "01",
        user["email"],
        base_url="https://quality.example.com",
    )
    cable_laying = update_equipment_status(
        database, cable_laying["equipment_id"], "point-001", "completed", user
    )
    cable_laying = update_equipment_remark(
        database,
        cable_laying["equipment_id"],
        "point-001",
        "Cable type verified",
        user,
    )
    cable_laying = update_equipment_final_remark(
        database,
        cable_laying["equipment_id"],
        "Ready for next inspection",
        user,
    )
    cable_laying = update_equipment_measurements(
        database,
        cable_laying["equipment_id"],
        "point-007",
        {"observation": "12 x cable OD"},
        user,
    )
    return database, user, cable_laying, transformer


def build_test_app(database, logged_in=False):
    admin = {
        "uid": "admin",
        "email": "admin@example.com",
        "is_admin": True,
        "all_projects": True,
        "projects": [],
    }
    app_module.get_db = lambda: database
    app_module.current_user = (lambda: admin) if logged_in else (lambda: None)
    return app_module.create_app()


class EquipmentWorkflowTests(unittest.TestCase):
    def test_create_update_export_and_delete(self):
        database, user, record, _transformer = build_fixture()
        self.assertEqual(record["counts"]["completed"], 1)
        self.assertEqual(record["counts"]["pending"], 11)
        self.assertEqual(record["checklist"][0]["remark"], "Cable type verified")
        self.assertEqual(
            record["checklist"][6]["measurements"]["observation"],
            "12 x cable OD",
        )
        self.assertEqual(record["checklist"][6]["check_type"], "Measurement")
        self.assertEqual(len(get_equipment_history(database, record["equipment_id"])), 4)

        csv_text = export_equipment_csv(
            database, project="100 MW AKOLA SITE", block="1"
        )
        self.assertIn("Cable Laying", csv_text)
        self.assertIn("Cable type verified", csv_text)
        self.assertIn("12 x cable OD", csv_text)
        self.assertIn("Measured Value / Observation", csv_text)
        workbook = load_workbook(
            export_all_xlsx(database, project="100 MW AKOLA SITE", block="1")
        )
        self.assertEqual(
            workbook.sheetnames,
            ["Structures", "History", "Equipment Checklists", "Equipment History"],
        )
        self.assertIn(
            "Observations / Measurements",
            [cell.value for cell in workbook["Equipment Checklists"][1]],
        )
        self.assertIn(
            "Activity / Section",
            [cell.value for cell in workbook["Equipment Checklists"][1]],
        )

        deleted = delete_equipment_checklist(database, record["equipment_id"])
        self.assertEqual(deleted["equipment_id"], record["equipment_id"])
        self.assertEqual(
            len(list_equipment_checklists(database, project="100 MW AKOLA SITE")), 1
        )

    def test_public_page_api_and_qr_are_read_only(self):
        database, _user, record, _transformer = build_fixture()
        client = build_test_app(database).test_client()

        page = client.get(f"/equipment/{record['equipment_id']}")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Cable Laying", page.data)
        self.assertIn(b"12 x cable OD", page.data)
        self.assertNotIn(b"Cable type verified", page.data)
        self.assertNotIn(b"Save Observation", page.data)

        payload = client.get(f"/api/equipment/{record['equipment_id']}").get_json()
        self.assertNotIn("remark", payload["checklist"][0])
        reading_point = next(
            item for item in payload["checklist"] if item["item_id"] == "point-007"
        )
        self.assertEqual(
            reading_point["measurements"]["observation"], "12 x cable OD"
        )
        self.assertNotIn("measurement_updated_by", reading_point)
        qr_response = client.get(f"/equipment/{record['equipment_id']}/qr.png")
        self.assertEqual(qr_response.status_code, 200)
        self.assertEqual(qr_response.mimetype, "image/png")

    def test_authorized_user_can_save_and_clear_reading(self):
        database, _user, record, _transformer = build_fixture()
        client = build_test_app(database, logged_in=True).test_client()
        endpoint = (
            f"/api/equipment/{record['equipment_id']}/items/point-007/measurements"
        )

        response = client.post(
            endpoint, json={"measurements": {"observation": "15 x cable OD"}}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json()["checklist"][6]["measurements"]["observation"],
            "15 x cable OD",
        )

        response = client.post(endpoint, json={"measurements": {"observation": ""}})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json()["checklist"][6]["measurements"]["observation"], ""
        )

        invalid = client.post(
            endpoint,
            json={"measurements": {"unknown_field": "Not allowed"}},
        )
        self.assertEqual(invalid.status_code, 400)

    def test_every_excel_checklist_has_correct_observation_schema(self):
        catalog = get_equipment_catalog()
        self.assertEqual(len(catalog), 44)
        self.assertEqual(sum(len(item["points"]) for item in catalog), 576)
        self.assertTrue(
            all(point.get("measurement_fields") for item in catalog for point in item["points"])
        )
        expected_field_counts = {
            "ert": 3,
            "voc-testing": 7,
            "ir": 11,
            "imp": 3,
            "inverter-pre-commisioning": 4,
            "voc": 5,
            "lv-ir": 12,
        }
        for template_id, field_count in expected_field_counts.items():
            template = get_equipment_template(template_id)
            self.assertEqual(len(template["points"][0]["measurement_fields"]), field_count)

    def test_every_excel_checklist_can_save_all_observation_fields(self):
        database = FakeFirestore()
        user = {"email": "qa@example.com", "uid": "qa-user"}

        for template in get_equipment_catalog():
            record = create_equipment_checklist(
                database,
                "100 MW AKOLA SITE",
                "1",
                template["template_id"],
                "01",
                user["email"],
                base_url="https://quality.example.com",
            )
            first_point = record["checklist"][0]
            values = {
                field["key"]: f"Test {field['label']}"
                for field in first_point["measurement_fields"]
            }
            updated = update_equipment_measurements(
                database,
                record["equipment_id"],
                first_point["item_id"],
                values,
                user,
            )
            self.assertEqual(updated["checklist"][0]["measurements"], values)

    def test_block_dashboard_contains_catalog_and_tracking(self):
        database, _user, record, _transformer = build_fixture()
        client = build_test_app(database, logged_in=True).test_client()
        url = "/admin?project=100-MW-AKOLA-SITE&block=BLOCK-1"
        page = client.get(url)
        self.assertEqual(page.status_code, 200)
        for expected in [b"44 types", b"Cable Laying", b"12 points", b"Completed points"]:
            self.assertIn(expected, page.data)

        payload = client.get(
            "/admin/api/structures?project=100-MW-AKOLA-SITE&block=BLOCK-1"
        ).get_json()
        self.assertEqual(payload["equipment_summary"]["total_records"], 2)
        self.assertEqual(payload["equipment_records"][0]["equipment_id"], record["equipment_id"])


if __name__ == "__main__":
    if "--preview" in sys.argv:
        preview_db, preview_user, preview_record, _preview_transformer = build_fixture()
        preview_ir = create_equipment_checklist(
            preview_db,
            "100 MW AKOLA SITE",
            "1",
            "ir",
            "01",
            preview_user["email"],
            base_url="https://quality.example.com",
        )
        preview_ir = update_equipment_measurements(
            preview_db,
            preview_ir["equipment_id"],
            "point-001",
            {
                "identification": "SCB-1",
                "cable_length": "250 m",
                "continuity": "OK",
                "r_e": "850",
                "y_e": "870",
                "b_e": "860",
            },
            preview_user,
        )
        preview_app = build_test_app(preview_db, logged_in=True)
        print(f"Preview equipment ID: {preview_record['equipment_id']}")
        print(f"Preview IR ID: {preview_ir['equipment_id']}")
        preview_app.run(host="127.0.0.1", port=5001, debug=False)
    else:
        unittest.main()
