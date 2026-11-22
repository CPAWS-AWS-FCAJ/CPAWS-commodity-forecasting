"""LSTM một bước tới cho từng thành phần (kế hoạch mục 3.2; siêu tham số đóng băng ở config.LSTM).

1 lớp LSTM, `units` đơn vị, đầu ra Linear 1 giá trị từ trạng thái ẩn cuối; MSE trên giá trị đã
chuẩn hóa; Adam, không lịch giảm learning rate; xáo batch bằng torch.Generator có seed; dừng sớm
theo loss đoạn early_stop (patience), khôi phục trọng số tốt nhất. Tái lập: seed Python, NumPy,
PyTorch và torch.use_deterministic_algorithms(True).
"""

from __future__ import annotations

import os

os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")  # phải đặt trước khi dùng CUDA

import random
import time
from dataclasses import dataclass

import numpy as np
import torch
from torch import nn

from . import config as C
from .dataset import AssetSamples, fit_scalers


class LSTMRegressor(nn.Module):
    def __init__(self, units: int, layers: int):
        super().__init__()
        self.lstm = nn.LSTM(1, units, num_layers=layers, batch_first=True)
        self.head = nn.Linear(units, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:  # x (B, L, 1) → (B,)
        out, _ = self.lstm(x)
        return self.head(out[:, -1, :]).squeeze(-1)


@dataclass(frozen=True)
class TrainInfo:
    best_epoch: int  # epoch (đếm từ 1) có loss early_stop nhỏ nhất
    epochs_run: int
    best_es_loss: float
    seconds: float


def set_determinism(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.use_deterministic_algorithms(True)


def resolve_device(name: str) -> torch.device:
    if name == "cpu":
        return torch.device("cpu")
    if name == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    raise ValueError("device must be 'auto' or 'cpu'")


def _tensor(a: np.ndarray, device) -> torch.Tensor:
    return torch.as_tensor(np.asarray(a, dtype=np.float32), device=device)


def train_lstm(
    x_fit: np.ndarray,
    y_fit: np.ndarray,
    x_es: np.ndarray,
    y_es: np.ndarray,
    seed: int,
    device: torch.device,
    params: dict | None = None,
) -> tuple[LSTMRegressor, TrainInfo]:
    """x: (n, L) hoặc (n, L, 1) đã chuẩn hóa; y: (n,). Trả mô hình đã khôi phục trọng số tốt nhất."""
    p = C.LSTM if params is None else params
    t0 = time.perf_counter()
    set_determinism(seed)
    model = LSTMRegressor(p["units"], p["layers"]).to(device)
    opt = torch.optim.Adam(model.parameters(), lr=p["lr"])
    loss_fn = nn.MSELoss()
    xf = _tensor(x_fit, device).reshape(len(x_fit), -1, 1)
    yf = _tensor(y_fit, device).reshape(-1)
    xe = _tensor(x_es, device).reshape(len(x_es), -1, 1)
    ye = _tensor(y_es, device).reshape(-1)
    gen = torch.Generator(device="cpu").manual_seed(seed)

    best, best_epoch, wait, epoch = float("inf"), 0, 0, 0
    best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
    for epoch in range(1, p["max_epochs"] + 1):
        model.train()
        perm = torch.randperm(len(xf), generator=gen).to(device)
        for i in range(0, len(xf), p["batch"]):
            b = perm[i : i + p["batch"]]
            opt.zero_grad()
            loss_fn(model(xf[b]), yf[b]).backward()
            opt.step()
        model.eval()
        with torch.no_grad():
            es = float(loss_fn(model(xe), ye))
        if es < best:
            best, best_epoch, wait = es, epoch, 0
            best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
        else:
            wait += 1
            if wait >= p["patience"]:
                break
    model.load_state_dict(best_state)
    model.eval()
    return model, TrainInfo(best_epoch, epoch, best, time.perf_counter() - t0)


def predict(model: LSTMRegressor, x: np.ndarray, device: torch.device) -> np.ndarray:
    if not len(x):
        return np.zeros(0)
    with torch.no_grad():
        out = model(_tensor(x, device).reshape(len(x), -1, 1))
    return out.cpu().numpy().astype(np.float64)


def fit_predict_variant(
    sm: AssetSamples,
    variant: str,
    seed: int,
    device: torch.device,
    components: list[int] | None = None,
    params: dict | None = None,
) -> tuple[np.ndarray, list[dict], dict[int, LSTMRegressor]]:
    """Train một LSTM cho mỗi thành phần của `variant`, dự báo mọi ngày gốc đã dùng.

    Trả (P̂ (n,) = tổng thành phần dự báo sau khi đảo chuẩn hóa, NaN ở ngày gốc bị loại;
    thông tin train từng thành phần; mô hình theo thành phần)."""
    X, Y = sm.X[variant], sm.Y[variant]
    scalers = fit_scalers(X, sm.segment)
    used = sm.segment != ""
    comps = list(range(X.shape[-1])) if components is None else components
    total = np.zeros(len(X))
    infos, models = [], {}
    fit, es = sm.mask("fit"), sm.mask("early_stop")
    for k in comps:
        sc = scalers[k]
        xk, yk = sc.transform(X[:, :, k]), sc.transform(Y[:, k])
        model, info = train_lstm(xk[fit], yk[fit], xk[es], yk[es], seed, device, params)
        pred = np.full(len(X), np.nan)
        pred[used] = sc.inverse(predict(model, xk[used], device))
        total += pred
        models[k] = model
        infos.append(
            {"component": k, **info.__dict__, "scaler_mean": sc.mean, "scaler_std": sc.std}
        )
    return total, infos, models
