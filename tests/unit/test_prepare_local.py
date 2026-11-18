"""Generated Local assets must not depend on an earlier build."""
import json
import runpy
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile

from autonavlog.forecast_backup import calculation_contract


def test_prepare_local_replaces_generated_tree(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[2]
    script = tmp_path / "scripts/prepare_local.py"
    script.parent.mkdir()
    script.write_text((root / "scripts/prepare_local.py").read_text())
    for name in ("pyproject.toml", "VERSION", "README.md"):
        (tmp_path / name).write_text("1.20.0")
    for name in ("src/autonavlog", "data/performance", "data/reference", "vendor", "web/public"):
        (tmp_path / name).mkdir(parents=True)
    (tmp_path / "src/autonavlog/__init__.py").write_text(
        'raise RuntimeError("package not built yet")'
    )
    (tmp_path / "src/autonavlog/runtime_data.py").write_text(
        (root / "src/autonavlog/runtime_data.py").read_text()
    )
    (tmp_path / "web/package.json").write_text(json.dumps({"dependencies": {"pyodide": "0.27.7"}}))
    (tmp_path / "vendor/jma_gpv_weather-0.6.0-py3-none-any.whl").write_bytes(b"vendor")
    (tmp_path / "web/public/current.txt").write_text("current")
    inputs = [
        "performance/manifest.json",
        "reference/default/airports.csv",
        "reference/rjfm/manifest.json",
        "reference/rjfm-inbound-guidance/artifacts/primary.pdf",
        "reference/vrep.json",
    ]
    for name in inputs:
        path = tmp_path / "data" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(name.encode())
    source = tmp_path / "data/reference/aip/20261029/sources/original.zip"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"source archive; not a runtime input")
    stale = tmp_path / "web/public-local"
    stale.mkdir()
    (stale / "_redirects").write_text("/* https://old.example 302")
    (stale / "removed.txt").write_text("old")
    monkeypatch.delenv("AUTONAVLOG_MSM_FEED", raising=False)
    monkeypatch.delenv("AUTONAVLOG_GSM_FEED", raising=False)
    monkeypatch.delenv("AUTONAVLOG_TEST_FIXTURES", raising=False)

    # Build in a fresh interpreter with a stale installed package ahead of the
    # checkout. prepare_local must choose the checkout before building its wheel.
    installed = tmp_path / "old-site/autonavlog"
    installed.mkdir(parents=True)
    (installed / "__init__.py").write_text('raise RuntimeError("stale installed package")')
    subprocess.run([sys.executable, "-S", "-c", """
import runpy, subprocess, sys
from pathlib import Path
sys.path.insert(0, sys.argv[2])
def build(command, **kwargs):
    Path(command[-1], 'autonavlog-1.20.0-py3-none-any.whl').write_bytes(b'wheel')
subprocess.run = build
runpy.run_path(sys.argv[1])
""", str(script), str(installed.parent)], check=True)
    assert not (stale / "_redirects").exists()
    assert not (stale / "removed.txt").exists()
    assert (stale / "current.txt").read_text() == "current"
    manifest = json.loads((stale / "local/manifest.json").read_text())
    assert manifest["version"] == "1.20.0"
    assert manifest["pyodideVersion"] == "0.27.7"
    with ZipFile(stale / "local/data.zip") as archive:
        assert set(archive.namelist()) == {f"data/{name}" for name in inputs}
        archive.extractall(tmp_path / "unpacked")
    assert source.read_bytes() == b"source archive; not a runtime input"
    # Packaging and the server must agree despite the source-only archives.
    assert calculation_contract(tmp_path / "data") == calculation_contract(
        tmp_path / "unpacked/data"
    )


def test_runtime_provenance_changes_still_change_backup_identity(tmp_path):
    artifact = tmp_path / "reference/rjfm-inbound-guidance/artifacts/primary.pdf"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"primary source")
    before = calculation_contract(tmp_path)
    artifact.write_bytes(b"changed source")
    calculation_contract.cache_clear()
    assert calculation_contract(tmp_path).data_sha256 != before.data_sha256


def test_local_archive_contains_runtime_inputs_without_map_source_archives(tmp_path, monkeypatch):
    """The reduced archive must still initialize the real integrity-checked facade."""
    from autonavlog.local import LocalApplication

    root = Path(__file__).resolve().parents[2]
    script = tmp_path / "scripts/prepare_local.py"
    script.parent.mkdir()
    script.write_text((root / "scripts/prepare_local.py").read_text())
    for name in ("pyproject.toml", "VERSION", "README.md"):
        (tmp_path / name).write_text("1.20.0")
    for name in ("src/autonavlog", "vendor", "web/public"):
        (tmp_path / name).mkdir(parents=True)
    (tmp_path / "src/autonavlog/runtime_data.py").write_text(
        (root / "src/autonavlog/runtime_data.py").read_text()
    )
    (tmp_path / "data").symlink_to(root / "data", target_is_directory=True)
    (tmp_path / "web/package.json").write_text(json.dumps({"dependencies": {"pyodide": "0.27.7"}}))
    (tmp_path / "vendor/jma_gpv_weather-0.6.0-py3-none-any.whl").write_bytes(b"vendor")
    for name in ("AUTONAVLOG_MSM_FEED", "AUTONAVLOG_GSM_FEED", "AUTONAVLOG_TEST_FIXTURES"):
        monkeypatch.delenv(name, raising=False)

    def build(command, **kwargs):
        Path(command[-1], "autonavlog-1.20.0-py3-none-any.whl").write_bytes(b"wheel")

    monkeypatch.setattr("subprocess.run", build)
    runpy.run_path(str(script))
    with ZipFile(tmp_path / "web/public-local/local/data.zip") as archive:
        assert not any(name.startswith("data/reference/aip/") for name in archive.namelist())
        # The solver verifies this source PDF, not just its normalized JSON.
        source_pdf = "data/reference/rjfm-inbound-guidance/artifacts/ks4-3-enr-5-3-21.pdf"
        assert source_pdf in archive.namelist()
        archive.extractall(tmp_path / "extracted")
    app = LocalApplication(tmp_path / "extracted/data")
    state = json.loads(app.dispatch_response("bootstrap", {}))
    assert "error" not in state
    assert state["airports"]
    assert app.app.rjfm_inbound_guidance_reference.available_for_solver
