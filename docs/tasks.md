# Danh sách việc theo cổng (Gate)

Làm lần lượt từng task, mỗi task một commit nhỏ. Mỗi task có tiêu chí nghiệm thu kiểm chứng được: viết test trước, code cho test qua. Chỉ sang Gate sau khi toàn bộ nghiệm thu của Gate trước đã qua. Thiết kế chi tiết ở `docs/design.md`; quy tắc cứng ở `CLAUDE.md`.

Công nghệ đề xuất (đổi được nếu có lý do, nhưng phải cập nhật `CLAUDE.md`): extension bằng TypeScript và Manifest V3, server bằng Python (FastAPI, Pydantic, SQLite, pytest), test e2e bằng Playwright, Windows agent bằng Python (gọi DLL của Java Access Bridge bằng `ctypes`, khi chạy không cần gói ngoài), mock Swing bằng Java thuần build với `javac --release 8`.

Hai hướng (xem `docs/design.md` mục 1): **A** là extension cho web trên Chromium, **B** là Windows agent cho Java applet trong IE mode. Task không ghi hướng là dùng chung hoặc thuộc hướng A. Số task cũ được giữ nguyên; task thêm sau được đánh số nối tiếp trong từng Gate.

## Gate 1: ghi được (tuần 1)

| Task | Việc | Nghiệm thu |
| --- | --- | --- |
| 1.1 | Khởi tạo repo theo cấu trúc trong `CLAUDE.md`, cấu hình build và test cho `extension/`, `server/`, `mock-site/`, `tests/e2e/` | Bốn lệnh trong `CLAUDE.md` chạy được và test mẫu qua |
| 1.2 | Mock site: đăng nhập, Báo cáo A, Báo cáo B, lọc theo ngày, bảng kết quả. Dữ liệu synthetic sinh theo seed, có dòng lệch cố ý (lệch số, thiếu dòng, lệch do làm tròn). Công tắc "giao diện mới" đổi id, tên nút và vị trí | Test xác nhận cùng ngày và seed cho cùng dữ liệu; các dòng lệch cố ý tìm được bằng một hàm tham chiếu; bật công tắc thì id đổi |
| 1.2b | Mock site: thêm tra cứu và mở CIF, lập lệnh chuyển tiền, hàng chờ phê duyệt; hai tài khoản maker và checker; dữ liệu synthetic theo seed | Test các trang trả đúng dữ liệu synthetic; lệnh maker lập hiện trong hàng chờ của checker; checker không duyệt được lệnh do chính mình lập |
| 1.3 | JSON Schema cho event và workflow trong `schemas/` theo `docs/design.md` mục 4 (có `engine`, selector Java, action `read_value` và `wait_for`), kèm hàm validate ở cả extension và server | Test có mẫu web và mẫu Java hợp lệ qua; mẫu sai (thiếu trường, `risk` sai giá trị, `engine` sai giá trị) bị từ chối |
| 1.4 | Khung extension MV3: manifest, service worker, content script, side panel có nút Bắt đầu ghi / Dừng, biểu tượng đang ghi | Nạp được extension vào Chromium bằng Playwright; bấm Bắt đầu thì hiện trạng thái đang ghi |
| 1.5 | Recorder: bắt click, input, select, navigate; lưu nhiều selector dự phòng; loại id sinh ngẫu nhiên; phân loại trường (bỏ qua, nhạy cảm, không nhạy cảm); che PII; xử lý trang đổi nội dung không đổi URL | Test đơn vị cho phân loại trường và che PII; thao tác trên mock site cho ra event đúng schema; không có giá trị mật khẩu, số tài khoản nào trong event (test tìm chuỗi) |
| 1.6 | API nhận phiên ghi: `POST /sessions`, `GET /sessions/{id}`, lưu SQLite, kiểm tra schema | Test API với event hợp lệ và không hợp lệ; extension gửi được phiên lên server chạy local |
| 1.7 | (Hướng B, người dùng làm trên máy test có hệ thống thật, không viết code) Spike Java Access Bridge: chạy `jabswitch -enable`, mở lại ứng dụng, xem màn hình CIF và chuyển tiền bằng `python -m rookie_agent tree` (xem `windows-agent/README.md`); thử thêm `record` với thao tác chuột và bàn phím | Ghi lại vào `docs/spike-jab.md`: các ô nhập, nút, bảng có vai trò và tên accessible không; JRE của ứng dụng là 32 hay 64-bit; kết luận có cần Java agent dự phòng không |
| 1.8 | (Hướng B) Mock Swing trong `mock-java/`: đăng nhập, CIF, chuyển tiền, phê duyệt; dữ liệu synthetic theo seed; công tắc "giao diện mới" đổi tên và vị trí thành phần | Build được bằng `javac --release 8`; test xác nhận mọi ô nhập và nút có tên accessible; cùng seed cho cùng dữ liệu |
| 1.9 | (Hướng B) Khung Windows agent trong `windows-agent/`: Native Messaging host, kết nối Java Access Bridge, liệt kê cửa sổ Java; side panel hiện trạng thái agent và chuyển lệnh Bắt đầu ghi / Dừng | Test đơn vị cho giao thức Native Messaging (đóng khung, nhận, gửi thông điệp); agent đọc được cây thành phần của mock Swing; side panel báo rõ khi agent chưa cài hoặc Java Access Bridge chưa bật |
| 1.10 | (Hướng B) Recorder Java: bắt click, nhập, chọn qua Java Access Bridge; sinh selector Java nhiều lớp; bỏ qua `password text`; phân loại trường và che PII bằng bảng cấu hình dùng chung với hướng A | Test đơn vị cho selector và phân loại trường; thao tác trên mock Swing cho ra event `engine: java` đúng schema; không có giá trị mật khẩu, số tài khoản nào trong event (test tìm chuỗi) |

