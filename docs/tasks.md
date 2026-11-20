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

## Gate 4: học bằng trợ lý (LLM)

Lý do: bộ ghi chỉ ghi những gì có luật mô tả (danh sách cứng phần tử bấm được) và learner luật chỉ học khi các phiên ghi khớp tuyệt đối từng bước. Gate này đảo lại: ghi tất cả (chỉ lọc để an toàn), rồi để LLM thiết kế workflow trên bản ghi đã che. Thiết kế (Fable 5.2) và quyết định: LLM chạy trên máy GDV qua Genie Codie CLI (agent nội bộ, self-host), hai mode `rookie-design` (Fable 5.2) và `rookie-workflow` (Sonnet 5.5), chỉ có quyền đọc; kết quả lấy từ marker `<<<MV_RESULT ... MV_RESULT>>>`. LLM chỉ trỏ tới `eid` và `el_id` có trong trace; code bơm selector, server tự tính `risk` và `mode` bằng `risk.py`. Không có Codie hoặc kiểm chứng sai nhiều lần thì rơi về learner luật, báo rõ lý do và hướng dẫn GDV. Cho học từ một phiên, nhưng chữ không phải control bị che thành `#` và hiện cảnh báo; nhánh điều kiện để sau PoC. Task đánh dấu (*) làm trước, chưa cần LLM.

| # | Task | Nghiệm thu |
|---|---|---|
| 4.1* | `schemas/trace.schema.json` (v1) và `validate_trace`: mọi sự kiện, danh mục phần tử, không có ký tự phím | Mẫu đúng qua; mẫu sai (thiếu `eid`, `kind` lạ, có ký tự phím, không phiên, `eid` trùng, `el_id` không có) bị từ chối |
| 4.2* | Dựng trace đã che trên máy GDV (`windows-agent/rookie_agent/ie/trace.py`) | Tìm chuỗi: không có mật khẩu, OTP, số dài, ký tự phím; chữ không phải control khác nhau giữa các phiên (hoặc chỉ một phiên) thành `#`; `eid` ổn định |
| 4.3* | `page_recorder.js` ghi thô, bỏ danh sách cứng phần tử bấm được | Trong `htmlfile` quirks: bấm vào TD, IMG, SPAN không có handler vẫn được báo; ô mật khẩu và ẩn vẫn không đọc giá trị |
| 4.4 | `LLMClient.build_workflow(traces, ...)`; `RuleBasedClient` bọc `learn()` | Offline: fixture trace ra workflow hợp lệ, `method: "rule"` |
| 4.5 | Cổng kiểm chứng V1 đến V11 (`learn_gate.py`) | Mỗi mã có một test đúng và một test sai |
| 4.6 | Bơm selector từ danh mục phần tử; server gán `risk` và `mode` | Selector trùng khít trace; `money` không bao giờ `auto`; `write` luôn `approve` |
| 4.7 | Bộ gọi Codie (subprocess, file prompt, marker, timeout, thử lại) | Với codie giả: ok, thiếu marker, hai marker, JSON hỏng, timeout, exit khác 0 |
| 4.8 | Cấu hình hai custom mode và mẫu prompt | Chỉ group `read`; prompt dựng ra qua `assert_masked`; khớp file mẫu |
| 4.9 | `CodieClient.build_workflow`: hai giai đoạn, vòng sửa tối đa 2 lần, rơi về luật | Kịch bản giả: qua ngay; sai rồi sửa được; sai quá lượt thì rơi về kèm lý do; dữ liệu chưa che thì không gọi Codie |
| 4.10 | `workflow.schema.json` v3 (thêm `learned_by`, `title`, `evidence`, `confidence`, tuỳ chọn); server kiểm chứng lại khi nhận | v1, v2 vẫn qua; bản nháp tự khai `risk` thấp bị server ghi đè |
| 4.11 | Trang "Học": tiến độ, câu hỏi cho GDV, lý do rơi về bằng lời thường kèm hướng dẫn | Test Core với client giả |
| 4.12 | Bộ fixture phát lại (tra CIF, chuyển tiền, phiên có bấm thừa) | E2E: 3 phiên có nhiễu ra workflow đúng; bước chuyển tiền là `money` và `approve`; không gọi mạng |

**Bước optional và bắt hết thao tác (thiết kế chốt, 16/11/2026).** Bước chọn giá trị (role, ngôn ngữ, nơi làm việc) là bước «đảm bảo giá trị» (đọc giá trị đang có, bằng đích thì bỏ qua, khác thì chọn rồi đọc lại; so theo `option.value`); ô đó là tham số tuỳ chọn (`input.required:false`). Cú bấm chỉ đôi khi có là «nếu có thì bấm», chỉ khi rủi ro `read` và bước ngay trước không phải ghi hoặc tiền. Căn các phiên bằng code (`server/app/align.py`), LLM chỉ đặt tên và gợi ý; người dùng quyết định khi Học. Role chọn sau khi đăng nhập; GDV có thể có 2 role, 1 location: role là tham số bắt buộc, location đảm bảo bằng giá trị đã ghi và dừng hỏi nếu khác. Đăng nhập là bước `manual` (mật khẩu không bao giờ qua agent). Không dùng BHO (máy GDV không cài thêm gì). Chạy thử trên UAT chỉ thực hiện bước `read` và dừng trước bước ghi/tiền đầu tiên. Mọi task chạm phần IE phải qua test trên Internet Explorer thật (`tests/test_ie_real.py`).

