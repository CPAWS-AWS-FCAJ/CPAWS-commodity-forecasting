import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter, useLocation } from "react-router-dom";
import App from "./App";
import type { AuthState } from "./auth/AuthContext";
import { SettingsProvider } from "./lib/settings";
import { ThemeProvider } from "./lib/theme";

const flags = vi.hoisted(() => ({ authEnabled: true, allowSignUp: true }));
const auth = vi.hoisted(() => ({
  state: {
    status: "unauthenticated",
    sampleMode: false,
    account: null,
    signOut: async () => {},
  } as AuthState,
}));
const api = vi.hoisted(() => ({ getForecasts: vi.fn() }));

vi.mock("./api/config", () => ({
  config: {
    apiUrl: "",
    useSample: true,
    sampleAccuracy: "collecting",
    accuracyApiEnabled: true,
    showMetalPrices: true,
    get authEnabled() {
      return flags.authEnabled;
    },
    get allowSignUp() {
      return flags.allowSignUp;
    },
    region: "ap-southeast-1",
    userPoolId: "",
    userPoolClientId: "",
  },
}));

// Không tải Amplify thật: provider giả đưa trạng thái đăng nhập do test đặt.
vi.mock("./auth/AmplifyAuthProvider", async () => {
  const { AuthContext } = await import("./auth/AuthContext");
  return {
    default: ({ children }: { children: ReactNode }) => (
      <AuthContext.Provider value={auth.state}>{children}</AuthContext.Provider>
    ),
  };
});
vi.mock("./auth/SignInPanel", () => ({
  default: ({ initialState }: { initialState: string }) => (
    <div data-testid="authenticator">{initialState}</div>
  ),
}));
vi.mock("./api/forecasts", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./api/forecasts")>();
  return { ...actual, getForecasts: api.getForecasts };
});
// Trang nặng (Recharts) của agent khác: thay bằng tiêu đề để chỉ kiểm định tuyến.
vi.mock("./pages/Overview", () => ({ default: () => <h1>Trang tổng quan</h1> }));
vi.mock("./pages/AssetPage", () => ({ default: () => <h1>Trang sản phẩm</h1> }));
vi.mock("./pages/Accuracy", () => ({ default: () => <h1>Trang độ chính xác</h1> }));
vi.mock("./pages/Guide", () => ({ default: () => <h1>Trang cách đọc</h1> }));

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{`${location.pathname}${location.search}`}</output>;
}

function mount(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <ThemeProvider>
      <QueryClientProvider client={client}>
        <SettingsProvider>
          <MemoryRouter initialEntries={[path]}>
            <App />
            <LocationProbe />
          </MemoryRouter>
        </SettingsProvider>
      </QueryClientProvider>
    </ThemeProvider>,
  );
}

const location = () => screen.getByTestId("location").textContent;

function setAuth(status: AuthState["status"]) {
  auth.state = { status, sampleMode: false, account: null, signOut: async () => {} };
}

beforeEach(async () => {
  flags.authEnabled = true;
  flags.allowSignUp = true;
  setAuth("unauthenticated");
  const { sampleList } = await import("./api/sample");
  api.getForecasts.mockReset();
  api.getForecasts.mockResolvedValue(sampleList());
});
afterEach(() => cleanup());

