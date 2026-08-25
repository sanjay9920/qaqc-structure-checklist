import json

import firebase_admin
from firebase_admin import credentials
from google.cloud import firestore

from .config import settings


def initialize_firebase():
    if firebase_admin._apps:
        return firebase_admin.get_app()

    options = {}
    if settings.firebase_project_id:
        options["projectId"] = settings.firebase_project_id

    if settings.firebase_service_account_json:
        service_account_info = json.loads(settings.firebase_service_account_json)
        cred = credentials.Certificate(service_account_info)
        return firebase_admin.initialize_app(cred, options or None)

    if settings.service_account_json:
        cred = credentials.Certificate(settings.service_account_json)
        return firebase_admin.initialize_app(cred, options or None)

    return firebase_admin.initialize_app(options=options or None)


def get_db():
    app = initialize_firebase()
    project_id = settings.firebase_project_id or app.project_id
    client = firestore.Client(
        project=project_id,
        credentials=app.credential.get_credential(),
        database="(default)",
    )
    # google-api-core currently URL-encodes "(default)" in the resource path.
    # Firestore expects the literal default database id.
    client._database_string_internal = f"projects/{project_id}/databases/(default)"
    return client