| 1.11 | (Hướng B) Agent ghi trong JVM (`java-agent/`): thấy Enter trong ô và hành động bằng phím, chỉ hoạt động khi đang Ghi, không ghi ký tự gõ; bước `submit` ghi, học và chạy lại được | Trên mock Swing nạp agent bằng `JAVA_TOOL_OPTIONS`: Enter ở ô mật khẩu được ghi thành `submit`, một cú bấm do cả hai nguồn báo chỉ thành một sự kiện, không ghi gì khi chưa bấm Ghi, không có giá trị nào trong event; workflow chạy lại đúng |
| 1.12 | (Hướng B) Trang quản lý chạy trên máy GDV (`windows-agent/rookie_agent/webui`) và gói chạy không cần cài Python: kiểm tra máy bằng lời thường (Java mấy bit, cầu nối, cửa sổ), Ghi, Học; biểu tượng trên màn hình nền tự chọn Python 32/64-bit theo Java | Test lõi với session giả: bản ghi không chứa giá trị nhập, bản ghi rỗng bị từ chối, học xong hiện bước bằng tiếng thường, file chẩn đoán không có giá trị; Host lạ và POST thiếu header bị từ chối; từ gói đã giải nén cả hai Python đều chạy `status`, trang mở được, máy chủ đi kèm bật được |
| 1.13 | (Hướng A) Bản thử cài được: manifest, service worker, content script ghi click, nhập, chọn, Enter, chuyển màn hình (kể cả đổi trang giữa chừng); side panel Ghi và Học; không cần chạy lại trên web | Test đơn vị: ô mật khẩu không ghi gì, ô nhạy cảm chỉ có loại, chữ che số dài, ô trong bảng chỉ có vị trí, event đúng schema; test thật nạp extension vào Chromium: ghi 3 lần trên mock site, không có số CIF trong bản lưu, Học ra bước đúng, không ghi khi chưa bấm Ghi, không giữ mật khẩu và tên đăng nhập qua trang chuyển |
| 1.14 | (Hướng B) Applet trong IE: agent tìm cả cửa sổ Java là cửa sổ con của trình duyệt; applet không có tên thì đặt tên theo tiêu đề trình duyệt | Test đặt cửa sổ Mock Swing làm cửa sổ con của một cửa sổ khác: agent vẫn thấy và đọc được cây thành phần; bản cũ (chỉ tìm cửa sổ cấp cao nhất) không qua test này |
| 1.15 | (Hướng B2) Thăm dò trang trong IE bằng COM trên máy thật: `soi-ie.py`, `soi-ie-dom.ps1` | Đã chạy trên máy IE thật: đọc được tab TouchPoint, các khung lồng nhau, ô nhập có `id`/`name` ổn định; không có Java/ActiveX |
| 1.16 | (Hướng B2) Cầu PowerShell và bộ ghi trong trang (ES3) | Bộ ghi chạy trong MSHTML quirks thật (đối tượng `htmlfile`): thấy nhập, bấm, Enter; không đọc giá trị ô mật khẩu và trường ẩn; cầu khởi động và liệt kê tab được |
| 1.17 | (Hướng B2) Recorder IE: che dữ liệu, selector theo khung, `engine: ie` | Test: không có giá trị nhạy cảm nào trong event (tìm chuỗi), event hợp lệ theo schema, chuỗi số dài trong nhãn bị che |
| 1.18 | (Hướng B2) Máy chủ: `engine: ie` (`schema_version: 2`), rủi ro theo màn hình và nhãn nút, học | Mẫu hợp lệ và sai trong `schemas/examples`; nút Lưu ra `write` và `approve`; nút chưa phân loại không bao giờ là `read` |
| 1.19 | (Hướng B2) Trang quản lý: chọn trang IE để Ghi, Kiểm tra máy báo đọc được N khung; tab Luồng | Test Core với cầu giả; `python -m rookie_agent ie-probe` in tab, khung, ô nhập |

