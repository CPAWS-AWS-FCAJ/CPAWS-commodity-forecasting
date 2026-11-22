// Cấu hình form đăng nhập/đăng ký của Amplify Authenticator (dữ liệu thuần, không import
// aws-amplify) để test kiểm tra được mà không phải render cả Authenticator.

/**
 * Chính sách mật khẩu, khớp `password_policy` của CpawsAuth (infra/stacks/cpaws_auth_stack.py).
 * Amplify.configure nhận để Authenticator kiểm tra ngay trên form; đổi pool thì sửa cả đây.
 */
export const PASSWORD_POLICY = {
  minLength: 8,
  requireLowercase: true,
  requireUppercase: true,
  requireNumbers: true,
  requireSpecialCharacters: true,
} as const;

export const PASSWORD_HINT =
  "Mật khẩu tối thiểu 8 ký tự, có chữ hoa, chữ thường, chữ số và ký tự đặc biệt (ví dụ ! @ # ?).";

/**
 * Thuộc tính gửi lên Cognito khi đăng ký. Pool đăng nhập bằng username; `email` để nhận mã xác minh,
 * `name` là Họ tên hiển thị (pool không bắt buộc, form bắt buộc). Không có số điện thoại.
 */
export const SIGN_UP_ATTRIBUTES = ["email", "name"] as const;

export const NAME_REQUIRED_MESSAGE = "Vui lòng nhập họ và tên.";

interface FieldOptions {
  label: string;
  placeholder: string;
  isRequired?: boolean;
  order?: number;
  type?: string;
  autocomplete?: string;
}

/** Nhãn tiếng Việt cho từng màn của Authenticator (prop `formFields`). */
export const FORM_FIELDS: Record<string, Record<string, FieldOptions>> = {
  signIn: {
    username: {
      label: "Tên đăng nhập",
      placeholder: "Nhập tên đăng nhập",
      autocomplete: "username",
    },
    password: {
      label: "Mật khẩu",
      placeholder: "Nhập mật khẩu",
      autocomplete: "current-password",
    },
  },
  signUp: {
    name: {
      label: "Họ và tên",
      placeholder: "Họ và tên của bạn",
      isRequired: true,
      order: 1,
      type: "text",
      autocomplete: "name",
    },
    email: {
      label: "Email",
      placeholder: "Email nhận mã xác minh",
      isRequired: true,
      order: 2,
      type: "email",
      autocomplete: "email",
    },
    username: {
      label: "Tên đăng nhập",
      placeholder: "Không dấu, không khoảng trắng",
      isRequired: true,
      order: 3,
      autocomplete: "username",
    },
    password: {
      label: "Mật khẩu",
      placeholder: "Tối thiểu 8 ký tự",
      isRequired: true,
      order: 4,
      autocomplete: "new-password",
    },
    confirm_password: {
      label: "Nhập lại mật khẩu",
      placeholder: "Nhập lại mật khẩu",
      isRequired: true,
      order: 5,
      autocomplete: "new-password",
    },
  },
  confirmSignUp: {
    confirmation_code: {
      label: "Mã xác minh",
      placeholder: "Nhập mã trong email",
      isRequired: true,
    },
  },
  forgotPassword: {
    username: {
      label: "Tên đăng nhập",
      placeholder: "Nhập tên đăng nhập",
      autocomplete: "username",
    },
  },
  confirmResetPassword: {
    confirmation_code: {
      label: "Mã xác minh",
      placeholder: "Nhập mã trong email",
      isRequired: true,
    },
    password: {
      label: "Mật khẩu mới",
      placeholder: "Tối thiểu 8 ký tự",
      autocomplete: "new-password",
    },
    confirm_password: {
      label: "Nhập lại mật khẩu mới",
      placeholder: "Nhập lại mật khẩu mới",
      autocomplete: "new-password",
    },
  },
  forceNewPassword: {
    password: {
      label: "Mật khẩu mới",
      placeholder: "Tối thiểu 8 ký tự",
      autocomplete: "new-password",
    },
    confirm_password: {
      label: "Nhập lại mật khẩu mới",
      placeholder: "Nhập lại mật khẩu mới",
      autocomplete: "new-password",
    },
  },
};

/**
 * Họ tên bắt buộc và không được chỉ có khoảng trắng (HTML `required` không bắt được trường hợp này).
 * Dùng làm `services.validateCustomSignUp` của Authenticator.
 */
export function validateSignUpName(
  formData: Record<string, string | undefined>,
  touchData: Record<string, boolean | undefined>,
): { name: string } | null {
  if (!touchData.name) return null;
  return (formData.name ?? "").trim() ? null : { name: NAME_REQUIRED_MESSAGE };
}

/**
 * Chuẩn hóa họ tên trước khi gửi Cognito: bỏ khoảng trắng thừa. Trả null khi rỗng để chặn gửi
 * (lớp chặn thứ hai, phòng khi người dùng bấm Enter trước khi rời ô).
 */
export function normalizeName(value: string | undefined): string | null {
  const text = (value ?? "").replace(/\s+/g, " ").trim();
  return text ? text : null;
}

