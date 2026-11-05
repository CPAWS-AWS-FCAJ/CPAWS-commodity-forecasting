"""PR75 fixed protocol, including 2026-11-03 centered-null bootstrap amendment.

Seed 7 follows K3/K3b; review before the single official run. Snapshot DT, hashes,
lineage and merged commit are REQUIRED runtime attestations, never defaults.
"""

RUN_ID = "test2020"
ASSETS = ("gold", "silver", "wti", "brent")
HORIZONS = tuple(range(1, 8))
BASELINE = "baseline-q252"
CHALLENGER = "s1a-l094"
EVALUATION_START = "2020-01-02"
EVALUATION_END = "2026-10-23"
TARGET_CUTOFF = "2026-10-23"
S1A_LAMBDA = 0.94
K_CLIP = (0.5, 2.0)
BLOCK_LENGTH = 20
N_BOOTSTRAP = 2000
CONFIDENCE_LEVEL = 0.95
ALPHA = 0.05
BOOTSTRAP_SEED = 7
SENSITIVITY_BLOCKS = (10, 40)
STRESS_WINDOWS = (
    ("COVID", "2020-02-15", "2020-05-31"),
    ("Russia-Ukraine", "2022-02-15", "2022-04-30"),
)
OIL_SAMPLES = ("all", "excl_roll")
PRIMARY_SAMPLE = "all"
PRIMARY_STATISTIC = "equal_mean_of_all_seven_horizon_pinball_skills"
PRIMARY_HYPOTHESES = tuple((a, "H0:S<=0;H1:S>0") for a in ASSETS)
DM_GAP_POLICY = "block_internal_session_gaps_for_h_gt_1_pending_Khai_review"
BUCKET = "cpaws-dev-lake"
PREFIX = "eval/test2020/"
SNAPSHOT_FILES = ("prices.parquet", "rejected.parquet", "quality.json")
REQUIRED_METADATA = (
    "run_id",
    "commit",
    "snapshot_dt",
    "snapshot_sha256",
    "lineage",
    "config_hash",
    "operator",
    "approved_for_official_run",
    "plan_reference",
)


# No CLI overrides for the protocol. A reviewed metadata config_hash binds both
# these values and source bytes; edits after locking fail before claim/data access.
def protocol():
    return {k: v for k, v in globals().items() if k.isupper()}
