/** Hằng dự phòng, đúng chuỗi `forecast_format.DISCLAIMER` của API. Ưu tiên trường `disclaimer` trong response. */
export const DISCLAIMER_TEXT = "Dự báo mang tính tham khảo, không phải lời khuyên đầu tư.";

export function Disclaimer({ text }: { text?: string }) {
  return <p className="text-xs text-muted">{text || DISCLAIMER_TEXT}</p>;
}
