#!/usr/bin/env bash
# Run in Google Cloud Shell from the repository root. Creates billable cloud resources.
set -euo pipefail
cd "$(dirname "$0")/.."
PROJECT='tg-control-center'
REGION='asia-east1'
SERVICE='tg-execution'
RUNTIME="tg-runtime@${PROJECT}.iam.gserviceaccount.com"
SCHEDULER="tg-scheduler@${PROJECT}.iam.gserviceaccount.com"
ADMIN='3bYS2rcw9jOf4A5sIvdO5DejMKP2'
gcloud config set project "$PROJECT"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com cloudscheduler.googleapis.com firestore.googleapis.com identitytoolkit.googleapis.com
for account in tg-runtime tg-scheduler; do
  if ! gcloud iam service-accounts describe "${account}@${PROJECT}.iam.gserviceaccount.com" >/dev/null 2>&1; then
    gcloud iam service-accounts create "$account"
  fi
done
for role in roles/datastore.user roles/firebaseauth.viewer; do
  gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:${RUNTIME}" --role="$role" --condition=None >/dev/null
done
if ! gcloud secrets describe tg-session-key >/dev/null 2>&1; then
  python3 -c 'import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode(),end="")' | gcloud secrets create tg-session-key --replication-policy=automatic --data-file=-
fi
gcloud secrets add-iam-policy-binding tg-session-key --member="serviceAccount:${RUNTIME}" --role=roles/secretmanager.secretAccessor >/dev/null
gcloud run deploy "$SERVICE" --source backend --region "$REGION" --service-account "$RUNTIME" --allow-unauthenticated --max-instances 2 --min-instances 0 --concurrency 10 --timeout 360 --memory 512Mi --set-env-vars "GOOGLE_CLOUD_PROJECT=${PROJECT},ADMIN_UID=${ADMIN},SCHEDULER_EMAIL=${SCHEDULER},ALLOWED_ORIGINS=https://tristaru816-wq.github.io" --set-secrets 'SESSION_KEY=tg-session-key:latest' --quiet
SERVICE_URL="$(gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)')"
gcloud run services update "$SERVICE" --region "$REGION" --update-env-vars "SERVICE_URL=${SERVICE_URL}" --quiet
# The endpoint verifies this scheduler service account's OIDC identity itself.
if gcloud scheduler jobs describe tg-minute-tick --location "$REGION" >/dev/null 2>&1; then
  gcloud scheduler jobs update http tg-minute-tick --location "$REGION" --schedule '* * * * *' --uri "${SERVICE_URL}/tick" --http-method POST --oidc-service-account-email "$SCHEDULER" --oidc-token-audience "$SERVICE_URL" --attempt-deadline 320s --max-retry-attempts 0 --time-zone Asia/Taipei --quiet
else
  gcloud scheduler jobs create http tg-minute-tick --location "$REGION" --schedule '* * * * *' --uri "${SERVICE_URL}/tick" --http-method POST --oidc-service-account-email "$SCHEDULER" --oidc-token-audience "$SERVICE_URL" --attempt-deadline 320s --max-retry-attempts 0 --time-zone Asia/Taipei --quiet
fi
export SERVICE_URL PROJECT ADMIN
python3 - <<'PY'
import json,os,subprocess,urllib.request
# Merge one configuration field. Do not replace the existing dashboard data.
token=subprocess.check_output(['gcloud','auth','print-access-token'],text=True).strip()
url=f"https://firestore.googleapis.com/v1/projects/{os.environ['PROJECT']}/databases/(default)/documents/adminData/{os.environ['ADMIN']}?updateMask.fieldPaths=executionEndpoint"
body=json.dumps({'fields':{'executionEndpoint':{'stringValue':os.environ['SERVICE_URL']}}}).encode()
req=urllib.request.Request(url,data=body,method='PATCH',headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
with urllib.request.urlopen(req) as response:
    assert response.status==200
print('部署與排程設定完成。請重新登入原網頁，開啟「連接 TG」。')
print('執行服務：'+os.environ['SERVICE_URL'])
PY
