/**
 * Dòng nguồn dữ liệu giá, đúng chuỗi `SOURCE_ATTRIBUTION` trong `src/data/config.py` (ADR-0005).
 * API không trả trường này nên web giữ hằng số; đổi chuỗi bên Python thì sửa cả ở đây
 * (tests/test_web_source_attribution.py kiểm hai chuỗi khớp nhau).
 */
export const SOURCE_ATTRIBUTION = "Nguồn: Yahoo Finance, U.S. EIA";

/** Nhãn đi kèm giá vàng theo VND/lượng (ADR-0005, skill forecast-display). */
export const GOLD_VND_NOTE =
  "Giá vàng VND/lượng là giá thế giới quy đổi, không phải giá vàng miếng trong nước (chưa gồm thuế, phí, chênh lệch thị trường).";