| # | Task | Nghiệm thu |
|---|---|---|
| 4.13 | (đã làm) Gộp thao tác lặp không liền kề, khớp phần tử theo id/name (`server/app/learner.py`) | Hai bản ghi thật: «User Account» còn 1 bước; LOGOFF và ĐĂNG XUẤT là 1 bước |
| 4.14 | (đã làm) Ghi giá trị ban đầu, danh sách lựa chọn, giá trị trước khi đổi của ô chọn (`page_recorder.js`, `ie/trace.py`, `trace.schema.json`) | IE thật: `initial` đúng khi script đặt mặc định sau onload; ô mật khẩu không có `initial` |
| 4.15 | (đã làm) `align.py`: căn các phiên cho phép thiếu bước, thay đoạn so khớp tuyệt đối | Fixture: thiếu select, đổi thứ tự fill, click write thiếu (từ chối), dưới 60% (từ chối), 1 phiên, 2 phiên |
| 4.16 | (đã làm) Schema workflow v3 (`optional`, `required`, ràng buộc engine ie là 2 hoặc 3) và V2 mới | v1, v2 vẫn qua; `if_present` kèm write bị từ chối; optional ngoài danh sách ứng viên bị từ chối |
| 4.17 | (đã làm) Runner `if_different` | IE thật: bằng thì bỏ qua; khác thì chọn và chờ nạp lại; đích không có thì dừng; để trống thì bỏ qua; ô khoá thì dừng |
| 4.18 | Trang Học: câu hỏi optional và `decided_by` | Chưa trả lời thì không duyệt được |
| 4.19 | (đã làm) Runner `if_present` | IE thật: hiện, không hiện, hiện muộn, hộp sau bước write thì dừng |
| 4.20 | Trace v2: nhiều nguồn một dòng thời gian, mã trang và số thứ tự để phát hiện mất dòng | IE thật: 50 click qua 3 khung có điều hướng không hở; ép tràn cookie thì báo mất dòng |
| 4.21 | Dừng hai pha, `screen_change`, `attach` | Dừng khi khung nạp chậm vẫn có click cuối; trang tự đổi bằng timer sinh `screen_change` |
| 4.22 | Độ phủ lúc Dừng ghi và chặn Học (`coverage.py`) | Trang tự đổi thì vàng; tiêu điểm vào OBJECT thì đỏ |
| 4.23 | Hộp thoại JS (`alert`/`confirm`/`prompt`) và hộp thoại Windows gốc | `confirm` sau click ghi đúng kết quả; `alert` lúc onload vẫn thấy qua Windows |
| 4.24 | press, contextmenu, paste, phím tắt, kéo thả, hover | `fireEvent` từng loại ra đúng sự kiện; Enter thật kiểm tay |
| 4.25 | `window.open` và `showModalDialog` | Click trong modal có `window=modal`; poll không treo khi modal mở |
| 4.26 | Thử nghiệm bọc XHR (mặc định tắt) | Trang dùng XHR gốc chạy y hệt khi bật; không đạt thì để tắt |
| 4.27 | Nguồn Java Access Bridge cho khung `fiApplet` | Applet thử ra sự kiện đúng thứ tự; không có JAB thì ra đỏ |
| 4.28 | Cổng Học: mọi sự kiện gây ra khớp một bước hoặc có lý do bỏ qua | Trace từ IE thật qua cổng; bỏ một sự kiện thì cổng chặn |
| 4.29 | Chạy thử khô trên UAT | Dừng đúng trước bước «Lưu»; đổi id trong trang thì báo đúng bước |
| 4.30 | Chính sách role và location | Trang chọn ngôn ngữ nạp lại danh sách role; sai role thì dừng |

Thứ tự làm: 4.13, 4.14, 4.20, 4.21, 4.22 trước (cho GDV biết ngay bản ghi có thiếu hay không), rồi 4.15 đến 4.19, rồi 4.23 đến 4.30. Câu hỏi còn mở: bước chọn role/language/location xếp `read` hay `write` (mặc định hiện là `write`, tức luôn dừng chờ duyệt).


**Đọc và ghi thông tin, rồi Runner IE (thiết kế chốt, 16/11/2026).** Chỉ ghi thao tác thì không mô phỏng được giao dịch viên: agent phải *nhận* thông tin (dữ liệu hiện trên màn hình sau mỗi thao tác) và *gửi* thông tin (giá trị vào ô, kể cả giá trị đọc từ bước trước). Quyết định: (1) đọc dữ liệu **từ màn hình** (bảng, cặp nhãn-giá trị, thông báo), không lấy nội dung request/response và không móc XHR; chỉ lấy siêu dữ liệu điều hướng (đường dẫn bỏ query, mã trạng thái, thời gian) nếu cầu bắt được sự kiện COM. (2) Bản đầy đủ có giá trị chỉ nằm trong bộ nhớ phiên trên máy giao dịch viên (panel «Agent đã thấy»), không ghi đĩa; bản đã che (kiểu, tiêu đề cột, `value_class`, số dòng) mới vào trace và lên máy chủ. (3) Liên kết dữ liệu A sang B (giá trị đọc ở bước trước là đầu vào bước sau) do Recorder tìm ngay trên máy; chỉ gửi mối nối, không gửi giá trị. (4) Thẻ duyệt cố định: tên bước, «Sẽ gửi» nguyên văn, «Đang thấy trên màn hình», wireframe dựng từ cấu trúc (không chụp điểm ảnh), kết quả sau bước, nút Duyệt/Không duyệt/Dừng khẩn. (5) UAT chỉ chạy bước `read`; `write` và `money` chỉ chạy trên `mock-site/` trong IE. Workflow IE lên `schema_version: 3`. Mỗi task chạm phần IE phải qua `tests/test_ie_real.py`.

