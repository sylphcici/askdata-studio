import os
import unittest
import uuid

os.environ.setdefault("ASKDATA_ADMIN_PASSWORD", "test-admin-password")
os.environ.setdefault("ASKDATA_SALES_PASSWORD", "test-sales-password")
os.environ.setdefault("ASKDATA_MOCK_PASSWORD", "test-mock-password")

from fastapi.testclient import TestClient

from app.main import app
from app.security import AuthService


class AuthServiceTest(unittest.TestCase):
    def test_conversation_api_persists_and_isolates_accounts(self) -> None:
        conversation_id = f"test-{uuid.uuid4().hex}"
        with TestClient(app) as client:
            self.assertEqual(client.get("/api/conversations").status_code, 401)
            sales_token = client.post(
                "/api/auth/login",
                json={"username": "sales", "password": "test-sales-password"},
            ).json()["access_token"]
            mock_token = client.post(
                "/api/auth/login",
                json={"username": "mock", "password": "test-mock-password"},
            ).json()["access_token"]
            sales_headers = {"Authorization": f"Bearer {sales_token}"}
            mock_headers = {"Authorization": f"Bearer {mock_token}"}
            base = {
                "id": conversation_id,
                "title": "销售对话",
                "updatedAt": 1000,
                "turns": [],
                "workspace": {},
            }
            try:
                self.assertEqual(
                    client.put(
                        f"/api/conversations/{conversation_id}",
                        headers=sales_headers,
                        json=base,
                    ).status_code,
                    200,
                )
                self.assertEqual(
                    client.put(
                        f"/api/conversations/{conversation_id}",
                        headers=mock_headers,
                        json={**base, "title": "Mock 对话"},
                    ).status_code,
                    200,
                )
                sales_items = client.get(
                    "/api/conversations", headers=sales_headers
                ).json()
                mock_items = client.get(
                    "/api/conversations", headers=mock_headers
                ).json()
                self.assertEqual(
                    next(item for item in sales_items if item["id"] == conversation_id)["title"],
                    "销售对话",
                )
                self.assertEqual(
                    next(item for item in mock_items if item["id"] == conversation_id)["title"],
                    "Mock 对话",
                )
                client.delete(
                    f"/api/conversations/{conversation_id}", headers=sales_headers
                )
                self.assertFalse(
                    any(
                        item["id"] == conversation_id
                        for item in client.get(
                            "/api/conversations", headers=sales_headers
                        ).json()
                    )
                )
                self.assertTrue(
                    any(
                        item["id"] == conversation_id
                        for item in client.get(
                            "/api/conversations", headers=mock_headers
                        ).json()
                    )
                )
            finally:
                client.delete(
                    f"/api/conversations/{conversation_id}", headers=sales_headers
                )
                client.delete(
                    f"/api/conversations/{conversation_id}", headers=mock_headers
                )

    def test_mock_accounts_issue_isolated_users(self) -> None:
        auth = AuthService()
        admin = auth.login("admin", "test-admin-password")
        sales = auth.login("sales", "test-sales-password")
        mock = auth.login("mock", "test-mock-password")

        self.assertEqual(admin[1].user_id, "demo_admin")
        self.assertEqual(sales[1].user_id, "demo_current_sales")
        self.assertEqual(mock[1].user_id, "demo_analyst")
        self.assertEqual(mock[1].role, "analyst")
        self.assertNotEqual(admin[0], sales[0])
        self.assertIsNone(auth.login("admin", "wrong"))

    def test_api_requires_login_and_filters_schema(self) -> None:
        with TestClient(app) as client:
            self.assertEqual(client.get("/api/schema").status_code, 401)
            admin_token = client.post(
                "/api/auth/login",
                json={"username": "admin", "password": "test-admin-password"},
            ).json()["access_token"]
            sales_token = client.post(
                "/api/auth/login",
                json={"username": "sales", "password": "test-sales-password"},
            ).json()["access_token"]
            mock_token = client.post(
                "/api/auth/login",
                json={"username": "mock", "password": "test-mock-password"},
            ).json()["access_token"]
            admin_schema = client.get(
                "/api/schema",
                headers={"Authorization": f"Bearer {admin_token}"},
            ).json()
            sales_schema = client.get(
                "/api/schema",
                headers={"Authorization": f"Bearer {sales_token}"},
            ).json()
            mock_schema = client.get(
                "/api/schema",
                headers={"Authorization": f"Bearer {mock_token}"},
            ).json()

            self.assertGreater(len(admin_schema), len(sales_schema))
            self.assertNotIn("orders_history", {item["id"] for item in sales_schema})
            self.assertTrue(mock_schema)
            self.assertEqual(
                {item["database"] for item in mock_schema},
                {"askdata_mock"},
            )
            self.assertIn("orders_current", {item["id"] for item in mock_schema})
            self.assertNotIn(
                "ecommerce_ops.orders",
                {item["id"] for item in mock_schema},
            )

            mock_tools = client.get(
                "/api/mcp/tools",
                headers={"Authorization": f"Bearer {mock_token}"},
            ).json()
            tool_names = {item["name"] for item in mock_tools}
            self.assertIn("query_askdata_mock", tool_names)
            self.assertNotIn("query_ecommerce_ops", tool_names)

    def test_evaluation_center_is_admin_only(self) -> None:
        with TestClient(app) as client:
            admin_token = client.post(
                "/api/auth/login",
                json={"username": "admin", "password": "test-admin-password"},
            ).json()["access_token"]
            sales_token = client.post(
                "/api/auth/login",
                json={"username": "sales", "password": "test-sales-password"},
            ).json()["access_token"]

            self.assertEqual(client.get("/api/admin/evaluations").status_code, 401)
            self.assertEqual(
                client.get(
                    "/api/admin/evaluations",
                    headers={"Authorization": f"Bearer {sales_token}"},
                ).status_code,
                403,
            )
            self.assertEqual(
                client.get(
                    "/api/admin/evaluations",
                    headers={"Authorization": f"Bearer {admin_token}"},
                ).status_code,
                200,
            )
            self.assertEqual(
                client.get(
                    "/api/admin/evaluations/sales-eval-20000101-000000",
                    headers={"Authorization": f"Bearer {admin_token}"},
                ).status_code,
                404,
            )


if __name__ == "__main__":
    unittest.main()