**Nghiệm thu Gate 1 (e2e):** mở extension, thao tác 3 lần trên mock site với 3 ngày khác nhau, server có đúng 3 phiên, đều qua validate schema, và không chứa giá trị nhạy cảm. Hướng B: thao tác 3 lần "tra CIF rồi lập lệnh chuyển tiền" trên mock Swing, server có đúng 3 phiên `engine: java`, đều qua validate schema, và không chứa giá trị nhạy cảm.

## Gate 2: chạy lại đúng (tuần 2)

| Task | Việc | Nghiệm thu |
| --- | --- | --- |
| 2.1 | Interface `LLMClient` (`explain`, `locate`), `RuleBasedClient` chạy offline, `OpenAICompatClient` cho LLM nội bộ có API tương thích OpenAI (ví dụ vLLM), tự rơi về luật khi model lỗi hoặc trả sai định dạng | Test dùng `RuleBasedClient`, không cần mạng; test `OpenAICompatClient` bằng endpoint giả; dữ liệu còn dãy số dài chưa che bị từ chối trước khi gửi |
| 2.2 | Learner dạng luật: chuẩn hoá, căn chỉnh các phiên, nhận tham số, gán `risk` bằng luật và bảng cấu hình rủi ro theo ứng dụng (endpoint cho web, màn hình và nhãn nút cho Java), sinh `read_value` khi giá trị đọc ở bước trước được dùng lại ở bước sau, sinh workflow đúng schema | Từ 3 phiên ghi mẫu (fixture) sinh ra workflow có tham số `ngay`; phiên chỉ có 1 giá trị ngày vẫn sinh được nhưng có cảnh báo; bước gọi API ghi được gắn `write`; từ fixture "tra CIF rồi lập lệnh chuyển tiền" (web và Java) sinh ra workflow có bước chuyển tiền gắn `money` và `approve`; bước thay đổi dữ liệu chưa có trong bảng cấu hình được gắn `write` |
| 2.3 | API workflow: lưu version, trạng thái `draft` / `tested` / `approved`, lấy bản đã duyệt mới nhất | Test chuyển trạng thái hợp lệ và chặn chuyển trạng thái sai; không phát được bản chưa `approved` |
| 2.4 | Sandbox ở server: chạy thử workflow bằng Playwright trên mock site | Workflow `draft` chạy thử được và trả kết quả; chạy thử xong mới cho phép chuyển sang `tested` |
| 2.5 | Runner web trong extension (hướng A): kéo workflow đã duyệt, kiểm tra version và chữ ký, giữ bản sao; thực thi các action; tìm phần tử theo thứ tự selector | Chạy workflow học từ 3 phiên với một ngày chưa từng ghi cho ra đúng bảng như thao tác tay |
| 2.6 | Chế độ kiểm soát `auto` / `review` / `approve` trên side panel, nút Dừng khẩn, quy tắc cứng cho `write` và `money` | Bước `approve` luôn dừng chờ duyệt; không đặt được `auto` cho bước `money`; Dừng khẩn dừng ngay bước đang chạy |
| 2.7 | Điều khiển tập trung: Runner kéo chính sách định kỳ; lệnh khoá agent | Khoá agent trên server thì Runner dừng ở bước kế tiếp và báo lý do |
| 2.8 | (Hướng B) Runner Java trong Windows agent: nhận workflow đã duyệt từ extension, tìm phần tử theo thứ tự selector Java, thực thi qua Java Access Bridge, dùng chung vòng điều khiển `auto` / `review` / `approve` và Dừng khẩn với hướng A | Workflow học từ 3 phiên trên mock Swing chạy đúng với khách hàng chưa từng ghi; bước `money` luôn dừng chờ duyệt; Dừng khẩn dừng ngay bước đang chạy; bật "giao diện mới" thì selector dự phòng vẫn tìm được, không tìm được thì dừng hỏi GDV |
| 2.9 | (Hướng B) Sandbox Java: Windows agent ở chế độ thử chạy workflow `draft` trên mock Swing và trả kết quả về server | Workflow Java `draft` chạy thử được và trả kết quả; chạy thử xong mới cho phép chuyển sang `tested` |

