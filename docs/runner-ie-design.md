# Thiết kế: Runner IE (hướng B2) chạy ngay trên canvas tab Luồng

Tài liệu này là thiết kế đủ để code của mốc "chạy lại flow đã học trên trang web trong Internet Explorer cũ". Người code làm đúng theo tài liệu, theo thứ tự task ở mục 15. Chỗ nào từng còn mở đều đã chốt và đánh dấu **Quyết định Dn** (danh sách đủ ở mục 18). Quy tắc cứng trong `CLAUDE.md` đứng trên tài liệu này; chỗ va chạm với quy tắc ghi ở mục 19.

Đọc kèm: `docs/design.md` mục 3C, 4, 6, 8, 9; `windows-agent/rookie_agent/runner.py` (vòng điều khiển Java, dùng lại); `windows-agent/rookie_agent/ie/` (cầu, bộ ghi); `windows-agent/rookie_agent/webui/` (trang quản lý).

## 1. Bối cảnh và phạm vi

**Vì sao.** TouchPoint chỉ mở được bằng Internet Explorer cũ (frameset lồng nhau, document mode 5). Ghi và Học đã chạy (task 1.15 đến 1.19). Còn thiếu Chạy. Chủ dự án đã chốt: flow chạy ngay trên canvas kiểu n8n ở tab Luồng, agent tự thao tác trên trang IE, GDV không thao tác tay.

**Trong phạm vi mốc này**

- Chạy flow `engine: "ie"` từ tab Luồng: Chạy thử, Duyệt agent, Chạy, Duyệt từng bước, Dừng khẩn.
- Thực thi qua COM: `fill`, `click` (nút, tab, mục cây, dòng danh sách theo vị trí), `select`, `submit` (Enter), `wait_for`, `read_value`.
- Form đầu vào mỗi lần chạy; bảng "Thông tin agent đã đọc".
- Sửa flow tối thiểu: đổi chế độ bước, xoá bước, đổi tên flow, thêm bước đọc giá trị.
- Audit từng bước lưu trên máy và gửi lên máy chủ.
- Trang thử "Mock TouchPoint" và bộ test không cần IE thật của ngân hàng.

**Ngoài phạm vi (không làm trong mốc này)**

- Self-healing bằng LLM (`LLMClient.locate`), ảnh chụp màn hình, đề xuất cập nhật selector.
- Nhánh có điều kiện, vòng lặp, sắp xếp lại thứ tự bước, đổi tên từng bước.
- Cửa sổ popup (`window.open`, `showModalDialog`), tải file, ActiveX, khung khác nguồn.
- Duyệt từ xa bởi người kiểm soát trên máy khác; chia sẻ agent; chấm điểm; khoá agent từ xa (task 2.7).
- `extract_table`, `compare`, `save`, `goto` cho engine `ie`.
- Chạy bước `money` trên trang không phải mock (cấm theo quy tắc cứng 6).

## 2. Ràng buộc đã đo (giữ nguyên, không thử cách khác)

Đo trên MSHTML thật ở các task trước:

| # | Ràng buộc |
| --- | --- |
| C1 | Chuỗi script đưa vào `execScript` phải là `[string]` thuần (`[string][IO.File]::ReadAllText(...)`); chuỗi lấy thẳng từ `Get-Content` làm COM treo. |
| C2 | Biến và hàm do trang tạo (expando) đọc, gọi bằng `[System.__ComObject].InvokeMember(name, 'GetProperty' hoặc 'InvokeMethod', ...)`, không dùng cú pháp dấu chấm. |
| C3 | Luôn viết `$null = $win.execScript(...)` để giá trị trả về không lọt ra stdout của cầu. |
| C4 | Khung khác nguồn từ chối `execScript` (Access is denied); đọc `name` của nó trả chuỗi rỗng. |
| C5 | Trang ở quirks mode (document mode 5): không có `JSON`, `addEventListener`, `trim`, `forEach`. Script trong trang chỉ viết ES3, file ASCII. |
| C6 | Mọi thứ trên pipe giữa Python và PowerShell là ASCII (`\uXXXX`). |

Đo thêm ngày 2026-11-16 trên máy phát triển (Windows 11), dùng một cửa sổ IE ẩn tạo bằng `New-Object -ComObject InternetExplorer.Application` mở frameset phục vụ từ `127.0.0.1`:

| # | Kết quả đo | Hệ quả thiết kế |
| --- | --- | --- |
| M1 | Máy phát triển không có IE để người dùng mở, nhưng đối tượng COM `InternetExplorer.Application` vẫn tạo được, chạy ẩn, và `Shell.Application.Windows()` liệt kê nó. | Test tích hợp chạy được trên IE thật ở máy phát triển (tự bỏ qua nếu máy không tạo được COM). |
| M2 | Không có thẻ meta thì IE11 không vào mode 5 (`typeof JSON` là `object`, `fireEvent` lỗi). Thêm `<meta http-equiv="X-UA-Compatible" content="IE=5">` thì `documentMode` = 5, `JSON` và `addEventListener` là `undefined`. | Mọi trang của Mock TouchPoint có thẻ meta này. |
| M3 | `el.fireEvent("onchange")` chạy handler inline; `fireEvent("onkeydown", evt)` với `evt.keyCode = 13` chạy handler và handler thấy `keyCode` 13. | Dùng `fireEvent` để báo cho trang sau khi đặt giá trị và để gửi Enter. |
| M4 | Enter giả (keydown, keypress) **không** kích hành vi mặc định của form (không submit). | Enter có hai pha, xem 8.4. |
| M5 | `td.click()` nổi bọt lên `onclick` của `table`; `button.click()` chạy `onclick`; `input[type=submit].click()` chạy `onsubmit` của form. | `click()` dùng được cho nút, tab, dòng danh sách có handler ở phần tử cha. |
| M6 | `offsetWidth` > 0 với phần tử đang hiện, = 0 với `display:none`. `document.all[el.sourceIndex] === el`. | Kiểm tra đang hiện bằng `offsetWidth`; định danh tạm thời một phần tử bằng `sourceIndex`. |
| M7 | Id trùng: `getElementById` chỉ trả phần tử đầu; `document.all["txtBlank"].length` = 2. | Không dùng `getElementById`; luôn duyệt hết và đếm. |
| M8 | `window.setTimeout(fn, 0)` trong trang IE thật tự chạy, không cần bơm message từ PowerShell. | Hành động được phát bằng `setTimeout` để lệnh COM trả về ngay. |
| M9 | Bấm nút gọi `confirm()` qua `setTimeout`: lệnh COM trả về trong vài ms, kết quả giữ ở "pending" khi hộp thoại còn mở, và `execScript` khác vẫn chạy được trong lúc đó. | Phát hiện được "trang đang chờ trả lời hộp thoại" mà cầu không treo. |
| M10 | `InvokeMember(name, 'InvokeMethod', ..., @(arg1, arg2))` truyền được tham số cho hàm của trang; `SetProperty` trên expando chưa có thì lỗi `DISP_E_UNKNOWNNAME`. | Không dùng `SetProperty`. Truyền tham số bằng chuỗi literal trong `execScript` (cách đã đo ở cả hai nơi). |
| M11 | Đối tượng `htmlfile`: không tạo khung (`frames.length` = 0), không chạy handler inline, không có layout (`offsetWidth` = 0), `setTimeout` chỉ chạy khi PowerShell bơm message (`[System.Windows.Forms.Application]::DoEvents()`), `submit.click()` ném lỗi. | `htmlfile` chỉ dùng để test hàm thuần của script trong trang (tìm, nhãn, đọc). Hành vi (sự kiện, khung, hộp thoại) test trên IE ẩn. |

## 3. Mười câu hỏi và quyết định (tóm tắt)

| # | Câu hỏi | Quyết định | Chi tiết |
| --- | --- | --- | --- |
| 1 | Chạy ở đâu | Ngay trên canvas tab Luồng; trang IE là nơi thao tác diễn ra, canvas là nơi điều khiển và theo dõi | 13 |
| 2 | Đầu vào mỗi lần chạy | Form sinh từ `workflow.inputs` ở ô "Bắt đầu"; giá trị chỉ nằm trong bộ nhớ của lần chạy, không lưu, không ghi log | 10.1 |
| 3 | Đọc thông tin chỉ xem | Có, bằng bước `read_value` do GDV thêm bằng "Chọn ô cần đọc"; giá trị chỉ trong bộ nhớ, chỉ hiện trên canvas máy này | 10.2 |
| 4 | Duyệt | Người đang chạy bấm Duyệt cho từng bước `write`/`money` trên canvas; cú bấm Duyệt của người kiểm soát trong hệ thống nghiệp vụ không bao giờ do agent bấm | 9.3 |
| 5 | Sửa flow | Đổi chế độ, xoá bước, đổi tên flow, thêm bước đọc; không sắp xếp lại; mỗi lần sửa là version mới ở `draft` | 10.3 |
| 6 | Định vị phần tử | Chấm điểm bằng chứng từ mọi selector, ngưỡng 0,8 (`read`) và 0,9 (`write`/`money`); không dùng LLM | 7 |
| 7 | Thực thi qua COM | Script ES3 trong trang (`page_runner.js`), phát hành động bằng `setTimeout`, token chống gửi lặp | 6, 8 |
| 8 | Dừng khẩn và trạng thái ô | Dừng trong 1 giây, không gửi thêm lệnh, không chạy tiếp từ giữa; 10 trạng thái ô | 9.4, 9.2 |
| 9 | Audit | Một bản ghi mỗi bước, lưu file trên máy rồi `POST /runs`; không bao giờ có giá trị | 11 |
| 10 | Test | Unit với cầu giả, `htmlfile` cho hàm thuần, IE ẩn + Mock TouchPoint cho hành vi; danh sách kiểm trên máy IE thật | 16 |

## 4. Kiến trúc

### 4.1 Thành phần

| Thành phần | File | Vai trò |
| --- | --- | --- |
| Canvas | `webui/index.html` | Tab Luồng: vẽ ô, form đầu vào, hộp hỏi, bảng giá trị đã đọc, nút Chạy thử, Chạy, Duyệt, Dừng khẩn. Hỏi trạng thái mỗi 500 ms. |
| Core | `webui/core.py` | Route `/api/run/*`, `/api/flows/*`, `/api/pick/*`; kho flow trên máy; chỉ một lần chạy tại một thời điểm. |
| RunSession | `webui/run.py` (mới) | Một lần chạy: luồng (thread) chạy `run_workflow`, `CanvasController`, trạng thái ô, câu hỏi đang mở, giá trị đã đọc, nhịp tim của trang. |
| Vòng điều khiển | `runner.py` (mở rộng) | Dùng chung cho Java và IE: kiểm tra workflow, cổng rủi ro, Duyệt, xem lại, Dừng khẩn, hỏi GDV. |
| IeDriver | `ie/driver.py` (mới) | Cài `Driver` cho IE: tìm, chấm điểm, phát hành động, chờ kết quả, chờ trang ổn định. |
| Chấm điểm | `ie/locate.py` (mới) | Hàm thuần: tách selector, tính ứng viên và điểm. |
| Cầu | `ie/ie-bridge.ps1`, `ie/bridge.py` | Thêm lệnh `run_*`; đi tới đúng khung; gọi script trong trang. |
| Script trong trang | `ie/page_lib.js` (mới, tách từ bộ ghi), `ie/page_runner.js` (mới), `ie/page_recorder.js` (sửa) | `__rkLib`: hàm nhãn dùng chung. `__rkRun`: tìm, đọc, hành động. |
| Audit | `audit.py` (mới) | Ghi bản ghi từng bước, tự kiểm không chứa giá trị, đệm và gửi lên máy chủ. |
| Mock TouchPoint | `webui/mock_touchpoint/*.html` (mới) | Frameset giả lập, phục vụ tại `/mock-touchpoint/`. |
| Máy chủ | `server/app/main.py`, `storage.py` | Mở rộng `revise`; thêm `POST /runs`, `GET /runs`. |

### 4.2 Ai nói với ai (luồng dữ liệu)

