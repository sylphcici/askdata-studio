from __future__ import annotations

import secrets
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AuthUser:
    user_id: str
    username: str
    display_name: str
    role: str

    def public(self) -> dict[str, str]:
        return {
            "user_id": self.user_id,
            "username": self.username,
            "display_name": self.display_name,
            "role": self.role,
        }


class AuthService:
    """进程内账号认证；令牌在服务重启后失效。"""

    @staticmethod
    def _accounts() -> dict[str, dict[str, object]]:
        return {
        "admin": {
            "password": os.getenv("ASKDATA_ADMIN_PASSWORD", ""),
            "user": AuthUser("demo_admin", "admin", "系统管理员", "admin"),
        },
        "sales": {
            "password": os.getenv("ASKDATA_SALES_PASSWORD", ""),
            "user": AuthUser("demo_current_sales", "sales", "销售分析员", "current_sales"),
        },
        "mock": {
            "password": os.getenv("ASKDATA_MOCK_PASSWORD", ""),
            "user": AuthUser("demo_analyst", "mock", "Mock 数据分析员", "analyst"),
        },
        }

    def __init__(self) -> None:
        self._tokens: dict[str, AuthUser] = {}
        self.accounts = self._accounts()

    def login(self, username: str, password: str) -> tuple[str, AuthUser] | None:
        account = self.accounts.get(username.strip())
        if not account or not secrets.compare_digest(str(account["password"]), password):
            return None
        token = secrets.token_urlsafe(32)
        user = account["user"]
        self._tokens[token] = user
        return token, user

    def authenticate(self, authorization: str | None) -> AuthUser | None:
        if not authorization:
            return None
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            return None
        return self._tokens.get(token)

    def logout(self, authorization: str | None) -> None:
        if not authorization:
            return
        _, _, token = authorization.partition(" ")
        self._tokens.pop(token, None)
