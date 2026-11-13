/** Plain business words for what was recorded and what the agent understood (no ids, no selectors). */

const ACTION_WORDS: Record<string, string> = {
  click: "Bấm",
  input: "Nhập vào",
  fill: "Nhập vào",
  select: "Chọn ở",
  submit: "Nhấn Enter ở",
  navigate: "Mở màn hình",
  goto: "Mở màn hình",
  read_value: "Đọc giá trị ở",
  wait_for: "Chờ",
};

export const RISK_WORDS: Record<string, string> = {
  read: "chỉ xem",
  write: "ghi dữ liệu, luôn hỏi trước khi làm",
  money: "liên quan tiền, luôn hỏi trước khi làm",
};

export const MODE_WORDS: Record<string, string> = { auto: "tự chạy", review: "dừng cho bạn xem", approve: "chờ bạn duyệt" };

export function friendlyStep(action: string, label?: string | null, url?: string | null): string {
  const verb = ACTION_WORDS[action] ?? "Thao tác";
  if (action === "navigate" || action === "goto") return url ? `${verb} ${url}` : verb;
  return label ? `${verb} «${label}»` : verb;
}
