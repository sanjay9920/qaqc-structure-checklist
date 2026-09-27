import copy
import sys
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask
from openpyxl import load_workbook

import checklist_app as app_module
from checklist_app import auth as auth_module
from checklist_app.dashboard_analytics import build_dashboard_intelligence
from checklist_app.equipment_catalog import get_equipment_catalog, get_equipment_template
from checklist_app.equipment_services import (
    build_equipment_family_summaries,
    build_equipment_template_summaries,
    create_equipment_checklist,
    delete_equipment_checklist,
    get_equipment_history,
    get_next_equipment_record_number,
    list_equipment_checklists,
    update_equipment_final_remark,
    update_equipment_details,
    update_equipment_measurements,
    update_equipment_remark,
    update_equipment_status,
)
from checklist_app.exports import export_all_xlsx, export_equipment_csv
from checklist_app.services import (
    build_project_summary,
    calculate_counts,
    delete_checklist_item,
    delete_project,
    get_active_checklist_items,
)


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
        document = self.database.data[self.collection_name][self.id]
        for path, value in copy.deepcopy(data).items():
            parts = path.split(".")
            target = document
            for part in parts[:-1]:
                target = target.setdefault(part, {})
            target[parts[-1]] = value

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
        vendor_name="Polycab",
        equipment_identification="SCB-1",
        specification="240 SQMM",
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
    def test_session_claims_are_reused_during_fast_page_navigation(self):
        auth_module._session_cache.clear()
        app = Flask(__name__)
        claims = {
            "uid": "worker-1",
            "email": "worker@example.com",
            "projects": ["SITE ONE"],
        }

        with (
            patch.object(auth_module, "initialize_firebase"),
            patch.object(
                auth_module.firebase_auth,
                "verify_session_cookie",
                return_value=claims,
            ) as verify_session,
        ):
            for _ in range(2):
                with app.test_request_context(
                    headers={"Cookie": "firebase_session=session-token"}
                ):
                    user = auth_module.current_user()
                    self.assertEqual(user["uid"], "worker-1")

        self.assertEqual(verify_session.call_count, 1)

    def test_dashboard_reuses_project_data_when_switching_blocks(self):
        database, _user, _cable_laying, _transformer = build_fixture()
        database.collection("projects").document("100-MW-AKOLA-SITE").set(
            {
                "project_id": "100-MW-AKOLA-SITE",
                "display_name": "100 MW AKOLA SITE",
                "block_count": 2,
            }
        )
        original_list_project_records = app_module.list_project_records
        original_list_structures = app_module.list_structures
        original_list_equipment = app_module.list_equipment_checklists

        with (
            patch.object(
                app_module,
                "list_project_records",
                wraps=original_list_project_records,
            ) as list_projects_call,
            patch.object(
                app_module,
                "list_structures",
                wraps=original_list_structures,
            ) as list_structures_call,
            patch.object(
                app_module,
                "list_equipment_checklists",
                wraps=original_list_equipment,
            ) as list_equipment_call,
        ):
            app = build_test_app(database, logged_in=True)
            client = app.test_client()
            for block in ("BLOCK-1", "BLOCK-2"):
                response = client.get(
                    "/admin?project=100-MW-AKOLA-SITE&block=" + block
                )
                self.assertEqual(response.status_code, 200)

        self.assertEqual(list_projects_call.call_count, 1)
        self.assertEqual(list_structures_call.call_count, 1)
        self.assertEqual(list_equipment_call.call_count, 1)

    def test_equipment_family_summary_tracks_unique_units_and_all_work(self):
        records = [
            {
                "equipment_id": "record-1",
                "equipment_identification": "SCB-32",
                "template_id": "dc-cable-laying",
                "template_name": "DC Cable Laying",
                "identity_profile": {"type": "cable"},
                "block": "BLOCK-1",
                "counts": {"total": 10, "completed": 10, "pending": 0, "na": 0, "progress": 100},
            },
            {
                "equipment_id": "record-2",
                "equipment_identification": "SCB-32",
                "template_id": "dc-cable-termination",
                "template_name": "DC Cable Termination",
                "identity_profile": {"type": "cable"},
                "block": "BLOCK-1",
                "counts": {"total": 10, "completed": 3, "pending": 7, "na": 0, "progress": 30},
            },
            {
                "equipment_id": "record-3",
                "equipment_identification": "IDT-1",
                "template_id": "transformer-installation",
                "template_name": "Transformer Installation",
                "block": "BLOCK-2",
                "counts": {"total": 18, "completed": 0, "pending": 18, "na": 0, "progress": 0},
            },
            {
                "equipment_id": "record-4",
                "equipment_identification": "SCB-32",
                "template_id": "dc-cable-laying",
                "template_name": "DC Cable Laying",
                "identity_profile": {"type": "cable"},
                "block": "BLOCK-2",
                "counts": {"total": 10, "completed": 10, "pending": 0, "na": 0, "progress": 100},
            },
        ]

        summaries = build_equipment_family_summaries(records)
        scb = next(item for item in summaries if item["family"] == "SCB")
        idt = next(item for item in summaries if item["family"] == "IDT")

        self.assertEqual(scb["equipment_count"], 2)
        self.assertEqual(scb["completed_equipment"], 1)
        self.assertEqual(scb["in_progress_equipment"], 1)
        self.assertEqual(scb["pending_equipment"], 1)
        self.assertEqual(scb["checklist_type_count"], 2)
        self.assertEqual(scb["total_records"], 3)
        self.assertEqual(scb["completed_points"], 23)
        self.assertEqual(scb["pending_points"], 7)
        self.assertEqual(scb["equipment"][0]["label"], "SCB-32")
        self.assertEqual(scb["block_count"], 2)
        self.assertEqual(idt["equipment_count"], 1)
        self.assertEqual(idt["not_started_equipment"], 1)
        self.assertEqual(idt["block_count"], 1)

    def test_checklist_summary_keeps_same_equipment_id_separate_by_block(self):
        template = get_equipment_template("string-cable")
        records = [
            {
                "equipment_id": "block-1-scb-1",
                "equipment_identification": "SCB-1",
                "template_id": template["template_id"],
                "block": "BLOCK-1",
                "counts": {"total": 12, "completed": 12, "pending": 0, "na": 0, "progress": 100},
            },
            {
                "equipment_id": "block-2-scb-1",
                "equipment_identification": "SCB-1",
                "template_id": template["template_id"],
                "block": "BLOCK-2",
                "counts": {"total": 12, "completed": 0, "pending": 12, "na": 0, "progress": 0},
            },
        ]

        summary = build_equipment_template_summaries([template], records)[0]

        self.assertEqual(summary["equipment_labels"], ["SCB-1"])
        self.assertEqual(
            summary["equipment_units"],
            [
                {"label": "SCB-1", "block": "BLOCK-1"},
                {"label": "SCB-1", "block": "BLOCK-2"},
            ],
        )
        self.assertEqual(summary["additional_equipment_unit_count"], 0)

    def test_password_fields_have_show_hide_controls(self):
        database = FakeFirestore()
        client = build_test_app(database).test_client()

        page = client.get("/login")

        self.assertEqual(page.status_code, 200)
        self.assertIn(b'data-password-toggle="loginPassword"', page.data)
        self.assertIn(b'aria-label="Show password"', page.data)
        self.assertIn(b"Forgot password?", page.data)
        self.assertIn(b'id="forgotPasswordForm"', page.data)
        self.assertIn(b"/static/js/login.js?v=2", page.data)
        self.assertIn(b"password-toggle.js", page.data)
        service_worker = client.get("/service-worker.js")
        self.assertIn(b"quality-sims-v22", service_worker.data)
        self.assertIn(b"/static/js/login.js?v=2", service_worker.data)
        self.assertIn(b"/static/js/password-toggle.js?v=2", service_worker.data)
        self.assertEqual(service_worker.headers.get("Cache-Control"), "no-cache")
        service_worker.close()

    def test_public_forgot_password_sends_a_generic_reset_response(self):
        database = FakeFirestore()
        client = build_test_app(database).test_client()

        missing = client.post("/auth/forgot-password", json={})
        self.assertEqual(missing.status_code, 400)

        class FakeAuthResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b'{}'

        with patch.object(
            app_module.url_request, "urlopen", return_value=FakeAuthResponse()
        ) as urlopen:
            response = client.post(
                "/auth/forgot-password",
                json={"email": " ADMIN@EXAMPLE.COM "},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json()["message"],
            "If this email is registered, a password reset link has been sent.",
        )
        request_payload = urlopen.call_args.args[0]
        self.assertIn(b'"requestType": "PASSWORD_RESET"', request_payload.data)
        self.assertIn(b'"email": "admin@example.com"', request_payload.data)

    def test_admin_and_user_account_page_supports_secure_password_change(self):
        database = FakeFirestore()
        client = build_test_app(database, logged_in=True).test_client()

        page = client.get("/account")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"My account", page.data)
        self.assertIn(b"Change password", page.data)
        self.assertIn(b'name="current_password"', page.data)
        self.assertIn(b'data-password-toggle="newPassword"', page.data)
        self.assertIn(b"Admin", page.data)

        mismatch = client.post(
            "/account/password",
            data={
                "current_password": "old-password",
                "new_password": "new-password",
                "confirm_password": "different-password",
            },
        )
        self.assertEqual(mismatch.status_code, 302)
        self.assertTrue(mismatch.headers["Location"].endswith("/account"))

        class FakeAuthResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b'{"localId":"admin","idToken":"verified-token"}'

        with (
            patch.object(app_module.url_request, "urlopen", return_value=FakeAuthResponse()),
            patch.object(app_module, "initialize_firebase"),
            patch.object(app_module.firebase_auth, "update_user") as update_user,
            patch.object(
                app_module.firebase_auth, "revoke_refresh_tokens"
            ) as revoke_refresh_tokens,
        ):
            changed = client.post(
                "/account/password",
                data={
                    "current_password": "old-password",
                    "new_password": "new-password",
                    "confirm_password": "new-password",
                },
            )

        self.assertEqual(changed.status_code, 302)
        self.assertTrue(changed.headers["Location"].endswith("/login"))
        self.assertIn("firebase_session=", changed.headers.get("Set-Cookie", ""))
        update_user.assert_called_once_with("admin", password="new-password")
        revoke_refresh_tokens.assert_called_once_with("admin")

    def test_admin_can_recreate_email_from_legacy_removed_user(self):
        database = FakeFirestore()
        database.collection("checklist_items").document("dummy").set(
            {"label": "Dummy", "order": 10, "active": True}
        )
        database.collection("projects").document("PROJECT-1").set(
            {"project_id": "PROJECT-1", "display_name": "Project 1"}
        )
        client = build_test_app(database, logged_in=True).test_client()
        legacy_user = SimpleNamespace(uid="legacy-uid", disabled=True)
        new_user = SimpleNamespace(uid="new-uid")
        email_exists = app_module.firebase_auth.EmailAlreadyExistsError(
            "Email exists", None, None
        )

        with (
            patch.object(app_module, "initialize_firebase"),
            patch.object(
                app_module.firebase_auth,
                "create_user",
                side_effect=[email_exists, new_user],
            ) as create_user,
            patch.object(
                app_module.firebase_auth,
                "get_user_by_email",
                return_value=legacy_user,
            ),
            patch.object(app_module.firebase_auth, "delete_user") as delete_user,
            patch.object(app_module.firebase_auth, "set_custom_user_claims"),
        ):
            response = client.post(
                "/admin/users",
                data={
                    "name": "Recreated Worker",
                    "email": "worker@example.com",
                    "password": "secret123",
                    "role": "worker",
                    "projects": "PROJECT-1",
                },
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(create_user.call_count, 2)
        delete_user.assert_called_once_with("legacy-uid")

    def test_checklist_item_delete_is_permanent_and_cascades(self):
        database = FakeFirestore()
        database.collection("checklist_items").document("alignment").set(
            {"label": "Alignment checked", "order": 10, "active": False}
        )
        database.collection("structures").document("STR-0001").set(
            {
                "structure_id": "STR-0001",
                "checklist": {
                    "alignment": {"label": "Alignment checked", "status": "completed"},
                    "earthing": {"label": "Earthing completed", "status": "pending"},
                },
            }
        )
        database.collection("history").document("history-1").set(
            {"item_id": "alignment", "structure_id": "STR-0001"}
        )

        deleted = delete_checklist_item(database, "alignment", "admin@example.com")

        self.assertEqual(deleted["updated_structures"], 1)
        self.assertEqual(deleted["deleted_history"], 1)
        self.assertFalse(
            database.collection("checklist_items").document("alignment").get().exists
        )
        structure = (
            database.collection("structures").document("STR-0001").get().to_dict()
        )
        self.assertNotIn("alignment", structure["checklist"])
        self.assertIn("earthing", structure["checklist"])
        self.assertEqual(len(database.data["history"]), 0)

    def test_deleted_checklist_items_are_not_seeded_again(self):
        database = FakeFirestore()
        database.collection("checklist_items").document("only-item").set(
            {"label": "Only item", "order": 10, "active": True}
        )

        delete_checklist_item(database, "only-item", "admin@example.com")

        self.assertEqual(get_active_checklist_items(database), [])
        self.assertEqual(len(database.data["checklist_items"]), 0)

    def test_removed_checklist_items_are_not_shown_on_admin_page(self):
        database = FakeFirestore()
        database.collection("checklist_items").document("active-item").set(
            {"label": "Active point", "order": 10, "active": True}
        )
        database.collection("checklist_items").document("removed-item").set(
            {"label": "Old removed point", "order": 20, "active": False}
        )
        client = build_test_app(database, logged_in=True).test_client()

        page = client.get("/admin/checklist-items")

        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Active point", page.data)
        self.assertNotIn(b"Old removed point", page.data)
        self.assertNotIn(b">Removed<", page.data)

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
        self.assertEqual(record["equipment_identification"], "SCB-1")
        self.assertEqual(record["specification"], "240 SQMM")
        self.assertEqual(record["vendor_name"], "Polycab")
        self.assertEqual(len(get_equipment_history(database, record["equipment_id"])), 4)

        csv_text = export_equipment_csv(
            database, project="100 MW AKOLA SITE", block="1"
        )
        self.assertIn("Cable Laying", csv_text)
        self.assertIn("Cable type verified", csv_text)
        self.assertIn("12 x cable OD", csv_text)
        self.assertIn("Measured Value / Observation", csv_text)
        self.assertIn("SCB-1", csv_text)
        self.assertIn("240 SQMM", csv_text)
        self.assertIn("Polycab", csv_text)
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
        self.assertIn(b"SCB-1", page.data)
        self.assertIn(b"240 SQMM", page.data)
        self.assertIn(b"Polycab", page.data)
        self.assertIn(b"equipmentVendorHeader", page.data)
        self.assertIn(b"Vendor / Manufacturer", page.data)
        self.assertNotIn(b"Cable type verified", page.data)
        self.assertNotIn(b"Save Observation", page.data)

        payload = client.get(f"/api/equipment/{record['equipment_id']}").get_json()
        self.assertEqual(payload["equipment_identification"], "SCB-1")
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

    def test_equipment_details_can_be_saved_and_cleared(self):
        database, user, record, _transformer = build_fixture()
        updated = update_equipment_details(
            database,
            record["equipment_id"],
            {
                "equipment_identification": "SCB-2",
                "specification": "400 SQMM",
                "vendor_name": "KEI",
            },
            user,
        )
        self.assertEqual(updated["equipment_identification"], "SCB-2")
        self.assertEqual(updated["specification"], "400 SQMM")
        self.assertEqual(updated["vendor_name"], "KEI")

        client = build_test_app(database, logged_in=True).test_client()
        partial = client.post(
            f"/api/equipment/{record['equipment_id']}/details",
            json={"vendor_name": "Polycab Limited"},
        )
        self.assertEqual(partial.status_code, 200)
        self.assertEqual(partial.get_json()["equipment_identification"], "SCB-2")
        self.assertEqual(partial.get_json()["specification"], "400 SQMM")
        self.assertEqual(partial.get_json()["vendor_name"], "Polycab Limited")

        response = client.post(
            f"/api/equipment/{record['equipment_id']}/details",
            json={
                "equipment_identification": "",
                "specification": "",
                "vendor_name": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["vendor_name"], "")
        history = get_equipment_history(database, record["equipment_id"])
        self.assertEqual(history[0]["change_type"], "details")

        too_long = client.post(
            f"/api/equipment/{record['equipment_id']}/details",
            json={"vendor_name": "X" * 121},
        )
        self.assertEqual(too_long.status_code, 400)

    def test_every_excel_checklist_has_correct_observation_schema(self):
        catalog = get_equipment_catalog()
        self.assertEqual(len(catalog), 45)
        self.assertEqual(sum(len(item["points"]) for item in catalog), 586)
        names = {item["name"] for item in catalog}
        self.assertTrue(
            {
                "AC Cable Laying",
                "DC Cable Laying",
                "AC Cable Termination",
                "DC Cable Termination",
            }.issubset(names)
        )
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

    def test_every_checklist_has_a_dynamic_identity_profile(self):
        catalog = get_equipment_catalog()
        profile_codes = set()

        for template in catalog:
            profile = template.get("identity_profile") or {}
            self.assertIn(profile.get("type"), {"cable", "test", "equipment"})
            self.assertTrue(profile.get("code"))
            self.assertTrue(profile.get("primary_label"))
            self.assertTrue(profile.get("specification_label"))
            self.assertTrue(profile.get("fields"))
            self.assertNotIn(profile["code"], profile_codes)
            profile_codes.add(profile["code"])

        self.assertEqual(
            get_equipment_template("cable-laying")["identity_profile"]["type"],
            "cable",
        )
        self.assertEqual(
            get_equipment_template("voc-testing")["identity_profile"]["type"],
            "test",
        )
        self.assertEqual(
            get_equipment_template("transformer-installation")["identity_profile"]["type"],
            "equipment",
        )

    def test_checklist_dashboard_paginates_and_searches_identity_details(self):
        database = FakeFirestore()
        for number in range(1, 56):
            create_equipment_checklist(
                database,
                "150 MW AKOLA SITE",
                "11",
                "cable-laying",
                f"{number:02d}",
                "admin@example.com",
                equipment_identification=f"AC-CIRCUIT-{number:03d}",
                specification="3C x 240 SQMM",
                identity_details={
                    "from_location": f"IDT-{number:02d}",
                    "to_location": "HT PANEL-1",
                    "run_number": f"RUN-{number:03d}",
                    "route_reference": f"ROUTE-{number:03d}",
                },
            )

        client = build_test_app(database, logged_in=True).test_client()
        base_url = (
            "/admin/api/equipment-dashboard/cable-laying"
            "?project=150-MW-AKOLA-SITE&block=BLOCK-11"
        )
        first_page = client.get(base_url).get_json()
        second_page = client.get(f"{base_url}&page=2").get_json()
        search = client.get(f"{base_url}&q=route-055").get_json()

        self.assertEqual(first_page["pagination"]["total"], 55)
        self.assertEqual(len(first_page["records"]), 50)
        self.assertEqual(second_page["pagination"]["page"], 2)
        self.assertEqual(len(second_page["records"]), 5)
        self.assertNotIn("checklist", first_page["records"][0])
        self.assertEqual(search["pagination"]["total"], 1)
        self.assertEqual(search["records"][0]["equipment_identification"], "AC-CIRCUIT-055")
        self.assertEqual(
            search["records"][0]["work_id"],
            "150-MW-AKOLA-SITE-ACL-B11-0055",
        )
        self.assertIn("ROUTE-055", search["records"][0]["identity_details_text"])

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
        for expected in [
            b"45 types",
            b"AC Cable Laying",
            b"DC Cable Laying",
            b"AC Cable Termination",
            b"DC Cable Termination",
            b"12 points",
            b"Completed points",
            b"SCB-1",
            b"240 SQMM",
            b"Browse Checklist Library",
            b"45 types",
            b"Open Dashboard",
            b"in progress",
            b"not started",
            b"ID missing",
            b"Search checklist, equipment or vendor",
            b"Combined checklist status",
            b"Click a card for its detailed dashboard",
            b"compact-tracking-grid compact-scroll-area",
            b"compact-card-link",
            b"mini-progress-ring",
            b"checklist-dashboard-grid",
            b"checklist-library-panel",
            b"Smart QA/QC tracking",
            b"Attention and next actions",
            b"Open points",
            b"Create Structure Checklist",
            b'class="structure-tools"',
        ]:
            self.assertIn(expected, page.data)
        self.assertNotIn(b"checklist-library-panel mb-3\" open", page.data)
        self.assertNotIn(b'class="structure-tools" open', page.data)
        self.assertNotIn(b"Equipment, asset and circuit register", page.data)
        self.assertIn(
            b"/admin/equipment-dashboard/cable-laying?project=100-MW-AKOLA-SITE&amp;block=BLOCK-1",
            page.data,
        )

        expanded = client.get(url + "&manage_structures=1")
        self.assertIn(b'class="structure-tools" open', expanded.data)

        payload = client.get(
            "/admin/api/structures?project=100-MW-AKOLA-SITE&block=BLOCK-1"
        ).get_json()
        self.assertEqual(payload["equipment_summary"]["total_records"], 2)
        self.assertEqual(payload["smart_tracking"]["open_records"], 2)
        self.assertEqual(payload["smart_tracking"]["pending_points"], 29)
        self.assertEqual(payload["equipment_records"][0]["equipment_id"], record["equipment_id"])
        self.assertEqual(len(payload["equipment_template_summaries"]), 45)
        cable_summary = next(
            item
            for item in payload["equipment_template_summaries"]
            if item["template_id"] == "cable-laying"
        )
        self.assertEqual(cable_summary["in_progress_records"], 1)
        self.assertEqual(cable_summary["not_started_records"], 0)
        self.assertEqual(cable_summary["identified_records"], 1)
        self.assertEqual(cable_summary["missing_identity_records"], 0)
        self.assertEqual(cable_summary["equipment_labels"], ["SCB-1"])
        self.assertEqual(
            cable_summary["equipment_units"],
            [{"label": "SCB-1", "block": "BLOCK-1"}],
        )
        self.assertEqual(cable_summary["vendor_names"], ["Polycab"])
        self.assertEqual(cable_summary["specifications"], ["240 SQMM"])
        self.assertNotIn(b"Created equipment checklists", page.data)
        self.assertNotIn(b"Equipment History CSV", page.data)

    def test_project_dashboard_combines_every_blocks_structure_and_equipment_work(self):
        database, _user, _record, _transformer = build_fixture()
        database.collection("projects").document("100-MW-AKOLA-SITE").set(
            {
                "project_id": "100-MW-AKOLA-SITE",
                "display_name": "100 MW AKOLA SITE",
                "block_count": 20,
            }
        )
        client = build_test_app(database, logged_in=True).test_client()
        url = "/admin?project=100-MW-AKOLA-SITE"

        page = client.get(url)
        self.assertEqual(page.status_code, 200)
        for expected in [
            b"Project QA/QC control center",
            b"All checklist and work status",
            b"Every block: checklist and work details",
            b"Block 1",
            b"Block 20",
            b"Equipment checklists",
            b"Combined QA/QC work",
            b"Open Block Dashboard",
            b"Combined checklist status",
            b"block-portfolio-grid",
            b"mini-progress-ring",
            b"Smart QA/QC tracking",
            b"Blocks needing focus",
        ]:
            self.assertIn(expected, page.data)
        self.assertNotIn(b"Open block", page.data)
        self.assertNotIn(b"Block detail", page.data)
        self.assertNotIn(b"Equipment, asset and circuit register", page.data)
        self.assertIn(b"B1 / SCB-1", page.data)
        self.assertIn(b"compact-card-link", page.data)
        self.assertIn(b"/admin/equipment-dashboard/cable-laying?project=100-MW-AKOLA-SITE", page.data)

        payload = client.get(
            "/admin/api/structures?project=100-MW-AKOLA-SITE"
        ).get_json()
        summary = payload["project_summary"]
        self.assertEqual(payload["smart_tracking"]["pending_points"], 29)
        self.assertTrue(payload["smart_tracking"]["block_pressure"])
        self.assertEqual(summary["equipment_total_records"], 2)
        self.assertEqual(summary["equipment_pending_records"], 2)
        self.assertEqual(summary["equipment_total_points"], 30)
        self.assertEqual(summary["equipment_completed_points"], 1)
        self.assertEqual(summary["work_total_points"], 30)
        self.assertEqual(summary["work_completed_points"], 1)
        self.assertEqual(len(summary["blocks"]), 20)
        self.assertEqual(summary["blocks"][-1]["block"], "BLOCK-20")
        block = next(item for item in summary["blocks"] if item["block"] == "BLOCK-1")
        self.assertEqual(block["equipment_total_records"], 2)
        self.assertEqual(block["equipment_pending_records"], 2)
        self.assertEqual(block["work_progress"], 3)

    def test_admin_project_delete_cascades_related_data(self):
        database = FakeFirestore()
        project_id = "150-MW-AKOLA-SITE"
        structure_id = f"{project_id}-BLOCK-1-STR-01"
        database.collection("projects").document(project_id).set(
            {"project_id": project_id}
        )
        database.collection("structures").document(structure_id).set(
            {"project": project_id, "block": "BLOCK-1"}
        )
        database.collection("equipment_checklists").document("equipment-1").set(
            {"project": project_id, "block": "BLOCK-1"}
        )
        database.collection("history").document("history-1").set(
            {"project": project_id, "structure_id": structure_id}
        )
        database.collection("equipment_history").document("equipment-history-1").set(
            {"project": project_id, "equipment_id": "equipment-1"}
        )

        deleted = delete_project(database, project_id, cascade=True)

        self.assertEqual(deleted["structures_deleted"], 1)
        self.assertEqual(deleted["equipment_deleted"], 1)
        self.assertFalse(database.collection("projects").document(project_id).get().exists)
        self.assertFalse(
            database.collection("structures").document(structure_id).get().exists
        )
        self.assertFalse(
            database.collection("equipment_checklists")
            .document("equipment-1")
            .get()
            .exists
        )
        self.assertFalse(
            database.collection("history").document("history-1").get().exists
        )
        self.assertFalse(
            database.collection("equipment_history")
            .document("equipment-history-1")
            .get()
            .exists
        )

    def test_checklist_dashboard_supports_multiple_equipment_records(self):
        database, _user, record, _transformer = build_fixture()
        client = build_test_app(database, logged_in=True).test_client()
        dashboard_url = (
            "/admin/equipment-dashboard/cable-laying"
            "?project=100-MW-AKOLA-SITE&block=BLOCK-1"
        )

        page = client.get(dashboard_url)
        self.assertEqual(page.status_code, 200)
        for expected in [
            b"Cable Laying",
            b"SCB-1",
            b"240 SQMM",
            b"Polycab",
            b'value="02"',
            b"Vendor / Manufacturer",
            b"In progress",
            b"Not started",
            b"Unique identities",
            b"Search Work ID, equipment, route, specification or vendor",
            b"summary-grid equipment-type-summary",
            b"Smart QA/QC tracking",
            b"Checklist bottlenecks",
        ]:
            self.assertIn(expected, page.data)

        created = client.post(
            "/admin/equipment",
            data={
                "project": "100-MW-AKOLA-SITE",
                "block": "BLOCK-1",
                "template_id": "cable-laying",
                "record_number": "",
                "equipment_identification": "SCB-2",
                "specification": "400 SQMM",
                "vendor_name": "KEI",
            },
            follow_redirects=False,
        )
        self.assertEqual(created.status_code, 302)
        self.assertIn("CABLE-LAYING-02", created.headers["Location"])

        payload = client.get(
            "/admin/api/equipment-dashboard/cable-laying"
            "?project=100-MW-AKOLA-SITE&block=BLOCK-1"
        ).get_json()
        self.assertEqual(payload["summary"]["total_records"], 2)
        self.assertEqual(payload["smart_tracking"]["open_records"], 2)
        self.assertEqual(payload["summary"]["pending_records"], 2)
        self.assertEqual(payload["next_record_number"], "03")
        scb_two = next(
            item
            for item in payload["records"]
            if item["equipment_identification"] == "SCB-2"
        )
        self.assertEqual(scb_two["record_number"], "02")
        self.assertEqual(scb_two["specification"], "400 SQMM")
        self.assertEqual(scb_two["vendor_name"], "KEI")

        summaries = build_equipment_template_summaries(
            get_equipment_catalog(), payload["records"]
        )
        cable_summary = next(
            item for item in summaries if item["template_id"] == "cable-laying"
        )
        self.assertEqual(cable_summary["total_records"], 2)
        self.assertEqual(
            get_next_equipment_record_number(payload["records"]), "03"
        )

        create_equipment_checklist(
            database,
            "100 MW AKOLA SITE",
            "2",
            "cable-laying",
            "01",
            "admin@example.com",
            equipment_identification="HT-PANEL-2",
            specification="400 SQMM",
            vendor_name="KEI",
        )
        project_dashboard_url = (
            "/admin/equipment-dashboard/cable-laying?project=100-MW-AKOLA-SITE"
        )
        project_page = client.get(project_dashboard_url)
        self.assertEqual(project_page.status_code, 200)
        for expected in [
            b"All active blocks",
            b"Combined quantity, progress and pending work across every block.",
            b"Quantity and progress by block",
            b"Block 1",
            b"Block 2",
            b"Quantity",
            b"Completed",
            b"Pending",
        ]:
            self.assertIn(expected, project_page.data)
        self.assertNotIn(b"Add checklist record", project_page.data)

        project_payload = client.get(
            "/admin/api/equipment-dashboard/cable-laying"
            "?project=100-MW-AKOLA-SITE"
        ).get_json()
        self.assertEqual(project_payload["summary"]["total_records"], 3)
        self.assertEqual(len(project_payload["block_summaries"]), 2)
        self.assertEqual(
            [item["block"] for item in project_payload["block_summaries"]],
            ["BLOCK-1", "BLOCK-2"],
        )
        self.assertEqual(
            {item["block"] for item in project_payload["records"]},
            {"BLOCK-1", "BLOCK-2"},
        )

    def test_smart_tracking_prioritizes_stale_and_incomplete_work(self):
        stale_time = datetime.now(timezone.utc) - timedelta(days=15)
        records = [
            {
                "equipment_id": "SCB-01",
                "equipment_identification": "",
                "vendor_name": "",
                "template_id": "string-cable",
                "template_name": "DC Cable Laying",
                "record_number": "01",
                "block": "BLOCK-2",
                "updated_at": stale_time,
                "counts": {
                    "total": 12,
                    "completed": 2,
                    "pending": 10,
                    "na": 0,
                    "progress": 17,
                },
            }
        ]
        templates = build_equipment_template_summaries(
            [get_equipment_template("string-cable")], records
        )
        intelligence = build_dashboard_intelligence(
            [],
            records,
            template_summaries=templates,
            project="150-MW-AKOLA-SITE",
            block="BLOCK-2",
        )

        self.assertTrue(intelligence["has_work"])
        self.assertEqual(intelligence["pending_points"], 10)
        self.assertEqual(intelligence["stale_work"], 1)
        self.assertEqual(intelligence["data_gaps"], 2)
        self.assertEqual(intelligence["priority_items"][0]["severity"], "critical")
        self.assertIn("Equipment ID missing", intelligence["priority_items"][0]["reason"])
        self.assertEqual(intelligence["bottlenecks"][0]["pending_points"], 10)

    def test_na_points_are_resolved_for_completion_progress(self):
        rows = (
            [{"status": "completed"} for _ in range(7)]
            + [{"status": "na"} for _ in range(5)]
        )
        counts = calculate_counts(rows)
        self.assertEqual(counts["completed"], 7)
        self.assertEqual(counts["na"], 5)
        self.assertEqual(counts["pending"], 0)
        self.assertEqual(counts["progress"], 100)

        summary = build_project_summary(
            [],
            equipment_records=[
                {
                    "block": "BLOCK-1",
                    "counts": counts,
                }
            ],
        )
        block = summary["blocks"][0]
        self.assertEqual(block["equipment_progress"], 100)
        self.assertEqual(block["work_progress"], 100)

        intelligence = build_dashboard_intelligence(
            [],
            [],
            block_rows=summary["blocks"],
            project="150-MW-AKOLA-SITE",
        )
        self.assertEqual(intelligence["block_pressure"][0]["state"], "complete")
        self.assertEqual(intelligence["block_pressure"][0]["progress"], 100)

    def test_security_headers_safe_redirect_and_missing_structure_qr(self):
        database, _user, _record, _transformer = build_fixture()
        public_client = build_test_app(database).test_client()
        response = public_client.get("/login")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(
            public_client.get("/structure/DOES-NOT-EXIST/qr.png").status_code,
            404,
        )

        logged_in_client = build_test_app(database, logged_in=True).test_client()
        redirected = logged_in_client.get(
            "/login?next=https://example.com/phishing", follow_redirects=False
        )
        self.assertEqual(redirected.status_code, 302)
        self.assertEqual(redirected.headers["Location"], "/admin")

    def test_exports_neutralize_spreadsheet_formulas(self):
        database, user, record, _transformer = build_fixture()
        update_equipment_details(
            database,
            record["equipment_id"],
            {
                "equipment_identification": "=HYPERLINK(\"https://example.com\")",
                "specification": "240 SQMM",
                "vendor_name": "Polycab",
            },
            user,
        )
        csv_text = export_equipment_csv(database, project="100 MW AKOLA SITE")
        self.assertIn("'=HYPERLINK", csv_text)


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
