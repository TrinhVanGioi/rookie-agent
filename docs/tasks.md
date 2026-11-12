# Danh sách việc theo cổng (Gate)

Làm lần lượt từng task, mỗi task một commit nhỏ. Mỗi task có tiêu chí nghiệm thu kiểm chứng được: viết test trước, code cho test qua. Chỉ sang Gate sau khi toàn bộ nghiệm thu của Gate trước đã qua. Thiết kế chi tiết ở `docs/design.md`; quy tắc cứng ở `CLAUDE.md`.

Công nghệ đề xuất (đổi được nếu có lý do, nhưng phải cập nhật `CLAUDE.md`): extension bằng TypeScript và Manifest V3, server bằng Python (FastAPI, Pydantic, SQLite, pytest), test e2e bằng Playwright.

## Gate 1: ghi được (tuần 1)

| Task | Việc | Nghiệm thu |
| --- | --- | --- |
| 1.1 | Khởi tạo repo theo cấu trúc trong `CLAUDE.md`, cấu hình build và test cho `extension/`, `server/`, `mock-site/`, `tests/e2e/` | Bốn lệnh trong `CLAUDE.md` chạy được và test mẫu qua |
| 1.2 | Mock site: đăng nhập, Báo cáo A, Báo cáo B, lọc theo ngày, bảng kết quả. Dữ liệu synthetic sinh theo seed, có dòng lệch cố ý (lệch số, thiếu dòng, lệch do làm tròn). Công tắc "giao diện mới" đổi id, tên nút và vị trí | Test xác nhận cùng ngày và seed cho cùng dữ liệu; các dòng lệch cố ý tìm được bằng một hàm tham chiếu; bật công tắc thì id đổi |
| 1.3 | JSON Schema cho event và workflow trong `schemas/` theo `docs/design.md` mục 4, kèm hàm validate ở cả extension và server | Test có mẫu hợp lệ qua và mẫu sai (thiếu trường, `risk` sai giá trị) bị từ chối |
| 1.4 | Khung extension MV3: manifest, service worker, content script, side panel có nút Bắt đầu ghi / Dừng, biểu tượng đang ghi | Nạp được extension vào Chromium bằng Playwright; bấm Bắt đầu thì hiện trạng thái đang ghi |
| 1.5 | Recorder: bắt click, input, select, navigate; lưu nhiều selector dự phòng; loại id sinh ngẫu nhiên; phân loại trường (bỏ qua, nhạy cảm, không nhạy cảm); che PII; xử lý trang đổi nội dung không đổi URL | Test đơn vị cho phân loại trường và che PII; thao tác trên mock site cho ra event đúng schema; không có giá trị mật khẩu, số tài khoản nào trong event (test tìm chuỗi) |
| 1.6 | API nhận phiên ghi: `POST /sessions`, `GET /sessions/{id}`, lưu SQLite, kiểm tra schema | Test API với event hợp lệ và không hợp lệ; extension gửi được phiên lên server chạy local |

**Nghiệm thu Gate 1 (e2e):** mở extension, thao tác 3 lần trên mock site với 3 ngày khác nhau, server có đúng 3 phiên, đều qua validate schema, và không chứa giá trị nhạy cảm.

## Gate 2: chạy lại đúng (tuần 2)

