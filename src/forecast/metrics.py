"""Lớp chuyển tiếp để duy trì khả năng tương thích với code cũ.

Code mới nên import từ `src.eval.metrics`.
Các file cũ vẫn có thể import từ `src.forecast.metrics`
trong quá trình chuyển đổi sang cấu trúc mới.
"""

from src.eval.metrics import *