describe("chưa đăng nhập: trang công khai và chuyển hướng", () => {
  it("/ là trang giới thiệu công khai, không gọi API dự báo, không có số giá", async () => {
    mount("/");
    expect(
      await screen.findByRole("heading", { level: 1, name: /Dự báo khoảng giá vàng, bạc và dầu/ }),
    ).toBeInTheDocument();
    expect(api.getForecasts).not.toHaveBeenCalled();
    const text = document.body.textContent ?? "";
    // Không có giá (2.655 / 74,86 / … USD) hay xác suất tăng dạng số
    expect(text).not.toMatch(/\d[\d.]*,\d{2}/);
    expect(text).not.toMatch(/\d\s*(USD|VND)\b/);
    expect(text).not.toMatch(/Xác suất giá tăng:/);
    for (const name of ["Vàng", "Bạc", "Dầu Brent", "Dầu WTI"]) {
      expect(screen.getByText(name)).toBeInTheDocument();
    }
    expect(screen.getByText("Dự báo mang tính tham khảo, không phải lời khuyên đầu tư.")).toBeInTheDocument();
  });

  it("có nút Đăng nhập; Tạo tài khoản chỉ hiện khi cho tự đăng ký", async () => {
    mount("/");
    expect((await screen.findAllByRole("link", { name: /Đăng nhập/ })).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("link", { name: "Tạo tài khoản" }).length).toBeGreaterThan(0);
    cleanup();
    flags.allowSignUp = false;
    mount("/");
    await screen.findByRole("heading", { level: 1 });
    expect(screen.queryByRole("link", { name: "Tạo tài khoản" })).toBeNull();
  });

  it.each([
    ["/overview", "/dang-nhap?next=%2Foverview"],
    ["/asset/gold", "/dang-nhap?next=%2Fasset%2Fgold"],
    ["/accuracy", "/dang-nhap?next=%2Faccuracy"],
  ])("%s → %s, hiện form đăng nhập", async (path, target) => {
    mount(path);
    expect(await screen.findByTestId("authenticator")).toHaveTextContent("signIn");
    expect(location()).toBe(target);
  });

  it.each([
    ["/guide", "Trang cách đọc"],
    ["/about", "Giới thiệu"],
  ])("%s là trang công khai", async (path, heading) => {
    mount(path);
    expect(await screen.findByRole("heading", { level: 1, name: heading })).toBeInTheDocument();
    expect(location()).toBe(path);
    // Mục cần đăng nhập có khóa và chữ cho trình đọc màn hình
    expect(screen.getAllByText("(cần đăng nhập)").length).toBeGreaterThan(0);
  });

  it("tab=dang-ky mở tab Đăng ký khi cho tự đăng ký, không thì tab Đăng nhập", async () => {
    mount("/dang-nhap?tab=dang-ky");
    expect(await screen.findByTestId("authenticator")).toHaveTextContent("signUp");
    cleanup();
    flags.allowSignUp = false;
    mount("/dang-nhap?tab=dang-ky");
    expect(await screen.findByTestId("authenticator")).toHaveTextContent("signIn");
  });

  it("đang kiểm tra đăng nhập thì chưa chuyển hướng", async () => {
    setAuth("loading");
    mount("/overview");
    // Khối chờ ở nội dung (và dòng trạng thái trong khối tài khoản)
    expect((await screen.findAllByText("Đang kiểm tra đăng nhập…")).length).toBeGreaterThan(0);
    expect(screen.getByRole("main")).toHaveTextContent("Đang kiểm tra đăng nhập…");
    expect(location()).toBe("/overview");
  });
});

describe("đã đăng nhập", () => {
  beforeEach(() => setAuth("authenticated"));

  it("/ là trang chủ dự báo", async () => {
    mount("/");
    expect(await screen.findByRole("heading", { level: 1, name: "Dự báo giá vàng, bạc và dầu" })).toBeInTheDocument();
    await waitFor(() => expect(api.getForecasts).toHaveBeenCalled());
  });

  it("/overview mở thẳng", async () => {
    mount("/overview");
    expect(await screen.findByRole("heading", { name: "Trang tổng quan" })).toBeInTheDocument();
  });

  it.each([
    ["/dang-nhap?next=%2Faccuracy", "/accuracy"],
    ["/dang-nhap?next=%2Fasset%2Fsilver%3Fh%3D3", "/asset/silver?h=3"],
    ["/dang-nhap", "/"],
    ["/dang-nhap?next=https%3A%2F%2Fevil.example%2F", "/"],
    ["/dang-nhap?next=%2F%2Fevil.example", "/"],
    ["/dang-nhap?next=%2F%5Cevil.example", "/"],
    ["/dang-nhap?next=javascript%3Aalert(1)", "/"],
  ])("đăng nhập xong %s → %s (chỉ đường dẫn nội bộ)", async (path, target) => {
    mount(path);
    await waitFor(() => expect(location()).toBe(target));
  });
});

describe("tắt đăng nhập (VITE_AUTH_ENABLED=false)", () => {
  beforeEach(() => {
    flags.authEnabled = false;
  });

  it("vào thẳng trang chủ, sidebar ghi chế độ dữ liệu mẫu", async () => {
    mount("/");
    expect(await screen.findByRole("heading", { level: 1, name: "Dự báo giá vàng, bạc và dầu" })).toBeInTheDocument();
    expect(screen.getAllByText("Chế độ dữ liệu mẫu").length).toBeGreaterThan(0);
    expect(screen.queryByText("(cần đăng nhập)")).toBeNull();
    expect(screen.queryByRole("button", { name: /Đăng xuất/ })).toBeNull();
  });

  it("trang cần dữ liệu mở thẳng, /dang-nhap quay về next", async () => {
    mount("/accuracy");
    expect(await screen.findByRole("heading", { name: "Trang độ chính xác" })).toBeInTheDocument();
    cleanup();
    mount("/dang-nhap?next=%2Foverview");
    await waitFor(() => expect(location()).toBe("/overview"));
  });
});
