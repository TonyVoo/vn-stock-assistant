"""Từ điển thuật ngữ cho người mới: mỗi mục có giải thích ngắn và ví dụ bằng số thật của bạn (vốn, mức cắt lỗ, mức chấp nhận mất)."""
from __future__ import annotations

from typing import Callable, Dict, Tuple


def _v(x: float) -> str:
    return f"{x:,.0f}đ".replace(",", ".")


def _ex(p: Dict) -> Tuple[float, float, float]:
    e, s = float(p.get("entry", 25000)), float(p.get("stop", 23500))
    return e, s, float(p.get("capital", 10_000_000))


def _stop(p):
    e, s, c = _ex(p)
    return f"Mua ở {_v(e)}, đặt cắt lỗ {_v(s)}. Nếu giá rơi về {_v(s)}, bạn bán và mất khoảng {(1 - s / e) * 100:.0f}% giá mua, tức khoảng {_v((e - s) * 100)} cho 100 cổ phiếu."


def _cost(p):
    return "Bạn mua 100 cổ phiếu giá 25.000đ rồi mua thêm 100 cổ phiếu giá 23.000đ: giá vốn bình quân là 24.000đ. Lãi hay lỗ được tính so với mức này."


def _lot(p):
    e, s, c = _ex(p)
    return f"Một lô là 100 cổ phiếu. Với giá {_v(e)}, một lô tốn khoảng {_v(e * 100 * 1.0015)} (đã gồm phí mua)."


def _t2(p):
    return "Mua hôm thứ Hai thì cổ phiếu về tài khoản chiều thứ Tư và bán được từ lúc đó (không tính thứ Bảy, Chủ nhật, ngày lễ). Nếu giá giảm ngay, bạn không thể bán trong 2 ngày đó."


def _weight(p):
    e, s, c = _ex(p)
    m = float(p.get("max_alloc", 30)) / 100
    return f"Tỷ trọng là phần tài sản nằm trong một mã. Mức tối đa bạn đặt là {m * 100:.0f}%: với {_v(c)} thì một mã nên không quá {_v(c * m)}. Không bỏ hết trứng vào một giỏ."


def _risk(p):
    e, s, c = _ex(p)
    r = float(p.get("risk_pct", 2.0)) / 100
    return f"Bạn chấp nhận mất tối đa {r * 100:.1f}% vốn cho một lệnh sai, tức {_v(c * r)} với vốn {_v(c)}. App tính số cổ phiếu để nếu chạm cắt lỗ thì chỉ mất đúng mức này."


def _cashbuf(p):
    e, s, c = _ex(p)
    return f"Tiền mặt dự phòng là phần tiền chưa mua cổ phiếu. Với {_v(c)}, giữ khoảng {_v(c * 0.1)} (10%) để có chỗ xoay xở khi giá giảm và không bị ép bán lỗ."


def _truepnl(p):
    return "Lãi thật = tổng tài sản hiện tại trừ tiền ròng bạn đã bỏ vào. Bỏ vào 10 triệu, nạp thêm 5 triệu, giờ có 16 triệu: lãi thật là 1 triệu, không phải 6 triệu."


def _annual(p):
    return "Tỷ suất quy năm cho biết nếu giữ tốc độ lãi này đủ một năm thì được bao nhiêu %. Lãi 2% trong 1 tháng không có nghĩa là 24% một năm, nên app chỉ tính khi đã đủ lâu."


def _div(p):
    return "Cổ tức là tiền (hoặc cổ phiếu) công ty chia cho người giữ cổ phiếu. Giữ 1.000 cổ phiếu, cổ tức 1.000đ mỗi cổ phiếu thì bạn nhận 1.000.000đ. Cổ phiếu thưởng làm bạn có thêm cổ phiếu nhưng giá vốn bình quân giảm tương ứng."


def _liq(p):
    return "Thanh khoản là mức dễ mua bán. Mã giao dịch vài chục tỷ mỗi phiên thì bán nhanh được; mã chỉ vài trăm triệu thì muốn bán có thể phải hạ giá nhiều."


