"""Install-integrity guard.

The SA packages are expected to be EDITABLE installs so the test suite (and the
running agents/gateway) exercise the source tree. A force-reinstalled *copy* in
site-packages silently lags the source — which has twice masqueraded as a
confusing failure: a cryptic ``ImportError`` for a symbol that exists in source,
and a "failing" test that actually passes against source. This test makes that
condition fail LOUDLY, with the exact remediation, instead of wasting a debugging
session chasing a phantom code bug.

Run ``./sa-local-refresh.sh <plugin>`` (editable by default) to fix a stale copy.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent

# import-name → source root that an editable install resolves the package under.
_SA_PACKAGES = {
    "solace_architect_core": _REPO / "solace-architect-core" / "src",
    "solace_architect_webui_entrypoint":
        _REPO / "plugins" / "solace-architect-webui-entrypoint" / "src",
}


@pytest.mark.parametrize("pkg,src_root", sorted(_SA_PACKAGES.items()))
def test_sa_package_imports_from_source_not_stale_copy(pkg: str, src_root: Path):
    mod = importlib.import_module(pkg)
    resolved = Path(mod.__file__).resolve()
    src_root = src_root.resolve()
    assert str(resolved).startswith(str(src_root)), (
        f"\n{pkg} is imported from a STALE copy:\n"
        f"    {resolved}\n"
        f"expected the editable source tree under:\n"
        f"    {src_root}\n"
        f"A copy silently lags the source. Reinstall editable:\n"
        f"    ./sa-local-refresh.sh "
        f"{pkg.replace('solace_architect_', '').replace('_', '-')}\n"
        f"(or: pip install -e <plugin-dir> --no-deps)"
    )
