"""Biểu đồ giá kiểu app chứng khoán: vùng tô gradient, đường tham chiếu, chú giải khi rê chuột."""
from __future__ import annotations

from typing import Dict, Optional

import altair as alt
import pandas as pd
import streamlit as st

from . import ui

RANGES: Dict[str, Optional[int]] = {"1 tháng": 21, "3 tháng": 63, "6 tháng": 126, "1 năm": 252, "3 năm": 756, "Tất cả": None}


def slice_range(df: pd.DataFrame, label: str) -> pd.DataFrame:
    n = RANGES.get(label)
    return df if n is None else df.tail(n)


def price_chart(df: pd.DataFrame, ycol: str = "close", kind: str = "up", height: int = 340,
                overlays: Optional[Dict[str, str]] = None, y_title: Optional[str] = None) -> None:
    """df cần cột `date`, `ycol`. overlays: {cột: nhãn} vẽ thêm đường (vd trung bình 50/200 phiên)."""
    t = ui.tokens()
    color = {"up": t["chart_up"], "down": t["chart_down"]}.get(kind, t["chart_flat"])
    d = df[["date", ycol] + list((overlays or {}).keys())].dropna(subset=[ycol]).copy()
    d = d.rename(columns={ycol: "v"})
    tip = [alt.Tooltip("date:T", title="Ngày", format="%d/%m/%Y"), alt.Tooltip("v:Q", title="Giá", format=",.0f")]
    base = alt.Chart(d).encode(x=alt.X("date:T", title=None, axis=alt.Axis(format="%m/%y", labelColor=t["soft"], grid=False, tickCount=6,
                                                                            labelOverlap=True, domain=False, tickSize=0, labelPadding=8)))
    axis_y = alt.Axis(format=",.0f", labelColor=t["soft"], gridColor=t["grid"], domain=False, tickSize=0, orient="right",
                      title=y_title, labelPadding=6)

    vals = [d["v"]] + [d[col] for col in (overlays or {})]
    lo = float(min(v.min() for v in vals))
    hi = float(max(v.max() for v in vals))
    pad = (hi - lo) * 0.08 or hi * 0.01
    dom = [lo - pad, hi + pad]  # đặt rõ để vùng tô KHÔNG kéo trục về 0 (Vega luôn lấy nền = 0 cho mark vùng)

    def ydef(field: str) -> alt.Y:  # cùng một định nghĩa trục cho MỌI lớp để Vega gộp đúng
        return alt.Y(field, scale=alt.Scale(domain=dom, nice=False, zero=False), axis=axis_y, title=None)

    grad = alt.Gradient(gradient="linear", x1=1, x2=1, y1=1, y2=0,
                        stops=[alt.GradientStop(color="rgba(0,0,0,0)", offset=0),
                               alt.GradientStop(color=color + "30", offset=1)])
    layers = [base.mark_area(line={"color": color, "strokeWidth": 1.8}, color=grad, interpolate="monotone").encode(y=ydef("v:Q"), y2=alt.Y2(datum=dom[0]))]
    for col, name in (overlays or {}).items():
        o = d[["date", col]].dropna().rename(columns={col: "o"}).assign(Đường=name)
        layers.append(alt.Chart(o).mark_line(strokeWidth=1.4, strokeDash=[5, 3], opacity=.9).encode(
            x="date:T", y=ydef("o:Q"),
            color=alt.Color("Đường:N", legend=alt.Legend(orient="top-left", title=None, labelColor=t["soft"]),
                            scale=alt.Scale(range=[t["brand"], "#F59E0B"]))))
    near = alt.selection_point(nearest=True, on="mouseover", fields=["date"], empty=False, clear="mouseout")
    yy = ydef("v:Q")
    layers.append(base.mark_point(opacity=0).encode(y=yy).add_params(near))
    layers.append(base.mark_rule(color=t["soft"], strokeDash=[3, 3]).encode(tooltip=tip).transform_filter(near))
    layers.append(base.mark_circle(size=70, color=color, opacity=1).encode(y=yy).transform_filter(near))
    chart = (alt.layer(*layers).resolve_scale(y="shared").properties(height=height)
             .configure_view(strokeWidth=0).configure(background="transparent"))
    st.altair_chart(chart, theme=None, width="stretch")