```
Canvas (trình duyệt hiện đại, http://localhost:8765)
   │  POST /api/run/start {inputs}      GET /api/run/state (500 ms)      POST /api/run/decide | /stop
   ▼
Core ── tạo ──► RunSession ── thread ──► run_workflow(engine="ie")
                    │ CanvasController        │ Driver
                    │ (hỏi, tiến độ, giá trị) ▼
                    │                     IeDriver ── locate.py (điểm)
                    │                         │ JSON từng dòng, ASCII
                    │                         ▼
                    │                     ie-bridge.ps1 (-Sta, COM Shell.Application)
                    │                         │ execScript + InvokeMember
                    │                         ▼
                    │                     Trang IE: từng khung có __rkLib + __rkRun
                    ▼
               audit.py ──► %LOCALAPPDATA%\RookieAgent\audit\outbox\<run_id>.json ──► POST {server}/runs
```

Giá trị GDV nhập đi theo đường: form trên canvas → `POST /api/run/start` (loopback) → bộ nhớ của RunSession → một dòng JSON trên pipe tới cầu → chuỗi literal trong `execScript` → ô nhập trên trang. Giá trị đọc được đi ngược lại tới bộ nhớ RunSession rồi tới canvas. Không đoạn nào ghi ra đĩa hay rời máy.

### 4.3 Kho flow trên máy

**Quyết định D11.** `Core.learn` lưu đầy đủ workflow (có selector) vào `<home>/flows/<workflow_id>.json`, thay cho mảng `flows` rút gọn trong `settings.json`. Lý do: bản rút gọn hiện nay không có selector nên không chạy được.

```json
{"workflow": {...}, "digest": "<sha256>", "warnings": [], "learned_at": "2026-11-16 09:12:00",
 "trial": {"version": 2, "ok": true, "at": "2026-11-16 09:20:11"}}
```

- Mục cũ trong `settings.json["flows"]` vẫn được liệt kê với `legacy: true` và dòng "Luồng này học từ bản cũ. Hãy Học lại để chạy được." Không tự chuyển đổi.
- Trước mỗi lần chạy, Core tính lại `digest(workflow)` và so với `digest` đã lưu; lệch thì từ chối ("Bản lưu trên máy đã bị thay đổi. Hãy Học lại hoặc tải lại.").
- `home` là `%LOCALAPPDATA%\RookieAgent` của người dùng Windows, nên flow mặc định riêng tư theo người dùng (đúng quyết định của chủ dự án).

## 5. Giao thức cầu: lệnh thêm vào `ie-bridge.ps1`

Lệnh cũ (`ping`, `tabs`, `probe`, `start`, `poll`, `stop`, `quit`) giữ nguyên. Lệnh `run_*` dùng biến `$runTab`, tách khỏi `$bound` của bộ ghi. Mỗi lệnh đi lại từ cửa sổ gốc tới khung theo đường dẫn; không giữ đối tượng khung giữa hai lệnh (khung có thể đã nạp trang mới).

Hàm phụ trong cầu:

- `Resolve-Frame($top, $path)`: `"top"` là cửa sổ gốc; tách theo `/`; phần `#i` là `frames.item(i)`; phần khác so với `[string]$f.name` của từng khung con. Không thấy thì trả `$null`.
- `JsLit([string]$s)`: trả `"` + từng ký tự viết thành `\uXXXX` + `"`. Mọi tham số đưa vào script đều qua hàm này (không còn chỗ nào để chèn mã).
- `Invoke-Run($win, [string]$expr)`: nạp `page_lib.js` + `page_runner.js` nếu `__rkRun` chưa có, rồi `$null = $win.execScript([string]("window.__rkOut = " + $expr), 'javascript')`, đọc `__rkOut` bằng `Get-Prop`.
- Lỗi của các lệnh `run_act`, `run_read` trả về chữ cố định kèm mã HRESULT, không trả `Exception.Message` (phòng khi thông báo chứa nội dung trang).

| Lệnh | Yêu cầu | Trả lời |
| --- | --- | --- |
| `run_bind` | `{"cmd":"run_bind","title":"TouchPoint"}` | `{"ok":true,"title":"TouchPoint","host":"tp.noi-bo:8080","path":"/tp/index.jsp","frames":7}`. Không thấy: `{"ok":false,"error":"tab not found"}`. Nhiều tab cùng tên: `{"ok":false,"error":"several tabs"}`. `path` không kèm query. |
| `run_find` | `{"cmd":"run_find","frame":"desktopFrame/rtop/main/fraProfileArea","tests":[["id","txtCustomerId"],["name","txtPartyID"],["label","Mã khách hàng"],["pos","input","3"]],"want":"field"}` | `{"ok":true,"state":"ok","raw":"{\"m\":[[41],[41],[41,57],[41]],\"h\":0,\"e\":[{\"u\":41,\"tag\":\"input\",\"type\":\"text\",\"id\":\"txtCustomerId\",\"name\":\"txtPartyID\",\"field\":1,\"press\":0,\"ro\":0,\"dis\":0}]}"}`. `state`: `ok`, `frame_missing`, `loading` (`document.readyState` của khung khác `complete`), `denied` (C4). |
| `run_act` | `{"cmd":"run_act","frame":"...","uid":41,"expect":{"tag":"input","id":"txtCustomerId","name":"txtPartyID"},"action":"fill","value":"900001","token":"r4f2a-3-1"}` | `{"ok":true,"state":"dispatched"}`. `state` khác: `moved` (phần tử ở `uid` không còn đúng `expect`), `seen` (token đã dùng), `refused` kèm `"code"`, `frame_missing`, `loading`, `denied`. |
| `run_result` | `{"cmd":"run_result","frame":"...","token":"r4f2a-3-1"}` | `{"ok":true,"state":"done","code":"ok"}`. `state`: `pending`, `done`, `error`, `gone` (khung đã nạp trang khác nên không còn kết quả). |
| `run_read` | `{"cmd":"run_read","frame":"...","uid":63,"expect":{"tag":"input","id":"txtFullName","name":""}}` | `{"ok":true,"state":"ok","raw":"{\"v\":\"NGUYEN VAN A\"}"}` hoặc `state`: `moved`, `refused` (`code`: `secret`). |
| `run_snapshot` | `{"cmd":"run_snapshot"}` | `{"ok":true,"sig":"top\|complete\|0\|4;desktopFrame\|complete\|0\|3;...","host":"...","path":"...","title":"TouchPoint"}`. `sig` nối theo từng khung đọc được: `tên\|readyState\|độ dài title\|document.all.length`. Không chứa chữ của trang. |
| `run_cancel` | `{"cmd":"run_cancel"}` | `{"ok":true}`. Gọi `__rkRun.cancel()` ở mọi khung đọc được. |
| `run_unbind` | `{"cmd":"run_unbind"}` | `{"ok":true}` |
| `run_open` | `{"cmd":"run_open","url":"http://127.0.0.1:8765/mock-touchpoint/index.html","visible":true}` | `{"ok":true,"title":"Mock TouchPoint"}`. Cầu chỉ nhận URL khớp `^http://127\.0\.0\.1:\d+/mock-touchpoint/`; URL khác trả lỗi. Tạo `InternetExplorer.Application`, chờ `ReadyState` 4 (tối đa 20 giây). |
| `run_close` | `{"cmd":"run_close"}` | `{"ok":true}`. Chỉ đóng cửa sổ do chính `run_open` tạo (gọi `Quit()`; không đóng được thì kết thúc các tiến trình `iexplore` xuất hiện sau `run_open`). |

`want` là `field` (ô nhập), `press` (thứ bấm được) hoặc `any`. Thử `pos` có ba phần: `["pos", tag, số thứ tự]`.

Phía Python, `IeBridge` thêm các hàm cùng tên (`run_bind`, `run_find`, ...), mỗi lệnh timeout 15 giây. Hết thời gian chờ: `IeBridge` đóng tiến trình cầu, mở cầu mới, `run_bind` lại theo tên, rồi ném `IeBridgeError`; IeDriver đổi thành `NeedsHelp("uncertain")` nếu đang giữa `run_act`, ngược lại là `ElementNotFound` để vòng chờ thử tiếp.

## 6. Script trong trang

### 6.1 `page_lib.js` (tách từ `page_recorder.js`, không đổi hành vi)

Tự chạy một lần (`if (window.__rkLib) return`). Đưa ra `window.__rkLib` gồm các hàm hiện có trong bộ ghi: `esc`, `str`, `clean`, `tag`, `typeOf`, `framePath`, `isSecret`, `labelOf`, `dataRowLabel`, `actionLabel`, `position`, `valueOf`, `handCursor`, `actionable`, `isField`, và hàm mới `mask(text)`.

`mask` phải cho cùng kết quả với `_mask` trong `ie/recorder.py`: gộp khoảng trắng, thay mỗi từ khớp `\S*\d\S*\d\S*\d\S*` bằng `#`, cắt 60 ký tự. Nhãn dùng để so khi chạy luôn là `mask(clean(...))`.

`page_recorder.js` bỏ các hàm đã chuyển và gọi qua `__rkLib`. Cầu nạp `page_lib.js` trước rồi mới tới `page_recorder.js` hoặc `page_runner.js` (nối hai chuỗi thành một `[string]`, C1). `page_lib.js` không bật ghi, không gắn sự kiện.

### 6.2 `page_runner.js`

Tự chạy một lần (`if (window.__rkRun) return`). Không gắn sự kiện nào, không đặt `__rkRec`. API:

| Hàm | Trả về (chuỗi) |
| --- | --- |
| `find(tests, want)` | JSON tự dựng: `m` (mảng `sourceIndex` khớp cho từng thử, chỉ phần tử đang hiện), `h` (số phần tử khớp nhưng đang ẩn), `e` (mô tả từng phần tử có trong `m`: `u`, `tag`, `type`, `id`, `name`, `field`, `press`, `ro`, `dis`). `tests` là chuỗi: các thử cách nhau bằng `\u0001`, các phần của một thử cách nhau bằng `\u0002`. |
| `read(uid, tag, id, name)` | `{"v":"..."}`, hoặc `moved`, hoặc `refused:secret`. |
| `act(uid, tag, id, name, action, value, token)` | `dispatched`, `moved`, `seen`, hoặc `refused:<mã>`. |
| `result(token)` | `pending`, `done:<mã>`, `error:script`, `unknown`. |
| `cancel()` | `ok`. Huỷ mọi `setTimeout` chưa chạy. |

Quy tắc tìm trong `find` (một lượt duyệt `document.getElementsByTagName("*")`, M7):

- `id`: mọi phần tử có `el.id === giá trị`. `name`: mọi phần tử có `el.name === giá trị`.
- `pos`: `document.getElementsByTagName(tag)[n]` (0 hoặc 1 phần tử).
- `label` theo `want`:
  - `field`: phần tử có `isField(el)` và không `isSecret(el)`; nhãn là `mask(labelOf(el))`.
  - `press`: phần tử X mà `actionable(X) === X`; nhãn là `mask(actionLabel(X))`. Dòng danh sách vì vậy có nhãn «dòng N».
  - `any`: hai tập trên, cộng phần tử lá (`TD`, `TH`, `SPAN`, `DIV`, `LABEL`, `B` không có phần tử con) với nhãn `mask(labelOf(el))`.
- Đang hiện: `offsetWidth > 0 && offsetHeight > 0` và không tổ tiên nào có `currentStyle.visibility === "hidden"` (M6). Khi `window.__rkNoLayout === true` (chỉ test `htmlfile` đặt, M11) thì chỉ xét chuỗi `currentStyle.display`/`visibility`.
- `field` = 1 khi `isField(el)` và không `isSecret(el)`. `press` = 1 khi `actionable(el) === el`. `ro` = `el.readOnly`, `dis` = `el.disabled`.

`act` kiểm tra đồng bộ rồi mới phát:

1. `document.all[uid]` phải có `tagName`, `id`, `name` đúng `expect`; sai thì `moved`.
2. Token đã có trong bảng kết quả thì `seen` (không làm gì).
3. Điều kiện trước theo hành động; sai thì `refused:<mã>`, không phát:
   - `fill`: `isSecret` → `secret`; `ro` hoặc `dis` → `not_editable`; `maxLength > 0` và giá trị dài hơn → `too_long`.
   - `select`: không có option nào có `text` (đã cắt khoảng trắng) hoặc `value` bằng đúng giá trị → `no_option`. Không so gần đúng.
   - `click`, `enter_keys`, `enter_default`: `dis` → `not_editable`; `enter_default` mà ô không thuộc form có nút gửi → `no_default`.
4. Ghi `results[token] = "pending"`, `setTimeout(function () {...}, 0)`, trả `dispatched` (M8, M9).

Việc làm trong `setTimeout` (bọc `try/catch`; lỗi thì `error:script`):

