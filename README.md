# Trợ lý chứng khoán VN

Công cụ hỗ trợ ra quyết định cho nhà đầu tư cá nhân vốn nhỏ. **Không dự đoán giá, không phải lời khuyên đầu tư.**
Mọi nhận định định lượng đều đã được kiểm chứng bằng backtest (xem "Kết quả nghiên cứu" bên dưới): đọc trước khi tin tín hiệu nào.

## Cài đặt và chạy
Cần Python ≥ 3.10.
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # rồi chọn nhà cung cấp AI (xem dưới)
streamlit run app.py
```
Chưa có dữ liệu thật? Đặt `DEMO_MODE=1` trong `.env` (dữ liệu giả lập, chỉ để thử giao diện; app luôn cảnh báo đỏ).

### Nhà cung cấp AI (bản tin sáng, phân tích + phản biện)
Chọn bằng `LLM_PROVIDER` trong `.env`: `anthropic` (Claude API, tính phí theo token, cần `ANTHROPIC_API_KEY`;
gói Pro của claude.ai KHÔNG dùng được cho việc này), `openai_compat` (Ollama trên máy, Gemini...), hoặc `mock` (kết quả mẫu).
Ví dụ Gemini đã thử chạy tốt: `OPENAI_COMPAT_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai`,
`OPENAI_COMPAT_MODEL=gemini-3.5-flash-lite`. Tên model Gemini đổi nhanh: nếu báo 404, liệt kê model bằng `/models`.
**Không bao giờ dán API key vào chat/ảnh chụp; file `.env` đã nằm trong `.gitignore`.**

### Dữ liệu giá
1. **vnstock (bản 5)**: `vnstock` không còn trên PyPI, cài từ kho của tác giả:
   ```bash
   pip install -U --extra-index-url https://vnstocks.com/api/packages vnstock
   export VNSTOCK_TELEMETRY=0          # tuỳ chọn: tắt đo lường sử dụng
   .venv/bin/vnstock register          # trong terminal của BẠN (key miễn phí: vnstocks.com/account)
   python scripts/download_prices.py --years 10     # VN30 + VNINDEX vào data/prices/
   ```
   Tài khoản Khách chỉ có 365 ngày giá cổ phiếu; có key cộng đồng được khoảng 8 năm (VN-Index khoảng 4 năm).
   Giấy phép cộng đồng: chỉ cá nhân/học tập/nghiên cứu; mỗi bản phát hành hết hạn sau 365 ngày.
2. **CSV tự cung cấp**: đặt `data/prices/<MÃ>.csv` (cột `date, open, high, low, close, volume`; giá nghìn đồng tự đổi sang đồng).
   CSV luôn được ưu tiên hơn mọi nguồn khác. Cập nhật giá hàng tháng bằng lại lệnh `download_prices.py`.

## Giao diện
Phong cách "Simplize + Linear": nền tối cố định, viền mảnh 1px, chữ nhỏ gọn, một màu nhấn (chàm), không bóng đổ, **không emoji**
(biểu tượng dùng bộ Material đơn sắc; mũi tên % là tam giác CSS). Bố cục theo app chứng khoán: thanh điều hướng ngang ở trên,
dải chỉ số (VN-Index + thế giới) với huy hiệu xanh/đỏ, giá lớn kèm huy hiệu %, thanh vùng giá 1 năm, nút chọn khoảng thời gian,
biểu đồ vùng, bảng theo dõi có biểu đồ nhỏ (bấm dòng để mở chi tiết). Màu theo thị trường Việt Nam: xanh = tăng, đỏ = giảm, vàng = đứng giá.
- **Cài đặt được lưu** vào `data/settings.json` (vốn, danh sách theo dõi, mức an toàn): tải lại trang vẫn còn. Mỗi trang có địa chỉ riêng (`/tra-cuu`, `/cai-dat`...).
- Viết cho người mới: mỗi trang mở đầu bằng "trang này giúp gì", thuật ngữ giải thích tại chỗ, số kiểu Việt Nam (1.234.567 / 12,5%).
- Có test chặn emoji quay lại trong mã giao diện.

## Các trang (thanh điều hướng trên cùng)
| Trang | Việc làm |
|---|---|
| 🏠 Tổng quan | VN-Index + biểu đồ, danh sách theo dõi dạng bảng gọn, "nên làm gì hôm nay", bản tin AI |
| 🔎 Tra cứu cổ phiếu | Giá lớn + huy hiệu %, vùng giá 1 năm, số liệu nhanh, "Đánh giá nhanh", câu "Nói đơn giản", AI phân tích + phản biện |
| 🧮 Tính lệnh mua | Nhập 3 mức giá -> nên mua bao nhiêu cổ phiếu, nếu sai mất bao nhiêu, nếu đúng lãi bao nhiêu (lô 100, phí, thuế, T+2) |
| Danh mục | Cổ phiếu đang giữ, tổng tài sản, lãi/lỗ, tỷ trọng, cảnh báo tập trung. Nhập tay / file CSV-Excel (danh mục đang giữ HOẶC lịch sử giao dịch, tự nhận loại) / từ Nhật ký / TCBS **chỉ đọc** |
| 📓 Nhật ký giao dịch | Ghi lệnh kèm lý do bắt buộc, theo dõi lệnh đang giữ (cảnh báo gần cắt lỗ), thống kê lệnh đã bán |
| 🔬 Nghiên cứu (nâng cao) | Kết luận bằng lời, kiểm chứng điểm xu hướng, kiểm tra gắt hơn (train/test), động lượng + sổ giả lập |
| ❓ Hướng dẫn | Cách dùng, nguyên tắc cho người mới, cập nhật dữ liệu, bật AI, từ điển |
| ⚙️ Cài đặt | Vốn, mã theo dõi, mức an toàn (bấm Lưu); trạng thái AI và dữ liệu |

Lưu ý: nếu phiên hôm nay chưa đóng cửa (trước 15:05), app báo giá/khối lượng là tạm thời.

## Cấu trúc
- `app.py` bộ điều hướng (`st.navigation` đặt trên cùng); `views/` mỗi trang một file (`overview`, `stock`, `calc`, `journal_view`,
  `research`, `guide`, `settings_view`, `shared`); `.streamlit/config.toml` giao diện tối.
- `src/ui.py` bảng màu + CSS + thẻ/huy hiệu/dải chỉ số (mọi chuỗi động đều escape), `src/charts.py` biểu đồ vùng,
  `src/explain.py` diễn đạt đơn giản + định dạng số Việt Nam, `src/settings.py` lưu cài đặt.
- `src/data.py` giá (CSV -> vnstock >= 5 -> VNDirect -> demo), `src/signals.py` chỉ báo + điểm, `src/risk.py` khối lượng/phí/thuế,
  `src/news.py` RSS + thế giới, `src/llm.py` lớp AI (JSON), `src/backtest.py` backtest + train/test,
  `src/xsection.py` xếp hạng giữa các mã + phép thử hoán vị, `src/paper.py` sổ giả lập, `src/journal.py` nhật ký.
- `scripts/download_prices.py`, `scripts/run_signals.py` (báo cáo 5 tín hiệu xếp hạng).
- `tests/` 73 kiểm thử: `python -m pytest -q`.

## Kết quả nghiên cứu (VN30, 2018-11 → 2026-11): đọc trước khi tin bất kỳ tín hiệu nào
Mọi kết quả: mua ở giá mở cửa phiên sau tín hiệu, trừ phí/thuế, so với đường cơ sở, có kiểm tra train/test.
Tổng cộng đã thử khoảng 120 cấu hình/giả thuyết, nên một kết quả "đẹp" đơn lẻ rất dễ là ngẫu nhiên.
- Điểm kỹ thuật theo từng mã (MA, RSI, MACD, khối lượng): KHÔNG hơn vào lệnh ngẫu nhiên (chênh ±0,1%/lệnh, z < 1).
  Lọc theo xu hướng VN-Index và trailing stop không thay đổi kết luận.
- Xếp hạng giữa các mã, top 5 / 30 mã, 82 kỳ tháng: động lượng 12T +7,6%/năm, 6T +6,8%/năm so với giữ đều
  (t ≈ 1,1–1,2: chưa đủ tin cậy). Gần đỉnh 52 tuần: tốt ở train, mất ở test. Đảo chiều 1 tuần: −12,7%/năm (t = −2,0).
  Biến động thấp: âm.
- Giới hạn trong mã mua nổi 1 lô với vốn 10 triệu (3 mã, giá ≤ 33.333đ): động lượng 12T −10,2%/năm (t = −1,7),
  6T −2,6%: KHÔNG có lợi thế trong phạm vi thực hiện được.
- Hạn chế chưa xử lý: thiên lệch người sống sót (VN30 hiện tại), chỉ 30 mã, chưa có dữ liệu cơ bản/khối ngoại,
  chưa có giai đoạn thị trường giảm kéo dài đủ dài trong mẫu.

## Kết nối TCBS (chỉ đọc) — giai đoạn 1 của tự động hoá
Dựa trên tài liệu chính thức iFlash Open API (developers.tcbs.com.vn; đã đối chiếu với file đặc tả OpenAPI công khai của TCBS).
- **Khoá API của TCBS không có chế độ chỉ-đọc** (cùng khoá dùng được lệnh đặt/sửa/huỷ và chuyển tiền). Vì vậy `src/broker_tcbs.py` tự chặn:
  chỉ có MỘT lệnh POST (đổi khoá + Smart OTP lấy mã truy cập, tối đa 8 giờ); mọi lệnh khác là GET tới danh sách đường dẫn chỉ-đọc
  (`/aion/.../se|cashInvestments|orders|ppse`, hồ sơ). Các đường dẫn ghi (`/akhlys/...`) không thể gọi. Có test chứng minh điều này.
- Mã truy cập chỉ ở bộ nhớ; không ghi đĩa, không vào log/thông báo lỗi. OTP không được lưu. Mỗi lần cần nhập Smart OTP từ app TCInvest.
- Cách bật: tạo khoá trong TCInvest (Menu trái → Tiện ích → iFlash Open API), thêm `TCBS_API_KEY=...` vào `.env` (xem `.env.example`), khởi động lại.
  Không gửi khoá cho ai; huỷ khoá trong trang iFlash Open API khi không dùng.
- Không có cách nào trong app để đặt lệnh. Giai đoạn 2 (soạn sẵn lệnh để bạn tự bấm) và 3 (tự động) chưa làm; chỉ nên cân nhắc sau khi có chiến lược được chứng minh.
- Danh mục lưu ở `data/portfolio.json` (đã nằm trong `.gitignore`); đổi đường dẫn bằng biến môi trường `PORTFOLIO_PATH`.

## Kiểm tra cơ bản bằng Claude + TCBS MCP
TCBS có MCP Connector chính thức (xem help.tcbs.com.vn/tcbs-mcp-server): chỉ đọc, 48 công cụ về dữ liệu thị trường/doanh nghiệp
(báo cáo tài chính, định giá, dự phóng, khối ngoại, giao dịch nội bộ, tin tức), KHÔNG có công cụ nào đọc danh mục cá nhân hay đặt lệnh.
Đây không phải API key và app không gọi trực tiếp: trang Tra cứu cổ phiếu chỉ soạn sẵn câu hỏi (`src/prompts.py`, có bộ chỉ số riêng cho
ngân hàng, không chứa vốn/danh mục) để bạn dán vào Claude đã kết nối connector.

## Nhập sao kê vào Nhật ký
Danh mục = đang giữ gì; Nhật ký = từng lệnh (lý do, cắt lỗ, lãi/lỗ đã chốt). File LỊCH SỬ GIAO DỊCH tải ở Danh mục (tab “Nhập từ file”) có thể cập nhật cả hai:
`src/importer.py` ghép lệnh mua với lệnh bán theo FIFO (mỗi lô mua là một lệnh; lô đã bán là lệnh đã chốt), mức cắt lỗ chưa biết nên lưu 0 (= “chưa đặt”, không tính R),
mỗi lệnh có khoá `[sao kê xxxxxxxxxx]` trong lý do để nhập lại cùng file không bị trùng. Giá vốn ở Danh mục tính bình quân; ở Nhật ký tính theo lô, nên có thể lệch nhau chút.
Sao kê lệnh khớp không có phí/thuế: app trừ ước tính khi tính lãi/lỗ. Đường dẫn nhật ký đổi được bằng biến môi trường `JOURNAL_PATH` (dùng khi thử).

## Tiền nạp/rút và lãi thật
`src/cashflow.py` (data/cashflows.db; đổi đường dẫn bằng `CASHFLOW_PATH`): ghi mỗi lần nạp (+) / rút (−). Lãi thật = tổng tài sản hiện tại (cổ phiếu + tiền mặt trong Danh mục)
trừ tiền ròng đã bỏ vào. Tỷ suất quy năm là XIRR có tính ngày từng lần nạp/rút (chỉ hiện khi đã >= 60 ngày; dưới 1 năm chỉ để tham khảo). Cần nhập đúng tiền mặt
trong Danh mục, nếu thiếu thì lãi thật bị tính thấp. Form chỉ xoá ô nhập khi ghi thành công; lỗi thì giữ nguyên lựa chọn (tránh ghi nhầm rút thành nạp).

## Sửa lệnh trong Nhật ký
`journal.update_trade / reopen_trade / delete_trade` (có kiểm tra hợp lệ toàn bộ lệnh sau khi sửa; lỗi thì không sửa gì). Mỗi lệnh đang giữ có form sửa nhanh (lý do, cắt lỗ, mục tiêu);
cuối trang có trình sửa đầy đủ (kể cả lệnh đã bán), mở lại lệnh bán nhầm và xoá có xác nhận. Lệnh nhập từ sao kê giữ nguyên khoá `[sao kê ...]` khi bạn sửa lý do,
nên nhập lại file không bị trùng. Đã đặt cắt lỗ thì lệnh đã bán có R, và cảnh báo gần cắt lỗ hoạt động.

## Bảng rủi ro danh mục
`src/risk_table.py` + mục “Rủi ro danh mục” ở trang Danh mục. Mức cắt lỗ mỗi mã = trung bình gia quyền các mức cắt lỗ của lệnh ĐANG GIỮ trong Nhật ký; phần số lượng không có lệnh nào phủ tới
là “chưa có cắt lỗ”. “Mất nếu chạm” = số lượng được phủ × (giá hiện tại − mức cắt lỗ), tức phần còn có thể mất thêm, không phải lỗ so với giá vốn. So với mức chấp nhận mất mỗi mã
(Cài đặt), kèm đánh giá nhanh (quy tắc kinh nghiệm, không phải ngưỡng chuẩn) và bảng thử kịch bản giảm thêm 5/10/20/30%. Khi sửa lệnh, cho phép kéo cắt lỗ lên trên giá mua để giữ lãi
(lệnh mới vẫn bắt buộc thấp hơn giá mua); những lệnh này không tính chỉ số R.

## Cập nhật giá bằng một nút (không realtime)
`src/updater.py` + `views/data_update.py`: nút “Cập nhật giá” ở Tổng quan (gọn), Cài đặt (đầy đủ, tuỳ chọn cả VN30) và màn hình chưa có dữ liệu. Cập nhật TĂNG DẦN (lấy từ 7 ngày trước ngày cuối của file, gộp theo ngày, bản mới thắng),
không bao giờ làm file ngắn đi, giữ nguyên file khi lỗi mạng/khoá, phát hiện giá lịch sử bị điều chỉnh (chia tách/cổ tức) thì tải lại toàn bộ (nhưng GIỮ file cũ nếu nguồn chỉ trả ít phiên hơn, ví dụ gói Khách 365 ngày), ghi nguyên tử.
Cần vnstock đã đăng ký. Dữ liệu KHÔNG realtime: chỉ đổi khi bấm nút; nến hôm nay là ảnh chụp tại lúc cập nhật, nên cập nhật sau 15:05. Đổi thư mục giá khi thử bằng `PRICES_DIR`.
