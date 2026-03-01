from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List


class FailureCode(str, Enum):
    """Machine-readable codes describing why a mass balance failed.

    Codes are ordered from specific root causes to general symptoms so that
    the most actionable information appears first.
    """
    MISSING_STOCK_COMPONENT = "missing_stock_component"
    STOCK_CONCENTRATION_TOO_LOW = "stock_concentration_too_low"
    TARGET_OUTSIDE_REACHABLE_COMPOSITIONS = "target_outside_reachable_compositions"
    BELOW_MINIMUM_PIPETTE_VOLUME = "below_minimum_pipette_volume"
    UNWANTED_STOCK_COMPONENT = "unwanted_stock_component"
    TOLERANCE_EXCEEDED = "tolerance_exceeded"


@dataclass
class FailureDetail:
    """One specific failure mode detected during diagnosis."""
    code: FailureCode
    description: str
    affected_components: List[str] = field(default_factory=list)
    affected_stocks: List[str] = field(default_factory=list)
    data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code.value,
            "description": self.description,
            "affected_components": self.affected_components,
            "affected_stocks": self.affected_stocks,
            "data": self.data,
        }


@dataclass
class BalanceDiagnosis:
    """Full diagnosis of a single balance result."""
    success: bool
    details: List[FailureDetail] = field(default_factory=list)
    component_errors: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "details": [d.to_dict() for d in self.details],
            "component_errors": self.component_errors,
        }

    def summary(self) -> str:
        """Return a human-readable failure summary."""
        if self.success:
            return "Balance succeeded."

        lines = ["Balance failed:"]
        for detail in self.details:
            lines.append(f"  [{detail.code.value}] {detail.description}")
            if detail.affected_components:
                lines.append(f"    Components: {', '.join(detail.affected_components)}")
            if detail.affected_stocks:
                lines.append(f"    Stocks: {', '.join(detail.affected_stocks)}")

        if self.component_errors:
            worst_comp = max(self.component_errors, key=lambda k: abs(self.component_errors[k]))
            worst_err = self.component_errors[worst_comp] * 100.0
            lines.append(f"  Worst error: {worst_comp} at {worst_err:.1f}%")

        return "\n".join(lines)