| Hành động | Trình tự | Mã kết quả |
| --- | --- | --- |
| `fill` | `focus()`; `el.value = v`; nếu `el.value !== v` → `value_not_set`; `fireEvent("onkeyup")`; `fireEvent("onchange")`; `fireEvent("onblur")`; đọc lại | `ok` (bằng `v`), `reformatted` (khác `v`, không rỗng: trang tự định dạng), `cleared_by_page` (rỗng) |
| `select` | `focus()`; đặt `selectedIndex`; `fireEvent("onchange")`; đọc lại | `ok`, `value_not_set` |
| `click` | `focus()` (bỏ qua lỗi); `fireEvent("onmousedown")`; `fireEvent("onmouseup")`; `el.click()` | `ok` |
| `enter_keys` | `focus()`; tạo `createEventObject()` với `keyCode = 13`; `fireEvent` lần lượt `onkeydown`, `onkeypress`, `onkeyup` | `enter_sent` |
| `enter_default` | `click()` vào nút gửi đầu tiên của `el.form` (`input` loại `submit`/`image`, hoặc `button` loại `submit`) | `ok` |

**Quyết định D7a.** Mọi hành động làm đổi trang đều phát qua `setTimeout`, không gọi thẳng trong `execScript`. Lý do: trang gọi `alert`/`confirm` sẽ giữ lệnh COM tới khi có người bấm (M9); phát trễ thì cầu không treo và Runner nhận ra hộp thoại.

**Quyết định D7b.** Dùng script ES3 trong trang cho tìm và hành động, không gọi DOM trực tiếp từ PowerShell. Lý do: một lượt COM cho mỗi việc (nhanh hơn duyệt 4.000 phần tử qua COM), dùng chung hàm nhãn với bộ ghi nên nhãn lúc chạy trùng nhãn lúc ghi.

## 7. Định vị phần tử và độ tin cậy

### 7.1 Selector

Dạng do bộ ghi sinh: `frame=<đường dẫn>|id=<v>`, `frame=<đường dẫn>|name=<v>`, `frame=<đường dẫn>|label=<v>`, `frame=<đường dẫn>|<tag>[<n>]`. Selector không có `frame=` (mẫu cũ `label=THÊM`) được tìm trong khung của selector đầu tiên có `frame=`; nếu không selector nào có khung thì dùng `top`. Selector sai cú pháp bị bỏ qua (không tính là bằng chứng). Mọi selector của một bước phải cùng một khung; khác khung thì chỉ dùng nhóm của selector đầu tiên.

`want` theo hành động: `fill`, `select`, `submit` → `field`; `click` → `press`; `read_value`, `wait_for` → `any`.

### 7.2 Điểm tin cậy (hàm thuần trong `ie/locate.py`)

"Độ tin cậy" ở mốc này là **điểm bằng chứng định vị** trong khoảng 0 đến 1, tính bằng luật, không có LLM.

Đầu vào: danh sách thử theo thứ tự selector, mỗi thử có loại (`id`, `name`, `label`, `pos`) và tập khớp `M` (chỉ phần tử đang hiện).

1. Mọi `M` rỗng → `NOT_FOUND` (vòng chờ thử lại tới hết thời gian).
2. Chọn ứng viên:
   - a. Selector đầu tiên thuộc loại mạnh (`id`, `name`, `label`) có đúng 1 phần tử khớp → ứng viên, điểm gốc: `id` 1,0; `name` 0,9; `label` 0,8.
   - b. Nếu không có: lấy giao của mọi `M` không rỗng. Giao có đúng 1 phần tử và có ít nhất 2 thử không rỗng → ứng viên, điểm gốc 0,8, cách tìm `intersect`. (Trường hợp id trùng như `txtBlank`, hoặc «dòng 2» có ở nhiều bảng, được gỡ nhờ vị trí.)
   - c. Nếu chỉ `pos` khớp (mọi loại mạnh rỗng) → ứng viên, điểm gốc 0,5.
   - d. Còn lại → `AMBIGUOUS`.
3. Điều chỉnh với từng thử khác (không phải thử đã chọn ứng viên) có `M` không rỗng: chứa ứng viên thì +0,1; không chứa thì −0,2. Kẹp trong 0 đến 1.
4. Sai loại → điểm 0: `want` là `field` mà `field` = 0, hoặc `want` là `press` mà `press` = 0.
5. Ngưỡng: bước `read` cần ≥ 0,8; bước `write` và `money` cần ≥ 0,9. Dưới ngưỡng → `LOW_CONFIDENCE`.

Ví dụ: id duy nhất, name và label cùng chỉ nó → 1,0. Nút không id, nhãn «LƯU» duy nhất, vị trí trùng → 0,9 (đủ cho `write`). Nhãn duy nhất nhưng vị trí chỉ phần tử khác → 0,6 (dừng hỏi). Chỉ còn vị trí → 0,5 (dừng hỏi).

**Quyết định D6a.** Ngưỡng 0,8 và 0,9, hằng số trong `ie/locate.py`. Lý do: vị trí đơn thuần không bao giờ đủ; bước ghi và tiền đòi bằng chứng mạnh hơn bước chỉ xem.

**Quyết định D6b.** Không gọi `LLMClient.locate` trong mốc này. Lý do: `docs/design.md` mục 6 đã chốt hướng B dừng ở selector dự phòng; chưa có ảnh đã che và chưa có cách che DOM gửi đi.

### 7.3 Chờ, khung đổi, không thấy

- Mỗi lần thử gọi `run_find` một lượt. `frame_missing`, `loading`, `NOT_FOUND`, hoặc chỉ có phần tử ẩn (`h` > 0) → `ElementNotFound`; vòng chờ của Runner thử lại mỗi 0,3 giây tới hết 15 giây (`element_timeout` cho IE).
- `AMBIGUOUS`, `LOW_CONFIDENCE`, `denied` → dừng hỏi ngay, không chờ (chờ không làm bằng chứng tốt lên).
- Sau mỗi hành động đã xong, IeDriver chờ trang ổn định: gọi `run_snapshot` mỗi 0,3 giây tới khi hai lần liền nhau có `sig` bằng nhau, tối đa 8 giây, rồi đi tiếp (bước sau còn vòng chờ riêng).
- Không tìm sang khung khác khi khung ghi trong selector không còn. Hết 15 giây thì dừng hỏi với lời "Màn hình khác với lúc ghi".
- Hằng số (trong `ie/driver.py`): `ELEMENT_TIMEOUT = 15.0`, `FIND_POLL = 0.3`, `ACT_RESULT_TIMEOUT = 5.0`, `ENTER_WAIT = 1.0`, `SETTLE_MAX = 8.0`, `SETTLE_POLL = 0.3`, `BRIDGE_TIMEOUT = 15.0`.

## 8. Thực thi hành động và kiểm chứng

### 8.1 Trình tự chung của IeDriver cho một hành động

1. `run_find` → chấm điểm (7.2). Không đạt thì ném `ElementNotFound` hoặc `NeedsHelp(mã)`; chưa có gì được gửi tới trang.
2. Nếu đang có token chưa có kết quả của chính bước này: **không** phát lại, nhảy tới bước 4 (hỏi kết quả).
3. `run_act` với token mới `"<run_id>-<số bước>-<lần>"`. `moved` → `ElementNotFound` (tìm lại). `refused` → `NeedsHelp(mã)`. `seen` → coi như đã phát.
4. Hỏi `run_result` mỗi 0,2 giây tới 5 giây:
   - `done` → xét mã (8.2 đến 8.4).
   - `gone` → trang đã chuyển sau hành động: coi là xong.
   - `error` → `NeedsHelp("script_error")`.
   - vẫn `pending` → `NeedsHelp("blocked")`, giữ token. Khi GDV chọn "Thử lại", bước 2 chỉ hỏi lại kết quả.
5. Chờ trang ổn định (7.3), ghi `sig` trước và sau vào báo cáo bước.

### 8.2 `fill`, `select`

- `ok`, `reformatted` → xong (`reformatted` ghi vào audit là "trang tự định dạng lại", không ghi giá trị).
- `cleared_by_page`, `value_not_set` → `NeedsHelp(mã)`.
- Giá trị điền là chuỗi sau khi thay `{tên}` (đã có trong `run_workflow`).

### 8.3 `click`

- Kết quả `ok` hoặc `gone` là xong. Không coi "trang không đổi" là lỗi (nhiều cú bấm không đổi DOM); báo cáo bước ghi `page_changed: true/false`.
- Hậu kiểm thật sự là bước kế tiếp: phần tử của bước sau phải xuất hiện trong 15 giây.
- Dòng danh sách: bấm phần tử tìm được theo 7.2 (thường là `intersect` giữa nhãn «dòng N» và vị trí). Không bao giờ tìm theo chữ trong dòng.

### 8.4 `submit` (Enter trong ô)

Hai pha vì Enter giả không kích hành vi mặc định (M4):

1. Pha 1: `enter_keys`. Chờ tới `ENTER_WAIT` (1 giây) xem `sig` có đổi không. Đổi (hoặc kết quả `gone`) → xong, ghi `enter: "handled"`.
2. Pha 2, chỉ khi `sig` không đổi **và bước là `read`**: `enter_default` (bấm nút gửi của form, đúng việc trình duyệt làm khi nhấn Enter). `refused:no_default` → `NeedsHelp("no_effect")`.
3. Bước `write`/`money` không bao giờ có pha 2: `sig` không đổi → `NeedsHelp("no_effect")` với lựa chọn không có "Thử lại".

**Quyết định D7c.** Enter gửi bằng sự kiện giả trong trang, không dùng `SendKeys`. Lý do: `SendKeys` cần cửa sổ IE đang có focus, trong khi GDV đang nhìn canvas ở trình duyệt khác.

### 8.5 `read_value`, `wait_for`

- `read_value`: `run_find` (`want: any`) → điểm ≥ 0,8 → `run_read`. Trước khi đọc, Python gọi `classify(nhãn)`; loại `ignore` thì không đọc (`NeedsHelp("secret")`). Giá trị cắt 200 ký tự.
- `wait_for`: `run_find` đạt ngưỡng là xong.

### 8.6 Chống gửi hai lần

- Trong trang: token đã thấy thì `act` trả `seen`, không làm lại.
- Trong IeDriver: token chưa có kết quả thì chỉ hỏi kết quả, không phát mới.
- Trong Runner: một lần Duyệt cho phép nhiều nhất một lần phát (luật R7, R8).
- Cầu hết thời gian chờ giữa `run_act` → `NeedsHelp("uncertain")`: không biết đã bấm hay chưa nên không bao giờ tự bấm lại.

### 8.7 Mã dừng hỏi và lựa chọn đưa cho GDV

| Mã | Ý nghĩa | Đã phát? | Lựa chọn (bước `read`) | Lựa chọn (bước `write`/`money`) |
| --- | --- | --- | --- | --- |
| `not_found` | Hết 15 giây không thấy | chưa | Thử lại, Tự làm, Dừng | Thử lại (phải Duyệt lại), Tự làm, Dừng |
| `ambiguous`, `low_confidence` | Nhiều phần tử giống nhau, hoặc bằng chứng yếu | chưa | như trên | như trên |
| `not_editable`, `too_long`, `no_option`, `denied`, `secret` | Trang không cho làm | chưa | như trên | như trên |
| `blocked` | Trang đang chờ trả lời hộp thoại | đang chờ | Thử lại (chỉ hỏi lại kết quả), Dừng | Thử lại (chỉ hỏi lại kết quả), Dừng |
| `uncertain` | Cầu không trả lời giữa lúc phát | không rõ | Thử lại, Tự làm, Dừng | Tự làm, Dừng |
| `no_effect`, `cleared_by_page`, `value_not_set`, `script_error` | Đã phát nhưng không thấy tác dụng | rồi | Thử lại, Tự làm, Dừng | Tự làm, Dừng |
| `write_on_real` | Bước ghi trên trang thật, chưa được bật (R4) | chưa | (không xảy ra) | Tự làm, Dừng |

"Tự làm" hiện là «Tôi đã tự làm bước này, đi tiếp»; ô chuyển sang trạng thái Bỏ qua.

## 9. Vòng điều khiển

### 9.1 Mở rộng `runner.py` (giữ nguyên hành vi Java)

