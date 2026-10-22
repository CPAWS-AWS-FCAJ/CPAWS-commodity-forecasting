import { signOut } from "aws-amplify/auth";

export default function SignOutButton() {
  return (
    <button
      type="button"
      onClick={() => void signOut()}
      className="rounded-md border border-line bg-white px-3 py-1.5 text-sm text-price hover:bg-canvas"
    >
      Đăng xuất
    </button>
  );
}
