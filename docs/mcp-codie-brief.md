# Yêu cầu cho Codie: MCP server của Rookie Agent

Đọc `CLAUDE.md` và `docs/design.md` trước. Làm theo `docs/tasks.md`: một task một commit nhỏ, viết test trước.

## Mục tiêu

Làm một MCP server chạy trên máy GDV, cho AI (Codie, MyGenie) gọi các luồng Rookie Agent đã học: liệt kê luồng, chạy luồng với tham số, xem trạng thái, dừng khẩn. MCP chỉ là lớp mỏng bọc trang quản lý cục bộ `http://127.0.0.1:8765` (`windows-agent/rookie_agent/webui/`). Không viết lại logic chạy.

Dùng cho hồ sơ AI Hackathon VietinBank 2026, Bảng B: MCP chuẩn, mô tả tool và schema, phân quyền, timeout, chống chạy trùng, nhật ký truy vết, ghi dữ liệu phải qua bước duyệt.

## Vị trí và công nghệ

- Thư mục mới `windows-agent/rookie_agent/mcp/` (module `python -m rookie_agent mcp`), kênh stdio.
- Máy nội bộ ngoại tuyến: chỉ dùng thư viện chuẩn nếu được (JSON-RPC 2.0 qua stdin/stdout, `urllib` gọi 127.0.0.1). Nếu dùng SDK `mcp` chính thức thì phải ghi rõ cách mang wheel vào máy nội bộ và đưa vào `requirements`.
- Gọi trang quản lý qua HTTP cục bộ. Không import trực tiếp `Core`.
- Trang quản lý phải đang chạy. Nếu không thì tool trả lỗi rõ: «Trang quản lý chưa mở. Chạy `python -m rookie_agent web`.»

## Tool cần có

Tên tool tiếng Anh, mô tả và thông báo cho người dùng bằng tiếng Việt. Mỗi tool có JSON Schema cho đầu vào và đầu ra. Đọc `webui/core.py` (`Core.ROUTES` ở cuối file) để lấy đúng dạng dữ liệu, không đoán.

| Tool | Gọi tới | Ghi chú |
|---|---|---|
| `list_flows` | `GET /api/flows` | Chỉ trả luồng đã duyệt (`workflow.status == approved`): tên, tên ô nhập, mức rủi ro lớn nhất. Không trả bản ghi, không trả giá trị. |
| `plan_from_sentence` | `POST /api/assistant/plan`, `POST /api/assistant/answer` | Câu hỏi tự nhiên vào, ra thẻ gồm luồng được chọn, ô còn thiếu, câu cần hỏi. Không chạy gì. |
| `start_run` | `POST /api/assistant/run` (hoặc `/api/run/start`) | Nhận `title`, `inputs`, `idempotency_key`. Xem phần an toàn. |
| `get_run_status` | `GET /api/run/status` | Trả `running`, `waiting_for_human`, `finished`, `failed`, `stopped`, kèm danh sách bước. |
| `stop_run` | `POST /api/run/stop` | Dừng khẩn. Luôn cho phép. |

## Không được làm

- **Không có tool Duyệt.** Không đưa `POST /api/run/decide` ra MCP. Khi luồng đến bước `write` hoặc `money`, `get_run_status` trả `waiting_for_human` và nội dung câu hỏi; người bấm Duyệt trên trang quản lý. AI không bao giờ tự duyệt (quy tắc 3 và 6 trong `CLAUDE.md`).
- Không có tool Ghi, Học hay duyệt luồng (`/api/flow/approve`, `/api/learn`, `/api/record/*`).
- Không trả giá trị nhập hay giá trị đọc được từ hệ thống. Chỉ trả tên trường và trạng thái, giống `audit.jsonl`. Ô nhạy cảm (số tài khoản, CCCD, tên, số tiền) và mật khẩu, OTP không đi qua MCP dưới dạng giá trị đã lưu.
- Chỉ chạy trên sandbox. Bước `money` chỉ chạy trên `mock-site/` hoặc `mock-java/`.
- Chỉ nghe stdio. Không mở cổng mạng.

## An toàn và vận hành (thể lệ chấm điểm)

1. **Chống chạy trùng.** `start_run` bắt buộc có `idempotency_key`. Cùng key thì trả kết quả lần đầu, không chạy lại. Cùng luồng với cùng tham số trong 10 phút (chỉnh được) thì hỏi lại thay vì chạy. Hiện `Core.run_start` chỉ chặn hai lần chạy cùng lúc (`core.py` quanh dòng 645).
2. **Timeout.** Timeout tổng cho một lần chạy (mặc định 15 phút, đặt qua biến môi trường). Hết hạn thì gọi dừng khẩn và ghi `status: timeout`. Mỗi lời gọi HTTP tới trang quản lý cũng có timeout. Timeout của Học là việc riêng, không thuộc MCP.
3. **Phân quyền.** Mỗi tool khai báo vai trò được dùng: `maker` được gọi `start_run`, `checker` chỉ được xem và mở hàng chờ. Vai trò đọc từ cấu hình, mặc định `maker`. Chạy trong phiên đăng nhập của chính GDV, không giữ mật khẩu.
4. **Nhật ký truy vết.** Mỗi lần gọi tool ghi một dòng vào `audit.jsonl` cùng thư mục với nhật ký hiện có: thời gian, tool, tên luồng, tên ô nhập, kết quả, số giây, mã `idempotency_key`. Không có giá trị. Dùng lại `Core._audit_line`, không tạo định dạng khác.
5. **Che PII** trước khi bất cứ thứ gì rời máy GDV (quy tắc 2). Lỗi trả về cũng không chứa giá trị.

## Tiêu chí nghiệm thu (viết test trước)

- `tools/list` trả đủ 5 tool, mỗi tool có mô tả tiếng Việt và schema hợp lệ.
- Không tồn tại tool nào gọi được `/api/run/decide`.
- Chạy luồng chứa bước `write` qua MCP: dừng ở `waiting_for_human`, không đi tiếp khi không có người bấm.
- Gọi `start_run` hai lần cùng `idempotency_key`: chỉ một lần chạy.
- Chạy quá timeout tổng: luồng bị dừng, audit ghi `timeout`.
- `audit.jsonl` và mọi phản hồi của MCP không chứa giá trị nhập (test quét theo mẫu có giá trị giả đặt sẵn).
- Trang quản lý chưa mở: lỗi tiếng Việt rõ, không treo.
- Demo end-to-end: client MCP giả gọi `list_flows`, `start_run` trên luồng đọc của `mock-site`, đọc `get_run_status` đến `finished`.

## Ngoài phạm vi

Học luồng, sandbox của BTC, MCP cho server FastAPI, giao diện. Gặp chỗ mơ hồ thì hỏi, đừng đoán.
