import importlib
import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_vercel_entrypoint_exports_application():
    module = importlib.import_module("api.index")
    assert module.app is not None


def test_app_imports_when_static_dir_is_excluded(monkeypatch):
    """Vercel excludes static/** from the function bundle, so the app module
    must import even when STATIC_DIR is absent (regression for a startup crash
    that surfaced as FUNCTION_INVOCATION_FAILED)."""
    real_isdir = os.path.isdir

    def fake_isdir(path):
        if str(path).replace("\\", "/").endswith("/static"):
            return False
        return real_isdir(path)

    monkeypatch.setattr(os.path, "isdir", fake_isdir)
    app_module = importlib.reload(importlib.import_module("app"))
    try:
        static_mounts = [r for r in app_module.app.routes if getattr(r, "name", "") == "static"]
        assert static_mounts == []  # mount skipped, no crash
    finally:
        monkeypatch.undo()
        importlib.reload(app_module)  # restore normal mount for other tests


def test_vercel_config_routes_to_python_and_excludes_static_bundle():
    config = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
    assert config["rewrites"][-1] == {"source": "/(.*)", "destination": "/api/index"}
    assert "public/**" in config["functions"]["api/index.py"]["excludeFiles"]


def test_vercel_public_static_copy_is_complete_and_current():
    source = ROOT / "static"
    public = ROOT / "public" / "static"
    source_files = {path.relative_to(source) for path in source.rglob("*") if path.is_file()}
    public_files = {path.relative_to(public) for path in public.rglob("*") if path.is_file()}
    assert public_files == source_files
    for relative_path in source_files:
        assert (public / relative_path).read_bytes() == (source / relative_path).read_bytes()


def test_pyproject_dependencies_match_requirements():
    import tomllib

    req_lines = [
        line.strip()
        for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    pyproject_data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    pyproject_deps = pyproject_data.get("project", {}).get("dependencies", [])
    assert sorted(req_lines) == sorted(pyproject_deps)