| # | Task | Nghiệm thu |
|---|---|---|
| 4.31 | (đã làm) Đọc màn hình khi Ghi và panel «Agent đã thấy» (`page_recorder.js`, `ie/read.py`, webui) | IE thật, frameset lồng: nhập, Enter thật, bảng hiện; đọc đúng tiêu đề, số dòng, từng ô |
| 4.32 | (đã làm) Vùng kết quả bằng so sánh màn trước và sau | Trang có đồng hồ chạy: vùng đúng là bảng kết quả; khung tải lại thì cả khung |
| 4.33 | (đã làm) Hai bản: đầy đủ trên máy, đã che lên máy chủ (`ie/trace.py`, `trace.schema.json`) | Trace không chứa số tài khoản hay tên của trang test; có `col_classes` |
| 4.34 | Pick «chỗ cần xem»: ô, cột, bảng, khối nhãn-giá trị | Bấm thật vào `TD` sinh đúng 3 lựa chọn; ô mật khẩu bị bỏ qua |
| 4.35 | (một phần: bắt request/response bằng XHR và ActiveX, giữ đầy đủ trong bộ nhớ, trace chỉ giữ hình dạng; chưa có thông báo lỗi trên màn hình thành mức riêng ở trace) Thông báo lỗi và siêu dữ liệu điều hướng (`ie-bridge.ps1`) | Trang 404 và trang «Không tìm thấy» đều là `level: error`; đường dẫn không còn query |
| 4.36 | Liên kết A sang B tính tại máy | Ghi «tìm rồi gõ số tài khoản sang màn sau»: trace có mối nối, không có giá trị |
| 4.37 | (một phần: schema v3 có `optional` và `required`; chưa có `read_fields`, `extract_table`, `expect`, `wait`, `verify`) Schema workflow v3 (đọc, `expect`, `wait`, `verify`, biến) và `check_workflow` | Flow v3 từ phiên IE thật qua kiểm; biến dùng trước khi tạo bị từ chối |
| 4.38 | (một phần: đọc lại giá trị sau khi nhập và chọn ô theo `option.value`; chưa có ô gợi ý và `expect`) Đọc lại sau khi nhập, ô chọn theo `option.value`, ô gợi ý, `expect` (`ie/page_runner.js`) | `SELECT` chọn đúng; ô tự định dạng thì `reformatted`; gợi ý trùng thì dừng |
| 4.39 | (đã làm) IeDriver và tìm phần tử (`ie/driver.py`, `ie/locate.py`) | Tìm đúng trong frameset lồng; hai phần tử giống nhau thì `ambiguous` |
| 4.40 | (đã làm) Nhập, chọn, bấm, Enter, chống phát lặp | Enter kích tìm kiếm thật; gửi lại cùng token không bấm lần hai |
| 4.41 | (một phần: `read_value` lưu biến dùng được cho bước sau; chưa có đọc bảng nhiều dòng và hỏi chọn dòng) Chờ, đọc, liên kết dữ liệu, hỏi chọn dòng | Tra cứu, lấy số, điền màn sau: chạy trọn trên mock-site |
| 4.42 | (đã làm) Duyệt, dừng hỏi, Chạy thử, luật rủi ro | Chạy thử dừng trước bước write; nút «Duyệt» nghiệp vụ bị `refused` |
| 4.43 | (đã làm) Dừng khẩn | Dừng trong 1 giây, không có hành động nào sau cờ |
| 4.44 | (đã làm) Canvas tab Luồng và thẻ duyệt | Thẻ có đủ mục với dữ liệu từ IE thật |
| 4.45 | (đã làm) Nhật ký đã che | File sau lần chạy thật không chứa giá trị nào của trang test |
| 4.46 | (một phần: chạy trọn flow có bước tiền và Duyệt trên trang cục bộ trong IE thật; chưa dựng bằng mock-site) Chạy trọn flow tiền trên mock-site trong IE | Duyệt từng bước, `expect` đạt |

Thứ tự: giai đoạn A là 4.31 đến 4.38 (đọc và ghi thông tin), giai đoạn B là 4.39 đến 4.46 (Runner). Giá trị thấy ngay cho giao dịch viên: 4.31.

**Tiến độ Gate 4 (17/11/2026).** Đã làm: 4.1 đến 4.3, 4.13 đến 4.17, 4.19, 4.31 đến 4.33, 4.39 đến 4.45. Làm một phần: 4.35, 4.37, 4.38, 4.41, 4.46. Chưa làm: 4.4 đến 4.12 (học bằng LLM qua Codie), 4.18 (giao diện hỏi người dùng về bước tuỳ chọn; hiện learner tự quyết định và báo ở phần cảnh báo), 4.20 đến 4.30 (trace nhiều nguồn, độ phủ, hộp thoại `alert`/`confirm`/modal, applet, chạy thử khô trên UAT, role/location), 4.34 (pick «chỗ cần xem»), 4.36 (liên kết dữ liệu A sang B tự động). Mọi task chạm phần IE chạy test trên IE thật ở chế độ tài liệu 5 (`tests/test_ie_real.py`).

**Nghiệm thu Gate 4:** từ ba phiên ghi có nhiễu, trợ lý dựng được workflow đúng và GDV duyệt được; không có Codie thì vẫn học được bằng luật và được báo rõ; không có dữ liệu chưa che nào đi vào lời nhắc.