- `ENGINE_SCHEMA = {"java": 1, "ie": 2}`; `check_workflow(workflow, inputs, sandbox, engine="java")` kiểm cặp engine và `schema_version` theo bảng này. Hành động hỗ trợ cho `ie` giống Java: `click`, `fill`, `select`, `submit`, `read_value`, `wait_for`.
- `run_workflow(..., engine="java", trial=False, allow_write_off_mock=True)`. Core gọi với `engine="ie"`, `element_timeout=15.0`, `allow_write_off_mock=<cài đặt ie_allow_write_on_real, mặc định False>`.
- Mock: dùng `driver.is_mock()` nếu driver có hàm này, không thì giữ cách cũ theo tiêu đề cửa sổ.
- Ngoại lệ mới `NeedsHelp(code)` (không kế thừa `ElementNotFound`).
- Hàm tuỳ chọn, tìm bằng `getattr`, không có thì giữ hành vi cũ:
  - `driver.prepare(step)`: báo cho driver biết `risk`, `action` của bước sắp chạy (để chọn ngưỡng).
  - `driver.report() -> dict`: thông tin định vị và tác dụng của bước vừa chạy (không có giá trị).
  - `controller.help(step, index, total, code, options) -> "retry" | "skip" | "stop"`. Không có hàm này thì kết thúc `needs_help` như hiện nay.
  - `controller.read(step, value)`: nhận giá trị vừa đọc.
  - `controller.report(step, info)`: nhận `driver.report()` cho audit.
- Thân mỗi bước nằm trong vòng lặp "lần thử": "Thử lại" quay về đầu vòng (qua lại cổng Duyệt nếu bước có `mode: approve`); "Tự làm" ghi trạng thái `skipped` rồi sang bước sau; "Dừng" kết thúc `needs_help`.
- Lần chạy thử (`trial=True`): gặp bước đầu tiên có `risk` khác `read` thì kết thúc với `status: "finished"` và lời "Chạy thử đã chạy k bước chỉ xem. Bước ghi và bước tiền không chạy khi thử."

### 9.2 Máy trạng thái

Lần chạy:

```
(không có) ──start──► preparing ──► running ◄──► waiting_approval | waiting_review | waiting_help
                          │            │
                          ▼            ▼
                       refused      finished | stopped | rejected | refused | needs_help | failed
```

`preparing`: kiểm tra flow, digest, `run_bind`. Sáu trạng thái cuối là kết thúc; không có "chạy tiếp".

Trạng thái ô trên canvas (khoá tiếng Anh dùng trong API, chữ tiếng Việt hiện cho GDV):

| Khoá | Hiện | Khi nào |
| --- | --- | --- |
| `pending` | Chờ | Chưa tới lượt (kể cả các ô sau khi lần chạy đã dừng) |
| `running` | Đang chạy | Runner đang tìm hoặc thao tác |
| `done` | Xong | Hành động xong và trang ổn định |
| `waiting_approval` | Đợi Duyệt | Bước `approve` chưa được bấm Duyệt |
| `waiting_review` | Đợi bạn xem | Bước `review` đã chạy xong, chờ "Đi tiếp" |
| `needs_help` | Dừng hỏi bạn | Một mã ở 8.7 |
| `skipped` | Bỏ qua (bạn tự làm) | GDV chọn "Tự làm" |
| `failed` | Lỗi | Lỗi ngoài dự kiến của driver hoặc cầu |
| `stopped` | Đã dừng | Dừng khẩn khi ô này đang chạy hoặc đang chờ |
| `refused` | Không được phép | Vi phạm luật R3, R9 |

Ánh xạ từ `controller.progress(step_id, status, detail)` hiện có: `running`, `done`, `waiting_approval`, `waiting_review`, `needs_help`, `failed`, `stopped`, `refused` giữ nguyên tên; `rejected` hiện là `stopped` với chi tiết "Bạn không duyệt"; `auto_approved` (chỉ sandbox) hiện là `running`.

### 9.3 Luật rủi ro và chế độ (mỗi luật có test)

| # | Luật |
| --- | --- |
| R1 | `check_workflow` từ chối và không chạy bước nào khi: engine hoặc `schema_version` sai cặp; `risk`/`mode` sai giá trị; `money` + `auto`; `write` mà `mode` khác `approve`; thiếu `target`, `value` (cho `fill`, `select`), `save_as` (cho `read_value`); thiếu giá trị đầu vào; hành động chưa hỗ trợ. |
| R2 | Chạy (không phải Chạy thử, không phải sandbox) chỉ nhận workflow `approved` có digest khớp bản lưu trên máy. |
| R3 | Bước `money` khi `driver.is_mock()` sai → `refused`, không có lệnh `run_act` nào được gửi. Kiểm ngay trước bước đó, không chỉ lúc bắt đầu. |
| R4 | Bước `write` khi không phải mock và `allow_write_off_mock` sai → hỏi GDV với mã `write_on_real` (Tự làm, Dừng); không có `run_act`. |
| R5 | Chạy thử không phát bước nào có `risk` khác `read`. |
| R6 | Bước `approve`: không có `run_act` trước khi `decide` trả "approve" với đúng `ask_id` đang mở. `AutoController` chỉ được dùng khi `sandbox=True` và `driver.is_mock()` đúng. |
| R7 | Một lần Duyệt cho nhiều nhất một lần phát. "Thử lại" trên bước `approve` luôn hỏi Duyệt lại. |
| R8 | Bước `write`/`money` đã phát (mã `no_effect`, `cleared_by_page`, `value_not_set`, `script_error`, `uncertain`) không có lựa chọn "Thử lại". |
| R9 | Bước `click` có nhãn khớp `^(duyệt\|từ chối\|phê duyệt\|approve\|reject)$` (không phân biệt hoa thường) → `refused` ở mọi màn hình: agent không bao giờ bấm nút phê duyệt của hệ thống nghiệp vụ. |
| R10 | `ambiguous`, `low_confidence`, hoặc không thấy sau 15 giây → hỏi GDV. Runner không bao giờ tự chọn một trong nhiều phần tử. |
| R11 | Sau Dừng khẩn không còn `run_act` nào được gửi; trạng thái lần chạy thành `stopped` trong 1 giây; câu hỏi đang mở được trả lời "không". |
| R12 | Đang `running` mà canvas không hỏi trạng thái quá 10 giây → tự Dừng khẩn với lời "Mất kết nối với trang điều khiển". Không áp dụng khi đang chờ GDV trả lời. |
| R13 | Giá trị đầu vào và giá trị đọc được không xuất hiện trong: kết quả `run_workflow`, `progress`, lời báo lỗi, audit, `agent.log`, file trong `home`. |
| R14 | `read_value` không đọc ô `password`, `hidden`, ô có tên giống mật khẩu/OTP, ô có nhãn thuộc loại `ignore`. |
| R15 | Không Chạy khi đang Ghi và ngược lại; mỗi lúc chỉ một lần chạy. |
| R16 | `sandbox=True` chỉ chạy trên mock (luật hiện có). |

**Mock là gì.** `IeDriver.is_mock()` gọi `run_snapshot` và trả đúng khi `host == "127.0.0.1:<cổng của trang quản lý>"` và `path` bắt đầu bằng `/mock-touchpoint/`. Mọi trang khác là "trang thật", kể cả môi trường thử của ngân hàng.

**Quyết định D4a (ai bấm Duyệt).** Người đang chạy flow bấm Duyệt trên canvas cho từng bước `write`/`money`, trong phiên của chính họ. Đây là xác nhận từng bước của người chịu trách nhiệm, không thay cho phê duyệt của người kiểm soát. Lý do: đúng `docs/design.md` mục 6 ("Chờ GDV duyệt") và mỗi GDV chỉ chạy trong phiên của mình.

**Quyết định D4b (maker-checker).** Phê duyệt của người kiểm soát vẫn nằm trong hàng chờ của hệ thống nghiệp vụ, do người đó bấm trên IE của mình. Learner đã cắt flow trước nút `human_only`; R9 chặn thêm lúc chạy. Trong PoC không có kênh duyệt từ máy khác. Lý do: không có đường nối an toàn giữa hai phiên, và quy tắc cứng cấm agent bấm Duyệt thay người.

**Bảo vệ cú bấm Duyệt trên canvas:** mỗi câu hỏi có `ask_id` ngẫu nhiên, `decide` phải gửi lại đúng `ask_id`; nút Duyệt bị khoá 800 ms đầu (chống bấm đúp sang câu hỏi kế); nút không nhận focus mặc định và phím Enter không kích nó.

**Quyết định D4c (ghi dữ liệu trên trang thật).** Mặc định tắt (`settings.json`: `ie_allow_write_on_real: false`, không có trên giao diện). Khi tắt, flow trên trang thật tự chạy các bước `read` và dừng hỏi ở bước `write` (R4). Lý do: quy tắc cứng 6 nói PoC không thao tác hệ thống thật; chủ dự án bật khoá này khi đã có môi trường thử được phép ghi.

### 9.4 Dừng khẩn

Nút «Dừng khẩn» luôn hiện và không bao giờ bị khoá khi có lần chạy. Khi bấm (`POST /api/run/stop`):

1. Đặt cờ dừng. Runner kiểm cờ trước mỗi bước, trong mọi vòng chờ (bước chờ ≤ 0,3 giây) và ngay sau mỗi câu hỏi.
2. Câu hỏi đang mở (Duyệt, xem, hỏi) được trả lời "không"; Dừng khẩn thắng mọi câu trả lời.
3. Gửi `run_cancel` để huỷ hành động đã hẹn mà chưa chạy trong trang.
4. Không gửi thêm lệnh nào. Hành động trang đã thực hiện xong thì không hoàn tác được; canvas ghi rõ ô nào đã xong, ô nào đã dừng.
5. Xoá giá trị đầu vào và giá trị đã đọc khỏi bộ nhớ. Ghi audit với `status: "stopped"`.
6. Không đóng IE, không tải lại trang. Không chạy tiếp từ giữa: muốn chạy lại thì bấm Chạy từ đầu.

**Quyết định D8.** Không có "chạy tiếp" sau Dừng khẩn. Lý do: sau khi dừng không biết chắc trạng thái trang; chạy tiếp là đoán.

## 10. Đầu vào, giá trị đọc, sửa flow, vòng đời

### 10.1 Form đầu vào (câu hỏi 2)

- Form hiện khi chọn ô «Bắt đầu» và luôn hiện trước khi bấm Chạy thử hoặc Chạy. Mỗi tham số trong `required_inputs(workflow)` là một ô chữ; tham số có `default` hiện sẵn giá trị đó.
- Nhãn ô: `inputs[].label`, không có thì `name`. Dưới ô nhạy cảm (có `value_class`) ghi "Chỉ dùng cho lần chạy này, không được lưu."
- Ô nhập là `type="text"`, `autocomplete="off"`. Không dùng `localStorage`. Chạy xong, ô của tham số có `value_class` bị xoá trắng.
- Kiểm tra ở Core (`POST /api/run/start`), trả lỗi 400 bằng lời thường:
  - bắt buộc, sau khi cắt khoảng trắng hai đầu không rỗng;
  - dài tối đa 200 ký tự, không có ký tự xuống dòng hay ký tự điều khiển;
  - `type: "number"`: chỉ gồm chữ số, dấu chấm, dấu phẩy, dấu trừ đứng đầu;
  - `type: "date"` và `string`: không ép định dạng (định dạng do trang quyết định; sai thì trang báo và Runner dừng hỏi với `cleared_by_page`).
- Điền vào trang: bước `fill` thay `{tên}` rồi gọi 8.2.
- Ghi log: chỉ tên tham số, `value_class` và việc "đã nhập". Không ghi giá trị, không ghi độ dài.

**Quyết định D2.** Ô chữ thường (GDV thấy thứ mình gõ), giá trị gửi một lần trong `POST /api/run/start`, sống trong bộ nhớ của lần chạy và bị xoá khi lần chạy kết thúc. Lý do: GDV cần soát số CIF trước khi chạy; quy tắc cứng 1 chỉ cho lưu loại trường.

### 10.2 Đọc thông tin chỉ xem (câu hỏi 3)

