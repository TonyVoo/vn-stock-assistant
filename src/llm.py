"""Lớp Claude: đọc tin tức/dữ liệu và trả về nhận định có cấu trúc.

Nguyên tắc: Claude KHÔNG dự đoán giá. Nó phân loại tin, tóm tắt, nêu rủi ro và phản biện.
Mọi con số (giá, chỉ báo) do code tính và đưa vào prompt; Claude không được tự bịa số.
"""
from __future__ import annotations

import json
import os
import re
from typing import Dict, List, Optional

SYSTEM = (
    "Bạn là trợ lý phân tích chứng khoán Việt Nam cho một nhà đầu tư cá nhân vốn nhỏ. "
    "Quy tắc bắt buộc: (1) Chỉ dùng dữ liệu được cung cấp, không tự bịa giá, số liệu hay tin. "
    "(2) Không dự đoán giá cụ thể và không hứa hẹn lợi nhuận; nói theo xác suất và kịch bản. "
    "(3) Luôn nêu rủi ro và điều kiện làm nhận định sai. "
    "(4) Nếu dữ liệu không đủ để kết luận, hãy nói rõ là chưa đủ. "
    "(5) Trả lời bằng tiếng Việt. Chỉ trả về JSON hợp lệ, không thêm văn bản ngoài JSON."
)


def provider() -> str:
    """anthropic | openai_compat (Ollama, Gemini...) | mock (kết quả mẫu để thử giao diện)."""
    return os.getenv("LLM_PROVIDER", "anthropic").lower()


def has_key() -> bool:
    p = provider()
    if p == "mock":
        return True
    if p == "openai_compat":
        return bool(os.getenv("OPENAI_COMPAT_BASE_URL"))
    return bool(os.getenv("ANTHROPIC_API_KEY"))


def _parse_json(text: str) -> Dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            return json.loads(m.group(0))
        raise


def _complete(prompt: str, max_tokens: int) -> str:
    p = provider()
    if p == "openai_compat":
        import requests

        base = os.getenv("OPENAI_COMPAT_BASE_URL", "").rstrip("/")
        r = requests.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {os.getenv('OPENAI_COMPAT_API_KEY', 'none')}"},
            json={"model": os.getenv("OPENAI_COMPAT_MODEL", ""),
                  "max_tokens": max_tokens,
                  "messages": [{"role": "system", "content": SYSTEM},
                               {"role": "user", "content": prompt}]},
            timeout=180,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

    import anthropic

    resp = anthropic.Anthropic().messages.create(
        model=os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5"),
        max_tokens=max_tokens,
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")


_MOCK_BRIEF = {
    "tong_quan": "[MẪU] Đây là kết quả giả để thử giao diện, không phải nhận định thật.",
    "ket_noi_the_gioi": "[MẪU] Chưa gọi AI thật.",
    "tin_quan_trong": [{"tieu_de": "Tin mẫu", "ma_lien_quan": ["FPT"], "tac_dong": "trung_tinh",
                        "muc_do": "thap", "thoi_gian": "ngan_han", "nhan_xet": "Dữ liệu mẫu."}],
    "luu_y_danh_muc": [{"ma": "FPT", "nhan_xet": "[MẪU]"}],
    "rui_ro_can_theo_doi": ["[MẪU] Rủi ro giả định"],
    "do_tin_cay_du_lieu": "thap (chế độ mock)",
}
_MOCK_ANALYSIS = {
    "tom_tat": "[MẪU] Kết quả giả để thử giao diện.",
    "luan_diem_mua": ["[MẪU] Lý do 1"],
    "phan_bien": ["[MẪU] Phản biện 1", "[MẪU] Phản biện 2", "[MẪU] Phản biện 3"],
    "dieu_kien_sai": "[MẪU] Thủng hỗ trợ.",
    "kich_ban": {"tot": "[MẪU]", "xau": "[MẪU]"},
    "ket_luan": "cho_theo_doi",
    "ly_do_ket_luan": "[MẪU] Không phải nhận định thật.",
    "thieu_du_lieu": ["Báo cáo tài chính"],
}


def _ask(prompt: str, max_tokens: int = 2000, mock: Optional[Dict] = None) -> Dict:
    if provider() == "mock":
        return dict(mock or {})
    return _parse_json(_complete(prompt, max_tokens))


def morning_brief(news: List[Dict], global_rows: List[Dict], watch: List[Dict]) -> Dict:
    """watch: [{symbol, score, close, rsi, warnings}] — số liệu do code tính sẵn."""
    prompt = f"""Dữ liệu đầu vào (đã được thu thập tự động):

THỊ TRƯỜNG THẾ GIỚI (biến động 1 phiên gần nhất):
{json.dumps(global_rows, ensure_ascii=False)}

TIN TỨC (tiêu đề + tóm tắt ngắn):
{json.dumps([{k: n[k] for k in ("source", "title", "summary")} for n in news[:40]], ensure_ascii=False)}

DANH MỤC THEO DÕI (điểm kỹ thuật do hệ thống tính, 0-100):
{json.dumps(watch, ensure_ascii=False)}

Hãy trả về JSON đúng cấu trúc sau:
{{
  "tong_quan": "2-3 câu về bối cảnh thị trường hôm nay",
  "ket_noi_the_gioi": "diễn biến thế giới có thể tác động thị trường VN như thế nào",
  "tin_quan_trong": [
    {{"tieu_de": "...", "ma_lien_quan": ["..."], "tac_dong": "tich_cuc|tieu_cuc|trung_tinh",
      "muc_do": "thap|vua|cao", "thoi_gian": "ngan_han|dai_han", "nhan_xet": "1 câu"}}
  ],
  "luu_y_danh_muc": [{{"ma": "...", "nhan_xet": "dựa trên điểm kỹ thuật + tin, 1-2 câu"}}],
  "rui_ro_can_theo_doi": ["..."],
  "do_tin_cay_du_lieu": "thap|vua|cao và lý do ngắn"
}}
Chọn tối đa 6 tin quan trọng nhất. Bỏ qua tin quảng cáo/không liên quan."""
    return _ask(prompt, 2500, _MOCK_BRIEF)


def analyze_symbol(symbol: str, signal: Dict, news: List[Dict]) -> Dict:
    """Phân tích một mã: luận điểm, phản biện, điều kiện sai."""
    safe = {k: signal.get(k) for k in
            ("close", "score", "rsi", "vol_ratio", "suggested_stop", "stop_pct",
             "avg_value", "reasons", "warnings")}
    prompt = f"""Mã: {symbol}
Số liệu kỹ thuật do hệ thống tính (đơn vị VND):
{json.dumps(safe, ensure_ascii=False)}

Tin liên quan gần đây:
{json.dumps([{k: n[k] for k in ("source", "title", "summary")} for n in news[:15]], ensure_ascii=False)}

Trả về JSON:
{{
  "tom_tat": "tình trạng hiện tại của mã trong 2 câu",
  "luan_diem_mua": ["tối đa 3 lý do ủng hộ"],
  "phan_bien": ["đúng 3 lý do KHÔNG nên mua lúc này"],
  "dieu_kien_sai": "điều gì xảy ra thì luận điểm mua mất hiệu lực",
  "kich_ban": {{"tot": "...", "xau": "..."}},
  "ket_luan": "cho_theo_doi|co_the_mua_thu_nho|nen_tranh",
  "ly_do_ket_luan": "1-2 câu",
  "thieu_du_lieu": ["những dữ liệu còn thiếu để kết luận chắc hơn, ví dụ báo cáo tài chính"]
}}"""
    return _ask(prompt, 1800, _MOCK_ANALYSIS)
