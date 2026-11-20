# Rookie Agent – Định hướng kiến trúc mới

## Self-Adaptive Digital Process Twin (SADPT)

**Bản sao số quy trình nghiệp vụ có khả năng tự thích nghi.**

**Thông điệp:** *Learn Once. Adapt Always. Work Together.*  
**Định vị:** Trợ lý AI đồng hành cùng giao dịch viên. Rookie giữ một bản sao số của mỗi quy trình nghiệp vụ, học quy trình từ công việc thực tế, tự thích nghi với thay đổi kỹ thuật của ứng dụng trong phạm vi an toàn, và cập nhật phần nghiệp vụ thay đổi qua hướng dẫn có kiểm soát của con người.

---

## 1. Tóm tắt định hướng

Rookie Agent không nên được phát triển như một công cụ Record & Replay chỉ ghi lại chuỗi click, phím bấm và HTTP request rồi phát lại. Định hướng mới là một nền tảng **Agentic Adaptive Process Automation**, lấy **Self-Adaptive Digital Process Twin (SADPT)** làm trung tâm: một bản sao số của quy trình nghiệp vụ, tự theo dõi môi trường chạy và tự điều chỉnh cách thực hiện trong giới hạn được phép.

Hệ thống cần duy trì được hiểu biết về nghiệp vụ ngay cả khi giao diện hoặc cách triển khai kỹ thuật của ứng dụng thay đổi. Khi chạy một quy trình, Agent liên tục quan sát trạng thái thực tế, đối chiếu với mô hình quy trình và lựa chọn cách thực hiện phù hợp.

Có hai loại thay đổi cần xử lý khác nhau:

1. **Thay đổi kỹ thuật/giao diện:** đổi vị trí nút, ID, nhãn, cấu trúc DOM, cửa sổ hoặc cách hiển thị. Agent có thể tự tìm lại mục tiêu và thích nghi nếu có đủ bằng chứng rằng ý nghĩa hành động không thay đổi.
2. **Thay đổi nghiệp vụ:** thêm/bớt bước, thay đổi điều kiện, tham số, ý nghĩa hoặc kết quả nghiệp vụ. Agent phải dừng tại điểm an toàn, hỏi người dùng phù hợp, tạo đề xuất cập nhật và kiểm thử trước khi phát hành phiên bản mới.

Nguyên tắc cốt lõi:

> **Học quy trình một lần; không phải học lại chỉ vì giao diện đổi. Khi nghiệp vụ thay đổi, Agent chỉ học phần thay đổi, không bắt GDV ghi lại toàn bộ quy trình.**

Định hướng này không có nghĩa Agent được tự ý sửa quy trình đang có hiệu lực. Agent có thể tự phục hồi cách nhận diện giao diện trong phạm vi an toàn; mọi thay đổi làm ảnh hưởng ý nghĩa nghiệp vụ phải được kiểm chứng, phê duyệt và quản lý phiên bản.

## 2. Tầm nhìn và mục tiêu sản phẩm

### 2.1. Tầm nhìn

Rookie Agent trở thành trợ lý nghiệp vụ chạy cùng giao dịch viên trên máy làm việc, có khả năng:

- Học quy trình từ thao tác thực tế trên nhiều ứng dụng và công nghệ cũ.
- Hiểu mục tiêu, dữ liệu, điều kiện, trạng thái và kết quả của từng bước nghiệp vụ.
- Thực thi quy trình bằng adapter thích hợp: giao diện, Java, Windows, SOAP/API hoặc file/report.
- Nhận biết khi ứng dụng thay đổi và tự thích nghi trong phạm vi được phép.
- Hỏi GDV đúng phần chưa rõ, tiếp nhận hướng dẫn và cập nhật phần quy trình bị ảnh hưởng.
- Duy trì lịch sử, phiên bản, bằng chứng, quyền phê duyệt và khả năng quay lui.

### 2.2. Mục tiêu không phải

Rookie Agent không hướng đến:

- Phát lại tọa độ chuột và bàn phím một cách mù quáng.
- Dùng LLM để tự suy đoán mọi control hoặc tự quyết định hành động nghiệp vụ.
- Gọi lại mọi request đã ghi như thể đó là API nghiệp vụ ổn định.
- Tự cập nhật quy trình sản xuất chỉ vì một lần chạy gặp giao diện khác.
- Thay thế quyền quyết định, kiểm soát hoặc phê duyệt của con người.

## 3. Các khái niệm cốt lõi

### 3.0. Self-Adaptive Digital Process Twin (SADPT)

SADPT ghép hai khái niệm:

- **Digital Process Twin:** mô hình số của quy trình nghiệp vụ (mục 3.1).
- **Self-adaptive:** vòng tự quan sát – phân tích – lập kế hoạch – thực thi – ghi tri thức, lấy từ lĩnh vực hệ thống tự thích nghi (MAPE-K, mục 3.5).

Ý nghĩa: bản sao số không chỉ mô tả quy trình, nó còn **biết khi nào thực tế lệch khỏi mô hình** và **biết nên xử lý theo cách nào** (tự phục hồi kỹ thuật, hỏi GDV, hay đề xuất thay đổi nghiệp vụ). Mỗi quyết định thích nghi đều có bằng chứng và được ghi lại.

