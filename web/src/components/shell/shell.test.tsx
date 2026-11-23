import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { AuthContext } from "../../auth/AuthContext";
import type { Account, AuthState } from "../../auth/AuthContext";
import { ThemeProvider } from "../../lib/theme";
import { Layout } from "../Layout";
import { AccountBlock } from "./AccountBlock";
import { PublicShell } from "./PublicChrome";
import { ThemeToggle } from "./ThemeToggle";

const flags = vi.hoisted(() => ({ allowSignUp: true }));
vi.mock("../../api/config", () => ({
  config: {
    showMetalPrices: true,
    authEnabled: true,
    get allowSignUp() {
      return flags.allowSignUp;
    },
  },
}));

function authState(partial: Partial<AuthState>): AuthState {
  return { status: "authenticated", sampleMode: false, account: null, signOut: async () => {}, ...partial };
}

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{location.pathname}</output>;
}

function wrap(node: ReactNode, state: AuthState, path = "/about") {
  return (
    <ThemeProvider>
      <AuthContext.Provider value={state}>
        <MemoryRouter initialEntries={[path]}>
          {node}
          <LocationProbe />
        </MemoryRouter>
      </AuthContext.Provider>
    </ThemeProvider>
  );
}

beforeEach(() => {
  window.localStorage.clear();
  document.documentElement.classList.remove("dark");
  flags.allowSignUp = true;
});
afterEach(() => cleanup());

describe("AccountBlock: Họ tên trong sidebar", () => {
  const show = (account: Account) => render(wrap(<AccountBlock />, authState({ account })));

  it("hiện Họ tên, không hiện tên đăng nhập", () => {
    show({ name: "Nguyễn Thị Lan", email: "lan@example.com", username: "lan01" });
    expect(screen.getByText("Nguyễn Thị Lan")).toBeInTheDocument();
    expect(screen.queryByText("lan01")).toBeNull();
    expect(screen.getByRole("button", { name: "Đăng xuất" })).toBeInTheDocument();
  });

  it("tài khoản cũ không có name → hiện email (một lần)", () => {
    show({ email: "lan@example.com", username: "lan01" });
    expect(screen.getAllByText("lan@example.com")).toHaveLength(1);
    expect(screen.queryByText("lan01")).toBeNull();
  });

  it("không có name, không có email → tên đăng nhập", () => {
    show({ username: "lan01" });
    expect(screen.getByText("lan01")).toBeInTheDocument();
  });

  it("chế độ dữ liệu mẫu: không có nút Đăng xuất", () => {
    render(wrap(<AccountBlock />, authState({ sampleMode: true })));
    expect(screen.getByText("Chế độ dữ liệu mẫu")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Đăng xuất" })).toBeNull();
  });

  it("chưa đăng nhập: nút Đăng nhập giữ trang đang xem; Tạo tài khoản theo cờ", () => {
    render(wrap(<AccountBlock />, authState({ status: "unauthenticated" }), "/about"));
    expect(screen.getByRole("link", { name: "Đăng nhập" })).toHaveAttribute("href", "/dang-nhap?next=%2Fabout");
    expect(screen.getByRole("link", { name: "Tạo tài khoản" })).toHaveAttribute(
      "href",
      "/dang-nhap?next=%2Fabout&tab=dang-ky",
    );
    cleanup();
    flags.allowSignUp = false;
    render(wrap(<AccountBlock />, authState({ status: "unauthenticated" })));
    expect(screen.queryByRole("link", { name: "Tạo tài khoản" })).toBeNull();
  });

  it("Đăng xuất gọi signOut rồi về trang công khai /", async () => {
    const signOut = vi.fn(async () => {});
    render(wrap(<AccountBlock />, authState({ account: { name: "Lan" }, signOut }), "/overview"));
    fireEvent.click(screen.getByRole("button", { name: "Đăng xuất" }));
    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent(/^\/$/));
    expect(signOut).toHaveBeenCalledTimes(1);
  });
});

