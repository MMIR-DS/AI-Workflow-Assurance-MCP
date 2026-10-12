# ruff: noqa: I001
"""Verify that a clean virtual environment imports AWA from its installed package.

Run after CI installs the freshly built wheel. The probe runs from a temporary
working directory with PYTHONPATH removed, so the repository checkout cannot
supply the import under test.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any


_PROBE = r"""
import importlib.metadata
import json
import sysconfig
from pathlib import Path
import ai_workflow_assurance_mcp as package

purelib = Path(sysconfig.get_paths()["purelib"]).resolve()
module_path = Path(package.__file__).resolve()
metadata_version = importlib.metadata.version("ai-workflow-assurance-mcp")
package_version = getattr(package, "__version__", None)

try:
    module_path.relative_to(purelib)
    import_from_installed_package = True
except ValueError:
    import_from_installed_package = False

print(json.dumps({
    "module_path": str(module_path),
    "site_packages": str(purelib),
    "metadata_version": metadata_version,
    "package_version": package_version,
    "import_from_installed_package": import_from_installed_package,
}, sort_keys=True))
"""


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path, required=True, help="Virtual-environment Python.")
    parser.add_argument("--cli", type=Path, required=True, help="Installed CLI console script.")
    parser.add_argument("--server", type=Path, required=True, help="Installed MCP server script.")
    args = parser.parse_args()

    python = args.python.resolve()
    cli = args.cli.resolve()
    server = args.server.resolve()
    for label, path in (("python", python), ("cli", cli), ("server", server)):
        if not path.is_file():
            parser.error(f"{label} path does not exist or is not a file: {path}")

    bin_dir = python.parent
    if not _inside(cli, bin_dir) or not _inside(server, bin_dir):
        raise SystemExit("Installed CLI and MCP entry points must be beside the virtual-environment Python.")

    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    with tempfile.TemporaryDirectory(prefix="awa-wheel-origin-") as working_directory:
        result = subprocess.run(
            [str(python), "-c", _PROBE],
            cwd=working_directory,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )

    try:
        probe: dict[str, Any] = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Installed-wheel import probe returned invalid JSON: {exc}") from exc

    if probe.get("import_from_installed_package") is not True:
        raise SystemExit(
            "AWA imported from outside the installed package directory: "
            f"{probe.get('module_path')!r}; expected beneath {probe.get('site_packages')!r}"
        )
    if not isinstance(probe.get("metadata_version"), str) or (
        probe["metadata_version"] != probe.get("package_version")
    ):
        raise SystemExit(
            "Installed distribution metadata version does not match the imported package version."
        )

    report = {
        "status": "passed",
        "python": str(python),
        "cli_entry_point": str(cli),
        "mcp_entry_point": str(server),
        **probe,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
