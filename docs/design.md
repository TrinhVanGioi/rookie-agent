# Thiết kế PoC: Rookie Agent (agent học thao tác GDV trên web và Java applet)

Tài liệu này là nguồn thiết kế duy nhất của PoC. Bản đầy đủ có sơ đồ ở dạng Mermaid để xem trực tiếp trên GitHub hoặc VS Code.

## 1. Mục tiêu và phạm vi

PoC chứng minh một agent có thể học thao tác của giao dịch viên (GDV) qua vài lần làm mẫu, rồi tự chạy lại và được kiểm soát từng bước. Agent phải học được mọi chức năng của một ứng dụng nghiệp vụ (ví dụ CIF, chuyển tiền, hàng chờ phê duyệt), không chỉ một quy trình demo.

Hệ thống nghiệp vụ chia hai nhóm, mỗi nhóm một hướng ghi và chạy:

| Hướng | Hệ thống | Cách ghi và chạy |
| --- | --- | --- |
| **A** | Ứng dụng web chạy được trên Chromium (Chrome, Edge) | Extension Manifest V3 (mục 3A) |
| **B** | Ứng dụng chạy trong IE mode với Java applet (JDK 1.8) | Windows agent dùng Java Access Bridge (mục 3B) |

Hai hướng dùng chung định dạng event và workflow, chung Learner, kho agent, chính sách và audit.

- **Trong phạm vi:** ứng dụng web trên Chromium, Java applet trong IE mode, dữ liệu giả lập (synthetic). Bài toán demo gồm đối chiếu 2 báo cáo cuối ngày và các chức năng dạng form (tra cứu CIF, lập lệnh chuyển tiền) trên mock.
- **Ngoài phạm vi:** ứng dụng desktop khác (không phải Java), kết nối hệ thống thật, bước tiền trên hệ thống thật, tự động phê duyệt.

Nguyên tắc thiết kế:

1. Học từ làm mẫu, không viết mã riêng cho từng quy trình.
2. Ghi theo ngữ nghĩa (id, label, role), không dùng toạ độ.
3. Con người chịu trách nhiệm cuối: mỗi bước cấu hình được là tự chạy, dừng xem hoặc xin duyệt.
4. Ưu tiên API/MCP khi có; thao tác trên màn hình là phương án dự phòng.
5. Che dữ liệu nhạy cảm ngay trên máy người dùng, trước khi gửi đi.

### Yêu cầu nguồn (từ cuộc họp)

- Người nghiệp vụ tự tạo agent cho việc hàng ngày, không cần IT viết API từng việc.
- Học từ làm mẫu: làm khoảng 10 giao dịch, agent sinh cách chạy tự động, chạy thử, người xác nhận đúng thì lưu vào kho.
- Khác RPA truyền thống: có bước tư duy (so sánh, phát hiện lệch, giải thích).
- Kiểm soát từng bước, con người chịu trách nhiệm cuối, có môi trường test, không tự động phê duyệt hay chuyển tiền.
- Chia sẻ tri thức mặc định trong đơn vị, có chế độ riêng tư; agent của người giỏi được chấm điểm để người khác dùng lại.
- Mô hình triển khai phân tán: Runner chạy trên từng máy PC. Giai đoạn này chỉ làm web, các ứng dụng khác dự kiến chuyển về web. (Cập nhật sau cuộc họp: đa số hệ thống đang chạy trong IE mode với Java applet JDK 1.8, nên bổ sung hướng B.)

## 2. Kiến trúc tổng thể

Hai nơi: mỗi máy PC của GDV có Recorder và Runner (extension cho hướng A, Windows agent cho hướng B); máy chủ nội bộ dùng chung giữ dịch vụ LLM, kho agent, chính sách và audit.

