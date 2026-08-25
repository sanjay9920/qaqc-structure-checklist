# Structure QR Code Checklist Management System

This is a complete Python + Flask + Firebase Firestore project for structure-specific QR checklist tracking.

Flow:

```text
Scan QR -> Open /structure/STR-0001 -> Login -> Load latest checklist -> Update status -> Save to Firestore -> Other users see latest status
```

## 1. Project Folder Structure

Save every file exactly as shown below inside:

```text
C:\Users\SANJAY RAJBHAR\OneDrive\Documents\New project
```

```text
New project/
  app.py
  manage.py
  requirements.txt
  .env.example
  .gitignore
  README.md
  checklist_app/
    __init__.py
    auth.py
    config.py
    exports.py
    firebase_client.py
    qr.py
    services.py
  templates/
    base.html
    login.html
    not_found.html
    structure.html
    admin/
      checklist_items.html
      dashboard.html
      history.html
      structure_detail.html
  static/
    css/
      styles.css
    js/
      login.js
      structure.js
```

## 2. Firebase Setup Instructions

1. Open the Firebase console: https://console.firebase.google.com/
2. Create a Firebase project.
3. Create a web app inside the Firebase project.
4. Copy the web app config values:
   - `apiKey`
   - `authDomain`
   - `projectId`
   - `storageBucket`
5. Enable Firebase Authentication:
   - Go to Authentication.
   - Open Sign-in method.
   - Enable Email/Password.
   - Create users from the Firebase console.
6. Enable Firestore:
   - Go to Firestore Database.
   - Create a database.
   - Use production/restrictive rules because this Flask backend uses Firebase Admin SDK for Firestore access.
7. Create a local service account key:
   - Go to Project settings.
   - Open Service accounts.
   - Generate new private key.
   - Save it as `serviceAccountKey.json` in the project folder.
   - Never commit this file.
8. Copy `.env.example` to `.env` and fill in the values.

Official references:

- Firebase Email/Password Auth: https://firebase.google.com/docs/auth/web/password-auth
- Firestore quickstart: https://firebase.google.com/docs/firestore/quickstart
- Cloud Run Python deploy: https://docs.cloud.google.com/run/docs/quickstarts/build-and-deploy/deploy-python-service

## 3. Required Python Packages

The packages are listed in `requirements.txt`:

```text
Flask
firebase-admin
google-cloud-firestore
python-dotenv
qrcode[pil]
Pillow
openpyxl
gunicorn
```

Install them with:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 4. Firestore Database Structure

The app creates and uses these collections.

### `checklist_items/{item_id}`

```json
{
  "item_id": "structure_erection_completed",
  "label": "Structure erection completed",
  "active": true,
  "order": 10,
  "created_at": "timestamp",
  "created_by": "admin@example.com"
}
```

Default checklist items:

```text
Structure erection completed
Module torque completed
String cable dressing completed
Structure torque completed
Alignment checked
Earthing completed
Inspection completed
Punch points cleared
Nomenclature completed
Ready for commissioning completed
Commissioning completed
```

### `structures/{structure_id}`

Example document ID: `STR-0001`

```json
{
  "structure_id": "STR-0001",
  "qr_url": "https://myapp.com/structure/STR-0001",
  "checklist": {
    "structure_erection_completed": {
      "label": "Structure erection completed",
      "status": "pending",
      "updated_at": null,
      "updated_by": null
    }
  },
  "created_at": "timestamp",
  "created_by": "admin@example.com",
  "updated_at": "timestamp",
  "updated_by": "admin@example.com"
}
```

Allowed status values:

```text
completed = OK / Completed
pending = Pending
na = Not Applicable
```

### `history/{auto_id}`

```json
{
  "structure_id": "STR-0001",
  "item_id": "module_torque_completed",
  "item_label": "Module torque completed",
  "previous_status": "pending",
  "new_status": "completed",
  "updated_by": "engineer@example.com",
  "updated_by_uid": "firebase-auth-uid",
  "updated_at": "timestamp",
  "updated_date": "2026-08-25",
  "updated_time": "14:30:00",
  "timezone": "Asia/Kolkata"
}
```

## 5. Environment File

Create `.env`:

```powershell
Copy-Item .env.example .env
```

Edit `.env`:

```text
SESSION_SECRET=change-this-long-random-string
APP_BASE_URL=http://localhost:5000
FIREBASE_PROJECT_ID=your-firebase-project-id
FIREBASE_API_KEY=your-firebase-web-api-key
FIREBASE_AUTH_DOMAIN=your-firebase-project-id.firebaseapp.com
FIREBASE_STORAGE_BUCKET=your-firebase-project-id.appspot.com
GOOGLE_APPLICATION_CREDENTIALS=serviceAccountKey.json
ADMIN_EMAILS=admin@example.com
APP_TIMEZONE=Asia/Kolkata
COOKIE_SECURE=false
```

