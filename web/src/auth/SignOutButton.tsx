import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { SignOutIcon } from "../components/shell/icons";
import { useAuth } from "./AuthContext";

/** Đăng xuất rồi về trang giới thiệu công khai. Không import aws-amplify (đi qua AuthContext). */
export default function SignOutButton() {
  const { signOut } = useAuth();
  const navigate = useNavigate();
  const [pending, setPending] = useState(false);

  const onClick = () => {
    setPending(true);
    signOut()
      .catch(() => {
        // Lỗi mạng khi đăng xuất: vẫn về trang công khai, phiên cục bộ đã bị xóa
      })
      .finally(() => {
        setPending(false);
        navigate("/", { replace: true });
      });
  };

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={pending}
      className="flex h-9 w-full items-center gap-2.5 rounded-md px-3 text-sm text-muted transition-colors duration-150 hover:bg-surface-muted hover:text-price active:bg-line disabled:cursor-not-allowed disabled:opacity-60"
    >
      <SignOutIcon />
      <span>{pending ? "Đang đăng xuất…" : "Đăng xuất"}</span>
    </button>
  );
}
