"""Production trading security boundary.

The package deliberately separates trade proposals, deterministic risk approval,
execution authorization, exchange credentials, and exchange transport.
"""

__all__ = [
    "models",
    "risk",
    "gate",
    "audit",
    "secrets",
    "adapter",
]