## Gate 5: Trợ lý (gõ một câu, chạy đúng agent đã duyệt)

Thiết kế: `docs/assistant-design.md`. Người Duyệt vẫn là người bấm; Trợ lý không tự chạy, không đổi `risk`/`mode`.

| # | Task | Trạng thái |
|---|---|---|
| 5.1 | Schema `plan-request`/`plan-reply` v1 và mẫu | Chưa làm (hiện kiểm bằng `assistant.check_request`/`check_plan_reply`) |
| 5.2 | `assistant/catalog.py` | Xong (`tests/test_assistant.py`) |
| 5.3 | `assistant/mask.py` | Xong |
| 5.4 | `plan_request` trên `LLMClient`, `RuleBasedClient` | Một phần: chấm điểm luật nằm ở `server/app/assistant.py`; chưa thêm vào interface `LLMClient` |
| 5.5 | `POST /assistant/plan`, kiểm câu trả lời, rơi về luật | Xong với luật; chưa có client mô hình thật (`app.state.assistant_client`) |
| 5.6 | `assistant/habits.py` | Xong (đếm tên và số lần; chưa có thống kê từ khoá) |
| 5.7 | `assistant/planner.py` (5 trạng thái) | Xong |
| 5.8 | `Core.assistant_*`, route, audit thêm `via`, `input_names` | Xong |
| 5.9 | Tab «Trợ lý» | Xong (JS chỉ kiểm cú pháp, chưa mở trong trình duyệt) |
| 5.10 | Chạy trọn trên IE thật | Một phần: luồng đọc chạy từ một câu trong test chuỗi đầy đủ; chưa có luồng tiền và bộ 20 câu mẫu |
| 5.11 | Đóng gói, `docs/design.md` | Đóng gói xong; chưa cập nhật `docs/design.md` |

## Gate 6: giao diện đổi không phải học lại, nhận lệnh từ chứng từ

Thiết kế: `docs/design.md` mục 6.1 và 6.2. Không đổi quy tắc cứng: bước `write` luôn `approve`, `money` không bao giờ `auto`, người kiểm soát luôn tự bấm Duyệt.

| # | Task | Tiêu chí nghiệm thu |
|---|---|---|
| 6.1 | Runner IE chọn phần tử theo điểm bằng chứng nhiều dấu hiệu (dùng 2.15), có ngưỡng và khoảng cách với ứng viên thứ hai | Test IE thật: đổi id của ô trên trang mẫu, nhãn giữ nguyên thì vẫn chạy đúng; hai ô cùng nhãn thì dừng và hỏi. **Xong**: lệnh `locate` của cầu nối, `IeDriver._target`, thao tác qua `src=N`; ngưỡng `write` cho thao tác, `read` cho đọc (driver chưa biết `risk` của bước); `tests/test_ie_real.py` 5/8/9 |
| 6.2 | Khi không tìm thấy: khoanh tối đa 3 ứng viên trong trang, hỏi GDV trên trang quản lý | Test: viền hiện đúng ô, không có thao tác nào lên trang; chọn «Không có» thì dừng. **Xong**: `suggest`/`mark`/`unmark` (tô bằng runtimeStyle, không đổi style của trang), câu hỏi «Có phải ô này?» trong thẻ chạy; `tests/test_repair.py`, test IE thật 5/8/9 |
| 6.3 | Lưu lựa chọn thành version mới của agent (chỉ đổi `target`), chờ Duyệt lại; trước khi Duyệt chỉ người chọn chạy được, chỉ bước `read` | Test server: version tăng, `risk`/`mode` không đổi, có audit; bước `write` bị chặn khi chưa Duyệt. **Xong** (lưu ở kho trên máy, `flows[].repair`; chưa đẩy lên máy chủ): version +1, chỉ đổi `selectors`, audit `mode=repair`; «Duyệt bản sửa» thay bản cũ |
| 6.4 | Dấu vân tay màn hình lúc Học; so trước khi Chạy, lệch thì báo và đề nghị Chạy thử | Test: thêm/bớt ô trên trang mẫu thì báo «Màn hình đã đổi»; không có giá trị nhập trong dấu vân tay. **Xong, khác thiết kế một chút**: dấu vân tay ghi ở lần Chạy thật xong đầu tiên (lúc Học thường không mở màn đầu); lệch thì báo, bấm Chạy lần nữa mới chạy; Chạy thử ghi chú «Màn hình đã đổi» |
| 6.5 | Request đã ghi làm dấu hiệu phụ cho bước `read` | Test: có lời gọi cùng hình dạng thì độ tin cậy tăng; không có lời gọi nào được agent tự gửi. **Hoãn**: lúc chạy bộ ghi yêu cầu cố ý tắt (`__rkNoXhr`, để không đụng TouchPoint) và Learner chưa giữ hình dạng request theo bước; cần quyết định trước khi làm |
| 6.6 | Mẫu UNC giả lập (ảnh và nội dung chuẩn) trong `mock-site/` | Ít nhất 5 mẫu, có 1 mẫu số tiền bằng số và bằng chữ lệch nhau. **Xong** (để ở `windows-agent/rookie_agent/voucher/samples/` để đi cùng gói, không ở `mock-site/`) |
| 6.7 | Interface `DocReader`, bản offline đọc từ mẫu; tách các trường của mục 6.2 kèm độ tin cậy, kiểm số tiền số/chữ | Test: 5 mẫu tách đúng; mẫu lệch bị đánh dấu. **Xong**: `voucher/reader.py` (`SampleReader`), `voucher/extract.py`; `tests/test_voucher.py` |
| 6.8 | Màn soát chứng từ trong tab Trợ lý: ảnh cạnh từng trường, sửa/xác nhận, chặn khi trường dưới ngưỡng | Test webui: chưa xác nhận thì không có nút Chạy; ảnh và giá trị không vào trace/audit. **Xong**: mục «Đưa chứng từ vào» ở tab Trợ lý; phải đánh dấu «đã soát từng trường»; `tests/test_voucher_run.py` |
| 6.9 | Nối chứng từ đã xác nhận vào Trợ lý và Runner (luồng chuyển tiền trên mock) | Chạy trọn trên mock: dừng ở bước `money` chờ người kiểm soát; audit chỉ có tên trường và người xác nhận. **Xong** trên mock giả (test); chưa chạy trên IE thật với luồng chuyển tiền đã học |

