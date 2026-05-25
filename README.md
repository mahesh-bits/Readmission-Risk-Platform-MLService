# Readmission Risk Platform - ML Service

FastAPI-based ML scoring service for hospital readmission risk.

## Overview

This service exposes:

- `GET /healthz` for health checks
- `POST /v1/predict` for risk scoring and explainability output (`shap`, `top_features`)

The app entry point is `app.main:app`.

## Project Structure

```text
Readmission-Risk-Platform-MLService/
  app/
    main.py
  requirements.txt
  Dockerfile
  .github/
    workflows/
      deploy-azure-webapp.yml
```

## Technology Stack

- Python 3.11
- FastAPI
- Uvicorn / Gunicorn (production startup on Azure)
- Optional Azure Application Insights tracing via `AI_CONNECTION_STRING`

## API Endpoints

### Health

- Method: `GET`
- Path: `/healthz`
- Response:

```json
{"status":"ok"}
```

### Predict

- Method: `POST`
- Path: `/v1/predict`
- Request body:

```json
{
  "features": {
    "age": 72,
    "los": 10,
    "previous_admissions": 3,
    "chf": true,
    "ckd": true,
    "spo2": 92,
    "creatinine": 2.8,
    "wbc": 15.2
  }
}
```

- Response fields:
  - `risk_score` (0.0 to 1.0)
  - `risk_bucket` (`LOW`, `MEDIUM`, `HIGH`)
  - `shap` (feature contribution map)
  - `top_features` (top feature impacts)
  - `model_version`
  - `latency_ms`

## Local Development

### 1. Create and activate virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Run service

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8082 --reload
```

### 4. Test locally

```bash
curl http://localhost:8082/healthz
```

```bash
curl -X POST http://localhost:8082/v1/predict \
  -H "Content-Type: application/json" \
  -d '{"features":{"age":72,"los":10,"chf":true,"ckd":true}}'
```

## Docker

### Build

```bash
docker build -t readmission-ml-service:local .
```

### Run

```bash
docker run --rm -p 8082:8082 readmission-ml-service:local
```

### Health check

```bash
curl http://localhost:8082/healthz
```

## Deploy to Azure Web App with GitHub Actions

Workflow file: `.github/workflows/deploy-azure-webapp.yml`

### Trigger

- Push to `main` when one of these changes:
  - `app/**`
  - `requirements.txt`
  - `Dockerfile`
  - workflow file itself
- Manual trigger via `workflow_dispatch`

### Required GitHub Secrets

Add in GitHub repository:

- `AZURE_WEBAPP_NAME`
  - Your Azure Web App name only
  - Example URL: `https://my-ml-service.azurewebsites.net` -> secret value: `my-ml-service`
- `AZURE_WEBAPP_PUBLISH_PROFILE`
  - Full XML content from Azure publish profile

### How to get publish profile

1. Azure Portal -> Web App -> Overview
2. Click **Get publish profile**
3. Open downloaded `.PublishSettings` file
4. Copy entire XML and store as `AZURE_WEBAPP_PUBLISH_PROFILE`

## Required Azure App Service Configuration

Set startup command in Azure Portal:

```bash
gunicorn -k uvicorn.workers.UvicornWorker app.main:app --bind=0.0.0.0:$PORT
```

Why this matters:

- App Service must start the FastAPI ASGI app from `app/main.py`
- Wrong startup command can result in `404 Not Found` on `/healthz`

## Verify Deployment

After workflow success and app restart:

```bash
curl https://<your-webapp-name>.azurewebsites.net/healthz
```

Expected:

```json
{"status":"ok"}
```

## Troubleshooting

### 404 on `/healthz`

Check:

1. Workflow deploys package `.` (repo root)
2. Startup command is exactly:
   - `gunicorn -k uvicorn.workers.UvicornWorker app.main:app --bind=0.0.0.0:$PORT`
3. Restart the Web App after changing startup command

### GitHub Actions deploy succeeds but app not updated

- Confirm push was to `main`
- Confirm changed file matches workflow `paths`
- Check Actions logs in deploy step for package path and file count

### Dependency/import errors on Azure

- Confirm `requirements.txt` includes all imports used by `app/main.py`
- Re-run workflow after dependency updates

## Optional Observability

This app supports Azure tracing when `AI_CONNECTION_STRING` is set:

- Azure Portal -> Web App -> Configuration -> Application settings
- Add key: `AI_CONNECTION_STRING`
- Restart app

## Security Notes

- Never commit publish profile XML to source control
- Store deployment credentials only in GitHub Secrets
- Restrict CORS origins in production (avoid `"*"` when possible)

## Useful Commands

List Azure Web Apps:

```bash
az webapp list --query "[].{name:name, rg:resourceGroup, host:defaultHostName}" -o table
```

Fetch publishing profile XML via CLI:

```bash
az webapp deployment list-publishing-profiles \
  --name <webapp-name> \
  --resource-group <resource-group> \
  --xml
```