```mermaid
flowchart LR
  subgraph PC["Máy PC của từng GDV"]
    EXT["Extension: side panel + Recorder/Runner web (hướng A)"]
    WA["Windows agent: Recorder/Runner Java (hướng B)"]
  end
  WEB["Hệ thống web trên Chromium"]
  JAVA["Java applet trong IE mode"]
  subgraph SRV["Máy chủ nội bộ (dùng chung)"]
    LLM["Dịch vụ LLM: Learner + Cổng LLM"]
    STORE["Kho agent và chính sách"]
    AUDIT["Audit và dashboard"]
  end
  EXT -- "quan sát, click, nhập, đọc bảng" --> WEB
  EXT <-- "Native Messaging" --> WA
  WA -- "Java Access Bridge" --> JAVA
  EXT -- "sự kiện đã che PII" --> LLM
  LLM -- "workflow chờ duyệt" --> STORE
  STORE -- "workflow đã duyệt" --> EXT
  EXT -- "cần LLM" --> LLM
  EXT -- "log + ảnh" --> AUDIT
```

Side panel của extension là giao diện duy nhất cho cả hai hướng. Với hướng B, extension chuyển lệnh (Ghi, Chạy, Dừng khẩn) cho Windows agent qua Native Messaging và nhận lại sự kiện đã che PII để gửi lên máy chủ. Máy chủ không phân biệt hai hướng ngoài trường `engine` trong event và workflow.

Vòng đời của một agent:

1. **Ghi:** GDV làm mẫu, Recorder gửi sự kiện đã che PII lên máy chủ.
2. **Học:** Learner sinh workflow từ các lần ghi; GDV xem và sửa.
3. **Thử:** workflow chạy ở sandbox; đúng như mong đợi thì lưu vào kho agent.
4. **Duyệt:** GDV xác nhận agent của mình; muốn chia sẻ cho người khác thì cần thêm người duyệt nghiệp vụ.
5. **Chạy:** máy GDV giữ bản đã duyệt và Runner chạy ngay tại máy, từng bước có kiểm soát.
6. **Giám sát:** log, ảnh và điểm chất lượng được đẩy lên audit để cải tiến agent.

## 3. Recorder

### 3A. Hướng A: extension cho web trên Chromium

Extension Manifest V3 ghi thao tác của GDV trên trang web và gửi về server nội bộ dưới dạng sự kiện có cấu trúc.

| Thành phần | Vai trò |
| --- | --- |
| Content script | Bắt click, nhập, chọn, submit; xử lý iframe cùng domain và shadow DOM; dùng MutationObserver cho trang SPA đổi nội dung không đổi URL |
| Service worker | Gom sự kiện theo phiên, che PII, gửi về server, giữ trạng thái đang ghi |
| Side panel | Bắt đầu / Dừng, gắn nhãn bước, xem lại và xoá bước ghi nhầm |
| Network observer | Ghi endpoint và mã kết quả của các API gọi sau mỗi hành động (webRequest, chỉ quan sát) |

**Cách ghi phần tử.** Mỗi phần tử lưu nhiều selector dự phòng theo thứ tự ưu tiên: id ổn định, name, label hoặc aria-label, role kèm text, vị trí tương đối trong form. Id sinh ngẫu nhiên bị loại bằng nhận dạng mẫu chuỗi.

**Quyền trong manifest.** `activeTab`, `scripting`, `storage` và `webRequest` giới hạn ở các host nội bộ. Chỉ ghi khi GDV bấm Bắt đầu và luôn hiện biểu tượng đang ghi.

### 3B. Hướng B: Windows agent cho Java applet trong IE mode

Extension không chạy được trong tab IE mode, và giao diện bên trong applet là Swing/AWT chứ không phải DOM. Hướng B vì vậy dùng một Windows agent cài trên máy GDV, đọc và điều khiển applet qua **Java Access Bridge (JAB)**, cầu accessibility chính thức có sẵn trong JRE 8.

| Thành phần | Vai trò |
| --- | --- |
| Native Messaging host | Nhận lệnh từ side panel của extension (Ghi, Dừng, Chạy, Dừng khẩn), trả sự kiện và trạng thái. Đăng ký ở `HKCU\Software\Microsoft\Edge\NativeMessagingHosts` |
| JAB reader | Đọc cây accessible của cửa sổ Java: vai trò (role), tên (name), mô tả, trạng thái, giá trị |
| Recorder Java | Nghe sự kiện focus, click, đổi giá trị qua JAB; phân loại trường và che PII trước khi trả về extension |
| Runner Java | Tìm phần tử theo selector, thực thi bằng hành động accessible (bấm, đặt text, chọn mục), đọc bảng |

