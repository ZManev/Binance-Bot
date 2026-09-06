from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class SecretProvider(Protocol):
    def get(self, name: str) -> str: ...


@dataclass(frozen=True)
class BinanceCredentials:
    api_key: str
    api_secret: str


class BinanceCredentialProvider:
    """Credential boundary. Production implementation must call a real secrets manager.

    Do not replace this with application-wide environment access. Only the Binance
    adapter should be wired to this provider in the production dependency graph.
    """

    def __init__(self, provider: SecretProvider) -> None:
        self._provider = provider

    def get(self) -> BinanceCredentials:
        return BinanceCredentials(
            api_key=self._provider.get("binance/production/api-key"),
            api_secret=self._provider.get("binance/production/api-secret"),
        )
