# Cài Codie để học luồng bằng mô hình

Máy GDV chỉ gọi Codie qua lệnh (`codie --mode M --cwd W -p ...`); Codie chạy phía local, đọc bản ghi **đã che** trong thư mục tạm.

1. Thêm hai mode trong `config/codie-modes.json` vào cấu hình Codie của máy (`rookie-design`, `rookie-workflow`).
2. Trong cấu hình model của Codie: `rookie-design` dùng Fable 5.2, `rookie-workflow` dùng Sonnet 5.5.
3. Biến môi trường (tuỳ chọn): `ROOKIE_CODIE_ENABLED` (0 = tắt), `ROOKIE_CODIE_COMMAND`, `ROOKIE_CODIE_MODE_DESIGN`, `ROOKIE_CODIE_MODE_WORKFLOW`, `ROOKIE_CODIE_TIMEOUT` (giây, mặc định 600).
4. Thử: tab **Kết nối** trong trang quản lý (http://localhost:8765) có nút thử và nhật ký các lần gọi (chế độ, kết quả, số giây, không có nội dung).
5. Khi Học: server thử Codie (thiết kế rồi dựng workflow, kiểm bằng cổng, sửa tối đa 2 lần). Không đạt hoặc không có Codie thì tự dùng bộ học theo luật; kết quả ghi rõ `method` là `codie` hay `rule` và lý do (`fallback_reason`).

Lưu ý: việc che dữ liệu gửi LLM/Codie còn để làm sau; Codie thật chưa được chạy thử (test dùng tiến trình giả `windows-agent/tests/fake_model.py`).
