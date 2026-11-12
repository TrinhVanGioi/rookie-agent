# Rookie Agent

Hệ thống để agent học thao tác của giao dịch viên (GDV) trên web qua vài lần làm mẫu, rồi chạy lại có kiểm soát từng bước. Recorder và Runner nằm trong extension, chạy trên từng máy PC; máy chủ nội bộ giữ LLM, kho agent, chính sách và audit.

Đọc `docs/design.md` trước khi viết code. Làm việc theo `docs/tasks.md`, mỗi lần một cổng (Gate), mỗi task một commit nhỏ.

## Cấu trúc repo

```
extension/   Chrome extension Manifest V3 (TypeScript): recorder, runner, side panel
server/      FastAPI (Python): ingest, learner, kho agent, audit, sandbox runner
mock-site/   Hệ thống đối chiếu giả lập (Báo cáo A, B) để demo và test
schemas/     JSON Schema của event và workflow (hợp đồng giữa các phần)
tests/e2e/   Test Playwright chạy extension thật trên mock site
docs/        design.md, tasks.md, demo-reference.html
```

## Lệnh (PowerShell, Windows)

```powershell
# server
cd server; python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt -r ..\mock-site\requirements.txt
pytest
uvicorn app.main:app --reload --port 8000

# mock site (dùng chung venv ở server/.venv, đã kích hoạt ở trên)
cd mock-site; pytest
uvicorn app:app --reload --port 8001

# extension
cd extension; npm install; npm run build; npm test

# e2e
cd tests/e2e; npm install; npx playwright install chromium; npx playwright test
```

Nếu lệnh nào chưa đúng với repo hiện tại thì sửa lệnh trong file này khi bạn phát hiện.

## Quy tắc cứng (không được phá)

1. Không lưu giá trị nhập nhạy cảm. Trường mật khẩu và OTP bỏ qua hoàn toàn. Trường nhạy cảm (số tài khoản, CCCD, tên, số tiền) chỉ lưu loại trường và tham số dạng `{ten}`. Chi tiết ở `docs/design.md` mục 4.2.
2. Che PII ngay trong extension, trước khi gửi bất cứ thứ gì về máy chủ (sự kiện, ảnh chụp, dữ liệu gửi LLM).
3. Mỗi bước workflow có `risk` (`read`, `write`, `money`) và `mode` (`auto`, `review`, `approve`). Bước `money` không bao giờ là `auto`. Bước `write` luôn là `approve`.
4. Runner nằm trong extension và chạy trong phiên đăng nhập của chính GDV. Playwright chỉ dùng ở server để chạy thử (sandbox) và trong test.
5. Schema trong `schemas/` là hợp đồng. Muốn đổi thì tăng `schema_version`, cập nhật test và `docs/design.md`.
6. PoC chỉ dùng dữ liệu synthetic. Không thao tác ghi tiền, không kết nối hệ thống thật.
7. Mọi chỗ gọi LLM đi qua interface `LLMClient`. Luôn có `RuleBasedClient` chạy offline để test và demo, không phụ thuộc mạng.
8. Dữ liệu đối chiếu được tính ngay trong Runner. Chỉ các dòng lệch đã che mới được gửi lên `LLMClient`.
9. Agent phải dừng và hỏi GDV khi gặp tình huống chưa từng thấy hoặc độ tin cậy dưới ngưỡng. Không đoán.
10. Giao diện hiển thị bằng tiếng Việt, tên hành động nhất quán: Ghi, Học, Duyệt, Chạy, Dừng khẩn.

## Cách làm việc

- Với task không nhỏ: lập kế hoạch trước (plan mode), chờ duyệt rồi mới sửa file.
- Viết test trước, rồi code cho test qua. Mỗi task trong `docs/tasks.md` có tiêu chí nghiệm thu kiểm chứng được.
- Chạy toàn bộ test của phần vừa sửa trước khi báo xong.
- Không thêm tính năng ngoài `docs/tasks.md`. Gặp chỗ mơ hồ thì hỏi.
- Tài liệu viết tiếng Việt; tên biến, hàm, file viết tiếng Anh.
- `docs/demo-reference.html` là bản mô phỏng một file để tham khảo hành vi và giao diện. Không sao chép cấu trúc code của nó.
