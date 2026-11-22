"""Quét đường ghi S3 của job accuracy (review IAM #89 của Tuấn, 11/11/2026).

IAM cho role job `s3:PutObject` trên `eval/shadow_eval/*`. Việc không ghi đè report do code bảo
đảm (`IfNoneMatch="*"`), nên test chốt hai điều:
1. Mọi module mà handler job nạp vào chỉ có một lệnh ghi S3: `Sources.write_shadow`, luôn kèm
   `IfNoneMatch="*"`.
2. Mọi `put_object` trong `src/eval/` (kể cả script offline) đều có `IfNoneMatch="*"`.
"""

import ast
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JOB_HANDLER = "src.eval.lambda_accuracy"
# Các API S3 có thể tạo, đổi hoặc xóa object (bỏ `copy` vì trùng tên DataFrame.copy của pandas)
S3_WRITE_METHODS = {
    "put_object",
    "upload_file",
    "upload_fileobj",
    "copy_object",
    "create_multipart_upload",
    "upload_part",
    "upload_part_copy",
    "complete_multipart_upload",
    "delete_object",
    "delete_objects",
    "put_object_acl",
    "put_object_tagging",
    "restore_object",
}


def _job_module_files() -> list[Path]:
    """Nạp handler job trong interpreter mới, lấy file của mọi module `src.*` đã được import."""
    code = (
        f"import json, sys; import {JOB_HANDLER}; "
        "print(json.dumps(sorted(m.__file__ for n, m in sys.modules.items() "
        "if n.startswith('src') and getattr(m, '__file__', None))))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True
    )
    return [Path(p).resolve() for p in json.loads(out.stdout)]


def _write_calls(path: Path) -> list[tuple[str, ast.Call]]:
    """Trả về (tên hàm chứa lệnh, node) cho mọi lời gọi `<x>.<api ghi S3>(...)` trong file."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []

    def visit(node, scope):
        for child in ast.iter_child_nodes(node):
            inner = scope
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                inner = f"{scope}.{child.name}" if scope else child.name
            if (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and child.func.attr in S3_WRITE_METHODS
            ):
                found.append((inner, child))
            visit(child, inner)

    visit(tree, "")
    return found


def _has_if_none_match_star(call: ast.Call) -> bool:
    return any(
        kw.arg == "IfNoneMatch" and isinstance(kw.value, ast.Constant) and kw.value.value == "*"
        for kw in call.keywords
    )


def test_job_has_single_conditional_s3_write():
    files = _job_module_files()
    # Chắc chắn đã quét đúng các module lõi của job
    names = {p.relative_to(ROOT).as_posix() for p in files}
    assert {"src/eval/lambda_accuracy.py", "src/eval/rolling_sources.py"} <= names

    writes = []
    for path in files:
        for scope, call in _write_calls(path):
            writes.append((path.relative_to(ROOT).as_posix(), scope, call))

    found = [(f, scope, call.func.attr) for f, scope, call in writes]
    assert found == [("src/eval/rolling_sources.py", "Sources.write_shadow", "put_object")]
    assert _has_if_none_match_star(writes[0][2])


def test_job_does_not_import_offline_scripts():
    """Script offline (run_test2020) không được nạp vào Lambda job."""
    names = {p.relative_to(ROOT).as_posix() for p in _job_module_files()}
    assert "src/eval/run_test2020.py" not in names
    assert "src/data/storage.py" not in names


def test_every_put_object_in_src_eval_is_conditional():
    calls = [
        (path.name, scope)
        for path in sorted((ROOT / "src" / "eval").glob("*.py"))
        for scope, call in _write_calls(path)
        if call.func.attr == "put_object" and not _has_if_none_match_star(call)
    ]
    assert calls == []
