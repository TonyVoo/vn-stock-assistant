"""Trang Hướng dẫn: cách dùng, cập nhật dữ liệu, bật AI, từ điển."""
from __future__ import annotations

import streamlit as st

from src import ui

GLOSSARY = [
    ("Cổ phiếu / Mã", "Phần sở hữu nhỏ trong một công ty. Mỗi công ty có một mã gồm 3 chữ cái, ví dụ FPT, VCB."),
    ("Lô", "Đơn vị mua tối thiểu. Một lô = 100 cổ phiếu. Bạn không thể mua 7 cổ phiếu lẻ trên sàn thông thường."),
    ("Cắt lỗ", "Tự bán khi giá giảm xuống một mức đã định trước, để không bị lỗ quá sâu. Đặt mức này TRƯỚC khi mua."),
    ("Giá mục tiêu", "Mức giá bạn hy vọng bán được để chốt lãi."),
    ("T+2", "Mua hôm nay thì sau 2 ngày làm việc cổ phiếu mới về tài khoản để bán được."),
    ("Biên độ giá", "Mức tăng/giảm tối đa trong một ngày: ±7% sàn HOSE, ±10% HNX, ±15% UPCoM."),
    ("VN-Index", "Chỉ số đo sức khỏe chung của thị trường (HOSE). Tăng nghĩa là phần lớn cổ phiếu đang tăng."),
    ("VN30", "Nhóm 30 cổ phiếu lớn và giao dịch nhiều nhất trên HOSE."),
    ("Xu hướng", "Hướng đi chung của giá trong vài tháng: đang tăng, đi ngang hay đang giảm."),
    ("Mức trung bình 50/200 phiên", "Giá trung bình của 50 hoặc 200 ngày giao dịch gần nhất. Giá nằm trên mức này thường là dấu hiệu tốt."),
    ("Tăng nóng", "Giá đã tăng quá nhanh trong thời gian ngắn, thường dễ có nhịp nghỉ hoặc giảm lại."),
    ("Thanh khoản / Lượng giao dịch", "Có nhiều hay ít người mua bán mã này. Ít người giao dịch thì khó bán khi bạn cần."),
    ("Lãi tiềm năng so với lỗ tiềm năng", "Nếu đúng bạn lãi gấp mấy lần số tiền mất khi sai. Nên ít nhất khoảng 2 lần."),
    ("Kiểm chứng bằng dữ liệu quá khứ (backtest)", "Mô phỏng một cách mua bán trên dữ liệu cũ để xem nó có từng hiệu quả không."),
    ("Động lượng", "Ý tưởng: cổ phiếu đã tăng mạnh gần đây có xu hướng tiếp tục tăng. Chưa được chứng minh ổn định ở app này."),
]


