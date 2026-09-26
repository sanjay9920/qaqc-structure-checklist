import copy
import sys
import unittest

from openpyxl import load_workbook

import checklist_app as app_module
from checklist_app.equipment_services import (
    create_equipment_checklist,
    delete_equipment_checklist,
    get_equipment_history,
    list_equipment_checklists,
    update_equipment_final_remark,
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
        self.assertEqual(len(get_equipment_history(database, record["equipment_id"])), 3)

        csv_text = export_equipment_csv(
            database, project="100 MW AKOLA SITE", block="1"
        )
        self.assertIn("Cable Laying", csv_text)
        self.assertIn("Cable type verified", csv_text)
        workbook = load_workbook(
            export_all_xlsx(database, project="100 MW AKOLA SITE", block="1")
        )
        self.assertEqual(
            workbook.sheetnames,
            ["Structures", "History", "Equipment Checklists", "Equipment History"],
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
        self.assertNotIn(b"Cable type verified", page.data)

        payload = client.get(f"/api/equipment/{record['equipment_id']}").get_json()
        self.assertNotIn("remark", payload["checklist"][0])
        qr_response = client.get(f"/equipment/{record['equipment_id']}/qr.png")
        self.assertEqual(qr_response.status_code, 200)
        self.assertEqual(qr_response.mimetype, "image/png")

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
        preview_db, _preview_user, preview_record, _preview_transformer = build_fixture()
        preview_app = build_test_app(preview_db, logged_in=True)
        print(f"Preview equipment ID: {preview_record['equipment_id']}")
        preview_app.run(host="127.0.0.1", port=5001, debug=False)
    else:
        unittest.main()
