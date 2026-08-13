"""Feishu OpenAPI client shared by Bitable and bot services."""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any, Optional

import httpx
from dotenv import load_dotenv


FEISHU_BASE_URL = "https://open.feishu.cn/open-apis"
TOKEN_INVALID_CODES = {99991663, 99991664, 99991668, 99991661}
RATE_LIMIT_CODES = {99991400, 99991401, 99991402}

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO_DIR = os.path.dirname(_BACKEND_DIR)
load_dotenv(os.path.join(_REPO_DIR, ".env"))
load_dotenv(os.path.join(_BACKEND_DIR, ".env"))


class FeishuConfigurationError(RuntimeError):
    """Raised when required Feishu credentials are absent."""


class FeishuAPIError(RuntimeError):
    """Normalized error for generic OpenAPI requests."""

    def __init__(
        self,
        code_or_message: int | str,
        msg: Optional[str] = None,
        path: str = "",
        *,
        status_code: Optional[int] = None,
        code: Optional[int] = None,
        log_id: str = "",
    ) -> None:
        if isinstance(code_or_message, int):
            self.code = code_or_message
            self.msg = msg or ""
            message = f"Feishu API error {self.code} ({path}): {self.msg}"
        else:
            self.code = code
            self.msg = str(code_or_message)
            message = self.msg
        self.path = path
        self.status_code = status_code
        self.log_id = log_id
        super().__init__(message)


def _parse_table_ids(raw: str) -> dict[str, str]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


class FeishuConfig:
    """Environment-driven configuration without exposing secret values."""

    def __init__(self) -> None:
        self.app_id = os.getenv("FEISHU_APP_ID", "").strip()
        self.app_secret = os.getenv("FEISHU_APP_SECRET", "").strip()
        self.base_url = os.getenv("FEISHU_BASE_URL", FEISHU_BASE_URL).rstrip("/")
        self.bitable_app_token = os.getenv("FEISHU_BITABLE_APP_TOKEN", "").strip()
        self.bitable_table_ids = _parse_table_ids(
            os.getenv("FEISHU_BITABLE_TABLE_IDS", "")
        )
        self.verification_token = os.getenv("FEISHU_VERIFICATION_TOKEN", "")
        self.encrypt_key = os.getenv("FEISHU_ENCRYPT_KEY", "")
        self.teacher_open_id = os.getenv("FEISHU_TEACHER_OPEN_ID", "")
        # Web app base URL for card jump buttons (no callback needed).
        self.web_base_url = os.getenv(
            "FEISHU_WEB_BASE_URL", "http://127.0.0.1:8000"
        ).rstrip("/")

    @property
    def is_configured(self) -> bool:
        return bool(self.app_id and self.app_secret)

    def summary(self) -> dict[str, Any]:
        return {
            "configured": self.is_configured,
            "app_id": (self.app_id[:8] + "...") if self.app_id else "",
            "bitable_configured": bool(self.bitable_app_token),
            "teacher_open_id_configured": bool(self.teacher_open_id),
        }