### 3.1. Digital Process Twin

Digital Process Twin là mô hình số đại diện cho một quy trình nghiệp vụ. Mô hình không chỉ chứa chuỗi thao tác mà cần thể hiện:

- Mục tiêu nghiệp vụ của quy trình.
- Các bước nghiệp vụ và quan hệ giữa các bước.
- Dữ liệu đầu vào, đầu ra và nguồn dữ liệu.
- Điều kiện trước/sau của từng bước.
- Các nhánh, ngoại lệ và trạng thái có thể xuất hiện.
- Các phương thức thực thi trên từng ứng dụng/công nghệ.
- Quy tắc an toàn, rủi ro và yêu cầu phê duyệt.
- Bằng chứng dùng để xác minh kết quả.

**Một bước nghiệp vụ không đồng nghĩa với một click hoặc một HTTP request.** Một bước như `EXPORT_STATEMENT` có thể bao gồm nhiều click, nhiều request SOAP, một cửa sổ báo cáo, một thao tác xuất file và bước xác minh PDF.

### 3.2. Companion Agent

Agent là thành phần đồng hành trong suốt vòng đời quy trình, không chỉ là bộ điều phối LLM ở thời điểm người dùng nhập lệnh.

Các năng lực logic:

- **Observer:** quan sát ứng dụng, cửa sổ, control, service event, file và trạng thái.
- **Planner/Orchestrator:** chọn quy trình và lập kế hoạch thực hiện theo mục tiêu.
- **Executor:** gọi adapter phù hợp để thao tác.
- **Verifier:** kiểm tra điều kiện trước/sau và kết quả thực tế.
- **Recovery Agent:** xử lý sai khác kỹ thuật trong giới hạn an toàn.
- **Learning Agent:** thu nhận hướng dẫn, đề xuất delta và tạo phiên bản mới.
- **Safety Guard:** kiểm soát quyền, rủi ro, phê duyệt và điểm dừng.

Các vai trò trên có thể là module trong cùng một Windows Agent; không bắt buộc phải triển khai thành nhiều LLM hoặc nhiều service độc lập.

### 3.3. Semantic Process Contract

Mỗi bước cần có hợp đồng ngữ nghĩa mô tả *bước này có ý nghĩa gì*, thay vì chỉ lưu *đã click vào đâu*.

Một contract nên có tối thiểu:

| Nhóm | Nội dung |
|---|---|
| Business intent | Mục tiêu và tên hành động nghiệp vụ |
| Input/Output | Tham số, kiểu dữ liệu, nguồn và kết quả mong đợi |
| Preconditions | Điều kiện cần có trước khi thực hiện |
| Postconditions | Trạng thái phải đạt sau khi thực hiện |
| Target semantics | Vai trò, nhãn, ngữ cảnh và đặc trưng của mục tiêu UI |
| Execution adapters | Các cách thực thi được hỗ trợ: DOM, UIA, Java, SOAP, file... |
| Recovery policy | Có được tự tìm lại mục tiêu, thử lại hoặc cần hỏi người dùng không |
| Risk policy | read/write/money và quyền phê duyệt |
| Evidence | Bằng chứng xác minh hành động và kết quả |

### 3.4. Self-adaptation và Delta Learning

- **Self-adaptation:** điều chỉnh phương thức kỹ thuật để tiếp tục thực hiện cùng một mục tiêu nghiệp vụ.
- **Delta Learning:** cập nhật phần mô hình nghiệp vụ bị thay đổi mà không xây dựng lại toàn bộ quy trình.

Hai cơ chế này phải được tách riêng. Tự tìm lại nút không đồng nghĩa với việc được phép thay đổi logic nghiệp vụ.

### 3.5. Vòng tự thích nghi (MAPE-K)

SADPT vận hành theo vòng MAPE-K: **Monitor – Analyze – Plan – Execute**, dùng chung một **Knowledge** (tri thức về quy trình).

| Thành phần | Trong Rookie | Module đề xuất |
|---|---|---|
| Monitor | Quan sát trạng thái thực tế: cửa sổ, control, request, file, dialog | `adaptive/observer.py`, `adaptive/state_snapshot.py` |
| Analyze | Phát hiện lệch so với mô hình; phân loại thay đổi kỹ thuật hay nghiệp vụ | `adaptive/drift_detector.py`, `adaptive/change_classifier.py` |
| Plan | Chọn cách nhận diện/adapter phù hợp; hoặc tạo đề xuất delta; hoặc hỏi GDV | `adaptive/target_resolver.py`, `adaptive/recovery_agent.py`, `adaptive/delta_learning.py` |
| Execute | Thực hiện qua adapter, kiểm postcondition, dừng tại checkpoint khi không chắc | `execution/semantic_replay.py`, `execution/state_verifier.py`, `execution/safe_checkpoint.py` |
| Knowledge | Semantic Process Contract, process version, evidence, audit, lịch sử thích nghi | `process/semantic_contract.py`, `process/process_version.py`, `process/patch_manager.py` |

