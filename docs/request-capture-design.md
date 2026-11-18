# Ghi nhận request/response của trang IE mà không ảnh hưởng trang

Phạm vi: recorder hướng B2 (`windows-agent/rookie_agent/ie/`), trang TouchPoint (GWT, chế độ tài liệu 5). Đây là bản thiết kế, chưa sửa code.
Chỉ dựa trên `page_recorder.js` (dòng 229-311), `ie-bridge.ps1` (Inject, Collect, start) và quy tắc cứng. Chưa đọc `test_ie_real.py` nên tên fixture bên dưới là dự kiến.

## 1. Hiện trạng và nguyên nhân nghi ngờ

Stand-in hiện tại là một object thường, sao chép `readyState/status/responseText` mỗi lần `onreadystatechange`. Chưa có nội dung lỗi thật nên dưới đây là giả thuyết, phải kiểm bằng test đối chứng (task 1):

1. Thiếu thành viên: `responseBody`, `responseStream`, `onprogress`... Trang đọc ra `undefined` rồi gọi tiếp thì lỗi "undefined".
2. Sai ngữ nghĩa ném lỗi: đối tượng thật ném lỗi khi đọc `status` trước `readyState 4`; stand-in trả 0. Code GWT dựa vào `try/catch` sẽ rẽ nhánh khác.
3. `window.ActiveXObject` mới bỏ tham số thứ hai (`new ActiveXObject(id, server)`), mất `prototype`, và `typeof` phương thức đổi từ `"unknown"` thành `"function"`.
4. Handler của trang được gọi với `this` là stand-in, không có `onload` cho request đồng bộ, `abort()` không báo lại trạng thái như thật.
5. Hook được cài giữa chừng (vòng poll 0,15 s): một phần code trang giữ constructor cũ, phần khác giữ constructor mới.
6. `window.__rkq` cộng chuỗi tới 600 KB, mỗi response tới 20 KB: chậm trong IE, có thể gây cảnh báo "script chạy lâu".

Rủi ro quy tắc cứng 1 (chưa kiểm chứng phần che phía sau): `req` ghi nguyên 4000 ký tự đầu của body, nên request đăng nhập có thể chứa mật khẩu/OTP. Thiết kế mới bắt buộc xoá ngay trong trang mọi giá trị trùng với giá trị đang có của phần tử `isSecret`, và mọi khoá tên kiểu `password|pwd|otp|pin`, trước khi đưa vào hàng đợi.

## 2. Các phương án

