from fastapi import FastAPI


from app.config import settings

app = FastAPI(
title="Forager × HubSpot Enrichment",
version="0.1.0",
)

@app.get("/")
def root():
    return {
    "service": "Forager HubSpot Enrichment",
    "status": "running",
    }

@app.get("/health")
def health():
    return {
    "status": "ok",
    "forager_configured": bool(
    settings.forager_api_key and settings.forager_account_id
    ),
    "hubspot_configured": bool(settings.hubspot_access_token),
    }