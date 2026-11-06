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
| Mua dần | Lập kế hoạch bỏ cố định mỗi tháng: chia cho các mã hoặc luân phiên, lô 100, phí 0,15%, tiền dư dồn sang tháng sau (giả định giá giữ nguyên, không dự báo lãi) |
| Báo cáo tháng | Chọn tháng, tải **Excel** hoặc **PDF** (tài sản, lệnh đã bán, tiền nạp/rút, cổ tức, nhận xét từ Nhật ký) |
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
- `tests/` 74 kiểm thử: `python -m pytest -q`.

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

## Đồng bộ giá giữa các trang
Mọi trang (Tổng quan, Tra cứu, Danh mục, Nhật ký, Rủi ro, lãi thật) đọc giá qua `views/shared.py`. Bộ nhớ đệm được gắn với PHIÊN BẢN FILE GIÁ (thời điểm sửa + kích thước file CSV của đúng các mã liên quan),
nên giá đổi bằng nút Cập nhật, lệnh Terminal hay tiến trình khác đều làm mọi trang đổi theo ngay, không chờ hết hạn (trước đây các trang giữ giá cũ tới 30–60 phút và có thể lệch nhau).
Bộ nhớ đệm cho mã chưa có file CSV (lấy trực tiếp) chỉ giữ 15 phút. Có test tái hiện lỗi cũ và kiểm tra Danh mục/Nhật ký/Tra cứu cùng hiện một giá.

## Phân tích Nhật ký (thẻ lỗi)
Mỗi lệnh có thể gắn tối đa 8 thẻ (ví dụ “Mua vì tin đồn”, “Mua đuổi giá (FOMO)”, “Đúng kế hoạch”). Lệnh chưa đặt cắt lỗ hoặc chưa ghi lý do được tự nhận thẻ. Trang Nhật ký thống kê tỷ lệ thắng và lãi trung bình theo thẻ, theo thời gian giữ, có/không cắt lỗ. Nhận xét tự động chỉ xuất hiện khi mỗi nhóm có từ 3 lệnh, và luôn cảnh báo khi dưới 20 lệnh đã bán. Bảng cũ được nâng cấp bằng `ALTER TABLE` nên không mất lệnh nào.

## Cổ tức
Trang Danh mục, mục “Cổ tức”: ghi cổ tức tiền mặt hoặc cổ phiếu thưởng (`data/dividends.db`). Tuỳ chọn “Cập nhật Danh mục luôn”: tiền mặt được cộng vào tiền mặt Danh mục (nên đã nằm trong lãi thật); cổ phiếu thưởng tăng số lượng và giảm giá vốn bình quân (tổng giá vốn giữ nguyên). Kiểm tra làm trước khi ghi nên không bao giờ ghi nửa chừng. Xoá ghi chép KHÔNG hoàn lại thay đổi đã áp dụng vào Danh mục.

## Mua dần và Báo cáo tháng
`src/dca.py` lập bảng mua dần (lô 100, phí 0,15%, tiền dư dồn sang sau, cảnh báo mã mà một lô lớn hơn phần tiền được chia). `src/report.py` gom số liệu một tháng và xuất Excel (openpyxl) hoặc PDF (fpdf2, cần phông Arial/DejaVu có tiếng Việt; không có thì nút PDF bị tắt, Excel vẫn dùng được). Cài thêm: `pip install fpdf2`.

## Sao lưu, cảnh báo, so sánh VN-Index
- **Sao lưu** (Cài đặt): tải file .zip hoặc lưu vào `data/backups` (giữ 20 bản). Khôi phục chỉ nhận đúng các file của app, kiểm tra CSDL không hỏng, và tự lưu bản dữ liệu hiện tại trước khi ghi đè. Không gồm file giá.
- **Cảnh báo** (đầu mọi trang): lệnh đang giữ trong Nhật ký chạm hoặc gần (trong 3%) mức cắt lỗ/mục tiêu. Trên Mac có thêm thông báo hệ thống cho cảnh báo chạm mức (mỗi cảnh báo một lần mỗi ngày). Mức cắt lỗ chưa đặt (0) không cảnh báo.
- **So với VN-Index** (Danh mục): mô phỏng bỏ cùng các khoản nạp/rút vào chỉ số đúng ngày, rồi so với tài sản hiện tại. Bỏ qua phí và cổ tức của chỉ số.

## Tin tức về mã đang giữ
Trang Danh mục có mục tin tức: chỉ lấy tin nhắc ĐÍCH DANH mã (viết hoa, đứng riêng) trong tiêu đề/mô tả từ CafeF, VnExpress, Vietstock; luôn hiện nguồn và liên kết gốc. Nếu đã bật AI, nút “Tóm tắt bằng AI” chỉ gửi mã và tiêu đề/mô tả tin công khai (không gửi số lượng, giá vốn, vốn). Kết quả AI được kiểm tra: chỉ nhận mã đã hỏi, tác động chỉ 4 loại, số thứ tự tin phải hợp lệ; nguồn và liên kết lấy từ tin gốc của code, không từ AI.