**Điều kiện trên máy.** Bật JAB bằng `jabswitch -enable` (không sửa ứng dụng nghiệp vụ). DLL `WindowsAccessBridge-32.dll` hoặc `-64.dll` phải khớp bitness với JRE của ứng dụng; applet trong IE mode thường chạy JRE 32-bit.

**Cách ghi phần tử.** Selector của Java theo thứ tự ưu tiên: vai trò kèm tên accessible, nhãn đứng cạnh, đường dẫn trong cây accessible (chuỗi vai trò và chỉ số từ cửa sổ gốc). Không dùng toạ độ.

**Trường mật khẩu.** Thành phần có vai trò `password text` (`JPasswordField`) bị bỏ qua hoàn toàn, giống trường mật khẩu ở hướng A. Bảng phân loại trường (4.2) dùng chung cho cả hai hướng.

**Khác biệt so với hướng A.** Không có `api_calls` (không quan sát được mạng của applet), nên mức rủi ro được gán theo màn hình và nhãn nút (4.3). Ảnh chụp là ảnh cửa sổ ứng dụng, được che vùng nhạy cảm theo toạ độ của thành phần lấy từ JAB.

**Dự phòng.** Nếu ứng dụng dùng component tự viết không có tên accessible, nạp một Java agent nhỏ vào JVM của applet (tham số runtime trong Java Control Panel) để nghe sự kiện bằng `AWTEventListener`. Chỉ làm khi spike trên hệ thống thật (task 1.7) cho thấy JAB không đủ.

**Cách bắt sự kiện (đã kiểm chứng trên mock Swing, JDK 21 64-bit).**

| Thao tác | Tín hiệu từ Java Access Bridge | Event |
| --- | --- | --- |
| Gõ vào ô nhập | Đổi nội dung text khi ô đang có focus; ghi ra khi ô mất focus, trước mỗi click, và khi Dừng | `input` |
| Bấm chuột vào nút, menu | Sự kiện click chuột | `click` |
| Chuyển tab | Tab chuyển sang trạng thái `selected` | `click` |
| Tích ô chọn, nút radio | Đổi trạng thái `checked` | `click` |
| Chọn dòng trong bảng | Đổi vùng chọn của bảng; lưu số thứ tự dòng | `select` |

Ứng dụng tự xoá form sau khi gửi không bị ghi nhầm thành thao tác nhập, vì lúc đó ô không có focus.

**Giới hạn của Java Access Bridge.** Bấm nút bằng bàn phím (Enter, phím cách, phím tắt) không sinh sự kiện nào, nên chưa ghi được. Nếu GDV quen thao tác bằng bàn phím thì phải dùng Java agent dự phòng bên dưới.

**Ngôn ngữ.** PoC viết Windows agent bằng Python, khi chạy chỉ dùng thư viện chuẩn (gọi DLL của Java Access Bridge bằng `ctypes`) để không phải mang thêm gói nào vào máy nội bộ. Bản triển khai thật cân nhắc C#/.NET để đóng gói gọn.

## 4. Định dạng dữ liệu

Hai định dạng JSON nối các thành phần: **event** (một hành động đã ghi) và **workflow** (quy trình đã tổng quát hoá). JSON Schema nằm trong `schemas/` và là hợp đồng giữa extension, Windows agent và server.

### 4.1 Event (Recorder sinh ra)

```json
{
  "schema_version": 1,
  "engine": "web",
  "session_id": "s-0142",
  "seq": 7,
  "ts": "2026-11-12T09:15:03Z",
  "type": "click",
  "url": "/baocao/cuoingay",
  "target": {
    "selectors": ["#btn-search", "button[name=search]", "role=button[name='Tìm kiếm']"],
    "label": "Tìm kiếm",
    "tag": "button"
  },
  "value": null,
  "value_class": null,
  "api_calls": [{"method": "GET", "path": "/api/report", "status": 200}],
  "screenshot": "s-0142/007.png"
}
```

`type` thuộc: `click`, `input`, `select`, `navigate`, `submit`.

`engine` thuộc: `web` (hướng A) hoặc `java` (hướng B). Với `java`:

