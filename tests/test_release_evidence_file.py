"""Kiểm file evidence mà infra/app.py đưa vào job accuracy (ROLLING_EVIDENCE_JSON).

Khối shadow_release do Khải duyệt bằng comment ở PR #89 (2026-11-04T14:22:51Z), sau lượt 19:15
đầu tiên của image c61abdd (#79). Test chốt đúng giá trị đã duyệt và kiểm job dùng được khối này.
"""

import json
from dataclasses import replace
from pathlib import Path

from src.eval.rolling_accuracy import utc
from src.eval.rolling_shadow import compare
from src.eval.rolling_sources import approved
from tests.test_rolling_shadow import shadow_case

EVIDENCE_FILE = (
    Path(__file__).resolve().parents[1]
    / "docs/eval/evidence/rolling-release-cutover-2026-10-30.json"
)
# Đúng nội dung Khải duyệt ở #89; approved_at = giờ comment duyệt (UTC), không phải giờ deploy
APPROVED_SHADOW_RELEASE = {
    "approved": True,
    "approved_by": "kha1rk19fpt",
    "approved_at": "2026-11-04T14:22:51Z",
    "reference": "pr79-deploy-2026-11-04T05:33:31Z+run-2026-11-04T12:15Z",
    "deployed_at": "2026-11-04T05:33:31.234Z",
    "immutable_write": True,
}


def _evidence() -> dict:
    def unique_keys(pairs):
        keys = [k for k, _ in pairs]
        assert len(keys) == len(set(keys)), "khóa JSON bị trùng"
        return dict(pairs)

    return json.loads(EVIDENCE_FILE.read_text(encoding="utf-8"), object_pairs_hook=unique_keys)


def test_shadow_release_is_the_approved_block():
    evidence = _evidence()
    # Cùng tập khóa mà CDK chấp nhận (cpaws_data_stack.ROLLING_EVIDENCE_KEYS)
    assert set(evidence) == {"release", "legacy", "shadow_release"}
    assert evidence["shadow_release"] == APPROVED_SHADOW_RELEASE
    assert approved(evidence["shadow_release"])
    # Duyệt sau deploy và sau lượt 19:15 đầu tiên (12:15Z), không duyệt trước khi có kết quả
    shadow = evidence["shadow_release"]
    assert utc(shadow["deployed_at"]) < utc("2026-11-04T12:15:00Z") < utc(shadow["approved_at"])


def test_shadow_release_opens_comparison_only_after_approval():
    """Job từ ngày sau duyệt so sánh S1a; object shadow ghi trước deployed_at bị loại."""
    shadow_release = _evidence()["shadow_release"]
    result, cfg, sources, evidence = shadow_case()
    evidence.config["shadow_release"] = shadow_release

    report = compare(result, cfg, sources, evidence)
    assert report["status"] == "ok" and report["paired_n_obs"] > 0
    assert any(e.get("reason") == "shadow_publication_unverified" for e in report["exclusions"])

    # Giả sử job chạy 13:45Z ngày 4/11, trước giờ duyệt 14:22:51Z → dừng ngay ở cổng duyệt
    early = replace(cfg, job_date="2026-11-04", as_of="2026-11-04T13:45:00Z")
    report = compare(result, early, sources, evidence)
    assert report == {"status": "shadow_not_ready", "paired_n_obs": 0}