- Loại ô: bước `read_value` (đã có trong schema: `target`, `save_as`, `risk: "read"`, `mode: "auto"`).
- Learner không tự sinh bước này cho IE (không có sự kiện "đọc"). GDV thêm bằng «Chọn ô cần đọc» (10.3).
- Ô đủ điều kiện: `INPUT` chữ (kể cả `readOnly`, `disabled`), `TEXTAREA`, `SELECT` (lấy chữ của mục đang chọn), và ô chữ lá (`TD`, `TH`, `SPAN`, `DIV`, `LABEL`, `B` không có phần tử con). Không bao giờ: `password`, `hidden`, `file`, tên giống mật khẩu/OTP/PIN, nhãn thuộc loại `ignore`.
- Giữ giá trị: chỉ trong bộ nhớ của RunSession (`values`), để dùng lại ở bước sau dưới dạng `{tên}` và để hiện ở bảng «Thông tin agent đã đọc». Xoá khi: bấm «Đóng lần chạy», bắt đầu lần chạy mới, đổi flow, Dừng khẩn, 10 phút sau khi lần chạy kết thúc, agent thoát.
- Hiện đủ chữ cho GDV (đó là dữ liệu đang có trên màn hình IE của chính họ), chỉ trên trang `localhost` của máy này; trả lời `/api/run/state` có `Cache-Control: no-store` (đã có).
- Audit chỉ ghi: tên biến, `value_class` suy từ nhãn, `read: true`. Không ghi giá trị, không gửi lên máy chủ, không đưa vào `LLMClient`.

**Quyết định D3.** Có đọc giá trị, do GDV chủ động chọn từng ô; giá trị chỉ ở bộ nhớ và trên canvas của máy đó. Lý do: khớp `docs/design.md` 4.3 ("Giá trị chỉ nằm trong Runner trên máy GDV") và quy tắc cứng 1, 2, 8.

### 10.3 Sửa flow (câu hỏi 5)

Làm được trong mốc này (mỗi thao tác tạo version mới ở `draft`, phải Chạy thử và Duyệt agent lại):

| Thao tác | Luật |
| --- | --- |
| Đổi chế độ một bước | `read`: `auto`, `review`, `approve`. `money`: `review`, `approve`. `write`: chỉ `approve`. (Luật hiện có của `revise`.) |
| Xoá một bước | Từ chối nếu bước đó tạo biến (`save_as`) mà bước sau còn dùng, hoặc nếu flow hết bước. Tham số không còn bước nào dùng thì bị bỏ khỏi `inputs`. |
| Đổi tên flow | Trường `title`, 1 đến 80 ký tự. |
| Thêm bước đọc | Chỉ `read_value`. Máy chủ tự đặt `risk: "read"`, `mode: "auto"`, `id`, và từ chối mọi hành động khác. |

Không làm: sắp xếp lại, thêm bước bấm hoặc nhập, đổi `risk`, đổi tên từng bước. Muốn đổi trình tự thì Ghi lại và Học lại.

**Quyết định D5.** Bộ sửa tối thiểu như bảng trên. Lý do: bốn thao tác này không nới lỏng được luật rủi ro (không ai đổi được `risk`), còn sắp xếp lại hay thêm bước bấm là tạo ra trình tự chưa ai làm mẫu.

**«Chọn ô cần đọc» (pick).** GDV chọn một ô trên canvas, bấm «Thêm ô cần đọc sau bước này», rồi bấm vào ô thông tin trên trang IE:

- Cầu: `{"cmd":"start","id":<tab>,"mode":"pick"}`; `poll`/`stop` như cũ. Chế độ pick đặt `window.__rkPick = true` thay cho `__rkRec`.
- `page_recorder.js` khi `__rkPick` đúng: cú bấm đầu tiên vào phần tử đủ điều kiện (10.2) sinh một dòng `kind: "pick"` (tag, id, name, nhãn theo `labelOf`, vị trí; không có giá trị, không có chữ của chính ô đó) rồi tắt `__rkPick`. Phần tử không đủ điều kiện thì bỏ qua.
- `ie/recorder.py`: hàm `pick_target(line)` trả `{"selectors": [...], "label": ..., "tag": ...}` bằng đúng `_selectors` và `_mask` hiện có.
- Core gửi `add` lên máy chủ với `save_as = slug(nhãn)` (thêm hậu tố `_2`... nếu trùng).

### 10.4 Vòng đời một flow IE

| Trạng thái | Hiện | Nút dùng được |
| --- | --- | --- |
| `draft` | Bản nháp | Chạy thử, sửa |
| `draft` + lần Chạy thử gần nhất của đúng version này đạt | Bản nháp, đã thử đạt | Chạy thử, Duyệt agent này, sửa |
| `approved` | Đã duyệt | Chạy, Chạy thử, sửa (sửa xong quay về Bản nháp) |

- **Chạy thử** (`kind: "trial"`): chạy trên trang GDV chọn, chỉ các bước `read` (R5). Kết thúc `finished` thì Core gửi `post_test_run` lên máy chủ và ghi `trial` vào kho flow.
- **Duyệt agent này**: Core gọi `set_status(tested)` rồi `set_status(approved)`, tải lại bản `approved` (kiểm digest), ghi đè kho flow. Chủ agent tự duyệt agent của mình (`docs/design.md` mục 2, bước 4). Không có máy chủ thì báo "Cần máy chủ để duyệt agent".
- **Chạy** (`kind: "run"`): chỉ bản `approved` (R2). Không cần máy chủ lúc chạy; audit được đệm.

**Quyết định D10a.** Với IE, "chạy ở sandbox trước" được thay bằng Chạy thử chỉ-đọc trên chính trang đích. Lý do: không có bản sao TouchPoint để thử, và flow học trên TouchPoint không chạy được trên mock (selector khác). Bước ghi và tiền vì vậy chưa được thử trước lần chạy thật đầu tiên; bù lại chúng luôn dừng chờ Duyệt.

## 11. Audit (câu hỏi 9)

Một file JSON cho mỗi lần chạy, ghi dần sau từng bước vào `<home>/audit/outbox/<run_id>.json`. Kết thúc lần chạy (mọi trạng thái cuối) thì gửi `POST {server}/runs`; thành công chuyển file sang `<home>/audit/sent/`. Không gửi được thì để lại trong `outbox`; mỗi lần bắt đầu hoặc kết thúc một lần chạy, Core thử gửi lại mọi file còn trong `outbox`.

```json
{
  "run_id": "r-20261116-093015-4f2a", "kind": "run", "engine": "ie",
  "workflow_id": "van-tin-khach-hang", "version": 2, "digest": "<sha256>", "server_verified": true,
  "user": "gdv01", "machine": "PC-QUAY-07", "agent_version": "0.4.0",
  "page": {"title": "TouchPoint", "host": "tp.noi-bo:8080", "mock": false},
  "started_at": "2026-11-16T02:30:15Z", "ended_at": "2026-11-16T02:30:41Z",
  "status": "finished", "message_code": "finished",
  "inputs": [{"name": "ma_khach_hang", "value_class": "cif_number", "supplied": true}],
  "steps": [
    {"step_id": "s1_ma_khach_hang", "index": 0, "action": "fill", "risk": "read", "mode": "auto",
     "label": "Mã khách hàng", "started_at": "...", "ended_at": "...", "status": "done",
     "locate": {"how": "id", "score": 1.0, "counts": [1, 1, 1, 1]},
     "effect": {"code": "ok", "page_changed": false},
     "decisions": [], "inputs_used": ["ma_khach_hang"], "read": null},
    {"step_id": "s5_luu", "index": 4, "action": "click", "risk": "write", "mode": "approve",
     "label": "LƯU", "status": "done",
     "locate": {"how": "label", "score": 0.9, "counts": [1, 1]},
     "effect": {"code": "ok", "page_changed": true},
     "decisions": [{"kind": "approve", "answer": "approve", "at": "...", "by": "gdv01"}],
     "inputs_used": [], "read": null}
  ]
}
```

- `user` là `%USERNAME%`, `machine` là `%COMPUTERNAME%` (`docs/design.md` mục 6: mỗi lần chạy ghi mã người dùng, mã máy, version agent).
- `label` là nhãn đã che lúc ghi (đã nằm trong workflow). `page.title` đi qua `_mask`. `page.host` không kèm đường dẫn hay query.
- **Không bao giờ ghi:** giá trị GDV nhập, giá trị đọc được, độ dài của chúng, chữ trên trang ngoài nhãn đã che, URL đầy đủ, nội dung hộp thoại, ảnh màn hình.
- Tự kiểm trước khi ghi: `audit.assert_clean(record, secrets)` tìm từng giá trị đầu vào và giá trị đã đọc (dài từ 3 ký tự) trong chuỗi JSON của bản ghi; thấy thì thay trường đó bằng `"[đã che]"` và đặt `"scrubbed": true`.
- Máy chủ: `POST /runs` (201; gửi lại cùng `run_id` trả 200 với `"already": true`), `GET /runs?workflow_id=` (danh sách: `run_id`, `workflow_id`, `version`, `status`, `user`, `started_at`). Bảng SQLite `runs(run_id PRIMARY KEY, workflow_id, version, status, started_at, document)`. Dashboard vẫn là task 3.5.

**Quyết định D9.** Audit mốc này không có ảnh màn hình. Lý do: chưa có cách che vùng nhạy cảm trên ảnh trang IE; gửi ảnh chưa che vi phạm quy tắc cứng 2. Ghi rõ ở mục 19.

## 12. Route của Core (trang quản lý)

Mọi `POST` cần header `X-Rookie: 1` (đã có). Lỗi cho GDV là `{"error": "<lời thường>"}` với mã 400.

| Route | Yêu cầu | Trả lời |
| --- | --- | --- |
| `GET /api/flows` | | `{"flows":[{"id":"van-tin-khach-hang","title":"Vấn tin khách hàng","version":2,"status":"draft","status_text":"Bản nháp, đã thử đạt","trial_ok":true,"legacy":false,"engine":"ie","learned_at":"...","inputs":[{"name":"ma_khach_hang","label":"Mã khách hàng","type":"string","sensitive":true,"default":null}],"steps":[{"id":"s1_ma_khach_hang","action":"fill","text":"Nhập vào «Mã khách hàng»","risk_key":"read","mode_key":"auto","risk":"chỉ xem","mode":"tự chạy"}]}]}` |
| `POST /api/run/start` | `{"flow_id":"van-tin-khach-hang","kind":"trial","window":"Internet Explorer: TouchPoint","inputs":{"ma_khach_hang":"900001"}}` | `{"run_id":"r-20261116-093015-4f2a"}`. `kind`: `trial` hoặc `run`. |
| `GET /api/run/state` | | `{"run":null}` hoặc `{"run":{"id":"r-...","flow_id":"...","version":2,"kind":"run","status":"waiting_approval","message":"","page":{"title":"TouchPoint","mock":false},"nodes":[{"id":"s1_ma_khach_hang","state":"done","detail":""},{"id":"s5_luu","state":"waiting_approval","detail":""}],"ask":{"id":"a-7c1e","kind":"approve","step_id":"s5_luu","title":"Bước 5: Bấm «LƯU»","text":"Agent sẽ bấm «LƯU» trên trang «TouchPoint». Hãy xem màn hình Internet Explorer trước khi Duyệt.","options":["approve","reject"]},"values":[{"name":"ho_ten","label":"Họ tên","value":"NGUYEN VAN A"}],"log":[{"at":"09:30:16","text":"Bước 1 xong"}]}}`. Mỗi lần gọi là một nhịp tim (R12). |
| `POST /api/run/decide` | `{"run_id":"r-...","ask_id":"a-7c1e","answer":"approve"}` | `{}`. `answer`: `approve`, `reject` (hỏi Duyệt); `continue`, `stop` (hỏi xem); `retry`, `skip`, `stop` (dừng hỏi). Sai `ask_id` hoặc `answer` không có trong `options`: 400 "Câu hỏi này đã đóng." |
| `POST /api/run/stop` | `{}` | `{"was_running":true}` |
| `POST /api/run/close` | `{}` | `{}`. Chỉ khi lần chạy đã kết thúc; xoá `values` và bỏ lần chạy khỏi bộ nhớ. |
| `POST /api/flows/edit` | `{"flow_id":"...","modes":{"s3_xem":"review"},"remove":["s4_dong"],"title":"Vấn tin KH"}` (mỗi trường tuỳ chọn, cần ít nhất một) | flow mới theo dạng của `GET /api/flows` |
| `POST /api/flows/approve` | `{"flow_id":"..."}` | flow mới |
| `POST /api/flows/delete` | `{"flow_id":"..."}` | `{}` (chỉ xoá bản trên máy) |
| `POST /api/pick/start` | `{"flow_id":"...","after":"s2_ho_so","window":"Internet Explorer: TouchPoint"}` | `{"picking":true}` |
| `GET /api/pick/state` | | `{"picking":true}` hoặc `{"picking":false,"added":{"text":"Đọc giá trị ở «Họ tên»"}}` |
| `POST /api/pick/cancel` | `{}` | `{}` |
| `POST /api/mock/open` | `{}` | `{"title":"Mock TouchPoint"}` (gọi `run_open` với `visible: true`) |