## Gate 7: chạy mô phỏng bằng request trong sơ đồ

Thiết kế: `docs/design.md` mục 6.3. Chỉ bước `read` được gửi; request đi trong phiên của chính trang IE của GDV; dữ liệu trả về chỉ hiện trên máy GDV.

| # | Task | Tiêu chí nghiệm thu |
|---|---|---|
| 7.1 | Lưu request mẫu cùng bản ghi, giá trị đã gõ thay bằng dấu sự kiện | Test: giá trị gõ và mật khẩu không có trong file; request có `***` hoặc bị cắt thì `complete=false`. **Xong**: `replay.templates`, bộ ghi trong trang giữ header và cờ `cut`; `tests/test_replay.py`, `test_webui.py` |
| 7.2 | Gắn request vào bước khi Học | Test: request thuộc đúng bước, dấu thành `⟦tham_số⟧` hoặc chữ cố định, request lúc tải trang bị bỏ. **Xong**: `replay.attach`, `flows[].requests` |
| 7.3 | Lệnh `send` của bridge: gửi từ đúng frame trong phiên của trang | Test IE thật: cookie trang đi theo, header được đặt, không có gì trên màn hình đổi; frame không có thì `no_frame`. **Xong**: `send`/`sendres` trong `page_recorder.js`, `IeBridge.send` |
| 7.4 | Rút gọn dữ liệu trả về | Test: JSON, GWT (bỏ tên lớp Java), HTML. **Xong**: `ie/response_view.py` |
| 7.5 | Nút «Chạy mô phỏng», sơ đồ sáng theo bước, khung chi tiết 4 phần | Test: request đi với giá trị mới; bước ghi có request thì dừng, không gửi; `//EX` thì dừng hỏi; audit không có giá trị. **Xong**: `replay.simulate`, `Core._simulate_start`, `run_status.details` |
| 7.6 | Tài liệu và đóng gói | **Xong**. Chưa thử trên TouchPoint UAT; mã chống giả và giá trị nối giữa các bước để sau (làm ở Gate 8) |

## Gate 8: luồng theo API (mỗi nút = một lời gọi API)

Thiết kế: `docs/design.md` mục 6.4. Nút «Chạy» ở tab «Luồng đã học» chạy luồng API; chạy trên giao diện IE nằm ở mục phụ.

| # | Task | Tiêu chí nghiệm thu |
|---|---|---|
| 8.1 | Ghi form gửi thật và trang tải trong khung | Test IE thật: form gửi vào iframe được ghi là POST với các ô, ô mật khẩu là `***`. **Xong**: dòng `form` (sau cú bấm, hoặc lúc rời trang) và `nav` trong `page_recorder.js`, ghép trong `session.py` |
| 8.2 | Giữ API lúc mở màn hình, bỏ polling | Test: API trước thao tác đầu là «Mở màn hình»; lặp ≥3 lần bị bỏ. **Xong**: `replay.build_api` |
| 8.3 | Tìm dữ liệu nối giữa các API | Test: token JSON và mã trong bảng chuỗi GWT thành liên kết; token không rõ nguồn bị che; không giá trị nào vào file. **Xong**: `replay.templates`, `locate_value`/`take_value` |
| 8.4 | Học thành nút API | Test: nút theo thứ tự, tên theo thao tác, tham số `⟦cif⟧`. **Xong**: `flows[].api`, `api_nodes` ở danh sách luồng |
| 8.5 | Chạy theo nút API trên sơ đồ | Test IE thật 8/9/5: ghi 3 API (mở màn hình lấy token, tìm dùng token + CIF, form chi tiết dùng mã KH vừa trả về), học từ 1 bản ghi, chạy với CIF khác: đúng giá trị mới đi ở mọi API, màn hình không đổi. **Xong**: `replay.run_api`, sơ đồ vẽ nút API |
| 8.6 | Tài liệu, đóng gói | **Xong**. Chưa thử trên TouchPoint UAT |
| 8.7 | Bộ nhớ phiên cho tra cứu; Trợ lý chạy tra cứu bằng API | Test: cùng khách lần hai không gọi máy chủ, «Làm mới» và khách khác thì gọi; xoá khi đóng tab, trang đăng nhập, nút xoá, hết hạn; lần chạy dừng ở nút ghi không được nhớ; audit không có giá trị; Trợ lý chọn chạy API chỉ khi mọi nút là `read`. **Xong**: `Core._cache*`, `/api/cache`, `/api/cache/clear`, nút «Làm mới», «Xoá bộ nhớ phiên»; `tests/test_replay.py`. Bộ ghi: dòng `nav`/`form` có `uid` (test đăng nhập khung lồng nhau đạt lại ở 5/8/9) |

