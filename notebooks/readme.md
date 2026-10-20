# CPAWS — Training Notebooks

This directory contains Jupyter notebooks for training and experimenting with forecasting models in the CPAWS project.

## Available Notebooks

| Notebook | Description |
|---|---|
| `train_dlinear_kaggle.ipynb` | Train independent DLinear models for Gold, Silver, Brent, and WTI on Kaggle. |

## DLinear Training

- **Input:** 60 trading sessions of log returns.
- **Output:** 7 forecast horizons × 7 quantiles.
- **Training period:** 2014–2018.
- **Validation period:** 2019 (evaluated separately).
- **Framework:** PyTorch.
- **Inference:** NumPy.

## Notes

- Model implementation is located in `src/forecast/`.
- Training data and model weights are not stored in this repository.
- Official training should use the reviewed source code and a recorded source commit.
- See `docs/models/dlinear.md` for architecture, training instructions, and artifact details.