`text` trong `ask` và `log` không bao giờ chứa giá trị. `message` và `detail` là lời thường sinh từ mã (bảng lời ở `webui/run.py`), không lấy từ `str(exception)`.

Mở rộng máy chủ: `POST /workflows/{id}/versions/{v}/revise` nhận `{"modes": {...}, "remove": [...], "add": [{"after": "<step_id>" | null, "step": {"action": "read_value", "target": {...}, "save_as": "ho_ten"}}], "title": "..."}`; mọi trường tuỳ chọn, cần ít nhất một; luật ở 10.3; kết quả phải qua `validate_workflow`. `ServerClient` thêm `revise(...)`, `post_run(document)`.

## 13. Giao diện tab Luồng (câu hỏi 1, 8)

**Quyết định D1.** Chạy ngay trên canvas hiện có của tab Luồng, không mở khung riêng. Lý do: đúng ý chủ dự án; GDV chỉ học một màn hình; trạng thái gắn vào đúng ô của bước. Trang IE không nhúng được vào canvas (IE cũ, khác trình duyệt), nên lời hướng dẫn ghi: "Đặt cửa sổ Internet Explorer cạnh cửa sổ này để nhìn agent làm."

Bố cục từ trên xuống (một cột, chữ to, không thuật ngữ kỹ thuật):

1. **Thanh flow:** ô chọn flow; nhãn trạng thái (Bản nháp / Bản nháp, đã thử đạt / Đã duyệt); ô chọn «Trang để chạy» (các trang IE đang mở, nút Tải lại); liên kết nhỏ «Mở trang thử».
2. **Thanh nút:** «Chạy thử», «Duyệt agent này», «Chạy», và khi có lần chạy: «Dừng khẩn» (đỏ, bên phải, luôn bấm được). Khi đang chạy, ba nút đầu bị khoá.
3. **Canvas:** các ô như hiện nay (viền trái theo rủi ro). Mỗi ô thêm một dòng trạng thái có biểu tượng và chữ (bảng 9.2); ô đang chạy có viền nhấp nháy (tắt khi `prefers-reduced-motion`); canvas tự cuộn tới ô đang chạy. Trạng thái luôn có chữ, không chỉ dựa vào màu.
4. **Hộp hành động** (ngay dưới canvas, chỉ một hộp tại một thời điểm):
   - Chưa chạy: form đầu vào (10.1) với tiêu đề "Thông tin cho lần chạy này".
   - Đợi Duyệt: tiêu đề bước, câu "Agent sẽ bấm «…» trên trang «…». Hãy xem màn hình Internet Explorer trước khi Duyệt.", nút «Duyệt» và «Không duyệt».
   - Đợi bạn xem: "Bước này đã chạy xong. Xem kết quả rồi chọn.", nút «Đi tiếp» và «Dừng».
   - Dừng hỏi bạn: một câu lời thường theo mã (bảng dưới), các nút theo 8.7: «Thử lại», «Tôi đã tự làm bước này, đi tiếp», «Dừng».
   - Kết thúc: câu kết quả và nút «Đóng lần chạy».
5. **Thông tin agent đã đọc:** bảng hai cột (Tên, Giá trị), dòng chú "Chỉ hiện trên máy này, không được lưu." Ẩn khi chưa có giá trị.
6. **Nhật ký lần chạy:** danh sách dòng giờ và lời thường ("Bước 3 xong", "Bạn đã duyệt bước 5").
7. **Sửa flow** (khi không có lần chạy, bấm vào một ô): ô chọn chế độ (chỉ các lựa chọn hợp lệ), nút «Xoá bước này», nút «Thêm ô cần đọc sau bước này»; ở ô «Bắt đầu» có ô đổi tên flow.

Lời cho từng mã dừng hỏi:

| Mã | Lời hiện cho GDV |
| --- | --- |
| `not_found` | Không thấy «…» trên màn hình sau 15 giây. Màn hình có thể khác với lúc ghi, hoặc đã hết phiên đăng nhập. |
| `ambiguous` | Có nhiều chỗ giống «…» trên màn hình, agent không chọn thay bạn. |
| `low_confidence` | Agent không chắc đâu là «…» trên màn hình này. |
| `not_editable` | Ô hoặc nút «…» đang bị khoá, chưa thao tác được. |
| `too_long` | Giá trị dài hơn mức ô «…» cho phép. |
| `no_option` | Danh sách «…» không có lựa chọn này. |
| `denied` | Phần màn hình này không cho agent đọc. |
| `secret` | Ô «…» là ô bí mật, agent không đọc. |
| `blocked` | Trang đang hiện một hộp thoại. Hãy trả lời hộp thoại trên Internet Explorer rồi bấm Thử lại. |
| `uncertain` | Agent không chắc bước «…» đã được thực hiện chưa. Hãy xem màn hình Internet Explorer. |
| `no_effect`, `value_not_set`, `script_error` | Agent đã thao tác «…» nhưng không thấy màn hình thay đổi. |
| `cleared_by_page` | Trang không nhận giá trị ở ô «…». |
| `write_on_real` | Bước «…» ghi dữ liệu trên hệ thống thật. Bản thử nghiệm chưa cho agent làm bước này. Bạn tự làm trên màn hình rồi bấm đi tiếp. |

Tên hành động nhất quán (quy tắc cứng 10): Ghi, Học, Duyệt, Chạy, Dừng khẩn. «Chạy thử» và «Duyệt agent này» là biến thể có thêm chữ để phân biệt với «Chạy» và «Duyệt» của từng bước.

## 14. Tác động tới schema (quy tắc cứng 5)

**Quyết định D12. Không đổi schema, không tăng `schema_version`.** Lý do: mọi thứ cần đã có trong bản 2:

| Cần | Đã có |
| --- | --- |
| Form đầu vào | `inputs[].name`, `type`, `value_class`, `label`, `default` |
| Bước đọc | `action: "read_value"` + `target` + `save_as` |
| Đổi tên flow | `title` |
| Trạng thái | `status` |

Trạng thái ô, điểm tin cậy, kết quả Chạy thử là dữ liệu lúc chạy, nằm trong RunSession, kho flow và audit, không nằm trong workflow. Không đổi tên từng bước chính là để khỏi thêm trường mới.

Thay đổi không thuộc schema nhưng phải có test: `config/risk-rules.json` khối `ie` (task 2.18).

## 15. Danh sách task (nối tiếp Gate 2 trong `docs/tasks.md`)

Làm đúng thứ tự. Mỗi task một commit, viết test trước. Chạy `cd windows-agent; pytest` (và `cd server; pytest` nếu sửa máy chủ) trước khi báo xong. Test cần IE ẩn dùng fixture `hidden_ie` và tự bỏ qua (`pytest.skip`) khi máy không tạo được `InternetExplorer.Application`.