## Dành cho người mới
- **Hôm nay bạn cần làm gì** (Tổng quan, `src/todo.py`): tối đa 3 việc xếp theo mức khẩn (chạm cắt lỗ, thiếu cắt lỗ, tỷ trọng quá cao, tiền mặt dự phòng, chưa cập nhật giá, chưa ghi lý do), mỗi việc có nút đi tới đúng trang. Không có việc thì ghi rõ là không cần làm gì.
- **Kiểm tra trước khi mua** (Tính lệnh mua, `src/precheck.py`): đèn xanh/vàng/đỏ cho số cổ phiếu bạn định mua: cắt lỗ, mức mất nếu sai, dồn vào một mã, tiền mặt dự phòng, lãi so với lỗ, thanh khoản. Không khuyên mua hay không mua; ngưỡng nào cũng được nêu trong câu giải thích. Tỷ lệ % tính theo vốn ở Cài đặt, tiền mặt lấy từ Danh mục.
- **Từ điển** (nút trên cùng mọi trang và trang Hướng dẫn, `src/glossary.py`): 16 thuật ngữ, ví dụ bằng số thật của bạn (vốn, mức chấp nhận mất, giá/cắt lỗ ở Tính lệnh mua).

## Hỏi trợ lý, bộ lọc, chế độ đơn giản, điện thoại
- **Hỏi trợ lý** (trang `hoi-dap`, `src/ask.py`): “giờ mua có ổn không, hay đợi giá xuống?”. Trả lời bằng số, không đoán giá: giá đang ở đâu so với đỉnh 1 năm và đường trung bình, so với giá vốn của bạn, giá vốn trung bình mới nếu mua một lần hoặc chia 2 đến 4 lần (kịch bản giá đi ngang, giảm, tăng), tỷ trọng sau khi mua. Ở đầu trang có ô **Hỏi AI** (nếu đã bật AI): AI nói thẳng quan điểm (mua ngay, mua chia lần, đợi, tránh) kèm mức tự tin, lý do từ số liệu, điều sẽ làm nó đổi ý và rủi ro; tin hay không là quyền của bạn. Câu trả lời được kiểm tra định dạng, AI không được bịa số liệu hay hứa lợi nhuận. Mặc định chỉ gửi số liệu thị trường và tỷ lệ; công tắc “Cho AI biết danh mục và số tiền của tôi” mới gửi thêm số tiền, số lượng, giá vốn, tiền mặt và vốn.
- **Bộ lọc cổ phiếu** (Tra cứu cổ phiếu, `src/screener.py`): thanh khoản, xu hướng, biến động, RSI, cách đỉnh 1 năm. Chỉ để thu hẹp danh sách cần xem, không phải khuyến nghị mua.
- **Chế độ đơn giản** (Cài đặt): ẩn Mua dần, Báo cáo tháng, Nghiên cứu.
- **Điện thoại**: giao diện co theo màn hình hẹp (menu mở bằng nút `>>`). Để mở trên điện thoại cùng WiFi: chạy `streamlit run app.py --server.address 0.0.0.0`, rồi vào `http://<địa chỉ IP máy tính>:8501`. Dữ liệu cá nhân của bạn sẽ hiện cho mọi thiết bị trong mạng đó, nên hãy đặt `APP_PIN=` (ít nhất 4 ký tự) trong file `.env` để app hỏi mã trước; sai 5 lần thì khoá 60 giây. Đây chỉ là lớp chắn cho WiFi nhà, KHÔNG dùng để đưa app ra Internet. Mỗi lần tải lại trang sẽ hỏi lại mã.
- Tự cập nhật giá chạy ở luồng nền, nên trang không bị chặn khi app mới khởi động.

## Chatbot AI nổi (mọi trang)
Nút **Hỏi AI** ở góc dưới bên phải mọi trang mở khung chat nhiều lượt (`views/chatbot.py`). AI đọc toàn bộ dữ liệu bạn đã nhập (danh mục và giá vốn, nhật ký kèm lý do và thẻ, tiền nạp/rút, cổ tức, so với VN-Index, rủi ro, cảnh báo, cài đặt) cùng giá hiện tại và tin tức nhắc mã bạn giữ (`src/chat_context.py`, giới hạn 30.000 ký tự, bỏ lệnh cũ nhất trước). Công tắc **Cho AI đọc dữ liệu của tôi** (mặc định bật): tắt thì chỉ gửi giá thị trường. Khoá API, mã PIN và thông tin đăng nhập broker không bao giờ được gửi. AI chỉ trả lời, không đặt lệnh hay sửa dữ liệu; nội dung trong dữ liệu (lý do ghi chú, tiêu đề tin) bị coi là dữ liệu, không phải chỉ thị. Dữ liệu được gửi tới nhà cung cấp AI bạn cấu hình (Gemini/Claude...).