- `url` là định danh màn hình: tiêu đề cửa sổ hoặc khung đang mở, ví dụ `TPSS/Chuyển tiền`.
- `target.selectors` dùng cú pháp Java, ví dụ `["role=push button[name='Tìm kiếm']", "label=Số CIF", "path=frame/panel[1]/text[0]"]`; `target.tag` là vai trò accessible.
- `api_calls` luôn là mảng rỗng.

### 4.2 Quy tắc lưu giá trị nhập

Learner cần so sánh giá trị giữa các lần ghi để nhận ra tham số, nhưng dữ liệu nhạy cảm không được rời máy. Vì vậy trường được phân loại ngay trên máy GDV (trong extension hoặc Windows agent):

| Loại trường | Ví dụ | Cách lưu trong event |
| --- | --- | --- |
| Bỏ qua | mật khẩu, OTP | Không ghi sự kiện giá trị. |
| Nhạy cảm | số tài khoản, CCCD, tên, số tiền | `value` = `null`, `value_class` = loại (ví dụ `account_number`). Learner luôn coi là tham số. |
| Không nhạy cảm | ngày, loại báo cáo, tuỳ chọn trong dropdown | `value` lưu giá trị thật để Learner so sánh giữa các lần ghi. |

Danh sách loại trường nằm trong một bảng cấu hình dùng chung cho extension và Windows agent (theo `name`, `label`, `type` hoặc vai trò accessible), mặc định là nhạy cảm khi chưa phân loại được.

### 4.3 Workflow (Learner sinh ra)

```json
{
  "schema_version": 1,
  "engine": "web",
  "id": "doi-chieu-cuoi-ngay",
  "version": 3,
  "status": "approved",
  "inputs": [
    {"name": "ngay", "type": "date"},
    {"name": "nguong_lech", "type": "number", "default": 1000}
  ],
  "steps": [
    {"id": "open_a", "action": "click", "target": {"selectors": ["#tab-a", "text=Báo cáo A"]}, "risk": "read", "mode": "auto"},
    {"id": "set_date_a", "action": "select", "target": {"selectors": ["#f-date", "label=Ngày báo cáo"]}, "value": "{ngay}", "risk": "read", "mode": "auto"},
    {"id": "search_a", "action": "click", "target": {"selectors": ["#btn-search", "text=Tìm kiếm"]}, "risk": "read", "mode": "auto"},
    {"id": "extract_a", "action": "extract_table", "target": {"selectors": ["#tbl-report"]}, "save_as": "bao_cao_a", "risk": "read", "mode": "auto"},
    {"id": "compare", "action": "compare", "inputs": ["bao_cao_a", "bao_cao_b"], "key": "id", "tolerance": "{nguong_lech}", "risk": "read", "mode": "review"},
    {"id": "save_report", "action": "save", "risk": "write", "mode": "approve"}
  ]
}
```

- `engine`: `web` hoặc `java`. Một workflow chỉ thuộc một hướng; Runner tương ứng mới chạy được nó.
- `action` của PoC: `goto`, `click`, `fill`, `select`, `read_value`, `wait_for`, `extract_table`, `compare`, `save`.
  - `read_value` đọc giá trị một trường và lưu vào biến (`save_as`) để dùng ở bước sau dưới dạng `{ten_bien}`, ví dụ số CIF vừa tra được. Giá trị chỉ nằm trong Runner trên máy GDV, không gửi lên máy chủ.
  - `wait_for` chờ một màn hình hoặc phần tử xuất hiện trước khi đi tiếp.
- `status`: `draft` → `tested` → `approved`.
- `risk` (`read` / `write` / `money`) do **luật cố định** gán, không để LLM tự quyết, dựa trên **bảng cấu hình rủi ro theo ứng dụng**:
  - Hướng A: theo endpoint gọi sau bước đó (API ghi là `write`, API tiền là `money`).
  - Hướng B: theo màn hình và nhãn nút (ví dụ nút "Lưu" là `write`, nút "Chuyển tiền" hoặc "Gửi duyệt" trên màn hình chuyển tiền là `money`).
  - Bước làm thay đổi dữ liệu mà bảng chưa phân loại thì mặc định là `write`.
