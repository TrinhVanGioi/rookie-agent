# Thiết kế Ghi (Record) và Chạy (Run) — công nghệ và luồng

Phạm vi: phần chạy trên máy GDV, hướng B2 (trang web trong Internet Explorer, như TouchPoint), kèm điểm khác của hướng A (extension) và hướng B (Java). Chi tiết quy tắc xem `docs/design.md` mục 4.2, 13, 14.

## 1. Bức tranh chung

```
Máy GDV (phiên đăng nhập của chính GDV)                     Máy chủ nội bộ
┌────────────────────────────────────────────┐              ┌─────────────────────┐
│ Trang trên máy (webui, :8765) = giao diện  │   đã che     │ Học (learner + LLM) │
│  Ghi · Học · Chạy · Duyệt · Dừng khẩn      │ ───────────▶ │ Kho quy trình       │
│                                            │              │ Audit, vai trò, AD  │
│ Windows agent (Python)                     │ ◀─────────── │ Trang quản trị /admin│
│  ├ Ghi:  IE qua COM + bộ ghi JS trong trang│  quy trình   │ Chạy thử trên bản sao│
│  ├ Học:  làm sạch → nhóm → gắn link       │              └─────────────────────┘
│  └ Chạy: gọi lại các lời gọi (API) hoặc    │
│          thao tác trên màn hình            │
└────────────────────────────────────────────┘
```

Nguyên tắc cứng áp dụng cho cả hai: che dữ liệu nhạy cảm ngay trên máy GDV; không lưu giá trị nhập nhạy cảm (chỉ loại trường và tham số `{ten}`); bước `money` không bao giờ tự chạy, bước `write` luôn chờ Duyệt; gặp tình huống lạ thì dừng và hỏi.

## 2. Công nghệ

| Lớp | Công nghệ | Làm gì |
|---|---|---|
| Giao diện GDV | Trang web tĩnh + máy chủ HTTP nhỏ của agent (`webui/core.py`, `index.html`) | Một giao diện cho Ghi, Học, Chạy, Duyệt, kết quả, file |
| Điều khiển IE | PowerShell + COM (`ie/ie-bridge.ps1`, `ie/bridge.py`) | Tìm cửa sổ IE, chạy script trong trang và các khung, đọc DOM, lấy địa chỉ |
| Bộ ghi trong trang | JavaScript ES3 (`ie/page_recorder.js`), chèn bằng `execScript` | Ghi bấm, gõ, Enter, hộp thoại; móc XHR/form/`window.open`; đọc màn hình (ô nhãn–giá trị, bảng, thông báo) |
| Phiên ghi | `ie/session.py`, `ie/recorder.py`, `ie/trace.py` | Gom sự kiện + lời gọi (request) + màn hình thấy được, gắn lời gọi vào thao tác sinh ra nó |
| Làm sạch | `ie/clean.py` (một bộ luật) | Bỏ thao tác thăm dò định kỳ, bấm nhầm rồi đóng cảnh báo, bấm thừa; đánh số lại |
| Kiểm bản ghi | `ie/check.py` | Sau Dừng ghi báo dùng được / đáng biết / cần ghi lại, bằng chữ dễ hiểu |
| Học | `server/app/learner.py`, `align.py`, `risk.py`, `llm/` (qua `LLMClient`, luôn có `RuleBasedClient` chạy offline) | Gộp nhiều lần ghi thành một quy trình: bước, tham số, rủi ro (`read/write/money`), chế độ (`auto/review/approve`) |
| Chuyển lời gọi thành nút | `ie/replay.py` (`build_api`, `groups_of`) | Mỗi lời gọi là một nút API; xác định chỗ nào là tham số, chỗ nào lấy từ trả lời trước |
| Giao thức đã biết | JSON, form, GWT-RPC (`//OK[...]`, bảng chuỗi), SOAP/IFX (XML), tài liệu base64 | Đọc, lấy giá trị nối (`json`/`gwt`/`xml`/`whole`/`before-after`) |
| File | `ie/files.py` | Nhận loại file theo byte đầu (PDF, ảnh, Excel, Word, XML, chữ), từ chối trang web, lưu tên đúng, dựng bản đọc XML |
| Bản in từ dữ liệu | `ie/report.py` | Học nhãn màn hình ↔ vị trí trong dữ liệu trả về; dựng `(bản in).html` |
| Chạy | `ie/replay.py` (`run_api`), `ie/twin.py` (bản sao), `runner.py` | Gửi lại lời gọi từ trang IE đã đăng nhập, ghép giá trị, lưu file, dừng chờ Duyệt |
| Sơ đồ | `ie/n8n.py` + `/admin` (JS thuần) | Vẽ quy trình kiểu n8n, xem lời gọi, sửa, chia sẻ |
| Máy chủ | FastAPI (Python), đăng nhập `off/dev/ldap` (AD) | Học, kho quy trình, chia sẻ, audit, số đo thời gian |
| Gọi từ ngoài | MCP (`mcp/`, stdio hoặc HTTP có token) | Cho Genie Codie gọi quy trình; không có tool Duyệt |
| Hướng A | Extension Manifest V3 (TypeScript) | Ghi/chạy web trên Chromium, side panel |
| Hướng B (Java) | Java Access Bridge (`jab/`) | Ghi/chạy ứng dụng Java applet |
| Kiểm thử | pytest; TouchPoint giả lập (`mock-site/touchpoint.py`); ma trận IE thật chế độ 8 và 9 (`tests/test_ie_matrix.py`) | Cổng chất lượng khi sửa phần Ghi hoặc Học |

