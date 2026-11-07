from __future__ import annotations

from .types import RouteShapeError
from ..simulation.models import RouteQuote


def validate_cross_dex_route(route: tuple[RouteQuote, ...]) -> None:
    """Require a two-leg cycle across distinct venues, returning to start token."""
    if len(route) != 2:
        raise RouteShapeError("cross-DEX route must contain exactly two swaps")
    if route[0].venue == route[1].venue:
        raise RouteShapeError("cross-DEX route must use two distinct venues")
    _validate_cycle(route)


def validate_triangular_route(route: tuple[RouteQuote, ...]) -> None:
    """Require a three-leg cycle visiting three distinct token symbols."""
    if len(route) != 3:
        raise RouteShapeError("triangular route must contain exactly three swaps")
    _validate_cycle(route)
    tokens = [route[0].token_in] + [q.token_out for q in route]
    if len(set(tokens[:-1])) != 3:
        raise RouteShapeError("triangular route must visit three distinct tokens")


def _validate_cycle(route: tuple[RouteQuote, ...]) -> None:
    if not route:
        raise RouteShapeError("route cannot be empty")
    for previous, current in zip(route, route[1:]):
        if previous.token_out != current.token_in:
            raise RouteShapeError("route is disconnected")
        if previous.output_amount != current.input_amount:
            raise RouteShapeError("route amounts do not match")
    if route[-1].token_out != route[0].token_in:
        raise RouteShapeError("route does not return to its starting token")