- `mode` (`auto` / `review` / `approve`): xem mục 6.

Nhánh có điều kiện (ví dụ CIF đã tồn tại hay chưa) chưa được Learner bằng luật sinh ra. Runner gặp màn hình khác với lúc ghi thì dừng và hỏi GDV.

## 5. Learner

Learner biến 3 đến 10 lần ghi thành một workflow có tham số: so sánh các lần làm với nhau, rồi hỏi LLM ở những chỗ còn mơ hồ.

1. **Chuẩn hoá:** gộp nhiều lần gõ phím thành một thao tác điền, bỏ click trùng.
2. **Căn chỉnh các phiên:** bước giống nhau ở mọi lần là bước cố định; giá trị khác nhau thành tham số.
3. **LLM diễn giải:** nhận bản tóm tắt các phiên kèm ảnh màn hình để đặt tên bước, nêu ý định, suy ra kiểu tham số và phát hiện bước có điều kiện.
4. **Gán mức rủi ro bằng luật** (xem 4.3).
5. **Người dùng duyệt:** xem workflow và form đầu vào sinh ra, sửa nếu cần.
6. **Chạy thử:** 1 đến 3 giao dịch mẫu ở sandbox; đúng như mong đợi thì lưu vào kho agent.

Giới hạn: từ vài lần ghi chỉ tổng quát hoá được các biến thể đã thấy. Gặp nhánh chưa từng thấy, agent dừng và hỏi GDV thay vì đoán.

Bản PoC đầu tiên của Learner dùng `RuleBasedClient` (bước 1, 2, 4 bằng luật; bước 3 để sau khi có LLM thật).

## 6. Runner và kiểm soát từng bước

Runner chạy ngay trên máy của từng GDV trong phiên đăng nhập của chính họ: hướng A là một phần của extension, hướng B là một phần của Windows agent và nhận lệnh từ side panel qua Native Messaging. Vòng điều khiển (chế độ kiểm soát, Dừng khẩn, chính sách, log) giống nhau ở hai hướng; chỉ khác phần tìm phần tử và thực thi. Mỗi bước có một chế độ kiểm soát do người dùng cấu hình trong giới hạn mà mức rủi ro cho phép.

| Chế độ | Hành vi | Dùng cho |
| --- | --- | --- |
| `auto` | Chạy liền, không dừng | Bước chỉ đọc dữ liệu |
| `review` | Chạy xong dừng để người xem kết quả rồi cho đi tiếp | Nhập liệu, kết quả đối chiếu |
| `approve` | Dừng trước khi chạy, chờ duyệt (maker-checker) | Bước ghi dữ liệu, giao dịch tiền |

Quy tắc cứng: bước `money` không thể đặt `auto`; bước `write` luôn là `approve`. Trong PoC, bước `money` chỉ được chạy trên mock và luôn dừng chờ duyệt. Agent không bao giờ tự bấm Duyệt thay người kiểm soát (checker): agent của checker chỉ mở hàng chờ, lọc và kiểm tra giao dịch, cú bấm Duyệt do người bấm. Người lập và người duyệt là hai tài khoản khác nhau nên là hai agent riêng. Mọi lần chạy có nút Dừng khẩn và ghi log từng bước kèm ảnh màn hình. Workflow mới luôn chạy ở sandbox trước khi được phép chạy ngoài.

Self-healing bằng LLM và ảnh (bước 2 bên dưới) trong PoC chỉ làm cho hướng A; hướng B dừng ở selector dự phòng rồi hỏi GDV.

**Tự sửa khi giao diện đổi (self-healing).** Khi selector không còn khớp:

1. Thử lần lượt các selector dự phòng đã ghi.
2. Nếu vẫn lỗi, LLM nhận ảnh màn hình và mô tả phần tử để tìm phần tử tương đương.
3. Độ tin cậy dưới ngưỡng thì dừng và hỏi người dùng.
4. Sửa thành công thì đề xuất cập nhật workflow; chỉ lưu khi người dùng duyệt.