## Gate 9: bản sao quy trình (Process Digital Twin)

Quy trình đầu cuối nhiều vai trò: GDV tra CIF và lập lệnh chuyển tiền, sau đó KSV duyệt. Bản sao dùng cho bốn việc: chạy thử không đụng hệ thống thật, nhìn quy trình thật, đo và tìm điểm nghẽn, thử «nếu… thì…». Thiết kế ở `docs/design.md` mục 12.

| Task | Nội dung | Tiêu chí nghiệm thu |
| --- | --- | --- |
| 9.1 | Nhật ký quy trình | Test: dựng dòng nhật ký (ca, bước, vai trò, thời điểm, kết quả, độ trễ API) từ phiên mẫu; nối ca maker/checker bằng mã băm. Không có mã người, không có giá trị. Sự kiện `schema_version` 3 có `api_calls[].ms` cho ie. **Xong** |
| 9.2 | Khám phá quy trình, mô hình đầu cuối | Test: sơ đồ «bước nào theo sau bước nào», biến thể có số ca và tỉ lệ đúng; mô hình quy trình (`schemas/process.schema.json`) có version; gợi ý thứ tự chặng. **Xong** |
| 9.3 | Đo và tìm điểm nghẽn | Test: thời gian xử lý, thời gian chờ, làm lại, lỗi, độ trễ API đúng trên dữ liệu có đáp án; dưới 5 ca thì ẩn số; điểm nghẽn đúng. **Xong** |
| 9.4 | Chạy thử trên bản sao | Test: khung trả lời không còn giá trị gốc (JSON, GWT, HTML); chạy đầu cuối trên bản sao qua các nút nối nhau, dừng chờ Duyệt ở nút ghi/tiền và chặng KSV; không request nào ra ngoài. **Xong** |
| 9.5 | Mô phỏng «nếu… thì…» | Test: cùng seed thì cùng kết quả; thêm 1 KSV thì giảm chờ duyệt; bỏ một bước thì thời gian ca giảm tương ứng; lời giải thích qua `LLMClient` (`RuleBasedClient` chạy offline). **Xong** |
| 9.6 | Trang «Bản sao quy trình», cả quy trình thành một luồng kiểu n8n | Nút «Dựng quy trình từ các lần ghi» ghép chặng maker và checker thành một sơ đồ: nút API, Bàn giao, Duyệt, nhánh theo biến thể. Cùng sơ đồ đó dùng cho số đo, chạy thử và nếu… thì…. «Xuất JSON kiểu n8n» là file trên máy, test chứng minh không có giá trị gốc. Chữ tiếng Việt. **Xong** |
| 9.7 | Dữ liệu demo, tài liệu, đóng gói | `scripts/twin_seed.py` sinh ca synthetic; tài liệu; gói `patch-ie.7z`. **Xong**. Test IE thật đạt ở 5/8/9; trang chưa mở bằng trình duyệt (chỉ kiểm cú pháp JS); chưa thử trên UAT |

## Gate 10: trang quản trị luồng kiểu n8n trên máy chủ

Mỗi người thấy luồng của mình và luồng được chia sẻ cho mình; vai trò quản trị thấy hết. Đăng nhập bằng AD. Sửa luồng trên canvas như n8n. Chạy vẫn chỉ ở máy GDV, trong phiên của GDV (quy tắc 4): trang quản trị không chạy và không Duyệt hộ bước của lần chạy. Mỗi lần sửa thành version `draft`; `risk` do luật gán lại, chỉ nâng không hạ; người sửa không tự duyệt bản mình sửa; mẫu không chứa giá trị. Thiết kế ở `docs/design.md` mục 13.