describe("ThemeToggle", () => {
  it("bật/tắt class dark trên <html> và lưu lựa chọn", () => {
    render(wrap(<ThemeToggle />, authState({})));
    const toggle = screen.getByRole("switch", { name: "Giao diện tối" });
    expect(toggle).toHaveAttribute("aria-checked", "false");
    fireEvent.click(toggle);
    expect(document.documentElement).toHaveClass("dark");
    expect(toggle).toHaveAttribute("aria-checked", "true");
    expect(window.localStorage.getItem("cpaws.theme")).toBe("dark");
    fireEvent.click(toggle);
    expect(document.documentElement).not.toHaveClass("dark");
  });

  it("bản icon trên thanh mobile cũng là công tắc có tên", () => {
    render(wrap(<ThemeToggle variant="icon" />, authState({})));
    fireEvent.click(screen.getByRole("switch", { name: "Giao diện tối" }));
    expect(document.documentElement).toHaveClass("dark");
  });
});

describe("Layout: sidebar và ngăn kéo mobile", () => {
  const mount = (state: AuthState, path = "/about") =>
    render(
      wrap(
        <Routes>
          <Route element={<Layout />}>
            <Route path="*" element={<h1>Nội dung</h1>} />
          </Route>
        </Routes>,
        state,
        path,
      ),
    );

  it("có đủ mục điều hướng, nhóm Sản phẩm có 4 sản phẩm", () => {
    mount(authState({ account: { name: "Lan" } }));
    const nav = screen.getAllByRole("navigation", { name: "Điều hướng chính" })[0];
    for (const label of ["Tổng quan giá", "Dự báo", "Độ chính xác", "Cách đọc dự báo", "Giới thiệu"]) {
      expect(within(nav).getByRole("link", { name: label })).toBeInTheDocument();
    }
    const products = within(nav).getByRole("list", { name: "Sản phẩm" });
    expect(within(products).getAllByRole("link").map((link) => link.getAttribute("href"))).toEqual([
      "/asset/gold",
      "/asset/silver",
      "/asset/brent",
      "/asset/wti",
    ]);
    expect(within(nav).getByRole("link", { name: "Giới thiệu" })).toHaveAttribute("aria-current", "page");
  });

  it("chưa đăng nhập: mục cần dữ liệu có khóa; Dự báo dẫn tới đăng nhập", () => {
    mount(authState({ status: "unauthenticated" }));
    const nav = screen.getAllByRole("navigation", { name: "Điều hướng chính" })[0];
    expect(within(nav).getByRole("link", { name: /Dự báo/ })).toHaveAttribute("href", "/dang-nhap");
    expect(within(nav).getByRole("link", { name: /Tổng quan giá/ })).toHaveTextContent("(cần đăng nhập)");
    expect(within(nav).getByRole("link", { name: "Giới thiệu" })).not.toHaveTextContent("(cần đăng nhập)");
  });

  it("mở menu bằng nút, đóng bằng Esc và trả focus về nút mở", () => {
    mount(authState({ account: { name: "Lan" } }));
    const openButton = screen.getByRole("button", { name: "Mở menu" });
    expect(openButton).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(openButton);
    expect(openButton).toHaveAttribute("aria-expanded", "true");
    const dialog = screen.getByRole("dialog", { name: "Menu điều hướng" });
    expect(dialog).toBeVisible();
    expect(screen.getByRole("button", { name: "Đóng menu" })).toHaveFocus();
    expect(document.body.style.overflow).toBe("hidden");

    fireEvent.keyDown(document, { key: "Escape" });
    expect(openButton).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("dialog", { name: "Menu điều hướng" })).toBeNull();
    expect(openButton).toHaveFocus();
    expect(document.body.style.overflow).toBe("");
  });

  it("bấm ra ngoài hoặc chọn một mục thì đóng menu", () => {
    mount(authState({ account: { name: "Lan" } }));
    fireEvent.click(screen.getByRole("button", { name: "Mở menu" }));
    fireEvent.click(screen.getByTestId("drawer-backdrop"));
    expect(screen.getByRole("button", { name: "Mở menu" })).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(screen.getByRole("button", { name: "Mở menu" }));
    const dialog = screen.getByRole("dialog", { name: "Menu điều hướng" });
    fireEvent.click(within(dialog).getByRole("link", { name: "Cách đọc dự báo" }));
    expect(screen.getByTestId("location")).toHaveTextContent("/guide");
    expect(screen.getByRole("button", { name: "Mở menu" })).toHaveAttribute("aria-expanded", "false");
  });

  it("Tab ở phần tử cuối của menu quay lại phần tử đầu (giữ focus trong menu)", () => {
    mount(authState({ account: { name: "Lan" } }));
    fireEvent.click(screen.getByRole("button", { name: "Mở menu" }));
    const dialog = screen.getByRole("dialog", { name: "Menu điều hướng" });
    const focusables = dialog.querySelectorAll<HTMLElement>("a[href], button:not([disabled])");
    focusables[focusables.length - 1].focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(focusables[0]).toHaveFocus();
  });
});

