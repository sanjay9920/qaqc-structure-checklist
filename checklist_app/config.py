import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()


DEFAULT_CHECKLIST_ITEMS = [
    "Structure erection completed",
    "Module torque completed",
    "String cable dressing completed",
    "Structure torque completed",
    "Alignment checked",
    "Earthing completed",
    "Inspection completed",
    "Punch points cleared",
    "Nomenclature completed",
    "Ready for commissioning completed",
    "Commissioning completed",
]


STATUS_OPTIONS = {
    "completed": "OK / Completed",
    "pending": "Pending",
    "na": "Not Applicable",
}


def _bool_env(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    session_secret: str = os.getenv("SESSION_SECRET", "dev-change-me")
    app_base_url: str = os.getenv("APP_BASE_URL", "")
    firebase_project_id: str = os.getenv("FIREBASE_PROJECT_ID", "")
    firebase_api_key: str = os.getenv("FIREBASE_API_KEY", "")
    firebase_auth_domain: str = os.getenv("FIREBASE_AUTH_DOMAIN", "")
    firebase_storage_bucket: str = os.getenv("FIREBASE_STORAGE_BUCKET", "")
    service_account_json: str = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
    firebase_service_account_json: str = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON", "")
    admin_emails_raw: str = os.getenv("ADMIN_EMAILS", "")
    cookie_secure: bool = _bool_env("COOKIE_SECURE", False)
    app_timezone: str = os.getenv("APP_TIMEZONE", "Asia/Kolkata")

    @property
    def firebase_web_config(self):
        return {
            "apiKey": self.firebase_api_key,
            "authDomain": self.firebase_auth_domain,
            "projectId": self.firebase_project_id,
            "storageBucket": self.firebase_storage_bucket,
        }

    @property
    def admin_emails(self):
        return {
            email.strip().lower()
            for email in self.admin_emails_raw.split(",")
            if email.strip()
        }

    @property
    def status_options(self):
        return STATUS_OPTIONS


settings = Settings()