## 3. Luồng Ghi

```
GDV bấm «Ghi»  →  agent gắn bộ ghi vào trang IE (và mọi khung con)
        │
        ▼
GDV làm việc bình thường trên TouchPoint
   Bộ ghi (trong trang) bắt:
   • thao tác: bấm, gõ, Enter, tick, đóng hộp thoại → nhãn ô, không giá trị nhạy cảm
   • lời gọi: XHR, form gửi, window.open, hộp thoại modal → địa chỉ, thân, trả lời (trong bộ nhớ)
   • màn hình: ô nhãn–giá trị, bảng, thông báo sau mỗi thao tác
   • file tải về: byte đầu để nhận loại
        │  (cầu nối COM lấy ra mỗi lúc)
        ▼
Phiên ghi (session.py)
   • mỗi lời gọi gắn vào thao tác cuối cùng xảy ra trước lúc gửi (theo đồng hồ)
   • lời gọi do script gửi form vào khung được ghi lúc khung rời đi
   • chỉ giữ địa chỉ thật; bỏ `javascript:`; thăm dò định kỳ đánh dấu
        │
GDV bấm «Dừng ghi»
        ▼
Làm sạch (clean.py) → Kiểm bản ghi (check.py) → Học bản in từ dữ liệu (report.py)
        ▼
Lưu bản ghi trên máy; GDV thấy nhận xét bằng chữ dễ hiểu
```

Về dữ liệu nhạy cảm:
- Mật khẩu, OTP: bỏ hoàn toàn.
- Số tài khoản, CCCD, tên, số tiền: chỉ lưu loại trường và tham số `{ten}`.
- Trả lời của server nằm trong bộ nhớ lúc ghi để đối chiếu; không ghi ra đĩa. Với bản in chỉ giữ nhãn và luật vị trí.
- Mã phiên nằm trong địa chỉ (`?sessionId=`): không lưu; lúc chạy lấy lại từ trang đang mở.
- Mọi thứ gửi về máy chủ đã che trên máy GDV trước.

## 4. Luồng Học