```mermaid
flowchart TD
  A["GDV bấm chạy agent"] --> B["Kiểm tra: bản đã duyệt, đúng quyền, chưa bị khoá"]
  B --> C{"Bước cần duyệt trước?"}
  C -- có --> D["Chờ GDV duyệt"] --> E
  C -- không --> E["Thực hiện bước trên trang"]
  E --> F{"Tìm thấy phần tử?"}
  F -- không --> G["Tự sửa: selector dự phòng, rồi LLM + ảnh"]
  G -- tìm được --> E
  G -- kém tin cậy --> H["Dừng và hỏi GDV"]
  F -- có --> I["Ghi log và ảnh"]
  I --> J{"Cần xem kết quả?"}
  J -- có --> K["GDV xem kết quả, bấm đi tiếp"] --> L
  J -- không --> L{"Còn bước nữa?"}
  L -- có --> C
  L -- không --> M["Xong: đẩy log lên audit"]
```

**Mô hình phân tán trên từng máy PC.**

| Vấn đề | Cách xử lý |
| --- | --- |
| Cài đặt và cập nhật | Hướng A: Runner nằm trong extension, phát hành và cập nhật qua kho extension nội bộ hoặc chính sách của IT, máy GDV không cần cài thêm gì. Hướng B: máy GDV cài thêm Windows agent (đóng gói một file cài, kèm đăng ký Native Messaging host) và bật Java Access Bridge; cần bộ phận an toàn thông tin duyệt |
| Phát workflow xuống máy | Máy chỉ nhận bản đã duyệt từ kho agent, kiểm tra version và chữ ký trước khi chạy, rồi giữ bản sao trên máy |
| Quyền và định danh | Chạy trong phiên đăng nhập của chính GDV; mỗi lần chạy ghi mã người dùng, mã máy và version agent; không dùng tài khoản chung |
| Điều khiển tập trung | Chính sách (agent nào, vai trò nào được chạy) và lệnh khoá agent được kéo về máy định kỳ; bị khoá thì Runner dừng ở bước kế tiếp |
| Gọi LLM | Máy không gọi LLM trực tiếp, chỉ qua cổng LLM nội bộ và chỉ gửi dữ liệu đã che PII |
| Xử lý dữ liệu | Trích xuất bảng và tính đối chiếu ngay trên máy; chỉ các dòng lệch đã che mới gửi lên khi cần LLM giải thích |
| Mất kết nối | Bước cần máy chủ hoặc LLM thì dừng an toàn và báo GDV; log và ảnh được đệm trên máy, đẩy lên khi có mạng lại |
| Kiểm thử | Workflow web chạy thử bằng Playwright trên sandbox ở máy chủ trước khi được phát xuống máy. Workflow Java chạy thử bằng Windows agent ở chế độ thử trên một máy Windows có JRE 8 và mock Swing |

## 7. Bước tư duy: đối chiếu 2 báo cáo

Ngoài lấy dữ liệu, agent so sánh theo rule của người dùng và giải thích chênh lệch.

- **Chia việc giữa mã và LLM.** Phần tính toán chắc chắn do mã làm: ghép dòng theo khoá (mã giao dịch, số tài khoản), cộng tổng, tìm dòng thiếu hoặc lệch số. LLM chỉ làm phần cần phán đoán: phân loại nguyên nhân lệch, gợi ý cách xử lý, soạn ghi chú.
- **Rule do người dùng nhập bằng ngôn ngữ tự nhiên**, ví dụ "lệch dưới 1.000 đồng do làm tròn thì bỏ qua". Hệ thống chuyển rule thành tham số của bước đối chiếu (ví dụ `nguong_lech`) và hiển thị lại để người dùng xác nhận.
- **Kết quả đầu ra:** bảng lệch gồm khoá, giá trị hai bên, chênh lệch, nguyên nhân dự đoán và độ tin cậy; kết luận khớp hoặc không khớp (không khớp thì dừng ở chế độ `review`); toàn bộ bước tính được lưu lại để kiểm tra lại, không chỉ lưu kết luận của LLM.

## 8. Kho agent, chấm điểm và chia sẻ

