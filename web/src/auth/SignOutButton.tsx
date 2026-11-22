import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { SignOutIcon } from "../components/shell/icons";
import { clearChatHistory } from "../lib/chatHistory";
import { useAuth } from "./AuthContext";

/**
 * Đăng xuất rồi về trang giới thiệu công khai. Không import aws-amplify (đi qua AuthContext).
 * `compact`: nút vuông chỉ có icon (sidebar desktop thu gọn), tên ở aria-label và tooltip.
 */
export default function SignOutButton({ compact = false }: { compact?: boolean }) {
  const { signOut } = useAuth();
  const navigate = useNavigate();
  const [pending, setPending] = useState(false);

  const onClick = () => {
    setPending(true);
    // Lịch sử chat của phiên bị xóa ngay cả khi đăng xuất lỗi mạng (và ở chế độ dữ liệu mẫu)
    clearChatHistory();
    signOut()
      .catch(() => {
        // Lỗi mạng khi đăng xuất: vẫn về trang công khai, phiên cục bộ đã bị xóa
      })
      .finally(() => {
        setPending(false);
        navigate("/", { replace: true });
      });
  };

  const label = pending ? "Đang đăng xuất…" : "Đăng xuất";
  if (compact) {
    return (
      <button
        type="button"
        onClick={onClick}
        disabled={pending}
        aria-label={label}
        title={label}
        className="mx-auto flex size-10 items-center justify-center rounded-md text-muted transition-colors duration-150 hover:bg-surface-muted hover:text-price active:bg-line disabled:cursor-not-allowed disabled:opacity-60"
      >
        <SignOutIcon />
      </button>
    );
  }

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={pending}
      className="flex h-9 w-full items-center gap-2.5 pointer-coarse:h-11 rounded-md px-3 text-sm text-muted transition-colors duration-150 hover:bg-surface-muted hover:text-price active:bg-line disabled:cursor-not-allowed disabled:opacity-60"
    >
      <SignOutIcon />
      <span>{label}</span>
    </button>
  );
}
