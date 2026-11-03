"""Verifying Supabase access tokens locally against the project's public signing keys (JWKS)."""

import asyncio
import time
import uuid
from dataclasses import dataclass

import httpx
import jwt

ALLOWED_ALGORITHMS = ("ES256", "RS256")  # asymmetric only; legacy HS256 is not accepted
MIN_REFRESH_INTERVAL_S = 30.0  # unknown key ids trigger a refetch, but not a refetch storm
JWKS_TIMEOUT_S = 5.0


class SupabaseAuthError(Exception):
    """The token is not a valid access token for this project."""


class SupabaseUnavailableError(Exception):
    """The project's signing keys could not be fetched."""


@dataclass(frozen=True)
class SupabaseClaims:
    user_id: uuid.UUID
    email: str | None


class SupabaseVerifier:
    def __init__(
        self,
        supabase_url: str,
        *,
        audience: str,
        cache_ttl_s: float,
        http: httpx.AsyncClient,
    ) -> None:
        self._issuer = f"{supabase_url}/auth/v1"
        self._jwks_url = f"{self._issuer}/.well-known/jwks.json"
        self._audience = audience
        self._cache_ttl_s = cache_ttl_s
        self._http = http
        self._keys: dict[str, jwt.PyJWK] = {}
        self._fetched_at = float("-inf")
        self._lock = asyncio.Lock()

    async def verify(self, token: str) -> SupabaseClaims:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.InvalidTokenError as exc:
            raise SupabaseAuthError("malformed token") from exc
        algorithm, key_id = header.get("alg"), header.get("kid")
        if algorithm not in ALLOWED_ALGORITHMS or not isinstance(key_id, str):
            raise SupabaseAuthError("unsupported token algorithm")

        key = await self._key(key_id)
        try:
            claims = jwt.decode(
                token,
                key.key,
                algorithms=[algorithm],
                audience=self._audience,
                issuer=self._issuer,
                options={"require": ["exp", "sub", "aud", "iss"]},
            )
            user_id = uuid.UUID(claims["sub"])
        except (jwt.InvalidTokenError, ValueError) as exc:
            raise SupabaseAuthError("invalid token") from exc
        if claims.get("role") != "authenticated":
            raise SupabaseAuthError("not a signed-in user")
        email = claims.get("email")
        return SupabaseClaims(user_id=user_id, email=email if isinstance(email, str) else None)

    async def _key(self, key_id: str) -> jwt.PyJWK:
        if not self._fresh() or key_id not in self._keys:
            async with self._lock:
                if not self._fresh() or key_id not in self._keys:
                    await self._refresh()
        key = self._keys.get(key_id)
        if key is None:
            raise SupabaseAuthError("unknown signing key")
        return key

    def _fresh(self) -> bool:
        return time.monotonic() - self._fetched_at < self._cache_ttl_s

    async def _refresh(self) -> None:
        if self._keys and time.monotonic() - self._fetched_at < MIN_REFRESH_INTERVAL_S:
            return
        try:
            response = await self._http.get(self._jwks_url, timeout=JWKS_TIMEOUT_S)
            response.raise_for_status()
            key_set = jwt.PyJWKSet.from_dict(response.json())
        except (httpx.HTTPError, ValueError, jwt.PyJWKSetError) as exc:
            raise SupabaseUnavailableError("could not fetch Supabase signing keys") from exc
        self._keys = {key.key_id: key for key in key_set.keys if key.key_id}
        self._fetched_at = time.monotonic()