Quy tắc: vòng chỉ được **Execute** thích nghi kỹ thuật tự động. Mọi thay đổi trong Knowledge làm ảnh hưởng ý nghĩa nghiệp vụ phải đi qua Plan → Delta Learning → kiểm thử → phê duyệt (mục 6).

## 4. Kiến trúc tổng thể

```text
┌─────────────────────────────────────────────────────────────────────┐
│                         GIAO DỊCH VIÊN                               │
│       Yêu cầu công việc · Hướng dẫn · Xác nhận · Dừng khẩn            │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────┐
│                    ROOKIE COMPANION AGENT                            │
│                                                                     │
│  Observer │ Planner │ Executor │ Verifier │ Recovery │ Learning     │
│                         Safety Guard                                 │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────┐
│        SELF-ADAPTIVE DIGITAL PROCESS TWIN (SADPT) · MAPE-K           │
│                                                                     │
│  Business Intent · Process Graph · Data Contract · State Contract   │
│  UI/Service Contract · Risk Policy · Evidence · Version              │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────┐
│                     MULTI-CHANNEL ADAPTERS                           │
│                                                                     │
│  Web/IE │ Java │ Windows UI │ SOAP/API │ Dialog │ Print/Report │ File │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────┐
│                  LEGACY / ENTERPRISE APPLICATIONS                    │
│       TouchPoint · IE Mode · Java Applet · Windows App · Services    │
└─────────────────────────────────────────────────────────────────────┘

Cross-cutting: Privacy · Audit · Approval · Versioning · Kill Switch
```

### 4.1. Recording Layer – ghi nhận đa kênh

Mỗi công nghệ có recorder/observer riêng. Tất cả sự kiện được chuẩn hóa về một event model chung.

| Kênh | Dữ liệu quan sát | Adapter/công nghệ nên đánh giá |
|---|---|---|
| Web/IE | DOM, frame, event, URL, form, XHR, trạng thái trang | JavaScript recorder hiện tại, IE COM/IEDriver tùy môi trường thực tế |
| Chromium | DOM, accessibility tree, network, navigation | Playwright/extension |
| Windows Desktop | Window, control, focus, dialog, menu, event | pywinauto (UIA/Win32), Windows UI Automation, WinEvent; cân nhắc FlaUI/UIA3 |
| Java | Java component, accessible name/role, hierarchy | Java Access Bridge; fallback UIA/CV |
| SOAP/API | Operation, request/response metadata, status, duration | Browser hooks nếu do JS phát; proxy/interceptor/logging nếu do JVM/service phát |
| Dialog/Popup | Window lifecycle, parent/child, control, screenshot | UIA, Win32, WinEvent |
| Print/Report | Viewer, preview, print dialog, job, output file | UIA/Win32, Windows Print Spooler API, file collector |

Không có một recorder đơn lẻ nào quan sát đầy đủ mọi kênh. Mục tiêu là nhiều adapter chuyên biệt nhưng cùng một chuẩn dữ liệu.

### 4.2. Unified Event Engine

Chịu trách nhiệm:

- Chuẩn hóa event từ các recorder.
- Gắn timestamp, process ID, window ID, frame/context và correlation ID khi có.
- Liên kết thao tác UI với service call và output sinh ra sau đó.
- Phân biệt event nghiệp vụ với event kỹ thuật/nhiễu.
- Che dữ liệu nhạy cảm ngay trên máy GDV trước khi lưu hoặc truyền đi.
- Lưu bằng chứng tối thiểu cần thiết để phân tích, xác minh và học.

Không được suy luận quan hệ nhân quả chỉ dựa vào thời gian nếu có thể dùng correlation ID hoặc quan hệ cha/con rõ ràng hơn. Nếu không đủ bằng chứng, ghi nhận quan hệ ở mức chưa chắc chắn.

### 4.3. Adaptive Process Twin Engine

Quản lý:

- Semantic Process Contract.
- Đồ thị bước nghiệp vụ, nhánh, điều kiện và ngoại lệ.
- Liên kết giữa business step và nhiều technical event.
- Các execution adapter và phương án dự phòng.
- UI signature và các locator/anchor có thể thay thế.
- State contract và cách xác minh kết quả.
- Process version, patch, approval và rollback.

### 4.4. Runtime Agent

Trong lúc chạy, Agent thực hiện vòng lặp:

1. Quan sát trạng thái hiện tại.
2. Xác định bước nghiệp vụ và điều kiện cần đạt.
3. So sánh trạng thái thực tế với trạng thái dự kiến.
4. Chọn adapter/cách nhận diện phù hợp.
5. Thực hiện hành động trong phạm vi quyền được cấp.
6. Xác minh postcondition.
7. Nếu sai khác: phân loại, tự phục hồi, hỏi GDV hoặc dừng an toàn.

### 4.5. Governance Layer

Quản lý quyền truy cập, phê duyệt, audit, bằng chứng, versioning, kill switch, chính sách dữ liệu và quyền chia sẻ quy trình.

## 5. Cơ chế tự thích nghi khi ứng dụng thay đổi

### 5.1. Phân loại thay đổi

| Loại thay đổi | Ví dụ | Xử lý đề xuất |
|---|---|---|
| Vị trí/hiển thị | Nút dịch vị trí, cửa sổ đổi kích thước | Agent tìm lại mục tiêu bằng semantic/accessibility/UIA/CV và xác minh |
| Định danh UI | DOM ID, AutomationID hoặc selector đổi | Resolve lại theo nhãn, role, context, hierarchy và evidence |
| Nhãn control | “Tra cứu” đổi thành “Tìm kiếm” | Có thể tự thích nghi nếu ngữ cảnh và postcondition đủ chắc chắn |
| Cấu trúc màn hình | Thêm panel/tab hoặc thay đổi layout | Quan sát lại, đối chiếu trạng thái; hỏi khi không xác định chắc chắn |
| Dialog mới | Xuất hiện xác nhận hoặc cảnh báo mới | Dừng tại checkpoint, hiển thị nội dung đã che và hỏi GDV |
| Thêm/bớt bước nghiệp vụ | Phải chọn thêm loại sao kê | Delta Learning, xác nhận và tạo phiên bản mới |
| Điều kiện nghiệp vụ đổi | Thay đổi điều kiện được phép tra cứu | Hỏi chủ quy trình/đầu mối nghiệp vụ; không tự suy luận |
| SOAP/API contract đổi | Operation, schema hoặc response thay đổi | Tạm vô hiệu adapter bị ảnh hưởng; chuyển quản trị viên/CNTT xác nhận |
| Output đổi | PDF chuyển sang Excel hoặc report viewer mới | Kiểm tra định dạng, nội dung và quy tắc đầu ra; hỏi nếu ảnh hưởng nghiệp vụ |

### 5.2. Phân loại mức độ tin cậy

Không nên đặt một ngưỡng confidence chung cho tất cả hành động. Cần kết hợp:

- Mức khớp semantic target.
- Mức khớp context và state.
- Tính nhất quán của nhiều tín hiệu độc lập.
- Kết quả postcondition.
- Mức rủi ro hành động.

Chính sách vận hành đề xuất:

| Tình huống | Hành động |
|---|---|
| Đủ bằng chứng, thao tác đọc, trạng thái hợp lệ | Có thể tự thích nghi và thực hiện; bắt buộc hậu kiểm |
| Có nhiều mục tiêu gần giống nhau | Hỏi GDV chọn mục tiêu đúng |
| Dialog/nhánh chưa từng gặp | Dừng và hỏi; không tự bấm xác nhận |
| Thay đổi ý nghĩa hoặc logic nghiệp vụ | Tạo đề xuất Delta Learning; không cập nhật production tự động |
| Hành động write/money | Áp dụng quy tắc phê duyệt hiện hành; tự thích nghi không được vượt quyền |
| SOAP contract không tương thích | Dừng adapter liên quan và chuyển người phụ trách kỹ thuật |

### 5.3. Self-healing có giới hạn

Thứ tự tìm lại control có thể là:

1. Locator/semantic selector đã xác nhận.
2. Accessibility tree / UI Automation.
3. Java Access Bridge nếu là Java component.
4. DOM/frame context nếu là web.
5. Computer Vision/OCR làm fallback.
6. Hỏi người dùng nếu vẫn chưa xác định chắc chắn.

Tọa độ tuyệt đối chỉ nên là phương án cuối cùng và cần ràng buộc với ảnh/trạng thái màn hình đã xác minh. Không click chỉ vì một hình ảnh giống nhau nếu không có context và postcondition.

## 6. Delta Learning – cập nhật phần thay đổi, không học lại toàn bộ

### 6.1. Luồng cập nhật

```text
Runtime phát hiện sai khác
          │
          ▼
Phân loại: UI/Technical hay Business
          │
     ┌────┴─────────┐
     │              │
     ▼              ▼
UI/Technical     Business Change
     │              │
Tìm lại target   Dừng tại checkpoint
     │              │
Xác minh          Hỏi đúng người
     │              │
     │          Thu nhận hướng dẫn
     │              │
     │          Tạo Delta Patch
     │              │
     └──────┬───────┘
            ▼
       Validate Patch
            │
            ▼
    Sandbox / Twin Test
            │
            ▼
    Người có thẩm quyền xác nhận
            │
            ▼
       Process Version N+1
            │
            ▼
      Giữ Version N để rollback
```

### 6.2. Nguyên tắc Delta Patch

- Chỉ thay đổi node/edge/contract bị ảnh hưởng.
- Giữ nguyên các bước không bị ảnh hưởng.
- Ghi nguồn thay đổi: GDV hướng dẫn, quản trị viên hoặc phát hiện từ runtime.
- Lưu bằng chứng và người xác nhận.
- Chạy kiểm thử hồi quy các bước phụ thuộc.
- Không sửa trực tiếp version đang được sử dụng.
- Có thể rollback về version trước.

### 6.3. Hỏi đúng người

Không phải mọi thay đổi đều hỏi GDV:

| Vấn đề | Người xử lý phù hợp |
|---|---|
| Cách sử dụng một trường mới hoặc lựa chọn nghiệp vụ | GDV/chủ quy trình |
| Nhãn nút hoặc vị trí control | Agent tự tìm; hỏi GDV nếu chưa rõ |
| Quy định nghiệp vụ mới | Chủ quy trình/đầu mối nghiệp vụ |
| SOAP operation/schema thay đổi | CNTT/quản trị tích hợp |
| Quyền truy cập, token, chứng thư, cấu hình bảo mật | Quản trị viên/bộ phận bảo mật |
| Bước ghi dữ liệu hoặc liên quan tiền | Người có thẩm quyền theo quy trình kiểm soát |

## 7. Mô hình dữ liệu đề xuất

### 7.1. Ví dụ Semantic Process Contract

Ví dụ minh họa cho bước tra cứu sao kê; cần chuẩn hóa thành JSON Schema trong triển khai thật.

```json
{
  "process_id": "ACCOUNT_STATEMENT",
  "version": 1,
  "step_id": "SEARCH_STATEMENT",
  "business_intent": "Tra cứu sao kê tài khoản",
  "inputs": {
    "account": {"type": "account_reference", "required": true},
    "from_date": {"type": "date", "required": true},
    "to_date": {"type": "date", "required": true}
  },
  "preconditions": [
    "Đã mở chức năng sao kê",
    "Đã xác định tài khoản cần tra cứu"
  ],
  "target_semantics": {
    "role": "button",
    "name": "Tra cứu",
    "context": "Màn hình sao kê",
    "alternatives": ["Tìm kiếm", "Search"]
  },
  "execution_adapters": ["DOM", "UIA", "JAVA", "VISION"],
  "postconditions": [
    "Kết quả sao kê hiển thị",
    "Khoảng thời gian đúng với yêu cầu"
  ],
  "risk": "read",
  "recovery_policy": {
    "allow_target_re_resolution": true,
    "allow_business_change": false,
    "on_unknown": "ASK_USER"
  }
}
```

### 7.2. Event Model

Một event chuẩn nên có:

- `event_id`, `session_id`, `process_id`, `step_id` nếu xác định được.
- `timestamp`, `source_channel`, `process_id_os`, `window_id`, `parent_window_id`.
- `event_type`, `action`, `target_signature`.
- `input_schema` hoặc tham chiếu tham số đã được che.
- `request/response_metadata` nếu là service event.
- `state_before`, `state_after` ở mức cần thiết.
- `correlation_id` hoặc `caused_by` nếu xác định được.
- `evidence_ref` tới screenshot/file/log đã được bảo vệ.
- `redaction_status`, `confidence`, `risk`.

Không lưu giá trị nhạy cảm chỉ để thuận tiện cho replay. Dùng tham chiếu tham số và lấy dữ liệu từ phiên hợp lệ hiện tại theo chính sách được duyệt.

## 8. Xử lý các trường hợp đặc thù

### 8.1. Web/IE và frame

- Giữ JavaScript ES3 recorder hiện tại nếu cần tương thích môi trường IE cũ.
- Tiếp tục ghi nhận DOM/event/XHR/form/window.open trong phạm vi script có thể quan sát.
- Ghi rõ frame/context phát sinh sự kiện.
- Không giả định IE COM điều khiển được Edge IE Mode. Xác định chính xác môi trường trước khi chọn adapter.
- Có thể POC Selenium IEDriver cho Edge IE Mode, nhưng phải kiểm tra session/SSO và chính sách máy trạm; không xem đây là thay thế mặc định cho COM.

### 8.2. Java Applet

- Giữ Java Access Bridge khi ứng dụng expose accessibility component.
- Bổ sung UI Automation/Win32 để quan sát cửa sổ ngoài browser.
- Dùng screenshot/CV làm fallback khi component không được expose.
- Không giả định Java Access Bridge quan sát được mọi custom component hoặc dialog native.

### 8.3. SOAP/Service

- Phân biệt request do JavaScript/XHR gửi với request do JVM hoặc process khác gửi.
- Dùng browser hook chỉ cho lưu lượng thực sự đi qua browser JavaScript.
- Với Java/JVM, cân nhắc service interceptor, gateway logging, client instrumentation hoặc proxy trong sandbox được phê duyệt.
- WSDL giúp hiểu contract nhưng không tự chứng minh một thao tác UI tương ứng với operation nào.
- Liên kết UI action và service call bằng correlation ID nếu có; nếu không, dùng thời gian/context và đánh dấu độ chắc chắn.
- Không phát lại request thô như một business action. Cần business mapping, kiểm tra trạng thái, idempotency và quyền.
- Khi operation/schema thay đổi, adapter phải chuyển trạng thái cần xác minh; không tự gửi request cũ.

### 8.4. Dialog/Popup

Cần có Window/Dialog Observer độc lập với browser recorder:

