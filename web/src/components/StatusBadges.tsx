function Badge({ children, title }: { children: string; title?: string }) {
  return (
    <span
      title={title}
      className="inline-flex items-center rounded-full bg-warn-bg px-2 py-0.5 text-xs font-medium text-warn-fg"
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