/**
 * Bản dịch tiếng Việt cho chuỗi của Authenticator (khóa là chuỗi tiếng Anh gốc của Amplify UI) và
 * các lỗi Cognito hay gặp. Chuỗi không có ở đây hiện tiếng Anh.
 */
export const VI_VOCABULARY: Record<string, string> = {
  // Tab, nút, tiêu đề
  "Sign In": "Đăng nhập",
  "Sign in": "Đăng nhập",
  "Signing in": "Đang đăng nhập",
  "Sign in to your account": "Đăng nhập vào tài khoản",
  "Create Account": "Tạo tài khoản",
  "Create a new account": "Tạo tài khoản mới",
  "Creating Account": "Đang tạo tài khoản",
  "Forgot your password?": "Quên mật khẩu?",
  "Forgot password?": "Quên mật khẩu?",
  "Reset your password": "Đặt lại mật khẩu",
  "Reset your Password": "Đặt lại mật khẩu",
  "Reset Password": "Đặt lại mật khẩu",
  "Send code": "Gửi mã",
  "Send Code": "Gửi mã",
  Sending: "Đang gửi",
  "Back to Sign In": "Quay lại đăng nhập",
  Submit: "Gửi",
  Submitting: "Đang gửi",
  Confirm: "Xác nhận",
  Confirming: "Đang xác nhận",
  "Confirm Sign Up": "Xác nhận đăng ký",
  "Confirm Email Code": "Xác nhận mã email",
  "Resend Code": "Gửi lại mã",
  "Change Password": "Đổi mật khẩu",
  Changing: "Đang đổi",
  Verify: "Xác minh",
  "Verify Contact": "Xác minh liên hệ",
  Skip: "Bỏ qua",
  Loading: "Đang tải",
  "Dismiss alert": "Đóng thông báo",
  or: "hoặc",
  "Account recovery requires verified contact information":
    "Cần email đã xác minh để khôi phục tài khoản",
  "We Emailed You": "Đã gửi mã qua email",
  "We Sent A Code": "Đã gửi mã",
  "Your code is on the way. To log in, enter the code we emailed to":
    "Mã đang được gửi. Để đăng nhập, nhập mã đã gửi tới",
  "Your code is on the way. To log in, enter the code we sent you":
    "Mã đang được gửi. Để đăng nhập, nhập mã chúng tôi đã gửi",
  "It may take a minute to arrive": "Có thể mất khoảng một phút",
  // Nhãn mặc định (khi không có formFields)
  Username: "Tên đăng nhập",
  "Enter your username": "Nhập tên đăng nhập",
  "Enter your Username": "Nhập tên đăng nhập",
  Password: "Mật khẩu",
  "Enter your Password": "Nhập mật khẩu",
  "Confirm Password": "Nhập lại mật khẩu",
  "Please confirm your Password": "Nhập lại mật khẩu",
  "New password": "Mật khẩu mới",
  Email: "Email",
  "Enter your Email": "Nhập email",
  Name: "Họ và tên",
  "Enter your Name": "Nhập họ và tên",
  Code: "Mã",
  "Code *": "Mã *",
  "Confirmation Code": "Mã xác minh",
  "Enter your code": "Nhập mã",
  "Enter your Confirmation Code": "Nhập mã xác minh",
  "Show password": "Hiện mật khẩu",
  "Hide password": "Ẩn mật khẩu",
  // Kiểm tra trên form
  "Your passwords must match": "Hai mật khẩu chưa khớp",
  "Password must have at least 8 characters": "Mật khẩu cần tối thiểu 8 ký tự",
  "Password must have lower case letters": "Mật khẩu cần có chữ thường",
  "Password must have upper case letters": "Mật khẩu cần có chữ hoa",
  "Password must have numbers": "Mật khẩu cần có chữ số",
  "Password must have special characters": "Mật khẩu cần có ký tự đặc biệt",
  // Lỗi từ Cognito
  "Incorrect username or password.": "Sai tên đăng nhập hoặc mật khẩu.",
  "User does not exist.": "Sai tên đăng nhập hoặc mật khẩu.",
  "User already exists": "Tên đăng nhập này đã có người dùng.",
  "User is not confirmed.": "Tài khoản chưa xác minh email.",
  "Password attempts exceeded": "Nhập sai mật khẩu quá nhiều lần, thử lại sau.",
  "Attempt limit exceeded, please try after some time.": "Thử quá nhiều lần, vui lòng thử lại sau.",
  "Invalid verification code provided, please try again.": "Mã xác minh không đúng, vui lòng thử lại.",
  "Invalid code provided, please request a code again.": "Mã đã hết hạn, vui lòng gửi lại mã.",
  "Username cannot be empty": "Vui lòng nhập tên đăng nhập.",
  "Invalid email address format.": "Email không đúng định dạng.",
  "Username should be either an email or a phone number.": "Tên đăng nhập không hợp lệ.",
  "Unable to send verification code. Please try again.": "Không gửi được mã xác minh, vui lòng thử lại.",
  "Your verification code has expired. Please request a new code.":
    "Mã xác minh đã hết hạn, vui lòng gửi lại mã.",
  "The verification code you entered is incorrect. Please try again.":
    "Mã xác minh không đúng, vui lòng thử lại.",
  "Network error": "Lỗi mạng, vui lòng thử lại.",
};