## Hiệu năng
Đo thực tế: mỗi trang dựng xong trong dưới 1 giây (lần đầu), lần gọi mạng lớn nhất (tin RSS, chỉ số thế giới) khoảng 1 đến 1,5 giây và được cache. Đã làm: (1) tự cập nhật giá chạy ở luồng nền nên không chặn trang; (2) chatbot và ô Hỏi AI ở trang Hỏi trợ lý trả lời dạng stream và gõ chữ dần từng từ như ChatGPT (`llm.smooth`: Gemini gửi cả câu trong khoảng 1 giây theo từng cục 60 đến 110 ký tự nên cần làm mượt nhịp hiện; nội dung không đổi); chữ đầu hiện sau khoảng 3 đến 5 giây, phần lớn là thời gian suy nghĩ của mô hình; (3) file Excel, PDF và bản sao lưu chỉ được tạo khi bấm tải, không tạo lại sau mỗi thao tác trên trang.

## Tỷ lệ tính trên vốn của bạn (chỉ đầu tư một phần)
Danh mục chỉ ghi cổ phiếu và tiền mặt bạn nhập. Nếu vốn đặt ở Cài đặt lớn hơn số đã ghi (bạn chỉ đầu tư một phần), mọi tỷ lệ % (tỷ trọng một mã, tiền mặt dự phòng, mất nếu chạm cắt lỗ, cảnh báo, chatbot) tính trên **vốn đó**, phần chưa ghi coi là tiền chưa đầu tư (`portfolio.valuate(..., capital)`, `risk_table.build(..., capital)`). Vốn nhỏ hơn số đã ghi thì dùng số đã ghi. Riêng **lãi thật** vẫn dùng số đã ghi trong Danh mục, nên muốn lãi thật chính xác hãy ghi tiền mặt thực tế ở tab “Nhập tay”.

## Chatbot không làm đứng trang và không mất tin nhắn
- Khung chat và ô Hỏi AI (trang Hỏi trợ lý) là `st.fragment`: gửi câu hỏi và stream câu trả lời chỉ chạy lại khung đó, phần trang phía sau không bị mờ hay đứng.
- Câu hỏi được lưu NGAY khi gửi; câu trả lời được lưu dần theo từng đoạn (`chatbot._tee`). Nếu bị ngắt giữa chừng, phần đã có vẫn còn và được ghi chú "bị ngắt giữa chừng"; tin dở dang không được gửi lại cho AI làm ngữ cảnh.
- Trong lúc AI đang trả lời (tối đa 120 giây), tự cập nhật giá không làm mới cả trang (việc đó từng cắt ngang câu trả lời); sau khi xong sẽ làm mới ở lần kiểm tra kế tiếp. Biến môi trường `AUTO_TICK` (mặc định `1m`) đổi chu kỳ kiểm tra, dùng để thử nghiệm.

## Giao diện chatbot
Nút **Hỏi AI** nổi (gradient chàm, bóng đổ) mở khung chat: tiêu đề có logo và trạng thái (chấm xanh khi đang đọc dữ liệu của bạn), nút xoá cuộc trò chuyện, mục “Quyền riêng tư” thu gọn (công tắc cho AI đọc dữ liệu), màn hình chào kèm 3 câu gợi ý dạng thẻ biến mất khi bạn gửi câu hỏi đầu tiên, bong bóng tin nhắn (của bạn căn phải, của AI căn trái, avatar tròn), ô nhập bo tròn với nút gửi tròn, dòng nhắc AI có thể sai. Hàng tiêu đề và hàng nhập luôn nằm ngang kể cả trên điện thoại. CSS nằm ở `src/ui.py` (khối “Chatbot nổi”); sau khi sửa CSS cần khởi động lại `streamlit run` để nạp bản mới.
Lưu ý kỹ thuật khi chỉnh CSS chatbot: (1) khung ngoài không cuộn, chỉ khung tin nhắn (`st.container(key="chatbox")`) cuộn, chiều cao co theo cửa sổ (`clamp(170px, 100vh - 495px, 420px)`); (2) Streamlit cho khối chữ lề dưới -16px để bù lề đoạn văn, nên khi đặt lại lề đoạn văn phải bỏ lề âm này, nếu không bong bóng bị cắt mép dưới; (3) bong bóng của bạn là phần tử `.chat-u` tự vẽ (nội dung được escape), không dựa vào khung nội bộ của Streamlit.

