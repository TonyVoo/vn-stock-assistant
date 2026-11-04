"""Câu hỏi soạn sẵn để bạn dán vào Claude (đã kết nối TCBS MCP) nhằm kiểm tra cơ bản một mã.

Chỉ đưa vào mã cổ phiếu và giá gần nhất của dữ liệu công khai; KHÔNG đưa vốn, danh mục hay thông tin cá nhân.
"""
from __future__ import annotations

from typing import Optional

MCP_URL = "https://mcp.tcbs.com.vn/mcp/tcinvest/"
MCP_DOC = "https://help.tcbs.com.vn/tcbs-mcp-server/"
BANKS = {"ACB", "BID", "CTG", "HDB", "MBB", "SHB", "SSB", "STB", "TCB", "TPB", "VCB", "VIB", "VPB", "LPB", "MSB", "OCB", "EIB", "BAB", "NAB", "VAB", "ABB", "BVB", "KLB", "NVB", "PGB", "SGB", "VBB"}


def fundamental_prompt(symbol: str, price: Optional[float] = None, as_of: Optional[str] = None) -> str:
    sym = symbol.upper().strip()
    is_bank = sym in BANKS
    ctx = f" Giá đóng cửa gần nhất trong dữ liệu của tôi là {price:,.0f} đồng".replace(",", ".") + (f" (ngày {as_of})." if as_of else ".") if price else ""
    metrics = ("NIM, CIR, nợ xấu (NPL), LDR, tăng trưởng tín dụng, chi phí dự phòng, ROE, ROA" if is_bank
               else "biên lợi nhuận gộp và ròng, EBITDA, nợ trên vốn chủ sở hữu, dòng tiền tự do, vòng quay tài sản, ROE")
    return (
        f"Hãy dùng các công cụ TCBS MCP để kiểm tra cơ bản cổ phiếu {sym} giúp tôi, một nhà đầu tư cá nhân vốn nhỏ và là người mới.{ctx}\n\n"
        "Làm lần lượt các việc sau, mỗi việc chỉ dựa trên số liệu lấy được từ công cụ (ghi rõ kỳ báo cáo và ngày của số liệu):\n"
        f"1. Tăng trưởng doanh thu và lợi nhuận 5 năm gần nhất. Với nhóm {'ngân hàng' if is_bank else 'phi ngân hàng'}, "
        f"nêu các chỉ số: {metrics}.\n"
        f"2. Định giá hiện tại (P/E, P/B, EV/EBITDA nếu có) so với trung bình ngành và so với chính lịch sử của {sym}.\n"
        "3. Dự phóng của các công ty chứng khoán (nếu có) và mức chênh với giá hiện tại.\n"
        "4. Dòng tiền khối ngoại và giao dịch nội bộ gần đây.\n"
        "5. Cổ tức, sự kiện sắp tới (đại hội cổ đông, chốt quyền) và tin tức đáng chú ý trong 3 tháng.\n\n"
        "Cách trả lời (viết bằng tiếng Việt đơn giản, ít thuật ngữ, giải thích thuật ngữ nếu dùng):\n"
        "- Tóm tắt 3 câu: doanh nghiệp này làm gì và đang khoẻ hay yếu.\n"
        "- 3 điểm mạnh và 3 điểm yếu, mỗi điểm kèm con số làm bằng chứng.\n"
        "- 3 lý do KHÔNG nên mua lúc này.\n"
        "- Liệt kê dữ liệu nào bạn không lấy được hoặc đã cũ.\n"
        "- Không dự đoán giá, không khuyên mua hay bán, không hứa hẹn lợi nhuận; đây chỉ để tôi tham khảo."
    )