| Thuộc tính | Nội dung |
| --- | --- |
| Version | Mỗi lần sửa tạo version mới, quay lại được bản cũ |
| Điểm | Tỷ lệ chạy đúng, số bước phải sửa tay, thời gian tiết kiệm so với làm thủ công |
| Chia sẻ | Riêng tư, nhóm hoặc toàn đơn vị; mặc định chia sẻ trong đơn vị, có chế độ riêng tư |
| Clone | Người khác sao chép agent và chỉnh rule theo cách làm của mình; bản gốc không đổi |

**Tri thức hai tầng.** Tầng cá nhân (rule và ghi nhớ riêng của từng người) tách khỏi tầng chung. Phản hồi sửa lỗi của người dùng chỉ đi vào tầng chung sau khi người sở hữu xác nhận và có người duyệt nghiệp vụ. Cách này tránh tình huống hai người làm khác nhau mà hệ thống không biết học theo ai.

## 9. Bảo mật, che PII và audit

| Lớp | Biện pháp |
| --- | --- |
| Thu thập | Chỉ ghi khi bấm Bắt đầu, có biểu tượng đang ghi; bỏ qua mật khẩu và OTP; giá trị nhạy cảm không lưu (4.2) |
| Che PII | Số tài khoản, CCCD, tên, số tiền được thay bằng mã giữ chỗ trước khi gửi; ảnh màn hình được che vùng nhạy cảm |
| Truyền và lưu | Kênh mã hoá về server nội bộ; LLM chạy on-prem hoặc trong vùng mạng được duyệt |
| Quyền | Agent chạy dưới quyền của chính người dùng; không có tài khoản dùng chung |
| Audit | Log từng bước: ai chạy, agent version nào, API nào, kết quả, người duyệt, ảnh màn hình |
| Rủi ro | Phân cấp `read` / `write` / `money`; bước `money` luôn cần duyệt trước; trong PoC bước `money` chỉ chạy trên mock với dữ liệu synthetic |

**Minh bạch với GDV.** Nói rõ mục đích là tạo agent hỗ trợ công việc của chính họ, không dùng để giám sát hay chấm điểm cá nhân, và có cơ chế xoá bản ghi của mình.

**Cần xác nhận với bộ phận an toàn thông tin:** chính sách cài extension và Windows agent trên máy giao dịch, việc bật Java Access Bridge, vị trí đặt LLM, thời gian lưu log và ảnh màn hình.

## 10. Mock site và kịch bản demo

Demo chạy trên hai hệ thống giả lập với dữ liệu synthetic: một web (hướng A) và một ứng dụng Java Swing (hướng B).

**Mock site (web, `mock-site/`) gồm:** trang đăng nhập, Báo cáo A (đối chiếu từ hệ thống nguồn 1), Báo cáo B (hệ thống nguồn 2), mỗi báo cáo có bộ lọc ngày và bảng kết quả xuất được. Dữ liệu sinh sẵn có một số dòng lệch cố ý (lệch số, thiếu dòng, lệch do làm tròn). Có một công tắc "giao diện mới" đổi id và vị trí nút để thử self-healing. Ngoài ra có ba chức năng dạng form: tra cứu và mở CIF, lập lệnh chuyển tiền, hàng chờ phê duyệt. Có hai tài khoản: người lập (maker) và người duyệt (checker); checker không duyệt được lệnh do chính mình lập.

**Mock Swing (`mock-java/`) gồm:** một ứng dụng Java Swing độc lập giả lập TPSS với đăng nhập, CIF, chuyển tiền và phê duyệt, cùng dữ liệu synthetic theo seed và công tắc "giao diện mới". Java Access Bridge đọc Swing độc lập giống hệt applet, nên test không cần dựng IE mode và plugin Java. Việc kiểm tra trên applet thật trong IE mode là task spike 1.7.

**Kịch bản khoảng 12 phút:**

