# Windows agent (hướng B)

Ghi thao tác của GDV trên ứng dụng Java (applet trong IE mode, hoặc ứng dụng Swing) qua Java Access Bridge. Thiết kế ở `docs/design.md` mục 3B.

Hiện có: kiểm tra bridge, in cây thành phần, ghi thao tác ra file JSON, Native Messaging host. Chưa có: chạy lại workflow (task 2.8) và nút bấm trên side panel (chờ task 1.4).

## Mang vào máy nội bộ

Ở máy ngoài, chạy một lệnh để đóng gói:

```powershell
.\scripts\package-path-b.ps1      # tạo dist\rookie-agent-path-b.zip
```

File zip gồm `windows-agent\`, `config\`, `schemas\` và `mock-java\mock-tpss.jar`. Copy file này vào máy nội bộ rồi giải nén, giữ nguyên cấu trúc thư mục.

Máy nội bộ cần có sẵn:

| Cần | Ghi chú |
| --- | --- |
| Python 3.10 trở lên | **Cùng bitness với JRE của ứng dụng Java.** Applet trong IE mode thường dùng JRE 32-bit, khi đó phải dùng Python 32-bit. |
| JRE hoặc JDK 8 trở lên | Chính là JRE mà ứng dụng đang dùng. Trong thư mục `bin` của nó có `jabswitch.exe` và `WindowsAccessBridge-32.dll` hoặc `-64.dll`. |

Agent chỉ dùng thư viện chuẩn của Python khi chạy, không cần `pip install`. Chạy test thì cần `pytest` và `jsonschema` (`requirements-dev.txt`).

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

Bảng phân loại trường nằm ở `config\field-classes.json`, dùng chung với extension. Trường chưa có trong bảng được coi là nhạy cảm.

## Hạn chế đã biết

- **Bấm nút bằng bàn phím (Enter, phím cách, phím tắt) chưa được ghi.** Java Access Bridge chỉ báo sự kiện khi bấm bằng chuột. Nếu GDV quen dùng bàn phím thì cần Java agent dự phòng.
- **Combo box chưa được ghi.** Mock chưa có combo box để kiểm chứng.
- **Nhánh bấm chuột chưa có test tự động trên ứng dụng thật**, chỉ có test đơn vị. Test tích hợp điều khiển mock qua bridge (điền text, chuyển tab) nên không sinh sự kiện chuột.
- Mới thử với JDK 21 64-bit trên mock Swing. Chưa thử với JRE 8 32-bit và applet thật trong IE mode.

## Test

```powershell
cd windows-agent
pytest
```

Test tích hợp tự bỏ qua nếu máy không có JDK kèm DLL của bridge, hoặc chưa build `mock-java\out` (`mock-java\build.ps1`).
