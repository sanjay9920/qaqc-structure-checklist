# Deploy QA/QC Structure Checklist App

This project is ready for server deployment. The app must run on a public HTTPS URL so QR codes can open from any mobile network.

## Important

- Do not upload `.env` or `serviceAccountKey.json` into a public repository.
- On the server, set secrets as environment variables.
- After deployment, set `APP_BASE_URL` to the final public URL.
- Generate QR codes again after `APP_BASE_URL` is updated, so QR links use the public URL.

## Required Environment Variables

```text
FLASK_ENV=production
COOKIE_SECURE=true
SESSION_SECRET=<long-random-secret>
APP_BASE_URL=https://your-public-url

FIREBASE_PROJECT_ID=str-checklist-8874
FIREBASE_API_KEY=<firebase-web-api-key>
FIREBASE_AUTH_DOMAIN=str-checklist-8874.firebaseapp.com
FIREBASE_STORAGE_BUCKET=str-checklist-8874.firebasestorage.app
FIREBASE_SERVICE_ACCOUNT_JSON=<full-service-account-json>

ADMIN_EMAILS=sanjayrajbhar8874@gmail.com
APP_TIMEZONE=Asia/Kolkata
```

## Render Deployment

1. Push this project to a private GitHub repository.
2. Open Render Dashboard.
3. Create `New` -> `Web Service`.
4. Connect the repository.
5. Use:
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 120 app:app`
6. Add all environment variables listed above.
7. Deploy.
8. Copy the Render URL and set it as `APP_BASE_URL`.
9. Redeploy after changing `APP_BASE_URL`.

## Cloud Run Deployment

Use Cloud Run if Google Cloud billing and permissions are ready.

```powershell
gcloud run deploy qaqc-structure-checklist --source . --region asia-south1 --allow-unauthenticated
```

Then set environment variables in Cloud Run service settings and redeploy.

## QR Code Rule

Local QR:

```text
http://127.0.0.1:5000/structure/...
```

Public QR must be:

```text
https://your-public-url/structure/...
```