| Task | Việc | Nghiệm thu |
| --- | --- | --- |
| 2.1 | Interface `LLMClient` và `RuleBasedClient` chạy offline | Test dùng `RuleBasedClient`, không cần mạng |
| 2.2 | Learner dạng luật: chuẩn hoá, căn chỉnh các phiên, nhận tham số, gán `risk` bằng luật, sinh workflow đúng schema | Từ 3 phiên ghi mẫu (fixture) sinh ra workflow có tham số `ngay`; phiên chỉ có 1 giá trị ngày vẫn sinh được nhưng có cảnh báo; bước gọi API ghi được gắn `write` |
| 2.3 | API workflow: lưu version, trạng thái `draft` / `tested` / `approved`, lấy bản đã duyệt mới nhất | Test chuyển trạng thái hợp lệ và chặn chuyển trạng thái sai; không phát được bản chưa `approved` |
| 2.4 | Sandbox ở server: chạy thử workflow bằng Playwright trên mock site | Workflow `draft` chạy thử được và trả kết quả; chạy thử xong mới cho phép chuyển sang `tested` |
| 2.5 | Runner trong extension: kéo workflow đã duyệt, kiểm tra version và chữ ký, giữ bản sao; thực thi các action; tìm phần tử theo thứ tự selector | Chạy workflow học từ 3 phiên với một ngày chưa từng ghi cho ra đúng bảng như thao tác tay |
| 2.6 | Chế độ kiểm soát `auto` / `review` / `approve` trên side panel, nút Dừng khẩn, quy tắc cứng cho `write` và `money` | Bước `approve` luôn dừng chờ duyệt; không đặt được `auto` cho bước `money`; Dừng khẩn dừng ngay bước đang chạy |
| 2.7 | Điều khiển tập trung: Runner kéo chính sách định kỳ; lệnh khoá agent | Khoá agent trên server thì Runner dừng ở bước kế tiếp và báo lý do |

**Nghiệm thu Gate 2 (e2e):** workflow học từ 3 phiên chạy đúng với ngày chưa từng ghi; bước `write` luôn dừng chờ duyệt; khoá từ xa dừng agent ở bước kế tiếp.

## Gate 3: demo đủ kịch bản (tuần 3)

| Task | Việc | Nghiệm thu |
| --- | --- | --- |
| 3.1 | Bước đối chiếu chạy trong Runner: ghép theo khoá, tìm lệch số và dòng thiếu, ngưỡng bỏ qua nhập bằng tham số, xuất bảng lệch | Với dữ liệu mock, tìm đúng toàn bộ dòng lệch cố ý; lệch dưới ngưỡng được đánh dấu bỏ qua |
| 3.2 | Giải thích lệch qua `LLMClient.explain(rows)` chỉ nhận dòng lệch đã che; `RuleBasedClient` trả nguyên nhân theo luật | Test xác nhận dữ liệu gửi vào `explain` không chứa giá trị nhạy cảm chưa che |
| 3.3 | Self-healing: selector dự phòng, rồi `LLMClient.locate(screenshot, description)`, ngưỡng tin cậy, dừng và hỏi GDV; đề xuất cập nhật workflow | Bật "giao diện mới" thì workflow vẫn chạy xong; độ tin cậy thấp thì dừng; chấp nhận đề xuất thì workflow lên version mới |
| 3.4 | Kho agent: version, điểm (tỷ lệ chạy đúng, số bước sửa tay, thời gian tiết kiệm), clone, phạm vi chia sẻ riêng tư / nhóm / đơn vị | Người dùng thứ hai clone agent và sửa rule mà bản gốc không đổi; agent riêng tư không hiện với người khác |
| 3.5 | Audit: log từng bước kèm ảnh đã che; đệm khi mất kết nối và đẩy lên khi có mạng; dashboard xem log | Ngắt kết nối giữa chừng thì log được đệm rồi đẩy đủ khi có lại; dashboard hiện đúng người chạy, version, kết quả |
| 3.6 | Kịch bản demo 7 bước (`docs/design.md` mục 10) và script đo bốn chỉ số (mục 11) | Script chạy hết kịch bản và in bốn chỉ số |

**Nghiệm thu Gate 3 (e2e):** 7 bước của kịch bản demo chạy được liền mạch, kèm số đo thời gian và độ đúng.

## Phần để sau PoC

- `LLMClient` thật (LLM đặt trong vùng mạng nội bộ); đánh giá độ chính xác của Learner và self-healing bằng LLM.
- Quy trình thật đầu tiên (đối chiếu cuối ngày, hành trình chuyển tiền ngoại tệ) và kết nối hệ thống thật.
- Ứng dụng không phải web.
