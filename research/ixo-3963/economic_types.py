from __future__ import annotations

from copy import deepcopy
from typing import Any

REQUIRED_SCENARIOS = (
    "base",
    "conservative",
    "failure",
    "rapid_growth",
    "liquidity_shock",
    "validator_exit",
    "concentrated_selloff",
    "low_fee_conversion",
    "domain_churn",
    "governance_capture",
)

REQUIRED_ALTERNATIVES = (
    "tokenless_service",
    "shared_security_agent",
    "recapitalized_ixo",
    "native_agent",
)


def deep_copy(value: Any) -> Any:
    return deepcopy(value)


def override(scenario: dict[str, Any], key: str, default: Any) -> Any:
    return scenario[key] if key in scenario else default


def product(values: list[float]) -> float:
    result = 1.0
    for value in values:
        result *= float(value)
    return result


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def safe_div(numerator: float, denominator: float, default: float = 0.0) -> float:
    if abs(denominator) < 1e-12:
        return default
    return numerator / denominator


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(v) for v in values)
    position = (len(ordered) - 1) * q
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction
