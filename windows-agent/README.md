# Windows agent (hướng B)

Ghi thao tác của GDV trên ứng dụng Java (applet trong IE mode, hoặc ứng dụng Swing) qua Java Access Bridge. Thiết kế ở `docs/design.md` mục 3B.

Hiện có: kiểm tra bridge, in cây thành phần, ghi thao tác ra file JSON, Native Messaging host. Chưa có: chạy lại workflow (task 2.8) và nút bấm trên side panel (chờ task 1.4).

## Mang vào máy nội bộ

Ở máy ngoài, chạy một lệnh để đóng gói:

```powershell
.\scripts\package-path-b.ps1                      # tạo dist\rookie-agent-path-b.zip
.\scripts\package-path-b.ps1 -Password <mật khẩu>   # zip có mật khẩu (máy đóng gói cần 7-Zip)
```

Zip có mật khẩu mở được bằng Windows Explorer (Extract All) hoặc 7-Zip. Thêm `-Encryption AES256` nếu muốn mã hoá mạnh hơn, khi đó máy đích cần 7-Zip hoặc WinRAR. Mật khẩu chỉ gõ ở dòng lệnh, không lưu trong repo.

File zip gồm `windows-agent\`, `config\`, `schemas\` và `mock-java\mock-tpss.jar`. Copy file này vào máy nội bộ rồi giải nén, giữ nguyên cấu trúc thư mục.

Máy nội bộ cần có sẵn:

| Cần | Ghi chú |
| --- | --- |
| Python 3.10 trở lên | **Cùng bitness với JRE của ứng dụng Java.** Applet trong IE mode thường dùng JRE 32-bit, khi đó phải dùng Python 32-bit. |
| JRE hoặc JDK 8 trở lên | Chính là JRE mà ứng dụng đang dùng. Trong thư mục `bin` của nó có `jabswitch.exe` và `WindowsAccessBridge-32.dll` hoặc `-64.dll`. |

Agent chỉ dùng thư viện chuẩn của Python khi chạy, không cần `pip install`. Máy chủ (để học workflow) cần bốn thư viện, đã có sẵn trong thư mục `wheels\` của gói; thư viện phải đúng phiên bản và 32/64-bit với Python ở máy nội bộ, nên đóng gói bằng `.\scripts\package-path-b.ps1 -PythonVersion 3.10 -Platform win32` nếu cần. Chạy test thì cần `pytest` và `jsonschema` (`requirements-dev.txt`).

## Chạy trên máy nội bộ

```powershell
# 1. Bật Java Access Bridge cho người dùng hiện tại (một lần), rồi đóng và mở lại ứng dụng Java
& "C:\đường\dẫn\tới\jre\bin\jabswitch.exe" -enable

# 2. Nếu DLL không nằm trong JAVA_HOME hay PATH, chỉ đường cho agent
$env:ROOKIE_JAB_DLL = "C:\đường\dẫn\tới\jre\bin\WindowsAccessBridge-32.dll"

cd windows-agent

# 3. Kiểm tra: bridge có chạy không, thấy cửa sổ Java nào
python -m rookie_agent status

# 4. In cây thành phần của màn hình đang mở (đây là spike của task 1.7)
python -m rookie_agent tree --window "TPSS" > tree.txt

