const TONES = {
  // Cảnh báo: dữ liệu mẫu, dữ liệu cũ, đáo hạn hợp đồng
  warn: "bg-warn-bg text-warn-fg",
  // Thông tin trung tính: không phải lỗi, chỉ cho biết nguồn dự báo
  info: "border border-line bg-white text-muted",
} as const;

function Badge({
  children,
  title,
  tone = "warn",
}: {
  children: string;
  title?: string;
  tone?: keyof typeof TONES;
}) {
  return (
    <span
      title={title}
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${TONES[tone]}`}
    >
      {children}
    </span>
  );
}

export function SampleBadge() {
  return <Badge title="Số liệu minh họa, chưa phải dự báo thật">Dữ liệu mẫu</Badge>;
}

export function StaleBadge({ sources }: { sources?: string[] }) {
  const detail = sources && sources.length ? `Nguồn lỗi: ${sources.join(", ")}` : undefined;
  return <Badge title={detail}>Dữ liệu chưa mới</Badge>;
}

export function RollBadge() {
  return (
    <Badge title="Kỳ dự báo chứa ngày đáo hạn hợp đồng tương lai; giá có thể nhảy khi chuyển hợp đồng.">
      Đáo hạn hợp đồng
    </Badge>
  );
}

/** Dự báo đang lấy từ mốc thống kê 252 phiên (model_version "baseline-q252"), chưa phải mô hình học máy. */
export function BaselineBadge() {
  return (
    <Badge
      tone="info"
      title="Khoảng dự báo lấy từ phân phối return của 252 phiên giao dịch gần nhất (khoảng 1 năm), chưa dùng mô hình học máy."
    >
      Mốc thống kê 252 phiên
    </Badge>
  );
}