describe("Layout: thu gọn sidebar desktop", () => {
  const mount = (state: AuthState) =>
    render(
      wrap(
        <Routes>
          <Route element={<Layout />}>
            <Route path="*" element={<h1>Nội dung</h1>} />
          </Route>
        </Routes>,
        state,
      ),
    );
  const sidebar = () => document.getElementById("sidebar-dieu-huong") as HTMLElement;

  it("mặc định mở; thu gọn thành dải hẹp cùng mục, tooltip và ổ khóa; nhớ trong localStorage", () => {
    mount(authState({ status: "unauthenticated" }));
    const toggle = within(sidebar()).getByRole("button", { name: "Thu gọn menu" });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(toggle).toHaveAttribute("aria-controls", "sidebar-dieu-huong");
    fireEvent.click(toggle);

    const open = within(sidebar()).getByRole("button", { name: "Mở menu" });
    expect(open).toHaveAttribute("aria-expanded", "false");
    expect(window.localStorage.getItem("cpaws.sidebar")).toBe("collapsed");
    const nav = within(sidebar()).getByRole("navigation", { name: "Điều hướng chính" });
    const guide = within(nav).getByRole("link", { name: "Cách đọc dự báo (cần đăng nhập)" });
    expect(guide).toHaveAttribute("title", "Cách đọc dự báo (cần đăng nhập)");
    expect(within(nav).getByRole("link", { name: "Giới thiệu" })).toHaveAttribute("title", "Giới thiệu");
    expect(within(nav).getAllByRole("link")).toHaveLength(9);
    // Khối tài khoản thu gọn vẫn có Đăng nhập, Tạo tài khoản, giao diện tối
    expect(within(sidebar()).getByRole("link", { name: "Đăng nhập" })).toHaveAttribute("title", "Đăng nhập");
    expect(within(sidebar()).getByRole("link", { name: "Tạo tài khoản" })).toBeInTheDocument();
    expect(within(sidebar()).getByRole("switch", { name: "Giao diện tối" })).toBeInTheDocument();

    fireEvent.click(open);
    expect(within(sidebar()).getByRole("button", { name: "Thu gọn menu" })).toBeInTheDocument();
    expect(window.localStorage.getItem("cpaws.sidebar")).toBe("expanded");
  });

  it("đọc lựa chọn đã lưu; đã đăng nhập thì dải hẹp có chữ cái đầu tên và nút Đăng xuất", () => {
    window.localStorage.setItem("cpaws.sidebar", "collapsed");
    mount(authState({ account: { name: "Lan" } }));
    expect(within(sidebar()).getByRole("button", { name: "Mở menu" })).toBeInTheDocument();
    expect(within(sidebar()).getByRole("img", { name: "Lan" })).toHaveAttribute("title", "Lan");
    expect(within(sidebar()).getByRole("button", { name: "Đăng xuất" })).toBeInTheDocument();
    expect(within(sidebar()).queryByText("(cần đăng nhập)")).toBeNull();
    // Ngăn kéo mobile không bị ảnh hưởng: vẫn đủ chữ
    fireEvent.click(screen.getAllByRole("button", { name: "Mở menu" }).find((b) => b.classList.contains("lg:hidden"))!);
    const dialog = screen.getByRole("dialog", { name: "Menu điều hướng" });
    expect(within(dialog).getByText("Tổng quan giá")).toBeInTheDocument();
  });

  it("localStorage bị chặn: vẫn mở mặc định và thu gọn được", () => {
    const get = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    const set = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    try {
      mount(authState({ account: { name: "Lan" } }));
      fireEvent.click(within(sidebar()).getByRole("button", { name: "Thu gọn menu" }));
      expect(within(sidebar()).getByRole("button", { name: "Mở menu" })).toBeInTheDocument();
    } finally {
      get.mockRestore();
      set.mockRestore();
    }
  });
});