# 5. Ghi thao tác; bấm Enter ở cửa sổ lệnh để Dừng
python -m rookie_agent record --window "TPSS" --out session.json
```

Thử trước với mock, không cần ứng dụng thật:

```powershell
java -jar mock-java\mock-tpss.jar      # đăng nhập gdv01 / demo-only-1234, hoặc ksv01 / demo-only-5678
```

### Đọc kết quả của `tree`

Mỗi dòng là `vai trò [tên]`. Dòng có `<-- KHÔNG CÓ TÊN` là ô nhập, nút hoặc bảng mà Java Access Bridge không đọc được tên. Cuối file có tổng số. Nếu phần lớn thành phần có tên thì hướng B đi được bằng Java Access Bridge. Nếu nhiều thành phần không có tên thì cần phương án Java agent dự phòng. Ghi kết quả vào `docs/spike-jab.md`.

`tree.txt` chứa nhãn và cả dữ liệu đang hiển thị trên màn hình. Mở màn hình trống hoặc dùng dữ liệu thử khi chạy lệnh này, và đừng mang file ra khỏi máy nội bộ khi chưa xem lại.

### Kết nối với extension

```powershell
.\install\register_host.ps1 -ExtensionId <id của extension> -Python C:\đường\dẫn\python.exe
.\install\register_host.ps1 -Unregister
```

Lệnh này đăng ký agent làm Native Messaging host cho Edge và Chrome của người dùng hiện tại. Phần side panel gọi host sẽ có ở task 1.4 và 1.9.

## Những gì được ghi

| Thao tác | Sự kiện | Ghi chú |
| --- | --- | --- |
| Gõ vào ô nhập | `input` | Một sự kiện cho mỗi lần sửa xong một ô. Trường nhạy cảm chỉ lưu loại trường, không lưu giá trị. |
| Ô mật khẩu, OTP | không ghi | Agent không đọc nội dung ô có vai trò `password text`. |
| Bấm chuột vào nút, menu | `click` | |
| Chuyển tab | `click` | |
| Tích ô chọn, nút radio | `click` | |
| Chọn dòng trong bảng | `select` | Lưu số thứ tự dòng, không lưu nội dung ô. |
| Enter trong một ô (cần agent Java) | `submit` | Không lưu gì của ô. Chạy lại bằng hành động Enter của ô. |

Bảng phân loại trường nằm ở `config\field-classes.json`, dùng chung với extension. Trường chưa có trong bảng được coi là nhạy cảm.

## Thử với một màn hình thật (ví dụ vấn tin tài khoản)

Dùng **môi trường thử và tài khoản thử**, không dùng số liệu thật. Mỗi bước sau chạy trong PowerShell, thư mục `windows-agent\`.

1. **Cài Python** cùng loại với Java đang chạy ứng dụng: mở ứng dụng, vào Task Manager, tab Details; nếu tiến trình Java (`jp2launcher.exe`, `javaw.exe`) có chữ `*32` thì dùng Python 32-bit.
2. **Bật Java Access Bridge** bằng `jabswitch.exe -enable` của đúng JRE đó (thư mục `bin` của JRE), rồi đóng hẳn trình duyệt hoặc ứng dụng và mở lại. Nếu DLL không tự tìm thấy: `$env:ROOKIE_JAB_DLL = "...\bin\WindowsAccessBridge-32.dll"`.
3. **Kiểm tra:** `python -m rookie_agent status`. Phải thấy "sẵn sàng" và danh sách cửa sổ Java. Không thấy cửa sổ nào nghĩa là ứng dụng không phải Java hoặc bridge chưa bật.
4. **Xem các ô có tên không:** mở màn hình vấn tin, `python -m rookie_agent tree --window "<một phần tiêu đề>" > tree.txt`. Cuối file ghi số thành phần không có tên.
5. **Ghi một lần:** `python -m rookie_agent record --window "<tiêu đề>" --out vantin1.json`. Làm đúng việc vấn tin (nhập số tài khoản thử, bấm Tra cứu hoặc Enter), rồi quay lại cửa sổ lệnh bấm Enter để dừng. Mở `vantin1.json`, tìm số tài khoản vừa gõ: **không được có**. Phải thấy các sự kiện `input` có `value_class` và `click` hoặc `submit`.
6. **Nếu bạn dùng Enter** thay vì bấm nút mà không thấy bước gửi trong file: bật agent Java (mục dưới), mở lại ứng dụng, ghi lại.
7. **Ghi ba lần** với ba tài khoản thử khác nhau (`vantin1.json` đến `vantin3.json`).
8. **Học (cần máy chủ):** `pip install --no-index --find-links ..\wheels -r ..\server\requirements-run.txt`, rồi `cd ..\server; python -m uvicorn app.main:app --port 8000`. Ở cửa sổ khác: `python -m rookie_agent upload --server http://localhost:8000 --file vantin1.json` (làm cho cả ba file, ghi lại mã phiên in ra), rồi `python -m rookie_agent learn --server http://localhost:8000 --id van-tin-tai-khoan --sessions <mã1> <mã2> <mã3>`. Kết quả liệt kê các bước, thông tin cần nhập, và mức rủi ro của từng bước.

**Chưa chạy lại được trên ứng dụng thật:** chạy thử chỉ cho phép trên mock (quy tắc PoC: dữ liệu giả lập), và Chạy chỉ cho workflow đã duyệt. Nên hiện chỉ làm được bước 1 đến 8.

## Ghi cả thao tác bằng bàn phím

Người quầy hay dùng Enter và Tab. Java Access Bridge không thấy Enter trong một ô, nên cần một agent nhỏ chạy trong chính ứng dụng Java:

```powershell
# một lần, cho người dùng Windows hiện tại (không cần quyền quản trị)
.\install\enable_java_agent.ps1 -Jar ..\java-agent\rookie-java-agent.jar
# đóng và mở lại ứng dụng Java; tắt đi bằng: .\install\enable_java_agent.ps1 -Disable
```

Agent này **chỉ làm việc khi bạn bấm Ghi**, không bao giờ ghi ký tự gõ hay giá trị của ô, và chỉ ghi ra thư mục `%LOCALAPPDATA%\RookieAgent` trên máy này. Gói đóng sẵn `dist\rookie-agent-path-b.zip` đã kèm jar.

## Hạn chế đã biết

- **Thao tác bằng bàn phím chỉ ghi được khi đã bật agent Java** (xem mục "Ghi cả thao tác bằng bàn phím"). Java Access Bridge một mình không thấy Enter trong ô hay nút bấm bằng phím.
- **Phím chức năng và phím tắt gắn với hành động không qua nút chưa ghi được**; chỉ đo được khi có Touchpoint thật.
- **Combo box chưa được ghi.** Mock chưa có combo box để kiểm chứng.
- **Nhánh bấm chuột chưa có test tự động trên ứng dụng thật**, chỉ có test đơn vị. Test tích hợp điều khiển mock qua bridge (điền text, chuyển tab) nên không sinh sự kiện chuột.
- Mới thử với JDK 21 64-bit trên mock Swing. Chưa thử với JRE 8 32-bit và applet thật trong IE mode.

## Test

```powershell
cd windows-agent
pytest
```

Test tích hợp tự bỏ qua nếu máy không có JDK kèm DLL của bridge, hoặc chưa build `mock-java\out` (`mock-java\build.ps1`).
