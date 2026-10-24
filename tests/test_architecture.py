"""Architecture fitness functions: the dependency rule is enforced, not just documented (ADR-0002).

    api ──► application ──► domain ◄── infrastructure
     └────► container (composition root) wires everything

Inner layers must never import outer ones, and the domain stays framework-free.
"""

import ast
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[1] / "fuel_route"

# layer -> internal modules it must NOT import (prefix match on the dotted path)
FORBIDDEN = {
    "domain": (
        "django",
        "rest_framework",
        "requests",
        "fuel_route.application",
        "fuel_route.infrastructure",
        "fuel_route.api",
        "fuel_route.models",
        "fuel_route.container",
    ),
    "application": (
        "rest_framework",
        "requests",
        "django",
        "fuel_route.infrastructure",
        "fuel_route.api",
        "fuel_route.models",
        "fuel_route.container",
    ),
    "infrastructure": ("rest_framework", "fuel_route.api", "fuel_route.container"),
}


def imports_of(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            base = node.module
            if node.level:  # relative import -> resolve against the file's package
                parts = path.relative_to(PKG.parent).with_suffix("").parts[: -node.level]
                base = ".".join((*parts, node.module))
            found.add(base)
    return found


@pytest.mark.parametrize("layer", sorted(FORBIDDEN))
def test_dependency_rule(layer):
    violations = [
        f"{py.relative_to(PKG.parent)} imports {name}"
        for py in sorted((PKG / layer).rglob("*.py"))
        for name in imports_of(py)
        if name.startswith(FORBIDDEN[layer])
    ]
    assert violations == []
