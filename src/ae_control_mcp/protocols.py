"""Abstractions (Protocols) following Interface Segregation and Dependency Inversion."""

from __future__ import annotations

from typing import Any, Protocol

from .geometry.models import CompositionGeometry, LayoutReport, SpatialFinding


class ScriptRunner(Protocol):
    """Executes an ExtendScript snippet and returns a structured result dict."""

    def run(self, script_code: str, timeout_seconds: float = 15.0) -> dict[str, Any]: ...


class GeometryProvider(Protocol):
    """Fetches composition and layer geometry from a host application."""

    def get_composition_geometry(
        self,
        comp_name: str | None = None,
        time_seconds: float | None = None,
    ) -> CompositionGeometry: ...


class LayoutRule(Protocol):
    """Single spatial evaluation rule applied to a composition's geometry."""

    @property
    def name(self) -> str: ...

    def evaluate(self, comp: CompositionGeometry) -> list[SpatialFinding]: ...


class LayoutAnalyzer(Protocol):
    """Analyzes composition geometry and produces a structured layout report."""

    def analyze(self, comp: CompositionGeometry) -> LayoutReport: ...