| Task | Nội dung | Tiêu chí nghiệm thu |
| --- | --- | --- |
| 10.1 | Định danh và vai trò | `ROOKIE_AUTH=off` (mặc định, như trước), `dev` (người cố định trong `config/roles.json`), `ldap` (AD; vai trò theo nhóm AD). Test: không đăng nhập thì 401 tiếng Việt; sai mật khẩu không nói sai phần nào; 5 lần sai khoá 10 phút; token hết hạn và đăng xuất; server chỉ giữ SHA-256 của token, không giữ mật khẩu; AD: vai trò theo nhóm, không thuộc nhóm thì từ chối, mật khẩu rỗng không gửi, tên lạ không vào câu tìm. Agent: «Đăng nhập máy chủ» ở trang `:8765`, chỉ giữ token, nhật ký «Gửi và nhận» không hiện mật khẩu hay token. **Xong** |
| 10.2 | Chủ luồng, quyền xem, chia sẻ, sao chép | Test: chủ luồng là người Học; mỗi người chỉ thấy luồng của mình và luồng chia sẻ cho đơn vị mình, quản trị thấy hết; chia sẻ có xem trước (bước, nhãn, tên tham số), chỉ chủ luồng chia sẻ được; clone thuộc người clone, bản gốc không đổi; luồng cũ «Chưa rõ chủ», quản trị gán chủ. **Xong**: `app/auth/access.py`, `workflow_meta`, `/share-preview`, `/share`, `/clone`, `/owner`; bản ghi có chủ |
| 10.3 | Nút API lên server | `schemas/api-nodes.schema.json`. Test: lúc Học gửi nút theo danh sách trường được phép (không `answer`, `shape`); server từ chối mẫu có giá trị nhạy cảm; digest tính trên cả luồng và nút; bản đã duyệt trả cả nút. **Xong**: ie/api_share.py che đoạn giống dữ liệu (≥3 chữ số, khoảng trắng, dấu tiếng Việt, >40 ký tự) thành •••, liên kết theo chữ xung quanh không mang chữ đó; pp/api_nodes.py kiểm cùng luật; pi_digest riêng, digest vẫn của workflow; nút đã che không sửa mẫu được trên máy chủ |
| 10.4 | API sửa luồng | Test: di chuyển, xoá, đổi thứ tự, thêm nút HTTP, sửa mẫu, đổi nhãn, thêm nút Duyệt, nâng mode; hạ rủi ro bị từ chối; url chuyển tiền thành `money`; xoá nút nguồn của liên kết bị từ chối; mẫu có số tài khoản bị từ chối; người sửa tự duyệt bị 409. **Xong**: pp/edit.py (hàm thuần, kiểm lại mọi luật), POST /workflows/{id}/versions/{v}/edit, bố cục PUT /workflows/{id}/layout (không tạo version), luật pi trong config/risk-rules.json (rủi ro là mức cao hơn của địa chỉ và nhãn); nút Duyệt là nâng mode của nút thành approve. Khi tắt đăng nhập (một máy) không áp luật hai người |
| 10.5 | Nhật ký chạy lên server | Test: dòng audit gửi lên (gửi lỗi thì giữ lại gửi sau); lịch sử chạy theo luồng: ai chạy, version, từng nút, ai Duyệt; không giá trị nào lọt qua. **Xong**: `POST /runs` (theo `run_id`, gửi lại không trùng), `GET /workflows/{id}/runs`, `GET /runs/summary`; agent ghi `run_id`, `workflow_id`, `version` vào dòng audit và gửi sau mỗi lần chạy (`Core._send_runs`): chỉ id bước, trạng thái và quyết định Duyệt, không gửi chữ chi tiết của bước |
| 10.6 | Trang quản trị `/admin` | JS thuần, SVG, không CDN. Đăng nhập; danh sách luồng có lọc; canvas kéo thả, thêm và xoá nút, bảng thuộc tính, Lưu thành bản nháp; lịch sử version và so sánh; lịch sử chạy; chia sẻ và clone. Chữ tiếng Việt. **Xong**: `server/app/admin/` (index.html, admin.css, admin.js) phục vụ ở `/admin`; mỗi thay đổi gửi `POST …/edit/preview` để canvas luôn hiện đúng điều máy chủ kiểm; danh sách có `max_risk`. Đã mở bằng Chromium (Playwright): đăng nhập, sơ đồ, thêm nút, lưu nháp, so sánh, lần chạy, chia sẻ, màn hình hẹp |
| 10.7 | Đồng bộ về máy GDV | Test: tab Luồng báo «Có bản mới», xem khác biệt, «Dùng bản này»; chưa bấm thì vẫn chạy bản cũ; mất kết nối thì chạy bản đang có; audit ghi version. **Xong**: `GET /api/flows/updates`, `POST /api/flows/update/try` (bản nháp chạy trên bản sao, không thay bản đang dùng; xong thì báo máy chủ và chuyển «đã chạy thử»), `POST /api/flows/update/take` (chỉ bản đã Duyệt; kiểm cả hai digest); `api_share.merge` giữ mẫu đầy đủ của máy này theo id nút; nút đặt Duyệt trên trang quản trị hỏi người cả khi chạy thật; nút thêm trên máy chủ thì bản sao trả lời rỗng |
| 10.8 | Test đầu cuối, tài liệu, đóng gói | Playwright cho `/admin`: đăng nhập, sửa, lưu nháp, người khác duyệt. `docs/design.md` mục 13, `CLAUDE.md`, wheel `ldap3`, gói mới. **Xong**: `tests/e2e/specs/admin.spec.ts` (máy chủ thứ hai cổng 8002, `ROOKIE_AUTH=dev`); mục 13 trong `docs/design.md`; `ldap3` trong `requirements-run.txt`; `package-patch-ie.ps1` mang cả `.html`, `.js`, `.css` của `server/app` (trang quản trị). Chưa thử với AD thật (chỉ thư mục giả) |

## Gate 11: hoàn thiện theo định hướng thi, Ghi và Học chắc chắn tổng thể

Định hướng thi (Digital Process Twin, ba giai đoạn Học, Xây bản sao số, Thực hiện bằng tiếng Việt). Ghi và Học được làm chắc bằng một hệ thống giả lập có đủ các mẫu khó của TouchPoint và một ma trận Ghi → Học → Chạy trên IE thật, thay cho việc sửa từng lỗi khi gặp. Cài đặt tạm giữ như hiện tại (zip).

