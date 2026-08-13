import json
import os
import unittest

import httpx

from feishu.client import FeishuClient

# feishu.client's import runs load_dotenv on backend/.env; purge any real
# credentials so "unconfigured" tests stay deterministic on machines that
# already have live Feishu config.
for _key in [k for k in os.environ if k.startswith("FEISHU_")]:
    os.environ.pop(_key, None)


class FeishuClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_tenant_token_is_cached(self):
        calls = {"auth": 0}

        async def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/auth/v3/tenant_access_token/internal/")
            calls["auth"] += 1
            body = json.loads(request.content.decode())
            self.assertEqual(body["app_id"], "cli_test")
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "msg": "success",
                    "tenant_access_token": "t-test-token",
                    "expire": 7200,
                },
            )

        transport = httpx.MockTransport(handler)
        http = httpx.AsyncClient(transport=transport, base_url="https://example.test")
        client = FeishuClient(
            "cli_test",
            "secret",
            base_url="https://example.test",
            http_client=http,
        )
        try:
            first = await client.get_tenant_access_token()
            second = await client.get_tenant_access_token()
            self.assertEqual(first, "t-test-token")
            self.assertEqual(second, first)
            self.assertEqual(calls["auth"], 1)
        finally:
            await http.aclose()

    async def test_unconfigured_health_is_explicit(self):
        client = FeishuClient(http_client=httpx.AsyncClient())
        try:
            result = await client.health_check()
            self.assertEqual(result["status"], "not_configured")
            self.assertFalse(result["auth"])
        finally:
            await client._http.aclose()


if __name__ == "__main__":
    unittest.main()