**Nghiệm thu Gate 2 (e2e):** workflow học từ 3 phiên chạy đúng với ngày chưa từng ghi; bước `write` luôn dừng chờ duyệt; khoá từ xa dừng agent ở bước kế tiếp. Chức năng "tra CIF rồi lập lệnh chuyển tiền" được học và chạy lại đúng ở cả mock site và mock Swing mà không có dòng mã nào viết riêng cho chức năng đó; bước chuyển tiền luôn dừng chờ duyệt.

## Gate 3: demo đủ kịch bản (tuần 3)

| Task | Việc | Nghiệm thu |
| --- | --- | --- |
| 3.1 | Bước đối chiếu chạy trong Runner: ghép theo khoá, tìm lệch số và dòng thiếu, ngưỡng bỏ qua nhập bằng tham số, xuất bảng lệch | Với dữ liệu mock, tìm đúng toàn bộ dòng lệch cố ý; lệch dưới ngưỡng được đánh dấu bỏ qua |
| 3.2 | Giải thích lệch qua `LLMClient.explain(rows)` chỉ nhận dòng lệch đã che; `RuleBasedClient` trả nguyên nhân theo luật | Test xác nhận dữ liệu gửi vào `explain` không chứa giá trị nhạy cảm chưa che |
| 3.3 | Self-healing: selector dự phòng, rồi `LLMClient.locate(description, candidates, screenshot)`, ngưỡng tin cậy, dừng và hỏi GDV; đề xuất cập nhật workflow | Bật "giao diện mới" thì workflow vẫn chạy xong; độ tin cậy thấp thì dừng; chấp nhận đề xuất thì workflow lên version mới |
| 3.4 | Kho agent: version, điểm (tỷ lệ chạy đúng, số bước sửa tay, thời gian tiết kiệm), clone, phạm vi chia sẻ riêng tư / nhóm / đơn vị | Người dùng thứ hai clone agent và sửa rule mà bản gốc không đổi; agent riêng tư không hiện với người khác |
| 3.5 | Audit: log từng bước kèm ảnh đã che; đệm khi mất kết nối và đẩy lên khi có mạng; dashboard xem log | Ngắt kết nối giữa chừng thì log được đệm rồi đẩy đủ khi có lại; dashboard hiện đúng người chạy, version, kết quả |
| 3.6 | Kịch bản demo 8 bước (`docs/design.md` mục 10) và script đo bốn chỉ số (mục 11) | Script chạy hết kịch bản và in bốn chỉ số |

Task 3.3 (self-healing bằng `LLMClient.locate`) chỉ áp dụng cho hướng A. Task 3.4 và 3.5 áp dụng cho cả hai hướng vì dùng chung server.

**Nghiệm thu Gate 3 (e2e):** 8 bước của kịch bản demo chạy được liền mạch, kèm số đo thời gian và độ đúng.

## Phần để sau PoC

- Đánh giá độ chính xác của LLM nội bộ (Learner, giải thích lệch, self-healing) trên bộ mẫu; self-healing bằng ảnh nếu model nhận được ảnh.
- Quy trình thật đầu tiên (đối chiếu cuối ngày, hành trình chuyển tiền ngoại tệ) và kết nối hệ thống thật.
- Hướng B: self-healing bằng ảnh và LLM; Java agent dự phòng (`AWTEventListener`) nếu spike 1.7 cho thấy Java Access Bridge không đủ; kiểm thử trên applet thật trong IE mode; đóng gói Windows agent bằng C#/.NET.
- Nhánh có điều kiện trong workflow (ví dụ CIF đã tồn tại hay chưa).
- Ứng dụng desktop khác (không phải web, không phải Java).