describe("Trang công khai (landing, /dang-nhap): cùng menu ngăn kéo như trang trong app", () => {
  const mountPublic = (path = "/", showAuthActions = true) =>
    render(
      wrap(
        <PublicShell showAuthActions={showAuthActions}>
          <h1>Nội dung</h1>
        </PublicShell>,
        authState({ status: "unauthenticated" }),
        path,
      ),
    );

  it("có nút Mở menu (dưới lg); ngăn kéo có đủ mục, ổ khóa, Đăng nhập/Tạo tài khoản, giao diện tối", () => {
    mountPublic();
    const openButton = screen.getByRole("button", { name: "Mở menu" });
    expect(openButton).toHaveClass("lg:hidden");
    expect(openButton).toHaveAttribute("aria-controls", "menu-dieu-huong");
    fireEvent.click(openButton);
    const dialog = screen.getByRole("dialog", { name: "Menu điều hướng" });
    const nav = within(dialog).getByRole("navigation", { name: "Điều hướng chính" });
    for (const label of [
      "Tổng quan giá",
      "Dự báo",
      "Vàng",
      "Bạc",
      "Dầu Brent",
      "Dầu WTI",
      "Độ chính xác",
      "Cách đọc dự báo",
    ]) {
      expect(within(nav).getByRole("link", { name: new RegExp(label) })).toHaveTextContent("(cần đăng nhập)");
    }
    expect(within(nav).getByRole("link", { name: "Giới thiệu" })).not.toHaveTextContent("(cần đăng nhập)");
    expect(within(dialog).getByRole("link", { name: "Đăng nhập" })).toBeInTheDocument();
    expect(within(dialog).getByRole("link", { name: "Tạo tài khoản" })).toBeInTheDocument();
    expect(within(dialog).getByRole("switch", { name: "Giao diện tối" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Đóng menu" })).toHaveFocus();
    expect(document.body.style.overflow).toBe("hidden");

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Menu điều hướng" })).toBeNull();
    expect(openButton).toHaveFocus();
  });

  it("chọn một mục trong ngăn kéo thì chuyển trang và đóng menu", () => {
    mountPublic();
    fireEvent.click(screen.getByRole("button", { name: "Mở menu" }));
    const dialog = screen.getByRole("dialog", { name: "Menu điều hướng" });
    fireEvent.click(within(dialog).getByRole("link", { name: "Giới thiệu" }));
    expect(screen.getByTestId("location")).toHaveTextContent("/about");
    expect(screen.getByRole("button", { name: "Mở menu" })).toHaveAttribute("aria-expanded", "false");
  });

  it("trên /dang-nhap, Tạo tài khoản trong ngăn kéo giữ trang đích cũ (next), không trỏ về chính nó", () => {
    mountPublic("/dang-nhap?next=%2Foverview", false);
    fireEvent.click(screen.getByRole("button", { name: "Mở menu" }));
    const dialog = screen.getByRole("dialog", { name: "Menu điều hướng" });
    expect(within(dialog).getByRole("link", { name: "Tạo tài khoản" })).toHaveAttribute(
      "href",
      "/dang-nhap?next=%2Foverview&tab=dang-ky",
    );
  });
});
