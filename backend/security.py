"""Small, environment-configured API access controls for the Odin prototype.

Set ODIN_API_TOKEN to require a bearer token on protected endpoints. In
ODIN_ENV=production, missing token configuration fails closed. This is a
shared-token gate, not per-user identity, role-based access control, or SSO.
"""
import hmac
import os

from fastapi import Header, HTTPException


def security_mode() -> str:
    if os.getenv("ODIN_API_TOKEN", "").strip():
        return "bearer_token_required"
    if os.getenv("ODIN_ENV", "").strip().lower() == "production":
        return "misconfigured_production"
    return "local_development_open"


def require_api_token(authorization: str | None = Header(default=None)) -> None:
    expected = os.getenv("ODIN_API_TOKEN", "").strip()
    production = os.getenv("ODIN_ENV", "").strip().lower() == "production"
    if not expected:
        if production:
            raise HTTPException(status_code=503, detail="API authentication is not configured")
        return
    scheme, _, supplied = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(
            status_code=401,
            detail="Valid bearer token required",
            headers={"WWW-Authenticate": "Bearer"},
        )