- Theo dõi window create/destroy, activate/focus và owner/parent.
- Đọc control qua UIA/Win32 khi có thể.
- Ghi nhận screenshot và cấu trúc cửa sổ đã che dữ liệu.
- Phân biệt dialog thuộc browser, Java, ứng dụng Windows hay process bên ngoài.
- Dialog chưa biết phải dừng và hỏi, không tự bấm nút theo suy đoán.

### 8.5. Print/Report

Không coi `Print` chỉ là một click. Mô hình hóa riêng các trạng thái:

- `OPEN_REPORT`
- `SET_REPORT_PARAMETER`
- `PREVIEW_REPORT`
- `OPEN_PRINT_DIALOG`
- `SELECT_PRINTER`
- `SUBMIT_PRINT_JOB`
- `VERIFY_PRINT_JOB`
- `EXPORT_FILE`
- `VERIFY_OUTPUT_FILE`

Phải phân biệt:

1. Báo cáo hiển thị trên màn hình.
2. File PDF/Excel được tạo và lưu.
3. Print job được gửi.
4. Print job hoàn tất theo trạng thái mà hệ thống có thể quan sát.

Ưu tiên lưu/thu thập output gốc do ứng dụng tạo. HTML do Rookie dựng chỉ là bản trình bày bổ sung, không mặc định thay thế biểu mẫu chính thức.

## 9. Chính sách an toàn và kiểm soát

Các nguyên tắc hiện tại tiếp tục được giữ và củng cố:

- Mật khẩu, OTP, token, session secret không được ghi vào quy trình hoặc gửi lên server học.
- Dữ liệu nhạy cảm được che ngay tại máy GDV trước khi lưu/truyền.
- Không lưu giá trị cụ thể của trường nhạy cảm trong bản ghi; chỉ lưu loại trường và tham chiếu tham số khi phù hợp.
- Không tự phê duyệt.
- Bước `money` không tự chạy; luôn tuân thủ cơ chế kiểm soát của ngân hàng.
- Bước `write` phải chờ phê duyệt theo chính sách hiện hành.
- Cơ chế self-healing không được tự thay đổi ý nghĩa nghiệp vụ hoặc nâng quyền hành động.
- Không rõ trạng thái, không xác minh được kết quả hoặc gặp dialog chưa biết thì dừng an toàn.
- Có kill switch và audit trail.
- Tách dữ liệu sandbox, dữ liệu thử nghiệm và dữ liệu production.
- Chỉ dùng proxy/interceptor hoặc thu thập traffic khi được bộ phận quản trị và bảo mật cho phép.

## 10. Công nghệ tham khảo và định hướng lựa chọn

Không nên thay toàn bộ stack hiện tại. Dùng kiến trúc adapter, lựa chọn công nghệ theo môi trường thực tế.

| Năng lực | Công nghệ hiện tại/đề xuất | Quyết định |
|---|---|---|
| Core Agent | Python | Giữ |
| Backend | FastAPI | Giữ |
| Legacy Web/IE | JavaScript ES3 + IE COM hiện tại | Giữ trước; xác minh loại IE và POC adapter thay thế khi cần |
| Edge IE Mode | Selenium IEDriver | POC riêng; không mặc định thay COM |
| Modern Web | Playwright | Dùng cho Chromium và môi trường hỗ trợ |
| Windows UI | pywinauto UIA/Win32 | Bổ sung |
| Windows UI nâng cao | FlaUI/UIA3 | Đánh giá nếu Python backend chưa đủ |
| Java | Java Access Bridge | Giữ và bổ sung fallback |
| Visual fallback | OpenCV/OCR | Dùng khi accessibility/DOM không đủ; phải hậu kiểm |
| Window/Dialog | UIA events + WinEvent/Win32 | Bổ sung |
| Print | Windows Print Spooler API + file collector | Bổ sung |
| SOAP observation | Interceptor/gateway logging; proxy chỉ trong môi trường được phép | POC theo kiến trúc thật |
| Process learning | `align.py` hiện tại; nghiên cứu PM4Py | Không đưa vào core ngay; rà soát giấy phép và độ phù hợp |
| Trace | OpenTelemetry cho trace nội bộ của Rookie | Bổ sung nếu cần correlation/observability |
| Agent desktop reference | Microsoft UFO/UFO² | Tham khảo kiến trúc và adapter, không thay toàn bộ Rookie |
| Browser agent reference | Stagehand | Tham khảo cho Chromium, không giải quyết IE/Java |

### 10.1. Tham khảo

- Microsoft UFO: https://github.com/microsoft/UFO
- Stagehand: https://github.com/browserbase/stagehand
- pywinauto: https://pywinauto.readthedocs.io/
- FlaUI: https://github.com/FlaUI/FlaUI
- Playwright: https://playwright.dev/
- Selenium Internet Explorer Driver: https://www.selenium.dev/documentation/ie_driver_server/
- mitmproxy: https://docs.mitmproxy.org/
- Apache CXF Interceptors: https://cxf.apache.org/docs/interceptors.html
- PM4Py: https://pm4py.fit.fraunhofer.de/
- OpenTelemetry: https://opentelemetry.io/docs/

