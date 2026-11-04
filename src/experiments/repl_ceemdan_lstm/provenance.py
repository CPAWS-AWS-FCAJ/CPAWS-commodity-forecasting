"""Kiểm tra nguồn gốc bản tách CEEMDAN và trạng thái git của lần chạy (review Long, #83).

artifacts_sha256.json nằm cạnh manifest.json: SHA-256 của 8 file bản tách, recorded_at (UTC) và
recorded_after_run (true khi ghi bằng --record-digests, tức sau khi bản tách đã có sẵn). Mọi kiểm
tra đều fail-closed: thiếu trường, thiếu khóa hay thiếu file đều báo lỗi, không bỏ qua.
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from . import config as C
from .data import file_sha256

ROOT = Path(__file__).resolve().parents[3]
DIGEST_FILE = "artifacts_sha256.json"
CLEAN_FILES = ("prices.parquet", "rejected.parquet")


def artifact_names() -> list[str]:
    return [f"{kind}_{a}.parquet" for kind in ("r_causal", "r_full") for a in C.ASSETS]


def write_digests(dec_dir: Path, recorded_after_run: bool) -> dict:
    """Tính SHA-256 của 8 file bản tách rồi ghi DIGEST_FILE. Thiếu file thì báo FileNotFoundError."""
    doc = {
        "sha256": {n: file_sha256(dec_dir / n) for n in artifact_names()},
        "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "recorded_after_run": recorded_after_run,
    }
    (dec_dir / DIGEST_FILE).write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return doc


def read_digests(dec_dir: Path) -> dict:
    """Đọc DIGEST_FILE. Thiếu file: FileNotFoundError; sai định dạng: ValueError hoặc TypeError."""
    doc = json.loads((dec_dir / DIGEST_FILE).read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or not isinstance(doc.get("sha256"), dict):
        raise TypeError("thiếu trường sha256")
    return doc


def check_digests(dec_dir: Path) -> list[str]:
    """Phải có DIGEST_FILE, đúng 8 file, và SHA-256 từng file trên đĩa khớp với bản đã ghi."""
    try:
        recorded = read_digests(dec_dir)["sha256"]
    except FileNotFoundError:
        return [f"thiếu {DIGEST_FILE}"]
    except (ValueError, TypeError) as e:
        return [f"{DIGEST_FILE} không hợp lệ: {e}"]
    errs = []
    names = artifact_names()
    errs += [f"{DIGEST_FILE}: thiếu {n}" for n in names if n not in recorded]
    errs += [f"{DIGEST_FILE}: thừa {n}" for n in recorded if n not in names]
    for n in names:
        if n not in recorded:
            continue
        if not (dec_dir / n).exists():
            errs.append(f"thiếu file {n}")
        elif file_sha256(dec_dir / n) != recorded[n]:
            errs.append(f"SHA-256 {n} lệch")
    return errs


def check_clean_sha256(recorded, clean_dir: Path) -> list[str]:
    """`manifest["sha256"]` phải có đúng hai khóa CLEAN_FILES và khớp file bản clean."""
    if not isinstance(recorded, dict):
        return ["manifest thiếu trường sha256"]
    errs = [f"manifest sha256: thiếu {f}" for f in CLEAN_FILES if f not in recorded]
    errs += [f"manifest sha256: thừa {f}" for f in recorded if f not in CLEAN_FILES]
    for f in CLEAN_FILES:
        if f not in recorded:
            continue
        if not (clean_dir / f).exists():
            errs.append(f"thiếu file bản clean {f}")
        elif file_sha256(clean_dir / f) != recorded[f]:
            errs.append(f"SHA-256 {f} lệch")
    return errs


def git_info() -> dict:
    """Commit và trạng thái dirty. Lệnh git lỗi: None và git_status "unavailable" (không chặn chạy,
    không báo nhầm là sạch)."""

    def run(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()

    try:
        commit, status = run("log", "-1", "--format=%H"), run("status", "--porcelain")
    except (OSError, subprocess.CalledProcessError):
        return {"commit": None, "dirty": None, "git_status": "unavailable"}
    return {"commit": commit, "dirty": bool(status), "git_status": "ok"}


def git_label(value) -> str:
    """Giá trị để in báo cáo: None thành "unknown"."""
    return "unknown" if value is None else str(value)