1. Bật record trong side panel, làm đối chiếu 3 lần với các ngày khác nhau.
2. Bấm Học: hiện workflow sinh ra, các bước và form đầu vào.
3. Chạy với ngày mới: agent tự chạy các bước đọc, dừng ở bước đối chiếu chờ xem kết quả.
4. Xem bảng lệch kèm nguyên nhân dự đoán; sửa rule làm tròn rồi chạy lại.
5. Bật công tắc đổi giao diện: agent tự tìm lại nút và chạy tiếp, ghi nhận đề xuất cập nhật workflow.
6. Mở dashboard: thời gian so với làm thủ công, tỷ lệ bước đúng, audit trail.
7. Người dùng thứ hai clone agent và chỉnh rule theo cách làm của mình.
8. Học một chức năng khác trên mock Swing: ghi 3 lần "tra CIF rồi lập lệnh chuyển tiền", bấm Học, chạy với khách hàng mới; agent dừng chờ duyệt ở bước chuyển tiền.

`docs/demo-reference.html` là bản mô phỏng tương tác một file của kịch bản này, dùng để tham khảo hành vi và giao diện.

## 11. Kế hoạch, KPI và rủi ro

PoC làm trong 3 tuần với ba cổng kiểm (chi tiết việc và tiêu chí nghiệm thu ở `docs/tasks.md`).

| Cổng | Tuần | Điều kiện qua cổng |
| --- | --- | --- |
| Gate 1: ghi được | 1 | 3 lần làm mẫu được ghi đủ và xuất được event JSON, ở cả mock web và mock Swing |
| Gate 2: chạy lại đúng | 2 | Workflow sinh ra chạy đúng với dữ liệu mới; học được chức năng "tra CIF rồi lập lệnh chuyển tiền" mà không viết mã riêng |
| Gate 3: demo đủ kịch bản | 3 | 8 bước trong mục 10 chạy được, kèm số đo thời gian và độ đúng |

Hướng B làm tăng khối lượng so với ước lượng 3 tuần ban đầu; mốc thời gian cần thống nhất lại sau khi có kết quả spike 1.7.

Các tiêu chí qua cổng là đề xuất từ kịch bản demo, cần thống nhất với khối vận hành.

**Chỉ số đo**

| Chỉ số | Cách đo |
| --- | --- |
| Bước tự chạy đúng | Số bước chạy đúng không cần sửa tay trên tổng số bước, qua các lần chạy với dữ liệu ngày mới |
| Phát hiện dòng lệch | Tỷ lệ dòng lệch cố ý trong dữ liệu mock mà agent tìm ra đúng |
| Tự sửa khi đổi giao diện | Số lần tự tìm lại đúng phần tử trên tổng số lần đổi giao diện thử |
| Thời gian | Thời gian agent chạy so với GDV làm thủ công cùng quy trình |

**Rủi ro và hướng xử lý**

| Rủi ro | Hướng xử lý |
| --- | --- |
| Tổng quát hoá kém từ vài lần ghi | Ghi nhiều biến thể; gặp nhánh chưa thấy thì agent dừng và hỏi GDV |
| Máy giao dịch không cho cài extension | Xin duyệt chính sách sớm; chạy PoC trên máy thử nghiệm trong lúc chờ |
| Ứng dụng nghiệp vụ chạy IE mode với Java applet | Hướng B: Windows agent dùng Java Access Bridge |
| Applet không lộ tên accessible cho thành phần | Spike 1.7 kiểm tra sớm trên hệ thống thật; dự phòng bằng Java agent nghe `AWTEventListener` |
| Máy giao dịch không cho cài Windows agent hoặc bật Java Access Bridge | Xin duyệt chính sách sớm; chạy PoC trên máy thử nghiệm trong lúc chờ |
| Bitness của JRE khác với Windows agent | Agent chọn DLL 32 hoặc 64-bit theo JRE của ứng dụng; kiểm tra trong spike 1.7 |
| Ứng dụng desktop khác (không phải web, không phải Java) | Ngoài phạm vi PoC |
| Vị trí đặt LLM chưa chốt | Xác nhận với bộ phận an toàn thông tin; PoC chỉ dùng dữ liệu synthetic |

**Câu hỏi mở**

- Ngưỡng đạt cho từng chỉ số (cuộc họp chưa nêu).
- Quy trình thật đầu tiên để thử sau PoC: cuộc họp nhắc đối chiếu cuối ngày và hành trình chuyển tiền ngoại tệ.
- Ai duyệt agent trước khi vào kho chung.
- Chính sách cài extension và vị trí đặt LLM trong ngân hàng.