Các công nghệ trên là lựa chọn để đánh giá, không phải cam kết tương thích với TouchPoint. Cần POC trên đúng phiên bản Windows, browser, Java runtime, chính sách bảo mật và cấu hình hệ thống.

## 11. Điều chỉnh trên codebase hiện tại

Không viết lại các module đang có. Nâng cấp theo hướng bổ sung semantic model, observer và adaptive runtime.

| Module hiện tại | Định hướng nâng cấp |
|---|---|
| `ie/recorder.py` | Ghi event kèm context, state before/after và target signature |
| `ie/trace.py` | Chuẩn hóa event, correlation giữa UI/service/window/file |
| `ie/session.py` | Quản lý phiên quan sát đa kênh |
| `ie/clean.py` | Phân loại noise nhưng giữ lại bằng chứng drift và ngoại lệ |
| `ie/check.py` | Kiểm tra chất lượng bản ghi và độ đầy đủ evidence |
| `learner.py` | Sinh Semantic Process Contract từ nhiều lần ghi |
| `align.py` | Căn chỉnh bước nghiệp vụ, phát hiện biến thể và delta |
| `risk.py` | Giữ policy hiện tại; thêm rule cho recovery/patch và version |
| `ie/replay.py` | Chuyển từ replay request thô sang business-step execution |
| `ie/twin.py` | Mở rộng từ response mock thành state/process validation trong sandbox |
| `runner.py` | Thêm observe–compare–adapt–verify loop |
| `ie/report.py` | Phân biệt report gốc, file export và bản trình bày HTML |
| `ie/files.py` | Xác minh output, metadata, nguồn và định dạng |
| `/admin` | Xem diff phiên bản, evidence, đề xuất patch và phê duyệt |
| `mcp/` | Chỉ cho phép gọi quy trình và xem trạng thái; không cấp quyền duyệt |

### 11.1. Module mới đề xuất

```text
windows-agent/
├── adaptive/
│   ├── observer.py
│   ├── state_snapshot.py
│   ├── drift_detector.py
│   ├── change_classifier.py
│   ├── target_resolver.py
│   ├── recovery_agent.py
│   ├── gdv_assistant.py
│   └── delta_learning.py
│
├── process/
│   ├── semantic_contract.py
│   ├── process_version.py
│   ├── patch_manager.py
│   └── conformance.py
│
├── execution/
│   ├── semantic_replay.py
│   ├── state_verifier.py
│   └── safe_checkpoint.py
│
└── adapters/
    ├── browser/
    ├── windows_ui/
    ├── java/
    ├── soap/
    ├── dialog/
    └── print/
```

Tên module là gợi ý tổ chức. Có thể điều chỉnh theo cấu trúc package hiện tại để tránh tạo quá nhiều lớp trừu tượng.

## 12. Lộ trình triển khai

### P0 – Chốt môi trường và baseline

- Xác định chính xác TouchPoint đang chạy IE11 desktop, Edge IE Mode hay WebBrowser Control nhúng.
- Xác định Java Applet chạy trong browser hay process Java riêng.
- Xác định SOAP call được phát từ JavaScript, JVM hay service trung gian.
- Chụp baseline cho một quy trình có dialog và print.
- Giữ nguyên luồng Record–Learn–Run hiện tại để có baseline so sánh.

**Kết quả:** sơ đồ runtime thật và ma trận adapter cần hỗ trợ.

### P1 – Observer đa kênh và state verification

- Bổ sung Windows Window/Dialog Observer.
- Ghi nhận UIA/Win32, Java Access Bridge và screenshot fallback.
- Ghi nhận Print Dialog, file output và print job metadata.
- Bổ sung state before/after và postcondition cho mỗi bước.

**Kết quả:** một phiên ghi nhận liên kết được browser, Java, window, report và file.

### P2 – Semantic Process Contract

- Nâng `learner.py` để sinh business step thay vì chỉ gom call.
- Tách business action khỏi HTTP request.
- Bổ sung precondition, postcondition, semantic target, adapter và risk contract.
- Liên kết UI event với service call bằng correlation/evidence.

**Kết quả:** quy trình không còn phụ thuộc cứng vào selector hoặc endpoint cũ.

### P3 – Adaptive Runtime

- Bổ sung drift detector và change classifier.
- Tự tìm lại control khi thay đổi chỉ mang tính giao diện.
- Kiểm tra postcondition trước khi tiếp tục.
- Xây dựng flow hỏi GDV khi gặp trạng thái hoặc dialog chưa biết.

**Kết quả:** demo được thay đổi ID/vị trí/nhãn control mà không phải record lại toàn bộ.

### P4 – Delta Learning và version management

- Cho phép GDV hướng dẫn thêm/sửa một phần quy trình.
- Tạo patch, không ghi đè process version hiện tại.
- Chạy sandbox/twin validation và regression test.
- Xác nhận, phát hành version mới và hỗ trợ rollback.

**Kết quả:** demo được thêm một bước nghiệp vụ và cập nhật v2 từ v1.

### P5 – Mở rộng đa ứng dụng