Set `ADMIN_EMAILS` to the Firebase Auth email that should open `/admin`.

## 6. Run Locally

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

After filling `.env` and adding `serviceAccountKey.json`:

```powershell
python manage.py seed-checklist
python manage.py create-structure STR-0001
python app.py
```

Open:

```text
http://localhost:5000
```

Admin panel:

```text
http://localhost:5000/admin
```

Structure page:

```text
http://localhost:5000/structure/STR-0001
```

## 7. Generate QR Codes

### From Admin Panel

1. Login as an admin.
2. Open `/admin`.
3. Create one structure or bulk create a range.
4. Download one QR PNG or the bulk QR ZIP.
5. Use `Delete` in the structures table to remove one structure checklist and history.
6. After delete, the same Structure ID is filled in the create box so it can be created again.

### From Command Line

Create structures:

```powershell
python manage.py create-bulk --start 1 --end 50
```

Create block-wise structures:

```powershell
python manage.py create-bulk --block BLOCK-1 --start 1 --end 300
python manage.py create-bulk --block BLOCK-2 --start 1 --end 200
```

Create project/block-wise structures:

```powershell
python manage.py create-bulk --project "100MW AKOLA STE" --block BLOCK-1 --start 1 --end 300
python manage.py create-bulk --project "100MW AKOLA STE" --block BLOCK-2 --start 1 --end 200
```

Generate QR PNG files:

```powershell
python manage.py qr --start 1 --end 50 --output generated_qr_codes
```

Generate block-wise QR PNG files:

```powershell
python manage.py qr --block BLOCK-1 --start 1 --end 300 --output generated_qr_codes
```

Generate project/block-wise QR PNG files:

```powershell
python manage.py qr --project "100MW AKOLA STE" --block BLOCK-1 --start 1 --end 300 --output generated_qr_codes
```

Generate specific QR files:

```powershell
python manage.py qr --ids STR-0001 STR-0002 STR-0003 --output generated_qr_codes
```

The QR content is:

```text
APP_BASE_URL/structure/STR-0001
APP_BASE_URL/structure/BLOCK-1-STR-0001
APP_BASE_URL/structure/100MW-AKOLA-STE-BLOCK-1-STR-0001
```

For real site QR codes, set `APP_BASE_URL` to the deployed HTTPS URL before generating or downloading QR codes.

## 8. Deploy So Mobile Phones Can Scan QR Codes

The simplest low-cost deployment for this Flask backend is Google Cloud Run.

### Prepare Google Cloud

Install and login to the Google Cloud CLI:

```powershell
gcloud auth login
gcloud config set project your-firebase-project-id
gcloud services enable run.googleapis.com cloudbuild.googleapis.com firestore.googleapis.com
```

Deploy from the project folder:

```powershell
gcloud run deploy structure-qr-checklist `
  --source . `
  --region asia-south1 `
  --allow-unauthenticated `
  --set-env-vars FIREBASE_PROJECT_ID=your-firebase-project-id,FIREBASE_API_KEY=your-api-key,FIREBASE_AUTH_DOMAIN=your-firebase-project-id.firebaseapp.com,FIREBASE_STORAGE_BUCKET=your-firebase-project-id.appspot.com,ADMIN_EMAILS=admin@example.com,SESSION_SECRET=change-this-long-random-string,COOKIE_SECURE=true,APP_TIMEZONE=Asia/Kolkata
```

Cloud Run will print a service URL, for example:

```text
https://structure-qr-checklist-xxxxx-as.a.run.app
```

Update the service with that public URL:

```powershell
gcloud run services update structure-qr-checklist `
  --region asia-south1 `
  --set-env-vars APP_BASE_URL=https://structure-qr-checklist-xxxxx-as.a.run.app
```

In Firebase Authentication, add the Cloud Run host to Authorized domains if Firebase requires it for your project.

Now generate QR codes again from `/admin` so each QR points to the public URL.

## 9. Main Routes

```text
GET  /login
GET  /logout
GET  /structure/<structure_id>
GET  /admin
POST /admin/structures
POST /admin/structures/bulk
GET  /admin/structures/<structure_id>
GET  /admin/structures/<structure_id>/qr.png
GET  /admin/qr-codes.zip
GET  /admin/checklist-items
POST /admin/checklist-items
POST /admin/checklist-items/<item_id>/remove
GET  /admin/history
GET  /admin/export/structures.csv
GET  /admin/export/history.csv
GET  /admin/export/all.xlsx
```

## 10. Notes

- Firestore data is persistent after the browser closes.
- Every status change writes a row into `history`.
- The structure page refreshes latest data every 5 seconds so another scanner sees updates without needing a manual refresh.
- For production, use HTTPS and set `COOKIE_SECURE=true`.
- Keep `serviceAccountKey.json` out of source control.
