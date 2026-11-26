# Trọ Nhà — quản lý nhà trọ và cổng khách thuê

Ứng dụng quản lý chạy trên máy tính Windows bằng Python/Tkinter. Khi mở, ứng dụng đồng thời khởi động máy chủ cục bộ để khách thuê đăng nhập trên điện thoại bằng trình duyệt.

## Chạy ứng dụng

1. Cài Python 3.10 trở lên, gồm thành phần Tcl/Tk.
2. Cài các gói trong `requirements.txt` bằng Python 3.11 trở lên; SQL Server ODBC Driver 18 cần có trên Windows.
3. Chạy `python app.py` hoặc nhấp đúp `run.bat`.
4. Ứng dụng kết nối `(localdb)\MSSQLLocalDB`, dùng Windows Authentication và database `QuanLyNhaTro`. Mật khẩu tài khoản được băm trước khi lưu.
5. Trong tab **Hợp đồng**, chọn hợp đồng đang thuê và bấm **Tạo tài khoản khách thuê**.
6. Điện thoại khách thuê cần dùng cùng Wi‑Fi với máy tính quản lý. Mở địa chỉ `http://<địa-chỉ-máy-tính>:8765` trên điện thoại và đăng nhập. Địa chỉ được hiện khi admin đăng nhập.

Máy tính quản lý cần bật và ứng dụng cần chạy để cổng khách thuê hoạt động. SQL Server LocalDB chỉ dành cho máy quản lý hiện tại; để nhiều máy/điện thoại kết nối SQL trực tiếp cần một SQL Server dùng chung, không phải LocalDB.

Khi đang chạy ứng dụng desktop, nếu lưu thay đổi vào `app.py`, `server.py` hoặc `database.py`, Trọ Nhà sẽ tự kiểm tra mã, chờ hộp thoại đang mở đóng lại, rồi tự khởi động lại để nạp phiên bản mới. Dữ liệu đã lưu trong SQL Server được giữ nguyên; admin cần đăng nhập lại sau khi ứng dụng tự khởi động.

## Phân quyền và quy trình điện nước

- Admin đăng nhập ứng dụng desktop để quản lý phòng, khách, hợp đồng, phí và thanh toán.
- Khi chốt hợp đồng, hệ thống tự tạo tài khoản khách: tên đăng nhập là số điện thoại (chỉ gồm chữ số), mật khẩu mặc định `tronha`. Khách nên đổi mật khẩu sau lần đăng nhập đầu tiên.
- Khách đăng nhập cổng di động để xem hóa đơn và thông báo, gửi ảnh điện/nước, theo dõi chỉ số đã cập nhật và đổi mật khẩu.
- Cổng di động dùng OCR trên thiết bị để gợi ý số từ ảnh. Khi khách gửi, hệ thống ghi số và ảnh vào SQL Server, tính lượng dùng so với lần gửi trước, cập nhật hóa đơn và thông báo cho khách ngay. Admin có thể xem ảnh trong tab **Chỉ số công tơ**.
- Lần gửi đầu tiên được lưu làm chỉ số gốc nên lượng dùng là 0. Hóa đơn tạm tính được cập nhật sau từng chỉ số; sau khi có cả điện và nước, hóa đơn chuyển sang **Chưa thanh toán**.
- Khi hóa đơn được tính lại từ số khách gửi hoặc admin nhập phí, ứng dụng lưu thông báo kèm tổng tiền/hạn thanh toán; hóa đơn chi tiết tự xuất hiện trong mục **Hóa đơn** của khách.
- Cổng khách tự làm mới định kỳ khi đang mở để hiển thị hóa đơn và thông báo mới; nếu khách đóng cổng, hóa đơn sẽ hiện khi họ mở lại.
- Email hóa đơn là kênh tùy chọn: cấu hình SMTP trong **Hóa đơn tháng → Cấu hình email** và bật tự gửi nếu muốn tự gửi email sau khi chốt số liệu.

## Kết nối ngoài mạng nội bộ

Cấu hình mặc định chỉ phù hợp để dùng trong mạng Wi‑Fi riêng: cổng dùng HTTP, chưa bật HTTPS và máy chủ chạy trên máy đang mở ứng dụng. Không chuyển tiếp cổng này ra Internet. Muốn khách truy cập từ mạng di động hoặc bên ngoài cần triển khai máy chủ có HTTPS và tên miền, rồi mới sử dụng dữ liệu thật qua Internet.

Ảnh công tơ, thông tin tài khoản, cấu hình và dữ liệu vận hành nằm trong SQL Server. Hãy bảo vệ SQL Server và máy tính quản lý. Thông tin SMTP được lưu trong database SQL Server.

## Các chức năng hiện có

- Quản lý phòng, khách quan tâm, lịch xem, hợp đồng thuê, trả phòng và thu chi.
- Tự tạo hóa đơn tháng, tính tiền phòng, điện, nước, Internet, dịch vụ, gửi xe và khoản phí khác.
- Theo dõi thanh toán, sao chép hóa đơn và gửi email SMTP thủ công hoặc tự động.
- Cổng di động hiển thị hóa đơn, trạng thái chỉ số, lịch sử gửi, thông báo và đổi mật khẩu.