| Task | Việc | File | Nghiệm thu (test viết trước) |
| --- | --- | --- | --- |
| 2.10 | Tách `page_lib.js` khỏi bộ ghi, thêm `mask`; cầu nạp lib trước bộ ghi | `ie/page_lib.js` (mới), `ie/page_recorder.js`, `ie/ie-bridge.ps1`, `tests/ie_mshtml_check.ps1`, `tests/test_ie_bridge.py` | Test bộ ghi hiện có vẫn qua không sửa kỳ vọng. Test mới: `mask` trong trang cho cùng kết quả với `_mask` của Python trên 8 nhãn mẫu (có số tài khoản, số tiền có dấu chấm, chuỗi dài hơn 60). Nạp lib không bật ghi (`__rkRec` vẫn `undefined`). |
| 2.11 | Mock TouchPoint và fixture IE ẩn; lệnh cầu `run_open`, `run_close` | `webui/mock_touchpoint/*.html` (mới), `webui/server.py` (phục vụ `/mock-touchpoint/`), `ie/ie-bridge.ps1`, `ie/bridge.py`, `tests/conftest.py`, `tests/test_ie_mock.py` (mới) | `GET /mock-touchpoint/index.html` trả 200; đường dẫn ra ngoài thư mục bị 404. Trên IE ẩn: `probe` thấy khung `desktopFrame/rtop/main/fraProfileArea`, mọi khung mode 5. `run_open` từ chối URL không phải `127.0.0.1/mock-touchpoint/`. `run_close` không đụng cửa sổ IE khác. Nội dung mock ở 16.3. |
| 2.12 | `page_runner.js`: `find`, `read` | `ie/page_runner.js` (mới), `tests/ie_runner_mshtml_check.ps1` (mới), `tests/test_ie_page_runner.py` (mới) | `htmlfile` (đặt `__rkNoLayout`): id trùng trả 2 phần tử; nhãn ô; nhãn «dòng 2»; ô `display:none` không nằm trong `m` nhưng tính vào `h`; `read` ô `readOnly` trả giá trị; `read` ô mật khẩu, ô ẩn, ô tên `otp` trả `refused:secret`; `uid` sai `expect` trả `moved`. |
| 2.13 | `page_runner.js`: `act`, `result`, `cancel` | `ie/page_runner.js`, `tests/test_ie_page_runner.py` | Trên IE ẩn với mock: `fill` làm handler `onchange` chạy và kết quả `ok`; ô `readOnly` → `refused:not_editable`; quá `maxLength` → `refused:too_long`; `click` tab làm panel đổi; `click` nút có `confirm` → `result` vẫn `pending` sau 1 giây; cùng token gọi lần hai trả `seen` và bộ đếm của mock không tăng; `enter_keys` làm ô tra cứu chạy; `cancel` trước khi timer chạy thì không có hành động. |
| 2.14 | Lệnh cầu `run_bind`, `run_find`, `run_act`, `run_result`, `run_read`, `run_snapshot`, `run_cancel`, `run_unbind` và hàm Python tương ứng; tự mở lại cầu khi hết thời gian chờ | `ie/ie-bridge.ps1`, `ie/bridge.py`, `tests/test_ie_bridge.py` | Trên IE ẩn: từng lệnh trả đúng dạng ở mục 5; khung không tồn tại → `frame_missing`; khung khác nguồn của mock → `denied`; hai tab cùng tên → `several tabs`; giá trị có dấu tiếng Việt và dấu nháy đi qua `run_act` nguyên vẹn; đầu ra của cầu toàn ASCII; `sig` đổi sau khi bấm tab. Test với tiến trình cầu giả không trả lời: `IeBridge` đóng và mở lại. |
| 2.15 | Chấm điểm định vị | `ie/locate.py` (mới), `tests/test_ie_locate.py` (mới) | Test bảng cho từng nhánh 7.2: id duy nhất 1,0; name 0,9 (+0,1 khi nhãn đồng ý); nhãn + vị trí 0,9; id trùng gỡ bằng giao 0,8; chỉ vị trí 0,5 → `LOW_CONFIDENCE`; bất đồng −0,2; sai loại → 0; mọi tập rỗng → `NOT_FOUND`; nhiều ứng viên → `AMBIGUOUS`; ngưỡng 0,8 và 0,9 theo `risk`; selector sai cú pháp bị bỏ; selector thiếu `frame=` dùng khung của selector đầu. |
| 2.16 | Mở rộng `runner.py` theo 9.1 | `runner.py`, `tests/test_runner.py` | Toàn bộ test Java hiện có qua không sửa. Test mới với driver giả: R1 đến R10, R16; `NeedsHelp` → `help` với đúng lựa chọn theo 8.7; "Thử lại" trên bước `approve` hỏi Duyệt lần hai; "Tự làm" cho `skipped` và chạy tiếp; không có `controller.help` thì kết thúc `needs_help` như cũ; `trial` dừng trước bước `write` đầu tiên với `finished`. |
| 2.17 | `IeDriver` | `ie/driver.py` (mới), `tests/test_ie_driver.py` (mới), `tests/fixtures/workflow-mock-touchpoint.json` (mới) | Với cầu giả: token chưa có kết quả thì gọi lại không sinh `run_act` mới; hết thời gian chờ giữa `run_act` → `NeedsHelp("uncertain")`; `pending` quá 5 giây → `blocked`; Enter hai pha, pha 2 không xảy ra với bước `write`; `is_mock` theo host và path. Trên IE ẩn: workflow fixture (hợp lệ theo schema) chạy hết trên mock bằng `AutoController` + `sandbox=True`, bộ đếm "số lần gửi" của mock bằng 1, giá trị đọc được đúng dữ liệu synthetic. |
| 2.18 | Bảng rủi ro IE: bấm dòng danh sách là `read`; Enter ở ô «mã khách hàng» là `read`; nhãn tab chỉ-xem đã biết | `config/risk-rules.json`, `server/tests/test_risk.py` | Sự kiện `ie` click nhãn «dòng 2» → `read`; submit nhãn «Mã khách hàng» → `read`; click «Hồ sơ», «Thông tin tài khoản» → `read`; nút «LƯU» vẫn `write`; nút lạ vẫn `write`; nút «Duyệt» ở màn hình phê duyệt vẫn `human_only`. Luật mới đặt **sau** luật `money` và `human_only`, **trước** luật `write`. |
| 2.19 | Kho flow đầy đủ trên máy; `GET /api/flows` dạng mới; mục cũ là `legacy` | `webui/core.py`, `tests/test_webui.py` | Học xong có `<home>/flows/<id>.json` chứa workflow và digest; học lại cùng tên thay bản cũ; sửa tay file làm lệch digest thì `run/start` từ chối; mục cũ trong `settings.json` hiện `legacy: true` và không chạy được; file flow không chứa giá trị nhập (tìm chuỗi). |
| 2.20 | `RunSession`, `CanvasController`, route `run/start`, `state`, `decide`, `stop`, `close`; kiểm đầu vào; nhịp tim | `webui/run.py` (mới), `webui/core.py`, `tests/test_webui_run.py` (mới) | Với driver giả: trạng thái ô đi đúng bảng 9.2; `decide` sai `ask_id` bị từ chối và không có gì chạy; Dừng khẩn trong lúc chờ Duyệt → `stopped` trong 1 giây và không có hành động; không hỏi trạng thái 10 giây (đồng hồ giả) → tự dừng; đầu vào rỗng, quá 200 ký tự, có xuống dòng, số sai dạng → 400; Chạy khi đang Ghi → 400; giá trị nhập không có trong bất kỳ trả lời route nào ngoài `values` do `read_value` sinh, và không có trong file nào dưới `home` (tìm chuỗi); `close` xoá `values`. |
| 2.21 | Audit trên máy và trên máy chủ | `audit.py` (mới), `server/app/main.py`, `server/app/storage.py`, `server_client.py`, `tests/test_audit.py` (mới), `server/tests/test_api.py` | Bản ghi đúng dạng mục 11; giá trị nhập và giá trị đọc không có trong file (tìm chuỗi); `assert_clean` che và đặt `scrubbed` khi cố tình nhét giá trị vào nhãn; máy chủ tắt thì file ở `outbox`, bật lại thì lần chạy sau gửi đủ và chuyển sang `sent`; gửi trùng `run_id` trả `already`. |
| 2.22 | Vòng đời: Chạy thử gửi `post_test_run`; `POST /api/flows/approve` | `webui/core.py`, `tests/test_webui_run.py` | Chưa Chạy thử đạt thì `approve` bị từ chối bằng lời thường; Chạy thử `finished` rồi `approve` → flow `approved`, digest khớp máy chủ; `kind: "run"` với flow `draft` bị từ chối (R2); máy chủ tắt thì `approve` báo "Cần máy chủ để duyệt agent". |
| 2.23 | Giao diện tab Luồng theo mục 13 | `webui/index.html`, `tests/test_webui.py` | Test tĩnh: trang có các phần tử `runTrial`, `runGo`, `runStop`, `flowApprove`, `runPage`, `askBox`, `valuesBox`, `runLog`, và các chữ «Chạy thử», «Chạy», «Duyệt», «Dừng khẩn»; không có `localStorage`; không còn câu "Trang này chỉ để xem". Kiểm tay theo 16.4 mục A trên mock. |
| 2.24 | Sửa flow: máy chủ `revise` nhận `remove`, `title`, `add`; route `flows/edit`, `flows/delete`; điều khiển trên canvas | `server/app/main.py`, `server/tests/test_api.py`, `server_client.py`, `webui/core.py`, `webui/index.html`, `tests/test_webui.py` | Đặt `auto` cho bước `money` hoặc khác `approve` cho bước `write` bị từ chối; xoá bước tạo biến còn dùng bị từ chối; xoá bước làm tham số mồ côi thì tham số biến mất; `add` với hành động khác `read_value` bị từ chối; `add` có `risk: "write"` do máy khách gửi vẫn ra `read`/`auto`; mỗi lần sửa ra version mới `draft`; `revise` cũ chỉ có `modes` vẫn chạy. |
| 2.25 | «Chọn ô cần đọc» | `ie/page_recorder.js`, `ie/ie-bridge.ps1`, `ie/bridge.py`, `ie/recorder.py`, `webui/core.py`, `webui/index.html`, `tests/test_ie_recorder.py`, `tests/test_webui.py`, `tests/ie_mshtml_check.ps1` | `htmlfile`: ở chế độ pick, bấm ô `readOnly` sinh đúng một dòng `pick` không có giá trị và không có chữ của ô; bấm ô mật khẩu không sinh gì; sau một lần pick thì `__rkPick` tắt; chế độ pick không sinh sự kiện ghi. Core với cầu giả: flow có thêm bước `read_value` đúng vị trí, `save_as` không trùng. |
| 2.26 | Test đầu-cuối trên IE ẩn, lệnh tự kiểm, tài liệu | `tests/test_ie_end_to_end.py` (mới), `__main__.py` (lệnh `ie-run-check`), `install/Kiem-tra-chay-IE.cmd` (mới), `scripts/package-path-b.ps1` (thêm file `.cmd` vào danh sách copy), `docs/design.md` (3C, 6), `docs/tasks.md` (thêm các dòng 2.10 đến 2.26), `windows-agent/README.md` | Trên IE ẩn, máy chủ thật trong thread (như `test_end_to_end.py`): ghi 3 lần trên mock (bấm bằng `click()` qua COM, nhập bằng `__rkHandlers`) → Học → Chạy thử → Duyệt agent → Chạy với khách chưa từng ghi qua các route của Core; bước «LƯU» dừng chờ Duyệt; bước «Chuyển tiền» dừng chờ Duyệt và chỉ gửi một lần; không số CIF nào có trong máy chủ, kho flow, audit (tìm chuỗi). `python -m rookie_agent ie-run-check` in từng dòng ĐẠT/KHÔNG ĐẠT theo 16.4 mục B và trả mã 0 khi đạt hết. |

Giao bản vá (quyết định của chủ dự án: chỉ file đổi): sau mỗi nhóm task đã qua test, tạo zip bằng một lệnh, ví dụ `git archive -o dist\patch-runner-ie.zip HEAD $(git diff --name-only <commit gốc> HEAD -- windows-agent config schemas server/app)`, giải nén đè lên thư mục gói trên máy nội bộ.

## 16. Kế hoạch test

### 16.1 Ba tầng

| Tầng | Chạy ở đâu | Kiểm gì |
| --- | --- | --- |
| Unit, cầu giả, driver giả | Mọi máy | `locate.py`, luật R1 đến R16, RunSession, route, audit, kho flow, sửa flow |
| `htmlfile` (MSHTML thật, quirks) | Windows | Hàm thuần của `page_lib.js`, `page_runner.js` (`find`, `read`, nhãn, `mask`), chế độ pick. Không dùng cho sự kiện, khung, layout, timer (M11) |
| IE ẩn + Mock TouchPoint | Windows tạo được `InternetExplorer.Application` (M1) | Khung lồng nhau, mode 5, sự kiện, `click`, Enter, hộp thoại, token, lệnh `run_*`, chạy trọn flow |

### 16.2 Fixture `hidden_ie`

Trong `tests/conftest.py`: bật máy chủ trang quản lý trên cổng trống với `home` tạm, mở `IeBridge`, gọi `run_open` (`visible: false`) tới `/mock-touchpoint/index.html`, trả `(bridge, port)`; kết thúc gọi `run_close`. `run_open` lỗi thì `pytest.skip("Máy này không tạo được Internet Explorer qua COM")`. Test về hộp thoại mở cửa sổ riêng và luôn `run_close` (cửa sổ ẩn có hộp thoại mở thì kết thúc tiến trình).

### 16.3 Mock TouchPoint (`webui/mock_touchpoint/`)

Trang tĩnh, script ES3, dữ liệu synthetic cố định (5 khách hàng giả, CIF `900001` đến `900005`, tên và số liệu bịa). Mọi trang có `<meta http-equiv="X-UA-Compatible" content="IE=5">` (M2) và tiêu đề gốc «Mock TouchPoint».

| File | Nội dung |
| --- | --- |
| `index.html` | Frameset: `top` (`banner.html`), `desktopFrame` (`desktop.html`) |
| `banner.html` | Chữ tiêu đề và một `iframe` trỏ `http://localhost:<cổng>/mock-touchpoint/other.html` (khác nguồn với `127.0.0.1`, để thử C4) |
| `desktop.html` | Frameset: `left` (`menu.html`), `rtop` (`rtop.html`) |
| `menu.html` | Mục cây là `span` có con trỏ bàn tay: «Hồ sơ khách hàng», «Chuyển tiền thử»; bấm thì đổi trang của `fraProfileArea` |
| `rtop.html` | Frameset một khung `main` (`main.html`) |
| `main.html` | `iframe` tên `fraProfileArea` nạp `profile.html` |
| `profile.html` | Ô «Mã khách hàng» (`id="txtCustomerId"`, `name="txtPartyID"`, `maxlength="12"`), Enter xử lý bằng `onkeydown`, kết quả hiện sau 700 ms. Dải tab bằng `td` có con trỏ bàn tay: «Hồ sơ», «Thông tin tài khoản». Tab Hồ sơ: các ô `readOnly` Họ tên, Ngày sinh, Mã số thuế, trong đó hai ô cùng `id="txtBlank"`; ô «Ghi chú»; nút «LƯU» (hiện "Đã lưu", bộ đếm số lần lưu); nút «LƯU CÓ HỎI» (gọi `confirm` trước). Tab Thông tin tài khoản: bảng ít nhất 3 dòng có con trỏ bàn tay; bấm dòng hiện ô «Số dư» `readOnly`. Một ô mật khẩu và một ô ẩn để thử việc không đọc. |
| `transfer.html` | Tiêu đề «Chuyển tiền thử»; ô «Tài khoản nhận», «Số tiền»; nút «Chuyển tiền» (rủi ro `money`), hiện "Số lần gửi: N" |
| `other.html` | Trang trống cho khung khác nguồn |

### 16.4 Kiểm trên máy có IE thật (sau khi giao bản vá)

**A. Trên Mock TouchPoint, bằng nút trên trang quản lý** (kiểm cả giao diện):

| # | Việc làm | Phải thấy |
| --- | --- | --- |
| A1 | Tab Luồng, bấm «Mở trang thử» | IE mở «Mock TouchPoint» |
| A2 | Tab Ghi và Học: Ghi 3 lần "nhập mã khách hàng, Enter, bấm Hồ sơ, bấm LƯU" với 3 mã khác nhau; bấm Học | Flow mới hiện ở tab Luồng, bước LƯU viền vàng, "chờ bạn duyệt" |
| A3 | Bấm «Chạy thử» với mã `900004` | Các ô chỉ-xem lần lượt Xong; dừng trước LƯU; nhãn thành "Bản nháp, đã thử đạt" |
| A4 | Bấm «Duyệt agent này», rồi «Chạy» | Ô LƯU ở "Đợi Duyệt"; trang IE chưa lưu |
| A5 | Bấm «Duyệt» | Trang IE hiện "Đã lưu", bộ đếm bằng 1; canvas Xong |
| A6 | Chạy lại, bấm «Dừng khẩn» khi ô thứ hai đang chạy | Dừng trong 1 giây; các ô sau vẫn "Chờ"; IE không bị đóng |
| A7 | Ghi và Học flow bấm «LƯU CÓ HỎI»; Chạy; Duyệt | Canvas báo "Trang đang hiện một hộp thoại"; trả lời hộp thoại trên IE, bấm «Thử lại» → Xong; bộ đếm bằng 1 |
| A8 | Ghi và Học flow chuyển tiền trên «Chuyển tiền thử»; Chạy; Duyệt | "Số lần gửi: 1" |
| A9 | «Thêm ô cần đọc» chọn ô Họ tên; Chạy thử lại | Bảng "Thông tin agent đã đọc" hiện họ tên synthetic; bấm «Đóng lần chạy» thì bảng trống |
| A10 | Mở thư mục `%LOCALAPPDATA%\RookieAgent`, tìm mã khách hàng vừa nhập trong mọi file | Không có |

