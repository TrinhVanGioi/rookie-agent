# Extension Rookie Agent (hướng A, web trên Chrome/Edge)

Ghi lại thao tác trên trang web để agent học. Bản thử này có hai việc: **Ghi** và **Học**. Chạy lại (Chạy, Duyệt) chưa có trên web.

## Cài thử (Edge hoặc Chrome, không cần Store)

Trong gói, bấm đúp `Cai-extension-Chrome.cmd` (sau khi đã chạy `Cai-dat.cmd`): nó chép extension vào `%LOCALAPPDATA%\RookieAgent\extension`, tạo biểu tượng trên màn hình nền, mở `chrome://extensions` và chép sẵn đường dẫn thư mục vào clipboard. Bạn chỉ còn bật Chế độ nhà phát triển, bấm Tải tiện ích đã giải nén, dán đường dẫn. Cách làm tay:

1. Mở `edge://extensions` (Chrome: `chrome://extensions`), bật **Chế độ nhà phát triển**.
2. Bấm **Tải tiện ích đã giải nén** và chọn thư mục `extension` (trong gói, hoặc `extension\dist` khi tự build).
3. Bấm biểu tượng Rookie Agent trên thanh công cụ. Khung bên phải mở ra.
4. Mở trang cần ghi ở thẻ đang chọn. Bấm **Bắt đầu ghi**. Trình duyệt hỏi cho phép trên trang đó, chọn **Cho phép**. Làm việc như thường, xong bấm **Dừng ghi**. Ghi 3 lần.
5. Mục **Học**: nhập địa chỉ máy chủ (máy chủ có sẵn trong gói: mở trang Rookie Agent bằng biểu tượng trên màn hình nền, mục Học, bấm **Bật máy chủ trên máy này**; địa chỉ là `http://localhost:8000`), chọn các bản ghi, đặt tên, bấm **Học**.

## Điều cần biết

- Chỉ ghi thẻ đã chọn khi bấm Bắt đầu ghi, và chỉ khi đang ghi. Biểu tượng hiện chữ REC.
- Ô mật khẩu và OTP không ghi gì. Ô nhạy cảm (số tài khoản, CCCD, tên, số tiền, và mọi ô chưa phân loại được) chỉ lưu loại ô. Giá trị chỉ lưu với ô thường như ngày, loại, trạng thái. Bảng phân loại là `config/field-classes.json`, dùng chung với Windows agent.
- Chữ trên nút và liên kết được che nếu có dãy số dài hay e-mail. Ô trong bảng dữ liệu chỉ được mô tả bằng vị trí, không lưu chữ.
- Địa chỉ trang chỉ lưu phần đường dẫn, không có tham số, và phần giống mã số được thay bằng `{id}`.
- Không ghi được trang chạy trong **IE mode** của Edge (extension không chạy trong tab IE mode; dùng Windows agent), khung (iframe) khác tên miền, và hộp thoại của trình duyệt.
- Bản ghi nằm trong trình duyệt trên máy này đến khi bạn gửi đi học hoặc xóa.

## Lệnh

```powershell
cd extension; npm install; npm run build; npm test   # dist\ là thư mục để tải lên
cd tests\e2e; npx playwright test specs\extension.spec.ts   # nạp extension thật vào Chromium, ghi trên mock site, học qua server
```
