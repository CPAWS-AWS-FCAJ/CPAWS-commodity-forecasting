"""requirements-predict.txt và docker/predict/ (image Lambda predict): đủ thư viện và code cho
đường chạy predict, không kéo thư viện nặng, cùng base image với ingest."""

import ast
import re
from importlib.metadata import version
from pathlib import Path

from tests.test_requirements_ingest import _reqs, _third_party

ROOT = Path(__file__).resolve().parents[1]
ENTRY = "src.forecast.lambda_predict"
REQS = ROOT / "requirements-predict.txt"
DOCKER = ROOT / "docker" / "predict"
FORBIDDEN = {
    "torch",
    "emd-signal",
    "scikit-learn",
    "statsmodels",
    "scipy",
    "yfinance",
    "requests",
    "python-dotenv",
}
IMPLICIT = {"pyarrow"}  # pandas dùng để đọc parquet, không import trực tiếp
# Import trong hàm mà Lambda không gọi: returns.prob_up_pchip (chỉ cho thí nghiệm, cần scipy)
LAZY_UNUSED = {"scipy"}


def _module_file(mod: str) -> Path | None:
    p = ROOT.joinpath(*mod.split("."))
    if p.with_suffix(".py").is_file():
        return p.with_suffix(".py")
    if (p / "__init__.py").is_file():
        return p / "__init__.py"
    return None


def _closure(entry: str = ENTRY) -> tuple[set[Path], set[str], set[str]]:
    """(file trong src/ mà entry import, kể cả import trong hàm; module ngoài src mọi chỗ;
    module ngoài src ở cấp module). Module src chưa có file (dlinear_numpy, PR #18) bị bỏ qua."""
    files: set[Path] = set()
    third: set[str] = set()
    top: set[str] = set()
    todo = [entry]
    while todo:
        mod = todo.pop()
        f = _module_file(mod)
        if f is None or f in files:
            continue
        files.add(f)
        parts = mod.split(".")
        todo += [".".join(parts[:i]) for i in range(1, len(parts))]  # package cha (__init__)
        pkg = mod if f.name == "__init__.py" else mod.rpartition(".")[0]
        tree = ast.parse(f.read_text(encoding="utf-8"))
        top_nodes = set(map(id, tree.body))
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                names = [a.name for a in n.names]
            elif isinstance(n, ast.ImportFrom):
                if n.level:
                    base = pkg.split(".")[: len(pkg.split(".")) - (n.level - 1)]
                    m = ".".join(base + ([n.module] if n.module else []))
                else:
                    m = n.module
                names = [m] + [f"{m}.{a.name}" for a in n.names]
            else:
                continue
            for name in names:
                root = name.split(".")[0]
                if root == "src":
                    todo.append(name)
                else:
                    third.add(root)
                    if id(n) in top_nodes:
                        top.add(root)
    return files, third, top


def test_closure_reaches_the_predict_modules():
    files = {f.relative_to(ROOT).as_posix() for f in _closure()[0]}
    for f in (
        "src/__init__.py",
        "src/forecast/predict.py",
        "src/features/build.py",
        "src/forecast/forecast_record.py",
        "src/data/quality.py",
        "src/data/storage.py",
    ):
        assert f in files, f
    assert "src/data/ingest_prices.py" not in files  # kéo theo requests
    assert not any("sources" in f or "decomposition" in f for f in files)


def test_predict_requirements_cover_runtime_imports():
    reqs = _reqs(REQS)
    _, third, _ = _closure()
    needed = _third_party(third) - _third_party(LAZY_UNUSED)
    missing = needed - set(reqs)
    assert not missing, f"thiếu trong requirements-predict.txt: {missing}"
    assert IMPLICIT <= set(reqs)


def test_predict_requirements_exclude_heavy_libraries():
    assert not FORBIDDEN & set(_reqs(REQS))


def test_heavy_libraries_never_imported_at_module_level():
    _, _, top = _closure()
    assert not _third_party(top) & FORBIDDEN


def test_versions_match_requirements_and_env():
    reqs = _reqs(REQS)
    main = _reqs(ROOT / "requirements.txt")
    for name, spec in reqs.items():
        assert spec.startswith("=="), f"{name} phải cố định bằng =="
        if main.get(name, "").startswith("=="):
            assert main[name] == spec, name
        assert version(name) == spec[2:], f"{name}: env {version(name)} != {spec}"


def _from_line(path: Path) -> str:
    return next(x for x in path.read_text(encoding="utf-8").splitlines() if x.startswith("FROM "))


def test_dockerfile_same_base_as_ingest_and_copies_closure():
    dockerfile = (DOCKER / "Dockerfile").read_text(encoding="utf-8")
    assert _from_line(DOCKER / "Dockerfile") == _from_line(
        ROOT / "docker" / "ingest" / "Dockerfile"
    )
    assert "@sha256:" in _from_line(DOCKER / "Dockerfile")
    copies = [ln.split()[1] for ln in dockerfile.splitlines() if ln.startswith("COPY ")]
    assert copies[0] == "requirements-predict.txt"
    for f in _closure()[0]:
        rel = f.relative_to(ROOT).as_posix()
        assert any(rel == c or (c.endswith("/") and rel.startswith(c)) for c in copies), rel
    ignore = (DOCKER / "Dockerfile.dockerignore").read_text(encoding="utf-8").splitlines()
    for c in copies:
        assert f"!{c}" in ignore, c
    cmd = re.search(r'CMD \["([\w.]+)\.handler"\]', dockerfile)
    assert cmd and cmd.group(1) == ENTRY