| # | Phương án | Bắt được | Rủi ro hỏng trang | Quyền | Offline, không cài | Độ phức tạp |
|---|---|---|---|---|---|---|
| a1 | Stand-in JS "gương" làm kỹ hơn | method, url, header, status, body gửi và nhận | Trung bình: chế độ 5 không có getter (`Object.defineProperty` không dùng được cho object thường) nên thuộc tính vẫn là bản sao, không "sống" | Không | Có | Thấp |
| a2 | Stand-in là **lớp VBScript** (`Class` có `Property Get/Let/Set`, tiêm bằng `execScript(code, "VBScript")`) | Như a1 | Thấp nếu chạy được: getter sống thật, ném lỗi y như đối tượng thật, cũng không nhận expando giống ActiveX thật | Không | Có, nếu VBScript không bị chính sách tắt ở zone của TouchPoint | Trung bình |
| b1 | Proxy cục bộ | Tất cả, kể cả request lúc tải; HTTPS thì không (cần cài CA gốc) | Cao: WinINet không có proxy theo tiến trình từ bên ngoài (`INTERNET_OPTION_PROXY` theo tiến trình chỉ gọi được từ trong iexplore; per-connection là theo kết nối LAN, không theo tiến trình). Đổi proxy HKCU ảnh hưởng mọi ứng dụng, có thể đổi zone Intranet và kéo theo đổi chế độ tài liệu | Không cần admin, nhưng GPO thường khoá | Có | Trung bình |
| b2 | Event COM `DWebBrowserEvents2` | Chỉ điều hướng trang và frame: URL, mã lỗi (`NavigateError`), mốc thời gian. Không thấy XHR, không có body response | Gần như không (không chạm JS trang); event đồng bộ nên handler phải rất nhanh | Không | Có (C# qua `Add-Type`) | Trung bình |
| b3 | ETW `Microsoft-Windows-WinINet` (và `-Capture`) | URL, header, status; provider Capture có cả payload | Không | **Cần admin** để mở phiên trace | Có | Trung bình |
| b4 | WinINet status callback, WinHTTP trace | Không dùng được: callback chỉ gắn trên handle của chính tiến trình; IE không đi qua WinHTTP | - | - | - | - |
| b5 | Kiểu Fiddler không cài | Chính là b1 | Như b1 | | | |
| b6 | Enhanced Protected Mode | Không phải cách bắt; nếu bật thì còn chặn COM và loopback. Chỉ cần kiểm tra và báo ở "Kiểm tra máy" | | | | |
| c | Tiêm sớm tại `NavigateComplete2` (sink C# gọi `execScript` ngay trong handler, IE đang chờ) | Thêm request gửi lúc tải; hook có trước khi script trang giữ constructor | Thấp; nếu agent treo thì IE treo theo cho tới khi RPC hết hạn | Không | Có | Trung bình-cao |
| d | Kết hợp b2 + c + a2 (lùi về a1) | Đầy đủ nhất trong ràng buộc | Thấp nhất có thể đạt | Không | Có | Cao |

Xếp hạng: **d > a2 > a1+c > b2 đơn lẻ > b1 > b3 > b4**.

Kết luận thẳng: trong ràng buộc "không cài, không admin", **không có cách nào đứng hoàn toàn ngoài trang mà lấy được body của XHR**. Bên ngoài chỉ lấy được điều hướng (b2). Muốn có body thì phải có stand-in trong trang; việc cần làm là khiến stand-in không phân biệt được với đối tượng thật và tự rút lui khi có dấu hiệu lạ.

## 3. Chốt

**Phương án chính (d), ba lớp:**

1. Lớp ngoài, luôn bật: sink `DWebBrowserEvents2` viết bằng C# (`Add-Type` trong `ie-bridge.ps1`, chạy trên luồng STA riêng có vòng message). Ghi dòng `kind: "nav"` gồm URL đã che, frame, mã lỗi, thời gian. **Không ghi `PostData`** (có thể chứa mật khẩu).
2. Tiêm sớm: trong handler `NavigateComplete2`, sink gọi `execScript` lên `pDisp.Document.parentWindow` của đúng frame vừa điều hướng. Vòng poll 0,15 s giữ lại làm lưới an toàn.
3. Stand-in v2:
   - Kiểm tra tương thích trước khi cài: tạo đối tượng thật, `open` (không `send`), so `typeof` các thành viên; không khớp thì không cài và báo `__rkAjax = "skip:<lý do>"`.
   - Ưu tiên lớp VBScript (a2); không dùng được thì gương JS (a1) bổ sung đủ thành viên, chuyển tiếp mọi tham số, đồng bộ trước và sau mỗi lời gọi.
   - Mọi đoạn ghi nhận nằm trong `try/catch` riêng, tách khỏi đoạn chuyển tiếp: lỗi của trang vẫn ném ra nguyên vẹn, lỗi của ta bị nuốt.
   - Lỗi nội bộ đầu tiên: trả lại `window.XMLHttpRequest` và `window.ActiveXObject` gốc, các stand-in đang sống chuyển sang chuyển tiếp thuần, ghi dòng `kind: "ajaxerr"` (giai đoạn, tên thành viên, thông báo lỗi).
   - Hàng đợi request là mảng riêng (`__rkaq`), không cộng vào chuỗi `__rkq`.

**Dự phòng:** chế độ thụ động. Khi kiểm tra tương thích thất bại hoặc có `ajaxerr` trên máy GDV, agent đặt `__rkNoXhr` cho cả phiên, chỉ giữ lớp 1 và các sự kiện DOM sẵn có. Mất body request/response nhưng trang không bị chạm. Proxy cục bộ giới hạn bằng PAC (b1) chỉ xem xét nếu TouchPoint chạy HTTP thuần và bộ phận IT của ngân hàng đồng ý; không nằm trong danh sách task.

Quy tắc cứng giữ nguyên: dữ liệu request/response chỉ ở bộ nhớ agent, không vào cookie `__rkkeep`, che PII trên máy GDV trước khi gửi; runner vẫn tắt hook (`__rkNoXhr`).

## 4. Chưa chắc, cần spike trước (làm trong task 1 và 4)

- S1. Lỗi thật trên máy GDV là gì. Cần dòng `ajaxerr` và một bản chụp F12 (Console) của IE trên máy đó.
- S2. VBScript có chạy ở chế độ 5 trong zone của TouchPoint không (IE11 tắt VBScript ở zone Internet từ 2019; Intranet thường còn). `typeof` của instance lớp VBScript và việc gán hàm JS vào `Property Set` cần thử thật.
- S3. `Add-Type` có bị chặn không (AppLocker, Constrained Language Mode, thiếu `csc.exe`). Nếu bị chặn: thử DLL dựng sẵn trong gói; vẫn bị chặn thì bỏ lớp 1 và 2, còn lại stand-in v2 với vòng poll.
- S4. Tại `NavigateComplete2` ở chế độ 5, `execScript` có chạy trước script nội tuyến trong `<head>` không, và có chạy cho iframe GWT (`*.cache.html`) không.
- S5. Gọi ngược vào IE từ trong handler event (COM lồng nhau, khác tiến trình) có ổn định không; IE phản ứng thế nào khi agent bị tắt giữa chừng.
- S6. Trang TouchPoint dùng HTTP hay HTTPS, và máy GDV có khoá cấu hình proxy không (chỉ để quyết định có bao giờ mở lại b1).

## 5. Task (test chạy trên IE thật, `windows-agent/tests/test_ie_real.py`, `ROOKIE_REAL_IE=1`)

1. **Trang giả lập kiểu GWT và test đối chứng.** Thêm trang chế độ 5 có iframe, dùng `ActiveXObject("Microsoft.XMLHTTP")` và `XMLHttpRequest` theo các kiểu ở mục 1 (đọc `status` sớm trong `try/catch`, dùng lại object, đồng bộ, `abort`, `responseBody`, gán handler sau `send`, hai tham số), tự ghi nhật ký vào một `textarea`. Nghiệm thu: `test_ajax_page_journal_same_with_and_without_hook` chạy trang hai lần (tắt và bật hook), hai nhật ký phải giống hệt. Test này được phép đỏ ở task 1; nó là thước đo cho task 3.
2. **Báo lỗi chi tiết.** Dòng `kind: "ajaxerr"` và `__rkAjax` nêu lý do, hiện ở trang quản lý. Nghiệm thu: `test_ajax_hook_reports_error_detail` (ép lỗi nội bộ bằng cờ thử, dòng lỗi có giai đoạn và thông báo).
3. **Stand-in v2** (VBScript trước, gương JS sau; kết quả S2 quyết định). Nghiệm thu: test ở task 1 xanh cho cả hai biến thể; `test_ajax_records_method_url_status_body` vẫn xanh.
4. **Kiểm tra tương thích và tự gỡ.** Nghiệm thu: `test_ajax_hook_skipped_when_probe_fails`, `test_ajax_hook_uninstalls_itself_on_internal_error` (sau khi gỡ, `window.XMLHttpRequest` và `window.ActiveXObject` là bản gốc, trang gửi request tiếp bình thường).
5. **Không lưu bí mật trong body.** Nghiệm thu: `test_ajax_body_drops_secret_field_values` (trang gửi mật khẩu và OTP qua XHR; dòng ghi được không chứa hai giá trị đó, kể cả khi đã mã hoá URL).
6. **Sink `DWebBrowserEvents2`.** Nghiệm thu: `test_sink_records_frame_navigations` (dòng `nav` cho trang và từng frame, không có `PostData`), `test_bridge_falls_back_to_poll_when_add_type_blocked` (giả lập `Add-Type` lỗi, recorder vẫn chạy).
7. **Tiêm sớm.** Nghiệm thu: `test_early_inject_captures_request_sent_during_load` (script nội tuyến trong `<head>` gửi XHR ngay; có dòng `ajax` tương ứng), `test_ie_keeps_working_when_bridge_is_killed` (tắt tiến trình bridge giữa lúc điều hướng, IE tải xong trang trong 5 giây).
8. **Chế độ thụ động và đóng gói.** Nghiệm thu: `test_passive_mode_leaves_page_untouched` (sau một `ajaxerr`, các trang kế tiếp có `window.XMLHttpRequest` gốc và vẫn có dòng `nav`); chạy `scripts/package-path-b.ps1`; cập nhật `docs/tasks.md` và `docs/design.md`.

Thứ tự: 1, 2 (mang lên máy GDV để lấy lỗi thật, trả lời S1), rồi 3, 4, 5; nhánh 6, 7 làm song song sau khi S3, S4 có kết quả; 8 cuối cùng.