- Hoàn thiện adapter SOAP/JVM theo kiến trúc thật.
- Mở rộng sang Windows app và các hệ thống khác.
- Bổ sung process mining/conformance nếu dữ liệu và nhu cầu thực tế đủ lớn.

## 13. Kịch bản demo Hackathon

**Tên demo:** Live Adaptive Learning – Ứng dụng thay đổi, Rookie vẫn làm việc.

### Kịch bản

1. GDV làm mẫu nghiệp vụ xuất sao kê trên TouchPoint.
2. Rookie tạo Process Twin v1 với business steps, tham số, điều kiện, adapter và risk.
3. Người demo thay đổi UI giả lập: đổi ID, nhãn hoặc vị trí nút.
4. GDV yêu cầu Rookie chạy lại.
5. Rookie phát hiện UI drift, tìm lại mục tiêu bằng semantic/accessibility/context và xác minh kết quả.
6. Người demo thêm một Dialog hoặc trường nghiệp vụ mới.
7. Rookie dừng ở checkpoint, giải thích điểm thay đổi và hỏi GDV.
8. GDV hướng dẫn đúng phần mới; Rookie tạo Delta Patch.
9. Patch được kiểm thử trên sandbox, GDV xác nhận và phát hành Process v2.
10. Chạy lại quy trình v2; giữ v1 để đối chiếu/rollback.

### Chỉ số đánh giá

- Tỷ lệ tự phục hồi khi chỉ thay đổi giao diện.
- Tỷ lệ nhận diện đúng control sau khi thay đổi.
- Tỷ lệ phát hiện đúng thay đổi nghiệp vụ.
- Tỷ lệ trường hợp Agent hỏi đúng người và đúng thời điểm.
- Số bước phải ghi lại khi có thay đổi.
- Thời gian từ khi phát hiện thay đổi đến khi cập nhật quy trình.
- Tỷ lệ hoàn thành có xác minh đúng postcondition.
- Số hành động sai hoặc vượt quyền: mục tiêu bằng 0.

## 14. Tiêu chí nghiệm thu PoC

| Nhóm | Tiêu chí |
|---|---|
| Self-adaptation (MAPE-K) | Mỗi quyết định thích nghi ghi được: quan sát gì, phân loại là kỹ thuật hay nghiệp vụ, chọn cách nào, kết quả postcondition ra sao |
| Record đa kênh | Ghi được thao tác trên kênh mục tiêu và liên kết được window/dialog/service/output khi có bằng chứng |
| Semantic Twin | Mỗi bước có business intent, input/output, pre/postcondition, adapter và risk |
| UI adaptation | Đổi selector/ID/vị trí nhưng giữ nguyên ý nghĩa thì Agent có thể tìm lại mục tiêu và xác minh |
| Business change | Thêm/bớt bước hoặc thay đổi điều kiện thì Agent dừng, hỏi và tạo đề xuất delta |
| Versioning | Không ghi đè version đang phát hành; có diff, approval và rollback |
| Print/report | Phân biệt preview, file export, print submission và trạng thái job |
| SOAP | Phân biệt event phía browser với event phía JVM/service; không replay request thô không kiểm soát |
| Safety | Không lưu secret; write/money luôn tuân thủ approval; unknown state thì dừng |
| Audit | Truy vết được process version, event, evidence, người hướng dẫn và người xác nhận |

## 15. Các quyết định kiến trúc cần chốt

1. **Giữ Python/FastAPI làm core.** Không chuyển toàn bộ sản phẩm sang một framework desktop agent khác.
2. **Giữ recorder hiện tại làm adapter legacy.** Chỉ thay khi benchmark trên đúng TouchPoint chứng minh phương án mới tốt hơn.
3. **Tách business process khỏi technical event.** Đây là thay đổi nền tảng quan trọng nhất.
4. **Đưa Observer và State Verifier vào runtime.** Không chỉ quan sát trong lúc Record.
5. **Tách UI self-healing khỏi business delta learning.** Hai loại thay đổi có quyền và quy trình xử lý khác nhau.
6. **Agent đề xuất, kiểm thử và giải thích thay đổi; con người xác nhận thay đổi nghiệp vụ.**
7. **Mọi execution phải có postcondition.** Click thành công không đồng nghĩa nghiệp vụ thành công.
8. **Mọi process version phải có evidence, audit và rollback.**
9. **SADPT là khung chính của sản phẩm.** Mọi tính năng mới (Record, Learn, Run, Adapt, Admin) phải nói rõ thuộc phần nào của vòng MAPE-K và cập nhật Knowledge tương ứng.

---

## 16. Thông điệp sản phẩm

> **Rookie Agent – Self-Adaptive Digital Process Twin (SADPT)**, bản sao số quy trình nghiệp vụ có khả năng tự thích nghi: trợ lý AI đồng hành cùng giao dịch viên, học quy trình nghiệp vụ từ thao tác thực tế, thực thi xuyên nhiều ứng dụng và công nghệ cũ, tự thích nghi khi giao diện thay đổi và học bổ sung từ hướng dẫn của con người khi nghiệp vụ thay đổi.

**Learn Once. Adapt Always. Work Together.**