**B. Tự kiểm bằng một lệnh** (bấm đúp `Kiem-tra-chay-IE.cmd`, tức `python -m rookie_agent ie-run-check`): mở Mock TouchPoint trong IE hiện, chạy workflow fixture bằng `AutoController`, in từng dòng:

| # | Dòng in | Điều kiện đạt |
| --- | --- | --- |
| B1 | Chế độ tài liệu | Mọi khung của mock ở mode 5 |
| B2 | Khung lồng nhau | Tới được `desktopFrame/rtop/main/fraProfileArea` |
| B3 | Khung khác nguồn | Bị từ chối, cầu không treo |
| B4 | Điền ô | Handler `onchange` của trang đã chạy |
| B5 | Enter | Kết quả tra cứu hiện ra |
| B6 | Bấm tab | Panel đổi |
| B7 | Bấm dòng danh sách | Ô Số dư hiện ra |
| B8 | Đọc ô chỉ-xem | Đúng giá trị synthetic |
| B9 | Ô mật khẩu, ô ẩn | Không đọc |
| B10 | Hộp thoại | Phát hiện `blocked`, cầu vẫn trả lời (tự bỏ qua bước trả lời, đóng cửa sổ thử) |
| B11 | Gửi một lần | Bộ đếm lưu và bộ đếm chuyển tiền đều bằng 1 |
| B12 | Thời gian | Mỗi lệnh `run_find` dưới 1 giây |

**C. Trên TouchPoint (môi trường thử, tài khoản thử; chỉ bước chỉ-xem):**

| # | Việc làm | Nút hoặc lệnh | Phải thấy |
| --- | --- | --- | --- |
| C1 | Kiểm tra đọc trang | Tab Ghi và Học, «Kiểm tra» (hoặc `python -m rookie_agent ie-probe`) | Đọc được N khung, có ô nhập |
| C2 | Học lại flow vấn tin đã ghi (để nhận bảng rủi ro mới) | «Học» | Các bước tab và dòng danh sách có viền xanh |
| C3 | Chạy thử với một khách thử chưa từng ghi | «Chạy thử» | Mọi ô chỉ-xem Xong; màn hình IE hiện đúng khách đó |
| C4 | Xem Enter ở ô mã khách hàng đi theo pha nào | Nhật ký lần chạy ở C3 | Ghi "Enter: trang tự xử lý" hoặc "Enter: bấm nút gửi của form"; không tra cứu hai lần |
| C5 | Ô có id trùng (`txtBlank`) | «Thêm ô cần đọc» chọn một ô như vậy, «Chạy thử» | Đọc đúng ô đã chọn (cách tìm `intersect`), hoặc dừng hỏi; không đọc nhầm ô |
| C6 | Trang chậm | «Chạy thử» lúc hệ thống chậm | Agent chờ, không báo lỗi trước 15 giây |
| C7 | Hết phiên đăng nhập | Đăng xuất TouchPoint rồi «Chạy thử» | "Không thấy «…»… có thể đã hết phiên đăng nhập"; agent không gõ gì vào trang đăng nhập |
| C8 | Bước ghi trên trang thật | Flow có nút chưa phân loại, «Chạy thử» rồi «Duyệt agent này», «Chạy» | Dừng ở bước đó với lời `write_on_real`; trang không đổi |
| C9 | Dừng khẩn | «Dừng khẩn» giữa chừng ở C3 | Dừng trong 1 giây |
| C10 | Không lưu giá trị | Tìm mã khách thử trong `%LOCALAPPDATA%\RookieAgent` | Không có |
| C11 | Sự kiện sau khi điền | Quan sát C3: ô mã khách hàng có được trang nhận như khi gõ tay không (tự viết hoa, tự định dạng) | Giống gõ tay; khác thì báo nhóm phát triển tên ô và hiện tượng (không gửi giá trị) |

Kết quả B và C ghi vào `docs/spike-ie-run.md` (tạo khi có kết quả thật).

## 17. Rủi ro và cách giảm

| Rủi ro | Cách giảm |
| --- | --- |
| TouchPoint cần sự kiện khác (`onkeypress` từng ký tự, `onpropertychange`) mới nhận giá trị | Trình tự sự kiện là một danh sách ở đầu `page_runner.js`; kiểm C11; sửa bằng bản vá một file |
| Enter trên TouchPoint không đi theo pha nào | Kiểm C4; Runner dừng hỏi (`no_effect`) chứ không đoán; GDV tự nhấn Enter rồi "đi tiếp" |
| Phần lớn nút, tab của TouchPoint chưa phân loại nên là `write` và bị R4 chặn trên trang thật | Task 2.18 thêm nhãn chỉ-xem đã biết; canvas cho thấy bước nào còn vàng để nhóm phát triển bổ sung bảng; chủ dự án quyết định khi nào bật `ie_allow_write_on_real` |
| Dòng danh sách "theo vị trí" chọn nhầm khi danh sách của khách khác dài ngắn khác nhau | Đây là hệ quả của quyết định chỉ lưu vị trí; cần đồng ý giữa nhãn «dòng N» và vị trí mới đạt 0,8, lệch thì dừng hỏi |
| `id` của phần tử chứa dữ liệu khách (ví dụ id dòng là số tài khoản) nằm trong selector | Ngoài phạm vi mốc này; ghi nhận để xử lý ở bộ ghi (che id có từ 3 chữ số liền) |
| Popup, `showModalDialog`, trang mở cửa sổ mới | Ngoài phạm vi; Runner không thấy phần tử và dừng hỏi |
| Hộp thoại mở làm lệnh COM chậm hoặc treo trên IE thật khác với máy đo | Mọi lệnh có timeout 15 giây, cầu tự mở lại, bước thành `uncertain`; kiểm A7, B10 |
| PowerShell bị chính sách máy chặn | Đã là điều kiện của Ghi; Kiểm tra máy báo sớm |
| Máy GDV không tạo được IE ẩn cho tự kiểm | `ie-run-check` dùng IE hiện; test tự động chỉ cần ở máy phát triển |
| Trình duyệt mặc định của máy là IE nên trang quản lý (JS hiện đại) không chạy | Đã là điều kiện của trang quản lý hiện nay; README ghi cần Edge hoặc Chrome để mở trang quản lý |
| Sửa `page_recorder.js` khi tách lib làm hỏng Ghi | Task 2.10 không đổi kỳ vọng của test hiện có; kiểm C1 và ghi thử lại trên máy thật |
| Hai cửa sổ (canvas và IE) làm GDV rối | Lời hướng dẫn đặt hai cửa sổ cạnh nhau; canvas luôn nói bằng chữ agent đang làm gì |

## 18. Danh sách quyết định

| Mã | Quyết định | Lý do một dòng |
| --- | --- | --- |
| D1 | Chạy ngay trên canvas tab Luồng | Đúng ý chủ dự án, một màn hình cho GDV |
| D2 | Đầu vào là form chữ thường, giá trị chỉ trong bộ nhớ lần chạy | GDV cần soát thứ mình gõ; quy tắc cứng 1 |
| D3 | Có `read_value`, GDV tự chọn ô; giá trị chỉ ở bộ nhớ và canvas máy đó | Khớp design 4.3 và quy tắc cứng 1, 2, 8 |
| D4a | Người đang chạy bấm Duyệt từng bước `write`/`money` | Design mục 6; mỗi GDV chạy trong phiên của mình |
| D4b | Phê duyệt của người kiểm soát ở lại hệ thống nghiệp vụ; không duyệt từ xa trong PoC; R9 cấm bấm nút phê duyệt | Quy tắc cứng: agent không tự phê duyệt |
| D4c | Ghi dữ liệu trên trang thật mặc định tắt (`ie_allow_write_on_real`) | Quy tắc cứng 6; chủ dự án bật khi có môi trường được phép |
| D5 | Sửa flow: chế độ, xoá bước, tên flow, thêm bước đọc; không sắp xếp lại | Không thao tác nào nới được luật rủi ro |
| D6a | Điểm bằng chứng, ngưỡng 0,8 (`read`) và 0,9 (`write`/`money`) | Vị trí đơn thuần không bao giờ đủ |
| D6b | Không dùng `LLMClient.locate` | Design mục 6; chưa có dữ liệu đã che để gửi |
| D7a | Hành động phát qua `setTimeout` trong trang | Cầu không treo khi trang mở hộp thoại (M9) |
| D7b | Tìm và hành động bằng script ES3 trong trang, dùng chung hàm nhãn với bộ ghi | Nhanh, nhãn lúc chạy trùng lúc ghi |
| D7c | Enter bằng sự kiện giả hai pha, không `SendKeys` | Không phụ thuộc cửa sổ nào đang có focus |
| D8 | Dừng khẩn là dừng hẳn, không chạy tiếp từ giữa | Không biết chắc trạng thái trang sau khi dừng |
| D9 | Audit không có ảnh màn hình trong mốc này | Chưa che được ảnh trang IE |
| D10a | Chạy thử chỉ-đọc trên trang đích thay cho sandbox | Không có bản sao TouchPoint |
| D10b | Test hành vi trên IE ẩn tạo bằng COM + Mock TouchPoint; `htmlfile` chỉ cho hàm thuần | Đã đo M1, M11 |
| D11 | Kho flow đầy đủ ở `<home>/flows/`, kiểm digest trước khi chạy | Bản rút gọn hiện nay không chạy được |
| D12 | Không đổi schema, không tăng `schema_version` | Bản 2 đã đủ trường |
| D13 | Mở rộng `runner.py` dùng chung thay vì viết Runner riêng cho IE | Một vòng điều khiển, một bộ luật, test Java giữ nguyên |
| D14 | Canvas hỏi trạng thái mỗi 500 ms; mất nhịp 10 giây khi đang chạy thì tự dừng | Không ai nhìn thì không ai bấm được Dừng khẩn |
| D15 | Dòng danh sách và Enter ở ô tra cứu được xếp `read` trong bảng rủi ro IE | Giống hướng Java (chọn dòng là `read`); không thì mọi flow vấn tin đều bị chặn |
| D16 | "Mock" xác định bằng host `127.0.0.1:<cổng>` và path `/mock-touchpoint/`, không bằng tiêu đề | Tiêu đề trang nào cũng đặt được |

## 19. Chỗ va chạm với quy tắc của chủ dự án (cần chủ dự án xem)

| # | Va chạm | Cách xử lý trong thiết kế |
| --- | --- | --- |
| V1 | Quy tắc cứng 6: "PoC không kết nối hệ thống thật", trong khi tính năng là chạy trên TouchPoint | Trên trang không phải mock: bước `money` luôn bị từ chối; bước `write` mặc định bị chặn (D4c); chỉ bước `read` tự chạy. Chạy bước chỉ-xem trên môi trường thử của TouchPoint vẫn là "chạm hệ thống thật" theo nghĩa chặt, chủ dự án cần xác nhận. |
| V2 | Quy tắc cứng 4: "Side panel của extension là giao diện duy nhất cho cả hai hướng", trong khi chủ dự án chốt chạy trên tab Luồng của trang quản lý | Hướng B2 dùng trang quản lý làm giao diện (extension không chạy trong IE cũ). Tài liệu này không sửa `CLAUDE.md`; đề nghị chủ dự án thêm ngoại lệ cho B2 vào quy tắc 4. |
| V3 | Design mục 6 và 9: log từng bước "kèm ảnh màn hình" | Mốc này không chụp ảnh (D9). |
| V4 | Design mục 6: "workflow mới luôn chạy ở sandbox trước" | Thay bằng Chạy thử chỉ-đọc (D10a); bước ghi và tiền chưa được thử trước lần chạy thật đầu tiên. |
| V5 | "Flow tự chạy, GDV không thao tác tay" so với "bước `write` luôn chờ Duyệt" và "gặp lạ thì dừng hỏi" | Chỉ bước `read` tự chạy liền mạch; mọi bước `write`/`money` cần một cú bấm Duyệt; khi dừng hỏi GDV có thể phải tự làm một bước trên IE. |
| V6 | Task 1.18: "nút chưa phân loại không bao giờ là `read`" so với nhu cầu cho tab và dòng danh sách tự chạy | Không nới luật mặc định; chỉ thêm luật `read` tường minh theo nhãn (D15). Nút lạ vẫn là `write`. |