def _limit(p):
    e, s, c = _ex(p)
    return f"Mỗi ngày giá chỉ được lên xuống trong biên độ (HOSE ±7%). Từ {_v(e)}, giá trong ngày nằm trong khoảng {_v(e * 0.93)} đến {_v(e * 1.07)}. Giá có thể giảm kịch sàn và không ai mua, nên cắt lỗ không phải lúc nào cũng bán được đúng giá."


def _fee(p):
    e, s, c = _ex(p)
    return f"Mua và bán đều mất phí khoảng 0,15%, bán mất thêm thuế 0,1%. Mua rồi bán 100 cổ phiếu giá {_v(e)} tốn khoảng {_v(e * 100 * (0.0015 * 2 + 0.001))} phí và thuế, nên giá phải tăng chút mới hòa vốn."


def _dca(p):
    return "Mua dần là mỗi tháng bỏ một số tiền cố định để mua, thay vì dồn một lần. Giúp giá vốn trung bình mượt hơn và đỡ lo chọn sai thời điểm, nhưng không đảm bảo có lãi."


def _vnindex(p):
    return "VN-Index là chỉ số đo giá trung bình của các cổ phiếu trên sàn HOSE. Nó tăng nghĩa là thị trường chung đang tốt. Ví dụ so với VN-Index trong app cho bạn biết mình đang hơn hay kém thị trường."


def _rr(p):
    e, s, c = _ex(p)
    t = float(p.get("target", 29000))
    return f"Lãi tiềm năng so với lỗ tiềm năng: mua {_v(e)}, cắt lỗ {_v(s)}, mục tiêu {_v(t)} thì lãi tối đa {_v(t - e)} mỗi cổ phiếu so với lỗ {_v(e - s)}: gấp {(t - e) / (e - s):.1f} lần." if e > s and t > e else "Là tỷ lệ giữa số tiền có thể lãi và số tiền có thể lỗ của một lệnh. Người kỷ luật thường chỉ vào lệnh khi từ 2 lần trở lên."


TERMS: Dict[str, Tuple[str, Callable[[Dict], str]]] = {
    "Cắt lỗ": ("Mức giá bạn đã quyết định trước là sẽ bán nếu giá rơi xuống, để không lỗ sâu hơn.", _stop),
    "Giá vốn": ("Giá trung bình bạn đã bỏ ra để có cổ phiếu đó.", _cost),
    "Lô (100 cổ phiếu)": ("Đơn vị mua tối thiểu trên sàn HOSE: 100 cổ phiếu.", _lot),
    "T+2": ("Mua xong phải đợi 2 ngày làm việc mới bán được.", _t2),
    "Tỷ trọng": ("Phần trăm tổng tài sản đang nằm trong một mã.", _weight),
    "Mức chấp nhận mất": ("Số tiền tối đa bạn sẵn sàng mất cho một lệnh sai.", _risk),
    "Tiền mặt dự phòng": ("Phần tiền giữ lại, chưa mua cổ phiếu.", _cashbuf),
    "Lãi thật": ("Lãi sau khi trừ đi tiền bạn bỏ thêm vào.", _truepnl),
    "Tỷ suất quy năm": ("Tốc độ lãi quy đổi ra một năm.", _annual),
    "Cổ tức": ("Tiền hoặc cổ phiếu công ty chia cho người giữ cổ phiếu.", _div),
    "Thanh khoản": ("Mức dễ mua bán một cổ phiếu.", _liq),
    "Giá trần, giá sàn": ("Biên độ giá tối đa lên hoặc xuống trong một ngày.", _limit),
    "Phí và thuế": ("Chi phí mỗi lần mua bán, làm lãi thực tế thấp hơn lãi trên màn hình.", _fee),
    "Mua dần (DCA)": ("Mỗi tháng bỏ một số tiền cố định để mua.", _dca),
    "VN-Index": ("Chỉ số đo thị trường chung trên sàn HOSE.", _vnindex),
    "Lãi so với lỗ": ("Lãi tiềm năng gấp mấy lần lỗ tiềm năng của một lệnh.", _rr),
}


def explain(term: str, p: Dict) -> Tuple[str, str]:
    """(giải thích ngắn, ví dụ bằng số của bạn). Lỗi khi tính ví dụ thì chỉ bỏ ví dụ, không làm hỏng trang."""
    short, fn = TERMS[term]
    try:
        return short, fn(p)
    except Exception:  # noqa: BLE001
        return short, ""
