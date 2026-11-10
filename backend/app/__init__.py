"""Flask app factory."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from flask import Flask, send_from_directory

from app.db import Database
from app.salesforce import MockSalesforce, SalesforceAPI, SalesforceClient

__version__ = "1.0.0"

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def build_salesforce(config: dict) -> SalesforceAPI:
    if config.get("SF_CLIENT_ID") and config.get("SF_CLIENT_SECRET") and config.get("SF_DOMAIN_URL"):
        return SalesforceClient.from_client_credentials(
            config["SF_DOMAIN_URL"], config["SF_CLIENT_ID"], config["SF_CLIENT_SECRET"], config["SF_API_VERSION"]
        )
    logging.getLogger(__name__).warning("Salesforce credentials not set: using the in-memory mock org")
    return MockSalesforce()


def create_app(overrides: dict | None = None) -> Flask:
    app = Flask(__name__, static_folder=None)
    app.config.update(
        DATABASE_URL=os.getenv("DATABASE_URL", "sqlite:///onboarding.db"),
        SF_DOMAIN_URL=os.getenv("SF_DOMAIN_URL"),
        SF_CLIENT_ID=os.getenv("SF_CLIENT_ID"),
        SF_CLIENT_SECRET=os.getenv("SF_CLIENT_SECRET"),
        SF_API_VERSION=os.getenv("SF_API_VERSION", "61.0"),
        MAX_CONTENT_LENGTH=10 * 1024 * 1024,
    )
    app.config.update(overrides or {})
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    db = Database(app.config["DATABASE_URL"])
    db.init_schema()
    app.extensions["db"] = db
    app.extensions["salesforce"] = app.config.get("SALESFORCE") or build_salesforce(app.config)

    from app.routes import api

    app.register_blueprint(api)

    # Serve the built React app (production / Docker). In dev, Vite serves it and proxies /api.
    @app.get("/", defaults={"path": ""})
    @app.get("/<path:path>")
    def frontend(path: str):
        if not FRONTEND_DIST.exists():
            return {"message": "API is running. Start the frontend with `npm run dev` in /frontend."}
        target = FRONTEND_DIST / path
        if path and target.is_file():
            return send_from_directory(FRONTEND_DIST, path)
        return send_from_directory(FRONTEND_DIST, "index.html")

    return app
