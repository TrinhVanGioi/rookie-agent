# Rookie Agent

Hệ thống để agent học thao tác của giao dịch viên (GDV) qua vài lần làm mẫu, rồi chạy lại có kiểm soát từng bước. Recorder và Runner chạy trên từng máy PC theo hai hướng: **hướng A** là extension cho hệ thống chạy trên Chromium; **hướng B** là Windows agent dùng Java Access Bridge cho hệ thống chạy IE mode với Java applet (JDK 1.8). Máy chủ nội bộ giữ LLM, kho agent, chính sách và audit.

Định hướng từ Gate 12: **Self-Adaptive Digital Process Twin (SADPT)**, bản sao số quy trình nghiệp vụ có khả năng tự thích nghi (`docs/Rookie_Agent_Adaptive_Digital_Process_Twin_Direction.md`, `docs/design.md` mục 15). Mỗi tính năng mới nói rõ thuộc phần nào của vòng MAPE-K.

Đọc `docs/design.md` trước khi viết code. Làm việc theo `docs/tasks.md`, mỗi lần một cổng (Gate), mỗi task một commit nhỏ.

## Cấu trúc repo

```
extension/      Chrome/Edge extension Manifest V3 (TypeScript): recorder web và side panel Ghi, Học (hướng A; runner web chưa làm); cài thử xem extension/README.md
windows-agent/  Windows agent (Python): recorder, runner Java qua Java Access Bridge (hướng B), trang web trong IE cũ qua COM (ie/, hướng B2), Native Messaging host
server/         FastAPI (Python): ingest, learner, kho agent, audit, sandbox runner, đăng nhập (app/auth/), trang quản trị luồng /admin (app/admin/)
mock-site/      Hệ thống web giả lập: Báo cáo A, B, CIF, chuyển tiền, phê duyệt
mock-java/      Ứng dụng Java Swing giả lập TPSS (CIF, chuyển tiền, phê duyệt) cho hướng B
schemas/        JSON Schema của event và workflow (hợp đồng giữa các phần), kèm mẫu hợp lệ và mẫu sai
config/         Bảng phân loại trường nhập, luật rủi ro, vai trò theo nhóm AD (roles.json); dùng chung cho extension, Windows agent và server
scripts/        Script đóng gói
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
# trang quản trị luồng (Gate 10): http://localhost:8000/admin/. Đăng nhập: ROOKIE_AUTH=off (mặc định, một máy), dev (người trong config/roles.json), ldap (AD)
$env:ROOKIE_AUTH = "dev"; uvicorn app.main:app --port 8000
$env:ROOKIE_AUTH = "ldap"; $env:ROOKIE_LDAP_URL = "ldaps://dc.bank.local"; $env:ROOKIE_LDAP_DOMAIN = "bank.local"; $env:ROOKIE_LDAP_BASE_DN = "DC=bank,DC=local"

# LLM nội bộ (tuỳ chọn; không đặt thì server dùng RuleBasedClient, chạy offline)
$env:ROOKIE_LLM_BASE_URL = "http://node:port/v1"; $env:ROOKIE_LLM_MODEL = "<tên model đang serve>"
cd server; python -m app.llm.check

# bản sao quy trình (Gate 9): sinh 30 ca synthetic GDV → KSV vào máy chủ đang chạy
python ..\scripts\twin_seed.py http://localhost:8000 --cases 30

# mock site (dùng chung venv ở server/.venv, đã kích hoạt ở trên)
cd mock-site; pytest
uvicorn app:app --reload --port 8001

# extension
cd extension; npm install; npm run build; npm test

# e2e (kể cả trang quản trị: tự chạy máy chủ thứ hai ở cổng 8002 với ROOKIE_AUTH=dev)
cd tests/e2e; npm install; npx playwright install chromium; npx playwright test
# pytest của server phải chạy trong thư mục server (một test gọi python -c "import app")

# mock Java (cần JDK 8 trở lên, không dùng Maven/Gradle): build, đóng jar và chạy SelfTest
.\mock-java\build.ps1
java -jar mock-java\mock-tpss.jar

# windows agent (dùng chung venv ở server/.venv; khi chạy chỉ cần thư viện chuẩn)
cd windows-agent; pip install -r requirements-dev.txt; pytest
$env:ROOKIE_REAL_IE = "1"; $env:RK_DOCMODE = "8"; pytest tests/test_ie_real.py   # (chạy cả 8 và 9; máy GDV là IE 8/9, IE 11 chỉ giả lập chế độ tài liệu) bắt buộc khi sửa phần IE: chạy trên Internet Explorer thật (tự mở cửa sổ IE riêng ở chế độ ẩn, không lên trước, không chiếm bàn phím nên vẫn làm việc bình thường lúc chạy)
python -m rookie_agent status
python -m rookie_agent web   # trang quản lý tại http://localhost:8765 (Kiểm tra máy, Ghi, Học)

# ma trận Ghi → Học → Chạy trên IE thật, trên TouchPoint giả lập (Gate 11): bắt buộc khi sửa phần ghi hoặc học
.\scripts\run-ie-matrix.ps1
# TouchPoint giả lập để demo: chạy mock site rồi mở http://localhost:8001/tp/ bằng Internet Explorer (gdv01 / demo-only-1234)
# MCP cho Genie Codie (Gate 11): stdio; hoặc HTTP khi Codie ở máy khác
python -m rookie_agent mcp
$env:ROOKIE_MCP_TOKEN = "<ít nhất 24 ký tự>"; python -m rookie_agent mcp --http 8770 --allow 10.0.0.5

# đóng gói hướng B để mang vào máy nội bộ (xem windows-agent/README.md)
.\scripts\package-path-b.ps1
```

Nếu lệnh nào chưa đúng với repo hiện tại thì sửa lệnh trong file này khi bạn phát hiện.

## Quy tắc cứng (không được phá)

1. Không lưu giá trị nhập nhạy cảm. Trường mật khẩu và OTP bỏ qua hoàn toàn. Trường nhạy cảm (số tài khoản, CCCD, tên, số tiền) chỉ lưu loại trường và tham số dạng `{ten}`. Chi tiết ở `docs/design.md` mục 4.2.
2. Che PII ngay trên máy GDV (trong extension hoặc Windows agent), trước khi gửi bất cứ thứ gì về máy chủ (sự kiện, ảnh chụp, dữ liệu gửi LLM).
3. Mỗi bước workflow có `risk` (`read`, `write`, `money`) và `mode` (`auto`, `review`, `approve`). Bước `money` không bao giờ là `auto`. Bước `write` luôn là `approve`.
4. Runner chạy trên máy GDV, trong phiên đăng nhập của chính GDV: hướng A nằm trong extension, hướng B nằm trong Windows agent. Side panel của extension là giao diện duy nhất cho cả hai hướng. Playwright chỉ dùng ở server để chạy thử (sandbox web) và trong test; sandbox Java dùng Windows agent ở chế độ thử.
5. Schema trong `schemas/` là hợp đồng. Muốn đổi thì tăng `schema_version`, cập nhật test và `docs/design.md`.
6. PoC chỉ dùng dữ liệu synthetic và không kết nối hệ thống thật. Bước `money` chỉ được chạy trên mock (`mock-site/`, `mock-java/`) và luôn dừng chờ duyệt. Cú bấm Duyệt của người kiểm soát (checker) luôn do người bấm, agent không tự phê duyệt.
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