def render(ctx) -> None:
    ui.page_header("Hướng dẫn", "Mọi thứ bạn cần biết để dùng app này, viết cho người mới.")
    ui.callout("App này giúp bạn XEM TÌNH HÌNH, TÍNH TOÁN AN TOÀN và GHI NHẬT KÝ. Nó KHÔNG đoán trước được giá sẽ tăng hay giảm, "
               "và không phải lời khuyên đầu tư. Mọi quyết định mua bán và khoản tiền đều là của bạn.", "warn", "Hiểu đúng về app này")

    st.markdown("### 4 bước dùng app")
    st.markdown(
        "1. **Tổng quan**: xem thị trường hôm nay và tình hình các mã bạn theo dõi.\n"
        "2. **Tra cứu cổ phiếu**: bấm vào một mã để đọc giải thích bằng lời thường.\n"
        "3. **Tính lệnh mua**: trước khi mua, biết nên mua bao nhiêu để nếu sai chỉ mất một phần nhỏ vốn.\n"
        "4. **Nhật ký giao dịch**: ghi lại lý do mua và học từ kết quả.")

    st.markdown("### Vài nguyên tắc cho người mới")
    st.markdown(
        "- **Chỉ đầu tư số tiền bạn chấp nhận có thể mất.** Giá có thể giảm nhiều và lâu.\n"
        "- **Đặt mức cắt lỗ trước khi mua** và làm theo nó, đừng đổi ý khi đã lỗ.\n"
        "- **Đừng dồn hết vốn vào một mã.**\n"
        "- **Không vay tiền để mua cổ phiếu** (margin) khi chưa có kinh nghiệm.\n"
        "- **Đừng tin lời hứa “chắc chắn lãi”**, kể cả từ app này, từ AI hay từ người quen.")

    st.markdown("### Cập nhật dữ liệu giá")
    st.write("Dữ liệu giá nằm trong máy bạn và không tự cập nhật. Mỗi tuần hoặc mỗi tháng, mở Terminal và chạy:")
    st.code("cd ~/Desktop/vn-stock-assistant/vn-stock-assistant\n.venv/bin/python scripts/download_prices.py --years 10", language="bash")
    st.caption("Lần đầu cần đăng ký key miễn phí của vnstock (xem README). Xong bấm F5 để tải lại trang.")

    st.markdown("### Bật AI (tuỳ chọn)")
    st.write("Phần AI (bản tin, phân tích) cần một khóa truy cập. Mở file `.env` trong thư mục dự án và điền theo hướng dẫn trong "
             "file `.env.example`. Nếu không bật, mọi phần khác vẫn dùng bình thường. "
             "**Không gửi khóa này cho bất kỳ ai và không dán vào chat.**")

    st.markdown("### Danh mục và kết nối TCBS (chỉ đọc)")
    st.write("Trang **Danh mục** cho thấy bạn đang giữ gì, giá trị hiện tại và lãi/lỗ. Bạn có thể nhập tay, tải file xuất từ công ty "
             "chứng khoán, dựng từ Nhật ký, hoặc kết nối TCBS để lấy tự động. App **chỉ đọc**: không đặt, sửa hay huỷ lệnh, "
             "không chuyển tiền. Khoá API của TCBS không có chế độ chỉ-đọc, nên hãy giữ khoá kín, không gửi cho ai, và huỷ khoá "
             "trong TCInvest khi không dùng. Mỗi lần lấy dữ liệu bạn nhập Smart OTP ngay trong app; mã này không được lưu.")

    st.markdown("### Danh mục khác Nhật ký thế nào?")
    st.write("**Danh mục** cho biết bạn ĐANG GIỮ gì và đáng giá bao nhiêu. **Nhật ký** ghi TỪNG LỆNH mua bán kèm lý do, mức cắt lỗ và bài học. "
             "Nếu bạn có file lịch sử giao dịch (sao kê lệnh khớp), tải ở Danh mục, tab “Nhập từ file”: app ghép lệnh mua với lệnh bán "
             "(mua trước bán trước), cập nhật Danh mục và thêm từng lệnh vào Nhật ký cùng lúc. Nhập lại cùng file không bị trùng.")

    st.markdown("### Dữ liệu có cập nhật realtime không?")
    st.write("**Không.** App đọc giá từ file trên máy bạn, nên giá chỉ đổi khi bạn bấm **Cập nhật giá** (trang Tổng quan hoặc Cài đặt). "
             "Giá của phiên hôm nay là ảnh chụp tại lúc bạn cập nhật; trong giờ giao dịch (9:00 đến 14:45) nó còn thay đổi trên sàn và app chưa thấy, "
             "nên cập nhật sau 15:05 để có giá đóng cửa. Dải chỉ số thế giới tự làm mới tối đa mỗi 15 phút và có thể chậm. "
             "Nút cập nhật chỉ tải phần mới và gộp vào dữ liệu có sẵn, không làm mất lịch sử.")

    st.markdown("### Bảng rủi ro danh mục")
    st.write("Ở trang **Danh mục**, mục “Rủi ro danh mục” cho biết nếu giá giảm bạn có thể mất thêm bao nhiêu. Nó lấy mức cắt lỗ từ các lệnh đang giữ trong "
             "Nhật ký: **Mất nếu chạm** là phần tài sản còn có thể mất từ giá hiện tại xuống mức cắt lỗ. Mã nào **chưa đặt cắt lỗ** thì không biết mất tối đa "
             "bao nhiêu, nên được đánh dấu để bạn bổ sung. Có thêm bảng thử kịch bản “nếu tất cả cổ phiếu giảm thêm 5%, 10%, 20%, 30%”. "
             "Các mức đánh giá chỉ là quy tắc kinh nghiệm; thực tế giá có thể nhảy qua mức cắt lỗ nên mất thực tế có thể lớn hơn.")

    st.markdown("### Sửa lệnh trong Nhật ký")
    st.write("Mỗi lệnh đang giữ có mục **Bổ sung lý do và cắt lỗ** để viết lý do mua, đặt mức cắt lỗ và giá mục tiêu (rất hữu ích với lệnh nhập từ file). "
             "Ở cuối trang Nhật ký có phần **Sửa hoặc xoá một lệnh**: đổi mã, số lượng, giá, ngày, giá bán; **mở lại** lệnh bấm “đã bán” nhầm; "
             "hoặc xoá lệnh (có ô xác nhận). App kiểm tra hợp lệ, ví dụ ngày bán không trước ngày mua. Khi giá đã tăng, bạn có thể kéo mức cắt lỗ lên trên giá mua để giữ lại phần lãi.")

    st.markdown("### Tiền nạp/rút và lãi thật")
    st.write("Mỗi lần bạn bỏ thêm tiền vào tài khoản hoặc rút ra, hãy ghi ở trang **Danh mục**, mục “Tiền nạp/rút và lãi thật”. "
             "Nếu không, tổng tài sản tăng lên do bạn nạp thêm sẽ bị hiểu nhầm là lãi. **Lãi thật** = tổng tài sản hiện tại trừ tiền ròng bạn "
             "đã bỏ vào. **Tỷ suất quy năm** có tính ngày từng lần nạp/rút, và chỉ hiện khi đã đủ 60 ngày. Nhớ nhập đúng tiền mặt còn lại "
             "trong tài khoản, nếu thiếu thì lãi thật bị tính thấp hơn thực tế.")

    st.markdown("### Kiểm tra cơ bản bằng TCBS MCP")
    st.write("Ở trang **Tra cứu cổ phiếu** có mục soạn sẵn câu hỏi để bạn dán vào Claude (đã kết nối TCBS MCP). Nó giúp xem lợi nhuận, nợ, "
             "định giá so với ngành, khối ngoại và tin tức của doanh nghiệp. TCBS MCP chỉ đọc dữ liệu thị trường và doanh nghiệp, "
             "không đặt lệnh và không đọc danh mục của bạn. Muốn ngắt: TCInvest, ảnh đại diện, AI Connector, Hủy chia sẻ.")

    st.markdown("### Từ điển")
    for term, desc in GLOSSARY:
        with st.expander(term):
            st.write(desc)
