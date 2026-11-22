"""requirements-ingest.txt (image Lambda ingest): đủ thư viện cho src/data, không kéo thư viện nặng."""

import ast
import re
import subprocess
import sys
import textwrap
from importlib.metadata import packages_distributions, version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = {"torch", "emd-signal", "scikit-learn", "statsmodels"}
LOCAL_ONLY = {"python-dotenv"}  # chỉ import trong main() của CLI, Lambda không cần
LOCAL_ONLY_IMPORTS = {"dotenv"}  # tên import tương ứng (để test chạy được cả khi gói chưa cài)
IMPLICIT = {"pyarrow"}  # pandas dùng để đọc/ghi parquet, không import trực tiếp


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _reqs(path: Path) -> dict[str, str]:
    out = {}
    for line in path.read_text(encoding="ascii").splitlines():
        line = line.split("#")[0].strip()
        if not line or line.startswith("-r"):
            continue
        m = re.match(r"([A-Za-z0-9_.\-\[\]]+)\s*(==|>=)?\s*([^\s;]*)", line)
        name = re.sub(r"\[.*\]", "", m.group(1))
        out[_norm(name)] = f"{m.group(2) or ''}{m.group(3)}"
    return out


def _imports(top_level_only: bool) -> dict[str, set[str]]:
    """{tên module gốc: {file}} cho các import tuyệt đối trong src/data."""
    found: dict[str, set[str]] = {}
    for f in (ROOT / "src" / "data").rglob("*.py"):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        nodes = tree.body if top_level_only else ast.walk(tree)
        for n in nodes:
            names = []
            if isinstance(n, ast.Import):
                names = [a.name for a in n.names]
            elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
                names = [n.module]
            for name in names:
                found.setdefault(name.split(".")[0], set()).add(f.name)
            if isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
                found.setdefault(n.module, set()).add(f.name)
    return found


def _third_party(mods) -> set[str]:
    dists = packages_distributions()
    out = set()
    for m in mods:
        if m in sys.stdlib_module_names or m in ("__future__", "src") or "." in m:
            continue
        if m in LOCAL_ONLY_IMPORTS:
            out |= LOCAL_ONLY
            continue
        out |= {_norm(d) for d in dists.get(m, [m])}
    return out


def test_ingest_requirements_cover_src_data_imports():
    ingest = _reqs(ROOT / "requirements-ingest.txt")
    needed = _third_party(_imports(top_level_only=False)) - LOCAL_ONLY
    missing = needed - set(ingest)
    assert not missing, f"thiếu trong requirements-ingest.txt: {missing}"
    assert IMPLICIT <= set(ingest)


def test_ingest_requirements_exclude_heavy_libraries():
    ingest = _reqs(ROOT / "requirements-ingest.txt")
    assert not FORBIDDEN & set(ingest)
    assert not LOCAL_ONLY & set(ingest)


def test_src_data_does_not_import_model_packages():
    mods = _imports(top_level_only=False)
    assert not [m for m in mods if m.startswith(("src.forecast", "src.features", "src.models"))]
    assert not _third_party(mods) & FORBIDDEN


def test_dotenv_only_imported_inside_functions():
    assert "dotenv" not in _imports(top_level_only=True)


def test_versions_match_requirements_and_env():
    ingest = _reqs(ROOT / "requirements-ingest.txt")
    main = _reqs(ROOT / "requirements.txt")
    for name, spec in ingest.items():
        assert spec.startswith("=="), f"{name} phải cố định bằng =="
        if main.get(name, "").startswith("=="):
            assert main[name] == spec, name
        assert version(name) == spec[2:], f"{name}: env {version(name)} != {spec}"


def test_ingest_runs_without_dotenv_or_model_libraries(tmp_path):
    """Chạy run_ingest trong tiến trình mới, chặn import dotenv và các thư viện mô hình."""
    code = textwrap.dedent(
        f"""
        import sys
        BLOCK = {{"dotenv", "torch", "PyEMD", "sklearn", "statsmodels", "scipy"}}

        class Blocker:
            def find_spec(self, name, path=None, target=None):
                if name.split(".")[0] in BLOCK:
                    raise ImportError("blocked " + name)
                return None

        sys.meta_path.insert(0, Blocker())
        sys.path.insert(0, {str(ROOT)!r})
        import pandas as pd
        from src.data import ingest_prices, lambda_ingest, storage
        from src.data.sources.yfinance_src import YFinanceSource
        from tests.data_fakes import FakeEIA, FakeYF

        src = {{"yfinance": YFinanceSource(FakeYF()), "eia": FakeEIA()}}
        st = storage.LocalStorage({str(tmp_path)!r})
        res = ingest_prices.run(st, src, start="2020-03-02",
                                now=pd.Timestamp("2020-05-29 20:00", tz="UTC"))
        assert res.ok
        assert not BLOCK & {{m.split(".")[0] for m in sys.modules}}
        print("OK")
        """
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT, check=False
    )
    assert out.returncode == 0 and out.stdout.strip().endswith("OK"), out.stderr[-2000:]