| Task | Nội dung | Tiêu chí nghiệm thu |
| --- | --- | --- |
| 11.1 | TouchPoint giả lập trên IE (`mock-site/touchpoint.py`, phục vụ ở `/tp/`) | Đăng nhập, frameset, getToken rồi TPClassLoader có Bearer (chỉ token mới nhất), thân GWT-RPC và trả lời kiểu GWT thật (số trỏ vào bảng chuỗi), tra tài khoản bằng Enter hoặc nút, lịch sử theo ngày, tick dòng, «IN BÁO NỢ/CÓ» mở hộp thoại tự gửi form lấy PDF, «XUẤT SAO KÊ» bằng `window.open`, «TẢI EXCEL» bằng form vào khung ẩn, hộp thông báo khi bấm sai, `keepalive` định kỳ, lập lệnh chuyển tiền và màn hình duyệt của KSV. Dữ liệu tự sinh. `mock-site/tests/test_touchpoint.py`. **Xong** |
| 11.2 | Ma trận trên IE thật (`windows-agent/tests/test_ie_matrix.py`) | Mỗi kịch bản: ghi hai lần với dữ liệu khác (có nhiễu: Enter thay nút, ngày sai và hộp thông báo), Học, chạy bằng yêu cầu với dữ liệu mới, so lời gọi máy chủ giả lập nhận được. 4 kịch bản (In báo nợ/có trong hộp thoại, sao kê `window.open`, Excel vào khung ẩn, lập lệnh tiền dừng chờ Duyệt và không bao giờ gửi bằng yêu cầu) **qua ở chế độ 8 và 9**, chạy lặp 3 lượt không lỗi. `scripts/run-ie-matrix.ps1` |
| 11.3 | Bản ghi tự kiểm tra (`ie/check.py`) | Sau «Dừng ghi»: dùng được, đáng biết, hay cần ghi lại, bằng chữ dễ hiểu và chỉ chỗ (lời gọi lỗi, mã bảo mật không rõ nguồn, file đoán, hộp thông báo, bấm nhầm, không thao tác nào gọi hệ thống, phần trang không đọc được). `tests/test_check.py`. **Xong** |
| 11.4 | Làm sạch có luật (`ie/clean.py`) | Luật 0 trang tự hỏi định kỳ (kể cả có thời gian trong địa chỉ); luật 2 hộp thông báo và bấm nhầm; luật 1 cùng tác dụng là cùng bước (Enter thay nút). Đánh số lại sự kiện, `after_seq` và dấu `⟦eN⟧`. Kèm ba sửa lỗi tổng thể ma trận tìm ra: giá trị đã nhập không thay vào giữa một hằng số (strong name GWT); request gửi trước cú bấm vài trăm mili giây thuộc về cú bấm đó (Enter); form trang tự gửi vào khung (cả lúc trang vừa mở, câu trả lời là file tải về) được ghi. `tests/test_clean.py`. **Xong**. Còn thiếu: báo cáo chất lượng và tự chạy thử bản sao ngay sau Học |
| 11.5 | Màn hình chính cho GDV | Đã có: «Sửa trên sơ đồ», «Chia sẻ» mở trang quản trị đúng quy trình và tự đăng nhập bằng mã dùng một lần 60 giây (`/auth/handoff`, `/auth/exchange`). Còn lại: sắp lại trang theo việc (Trợ lý, Việc hay làm, Dạy việc mới, Nâng cao) |
| 11.6 | Gợi ý theo màn hình | Chưa làm |
| 11.7 | Dùng quy trình được chia sẻ ở máy khác | `GET /api/flows/shared`, `POST /api/flows/import`, «Làm mẫu một lần để dùng» (`POST /api/flows/bind`, `api_share.bind`: ghép theo tác dụng và thứ tự, mẫu đầy đủ của máy này, cấu trúc và Duyệt giữ nguyên, nút không khớp thì báo). **Xong** (chưa thử trên IE thật) |
| 11.8 | Đo thời gian tiết kiệm | Trung vị làm tay (bản ghi) và trợ lý (lần chạy xong), dưới 3 lần mỗi bên thì không hiện số; thẻ quy trình và trang quản trị (`/runs/summary`). **Xong** |
| 11.9 | MCP cho Genie Codie (`python -m rookie_agent mcp`) | 5 tool, không có tool Duyệt, không trả giá trị, `idempotency_key`, timeout tổng rồi Dừng khẩn, vai trò maker/checker, audit qua `/api/mcp/audit`, stdio hoặc HTTP có token và danh sách địa chỉ. `tests/test_mcp.py`. **Xong** |
| 11.11 | Bản in dựng từ dữ liệu trả về (màn hình điền từ XML/GWT) | `ie/report.py`: học nhãn và luật lúc Ghi, dựng `(bản in).html` lúc Chạy; kèm SOAP, loại file theo byte. `tests/test_report.py`, `tests/test_soap.py`, ma trận IE 8/9 (`btnPrintData`). **Xong** (chưa thử trên TouchPoint thật) |
| 11.10 | Slide, tài liệu, đóng gói | Slide: «Tình huống lạ» thay «Điều kiện», bỏ Java ở slide Bài toán, thêm trang «Gọi quy trình ở đâu». Còn lại: tài liệu, đóng gói |

## Phần để sau PoC

- Lắng nghe điều hướng của trình duyệt (`BeforeNavigate2`) từ cầu nối, để bắt mọi form và tải file kể cả trong hộp thoại modal; cần một luồng có vòng thông điệp riêng.

- Đánh giá độ chính xác của LLM nội bộ (Learner, giải thích lệch, self-healing) trên bộ mẫu; self-healing bằng ảnh nếu model nhận được ảnh.
- Quy trình thật đầu tiên (đối chiếu cuối ngày, hành trình chuyển tiền ngoại tệ) và kết nối hệ thống thật.
- Hướng B: self-healing bằng ảnh và LLM; Java agent dự phòng (`AWTEventListener`) nếu spike 1.7 cho thấy Java Access Bridge không đủ; kiểm thử trên applet thật trong IE mode; đóng gói Windows agent bằng C#/.NET.
- Nhánh có điều kiện trong workflow (ví dụ CIF đã tồn tại hay chưa).
- Ứng dụng desktop khác (không phải web, không phải Java).
