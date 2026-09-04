"""FastAPI entrypoint for the Cross-Merchant Coalition Engine.

Run locally:
    uvicorn app.main:app --reload
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import audit as audit_api
from app.api import catalog as catalog_api
from app.api import checkout as checkout_api
from app.api import health as health_api

app = FastAPI(
    title="Cross-Merchant Coalition Engine",
    description=(
        "Autonomous commerce graph: semantic matching, machine-to-machine "
        "agent negotiation, and Razorpay Route payment splitting with a "
        "saga-based failure recovery layer. TEST MODE ONLY."
    ),
    version="0.1.0",
)

# Dev CORS — allow the Vite frontend (localhost:5173) to call the API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_api.router)
app.include_router(catalog_api.router)
app.include_router(checkout_api.router)
app.include_router(checkout_api.webhook_router)
app.include_router(audit_api.router)
