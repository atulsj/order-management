from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from app.core.config import Settings, get_settings

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    subject: str
    email: str | None
    name: str | None
    roles: frozenset[str]

    def has_any_role(self, roles: set[str]) -> bool:
        return bool(self.roles.intersection(roles))


@lru_cache
def _jwk_client(url: str) -> PyJWKClient:
    return PyJWKClient(url, cache_keys=True, lifespan=300)


def get_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Principal:
    if settings.auth_disabled:
        role_header = request.headers.get("X-Debug-Roles", "customer,operator,admin")
        return Principal(
            subject=request.headers.get("X-Debug-Subject", "local-development-user"),
            email=request.headers.get("X-Debug-Email", "developer@example.com"),
            name="Local Developer",
            roles=frozenset(role.strip() for role in role_header.split(",") if role.strip()),
        )
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Bearer token is required")
    try:
        signing_key = _jwk_client(settings.jwks_url).get_signing_key_from_jwt(
            credentials.credentials
        )
        claims: dict[str, Any] = jwt.decode(
            credentials.credentials,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.keycloak_audience,
            issuer=settings.keycloak_issuer,
            options={"require": ["exp", "iat", "iss", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token is invalid or expired") from exc
    realm_roles = claims.get("realm_access", {}).get("roles", [])
    client_roles = claims.get("resource_access", {}).get(
        settings.keycloak_audience, {}
    ).get("roles", [])
    return Principal(
        subject=claims["sub"],
        email=claims.get("email"),
        name=claims.get("name") or claims.get("preferred_username"),
        roles=frozenset([*realm_roles, *client_roles]),
    )


def require_roles(*roles: str):
    def dependency(principal: Annotated[Principal, Depends(get_principal)]) -> Principal:
        if not principal.has_any_role(set(roles)):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
        return principal

    return dependency