```
GDV chọn 2–3 lần ghi → «Học»
  1. Căn các lần ghi với nhau (align.py): bước nào giống, bước nào đổi
  2. Phần đổi giữa các lần = tham số (tài khoản, từ ngày, đến ngày…)
  3. Gán rủi ro read/write/money theo config/risk-rules.json và chế độ
     (money không auto, write luôn approve)
  4. Lời gọi → nút API (replay.build_api):
        • giá trị lấy từ lời gọi trước: tìm vị trí trong trả lời (json/gwt/xml/before-after/whole)
        • token (getToken → Bearer) nối đúng nguồn; đăng nhập không bao giờ chạy lại
        • nhóm các lời gọi nối nhau thành một nhóm (groups)
        • nút file: đánh dấu kiểu file; nút báo cáo: gắn luật bản in
  5. Hai lần ghi khác trình tự → không học bừa, đề nghị tách thành hai quy trình
  6. Tự chạy thử trên bản sao (twin) → báo bao nhiêu bước chạy lại được, chỗ nào chưa chắc
  7. LLM (nếu có) chỉ nhận dòng lệch đã che; không có thì RuleBasedClient
```

## 5. Luồng Chạy

```
GDV hỏi trợ lý / bấm quy trình / Codie gọi MCP
  ▼
Thẻ xác nhận (tham số điền sẵn, GDV sửa được)
  ▼
Chọn cách chạy
  ├─ Theo lời gọi (API): nhanh, không cần thao tác màn hình
  └─ Trên màn hình: thao tác lại như người
  ▼
Từng bước, theo thứ tự (replay.run_api)
  • giá trị tham số + giá trị lấy từ trả lời của bước trước
  • lời gọi gửi từ trang IE đã đăng nhập của GDV (khung gốc nếu khung ghi không còn)
  • read   → chạy (auto/review)
  • write  → dừng chờ GDV Duyệt
  • money  → không bao giờ tự chạy; chờ người kiểm soát bấm Duyệt (agent không tự duyệt)
  • không lấy được giá trị / lạ / độ tin cậy thấp → dừng và hỏi bằng lời dễ hiểu
  • Dừng khẩn: dừng tại bước hiện tại
  ▼
Kết quả mỗi nút: yêu cầu đã gửi, dữ liệu trả về (che), thời gian, trạng thái
  ▼
Đầu ra
  • file (PDF, Excel, XML): lưu thư mục Rookie, tên theo quy trình + giờ, nút Mở/In
  • màn hình điền từ dữ liệu (IN BÁO NỢ/CÓ): dựng «… (bản in).html» từ trả lời mới
  ▼
Audit (không chứa giá trị) → server; số đo thời gian tiết kiệm
```

## 6. Chế độ thử (sandbox) và bản sao

- Bản sao (`ie/twin.py`) trả lời theo hình dạng đã học, dùng để chạy thử và demo, không chạm hệ thống thật.
- PoC chỉ dùng dữ liệu synthetic; bước `money` chỉ chạy trên mock.
- Hộp cát thật (VM của cuộc thi) tính sau.

## 7. Cách kiểm chứng

| Việc | Cách |
|---|---|
| Đơn vị | `pytest` trong `windows-agent` và `server` |
| Trên IE thật | `ROOKIE_REAL_IE=1`, `RK_DOCMODE=8` và `9`: IE ẩn riêng, không đụng phiên của GDV |
| Ma trận Ghi → Học → Chạy | `scripts/run-ie-matrix.ps1`: in dữ liệu, tra cứu, sao kê PDF/Excel, chuyển tiền (money), bản in từ dữ liệu |
| Gói cài | `scripts/package-path-b.ps1`, `scripts/package-patch-ie.ps1` |

## 8. Giới hạn hiện tại

- Chưa thử Ghi/Học bản in trên TouchPoint thật; cảnh báo `getSecData` lúc Ghi chưa xác nhận hết.
- Ngày chọn bằng lịch chưa thành tham số.
- Bản in là mẫu chung của agent, chưa theo biểu mẫu chính thức của ngân hàng.
- Hộp cát và cách cài trên máy nội bộ chưa chốt.