class FeishuClient:
    """Async Feishu client with token caching."""

    def __init__(
        self,
        app_id: str | FeishuConfig = "",
        app_secret: str = "",
        *,
        base_url: str = FEISHU_BASE_URL,
        timeout: float = 20.0,
        refresh_margin: int = 300,
        http_client: Optional[httpx.AsyncClient] = None,
        config: Optional[FeishuConfig] = None,
    ) -> None:
        if isinstance(app_id, FeishuConfig):
            config = app_id
            app_id = config.app_id
            app_secret = config.app_secret
            base_url = config.base_url
        self.config = config or FeishuConfig()
        if app_id:
            self.config.app_id = str(app_id).strip()
        if app_secret:
            self.config.app_secret = app_secret.strip()
        if base_url != FEISHU_BASE_URL or not self.config.base_url:
            self.config.base_url = base_url.rstrip("/")

        self.app_id = self.config.app_id
        self.app_secret = self.config.app_secret
        self.base_url = self.config.base_url.rstrip("/")
        self.refresh_margin = refresh_margin
        self._http = http_client or httpx.AsyncClient(timeout=timeout)
        self._owns_http_client = http_client is None
        self._tenant_token = ""
        self._tenant_token_expires_at = 0.0
        self._token_lock = asyncio.Lock()

    @classmethod
    def from_env(cls) -> "FeishuClient":
        return cls(config=FeishuConfig())

    @property
    def configured(self) -> bool:
        return bool(self.app_id and self.app_secret)

    async def close(self) -> None:
        if self._owns_http_client:
            await self._http.aclose()

    async def aclose(self) -> None:
        await self.close()

    def _cached_token_is_valid(self) -> bool:
        return bool(
            self._tenant_token
            and time.monotonic()
            < self._tenant_token_expires_at - self.refresh_margin
        )

    async def get_tenant_access_token(self, *, force_refresh: bool = False) -> str:
        if not self.configured:
            raise FeishuConfigurationError(
                "FEISHU_APP_ID and FEISHU_APP_SECRET must be configured"
            )
        if not force_refresh and self._cached_token_is_valid():
            return self._tenant_token

        async with self._token_lock:
            if not force_refresh and self._cached_token_is_valid():
                return self._tenant_token
            response = await self._http.post(
                f"{self.base_url}/auth/v3/tenant_access_token/internal/",
                json={"app_id": self.app_id, "app_secret": self.app_secret},
            )
            payload = self._json_payload(response)
            if response.status_code >= 400 or payload.get("code") != 0:
                self._raise_api_error(
                    response, payload, "Failed to obtain tenant access token"
                )
            token = str(payload.get("tenant_access_token") or "").strip()
            if not token:
                raise FeishuAPIError(
                    "Feishu returned success without tenant_access_token",
                    status_code=response.status_code,
                    code=payload.get("code"),
                )
            expires_in = max(int(payload.get("expire") or 7200), 60)
            self._tenant_token = token
            self._tenant_token_expires_at = time.monotonic() + expires_in
            return token

    async def request(
        self,
        method: str,
        path: str,
        params: Optional[dict] = None,
        json_body: Optional[dict] = None,
        files: Optional[dict] = None,
        form: Optional[dict] = None,
        retries: int = 2,
    ) -> Any:
        """Call a JSON OpenAPI endpoint with auth refresh and rate retries."""
        url = f"{self.base_url}/{path.lstrip('/')}"
        for attempt in range(retries + 1):
            token = await self.get_tenant_access_token(force_refresh=False)
            headers = {"Authorization": f"Bearer {token}"}
            try:
                response = await self._http.request(
                    method,
                    url,
                    params=params,
                    json=None if files is not None else json_body,
                    files=files,
                    data=form if files is not None else None,
                    headers=headers,
                )
            except httpx.HTTPError as exc:
                raise FeishuAPIError(-1, f"network error: {exc}", path) from exc

            payload = self._json_payload(response)
            code = payload.get("code")
            if response.status_code == 429 or code in RATE_LIMIT_CODES:
                if attempt < retries:
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
            if code in TOKEN_INVALID_CODES and attempt < retries:
                self._tenant_token = ""
                self._tenant_token_expires_at = 0.0
                continue
            if response.status_code >= 400 or code not in (None, 0):
                self._raise_api_error(response, payload, f"Feishu request failed: {path}")
            if not payload:
                raise FeishuAPIError(
                    "Feishu JSON endpoint returned a non-JSON response",
                    status_code=response.status_code,
                    path=path,
                )
            return payload.get("data", payload)
        raise FeishuAPIError(-1, "request failed after retries", path)

    async def health_check(self) -> dict[str, Any]:
        if not self.configured:
            return {
                "status": "not_configured",
                "auth": False,
                "message": "Set FEISHU_APP_ID and FEISHU_APP_SECRET",
            }
        try:
            await self.get_tenant_access_token()
            return {"status": "auth_ok", "auth": True}
        except (FeishuConfigurationError, FeishuAPIError, httpx.HTTPError) as exc:
            result = {
                "status": "error",
                "auth": bool(self._tenant_token),
                "message": str(exc),
            }
            if isinstance(exc, FeishuAPIError):
                result.update(
                    code=exc.code,
                    status_code=exc.status_code,
                    log_id=exc.log_id,
                )
            return result

    @staticmethod
    def _json_payload(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
            return payload if isinstance(payload, dict) else {}
        except ValueError:
            return {}

    @staticmethod
    def _raise_api_error(
        response: httpx.Response,
        payload: dict[str, Any],
        prefix: str,
    ) -> None:
        error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
        message = str(payload.get("msg") or response.reason_phrase or "unknown error")
        raise FeishuAPIError(
            f"{prefix}: {message}",
            status_code=response.status_code,
            code=payload.get("code"),
            log_id=str(error.get("log_id") or ""),
        )