## Lịch sử chat, số liệu AI, sao lưu tự động
- **Lịch sử chat** lưu ở `data/chat_history.json` (`src/chat_store.py`, tối đa 60 tin nhắn, ghi nguyên tử, file hỏng thì bỏ qua), nên tải lại trang hay đóng tab vẫn còn; nút xoá cũng xoá file. File này nằm trong bản sao lưu và trong `.gitignore`.
- **Số liệu cho AI** (`chat_context.so_lieu_da_tinh_san`): code tính sẵn và gắn nhãn rõ nghĩa (lãi/lỗ của phần cổ phiếu so với giá vốn khác lãi/lỗ so với TỔNG tài sản; mã chưa có lệnh trong nhật ký khác mã có lệnh nhưng chưa đặt cắt lỗ). AI được dặn trích đúng nhãn, không tự tính lại.
- **Sao lưu tự động**: mỗi ngày mở app là có tối đa một bản `sao-luu-...-tu-dong.zip` trong `data/backups` (giữ 14 bản, tính riêng với bản thủ công giữ 20); chỉ tạo khi đã có dữ liệu; lỗi thì bỏ qua. Biến môi trường `BACKUP_DIR`, `CHAT_PATH` đổi nơi lưu (dùng khi thử nghiệm).

## Chatbot hiểu trang đang xem, sức khoẻ dữ liệu, ghi lệnh bằng chat
- **Hiểu trang đang xem** (`chat_context.describe_page`): chatbot biết bạn đang ở trang nào, đang xem mã nào (Tra cứu, Tính lệnh mua, Hỏi trợ lý) và đang nhập số gì, nên “mã này”, “ở đây”, “số này” được hiểu đúng; câu gợi ý cũng đổi theo trang. Khung chat được vẽ SAU phần trang để biết trang hiện tại.
- **Sức khoẻ dữ liệu** (`src/health.py`, mục thu gọn ở Tổng quan; cũng đưa cho chatbot): giá thiếu hoặc cũ từ 2 đến 3 phiên, Danh mục cũ hơn 7 ngày, chưa ghi tiền mặt dù đã ghi tiền nạp/rút, Danh mục và Nhật ký lệch số lượng hoặc lệch mã, vốn ở Cài đặt nhỏ hơn Danh mục, chưa có bản sao lưu gần đây. Mỗi mục có nút đi tới trang cần sửa.
- **Ghi lệnh bằng chat** (`src/trade_parse.py`): gõ “hôm nay mua 100 FPT giá 120k, cắt lỗ 112k, mục tiêu 140k vì báo cáo tốt” hoặc “bán 100 FPT giá 130k hôm qua” thì chatbot soạn BẢN NHÁP (không gọi AI; bộ đọc câu theo quy tắc cố định, vì AI có thể hiểu sai số). Bạn sửa các ô rồi bấm “Ghi vào Nhật ký”; chưa duyệt thì chưa ghi gì. Câu hỏi (“có nên mua 100 FPT không?”) không bao giờ bị coi là lệnh. Giá ghi tắt “k” = nghìn; số nhỏ hơn 1.000 không đơn vị được hiểu là nghìn đồng và có ghi chú. Bán chỉ đóng được lệnh đang mở khớp đúng mã và số lượng (bán một phần chưa hỗ trợ). Chỉ ghi vào Nhật ký, Danh mục không tự đổi.

## Tự nhập sao kê (không cần API)
- **Thư mục sao kê** (`src/inbox.py`, mặc định `data/inbox`, đổi bằng `INBOX_DIR`): tải sao kê Excel/CSV (danh mục đang giữ hoặc lịch sử lệnh khớp) từ công ty chứng khoán rồi lưu vào thư mục này; app (đang mở hoặc lần mở sau) tự đọc, cập nhật Danh mục (giữ nguyên tiền mặt đã ghi) và Nhật ký (không trùng lệnh). Trước mỗi lần nhập có một bản sao lưu đầy đủ (`...-truoc-nhap.zip`); Cài đặt, mục “Tự nhập sao kê” có nút **Hoàn tác lần nhập gần nhất** (chỉ khôi phục Nhật ký và Danh mục). File xử lý xong được chuyển sang `da-xu-ly`, không xoá; mỗi file chỉ xử lý một lần theo nội dung.
- Không nhận ra mã cổ phiếu trong file thì app KHÔNG ghi gì và báo lý do; khi đó tải file lên ở trang Danh mục và tự chọn cột.
- **Dán bảng từ web**: ở trang Danh mục, tab Nhập từ file, mở mục “Hoặc dán bảng copy từ trang web”.
- Chưa kiểm tra với file sao kê thật của TCBS (chưa có file mẫu): tên cột được nhận theo cách đoán chung (Mã, Khối lượng, Giá vốn; Mua/Bán, Khối lượng, Giá).
