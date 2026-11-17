"""Build the report deck as PPTX. Charts are native PowerPoint charts, so every one is editable."""

from datetime import date
from io import BytesIO
from pathlib import Path
from typing import Any

from pptx import Presentation
from pptx.chart.data import CategoryChartData, XyChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

NAVY = RGBColor(0x0C, 0x16, 0x40)
BLUE = RGBColor(0x1F, 0x68, 0x92)
GREY = RGBColor(0x5E, 0x67, 0x70)
LIGHT = RGBColor(0xF3, 0xF5, 0xF8)
LINE = RGBColor(0xD9, 0xDE, 0xE4)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
PALETTE = [
    "1F6892",
    "0C1640",
    "A6AAAD",
    "4A9AD0",
    "2BB3A3",
    "F2A541",
    "7A5195",
    "C44536",
    "6A994E",
    "8D6E63",
]
LOGO = Path(__file__).resolve().parents[2] / "assets" / "quant_os_logo.png"
_FORMATS = {"pct": '0"%"', "mean": "0.00", "score": "0", "number": "General"}


def build_deck(deck: dict[str, Any]) -> bytes:
    """Write the deck.

    Args:
        deck: ``title``, ``subtitle`` and ``slides``. Each slide has ``type``
            (title, section, text, chart, table) and its fields.

    Returns:
        PPTX bytes.
    """
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    blank = prs.slide_layouts[6]
    number = 0
    for spec in deck["slides"]:
        slide = prs.slides.add_slide(blank)
        number += 1
        kind = spec.get("type")
        if kind == "title":
            _title_slide(slide, deck, spec)
            continue
        if kind == "section":
            _section_slide(slide, spec)
            continue
        _header(slide, spec)
        if kind == "chart" and spec.get("chart"):
            _chart_area(slide, spec)
        elif kind == "table" and spec.get("table"):
            _table(slide, spec["table"], Inches(0.5), Inches(1.75), Inches(12.3), Inches(4.9))
        else:
            _bullets(
                slide,
                spec.get("bullets") or [],
                Inches(0.5),
                Inches(1.75),
                Inches(12.3),
                Inches(4.9),
                size=18,
            )
        _footer(slide, spec, number)
        if spec.get("notes"):
            slide.notes_slide.notes_text_frame.text = spec["notes"]
    buffer = BytesIO()
    prs.save(buffer)
    return buffer.getvalue()


def _text(
    slide,
    text,
    left,
    top,
    width,
    height,
    *,
    size=14,
    bold=False,
    color=NAVY,
    align=PP_ALIGN.LEFT,
    anchor=MSO_ANCHOR.TOP,
):
    box = slide.shapes.add_textbox(left, top, width, height)
    frame = box.text_frame
    frame.word_wrap = True
    frame.vertical_anchor = anchor
    para = frame.paragraphs[0]
    para.alignment = align
    run = para.add_run()
    run.text = str(text)
    run.font.size, run.font.bold, run.font.color.rgb = Pt(size), bold, color
    run.font.name = "Segoe UI"
    return box


def _title_slide(slide, deck, spec) -> None:
    band = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, Inches(6.9), Inches(13.333), Inches(0.6))
    band.fill.solid()
    band.fill.fore_color.rgb = NAVY
    band.line.fill.background()
    if LOGO.exists():
        slide.shapes.add_picture(str(LOGO), Inches(0.6), Inches(0.5), height=Inches(2.6))
    _text(
        slide,
        spec.get("title") or deck["title"],
        Inches(0.8),
        Inches(3.3),
        Inches(11.5),
        Inches(1.3),
        size=38,
        bold=True,
    )
    _text(
        slide,
        spec.get("subtitle") or deck.get("subtitle", ""),
        Inches(0.8),
        Inches(4.6),
        Inches(11.5),
        Inches(0.8),
        size=18,
        color=GREY,
    )
    _text(
        slide,
        date.today().strftime("%B %Y"),
        Inches(0.8),
        Inches(5.4),
        Inches(6),
        Inches(0.5),
        size=14,
        color=GREY,
    )
    _text(
        slide,
        "Prepared with Quant OS",
        Inches(0.8),
        Inches(6.98),
        Inches(6),
        Inches(0.4),
        size=12,
        color=WHITE,
    )


def _section_slide(slide, spec) -> None:
    bg = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(13.333), Inches(7.5))
    bg.fill.solid()
    bg.fill.fore_color.rgb = NAVY
    bg.line.fill.background()
    bar = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(0.8), Inches(2.85), Inches(0.12), Inches(1.6)
    )
    bar.fill.solid()
    bar.fill.fore_color.rgb = BLUE
    bar.line.fill.background()
    if spec.get("number"):
        _text(
            slide,
            f"{spec['number']:02d}",
            Inches(1.15),
            Inches(1.9),
            Inches(3),
            Inches(0.8),
            size=28,
            bold=True,
            color=RGBColor(0x4A, 0x9A, 0xD0),
        )
    _text(
        slide,
        spec.get("title", ""),
        Inches(1.15),
        Inches(2.75),
        Inches(11),
        Inches(1.2),
        size=34,
        bold=True,
        color=WHITE,
    )
    if spec.get("subtitle"):
        _text(
            slide,
            spec["subtitle"],
            Inches(1.15),
            Inches(3.9),
            Inches(10.5),
            Inches(1.4),
            size=16,
            color=RGBColor(0xC9, 0xD3, 0xE0),
        )


def _header(slide, spec) -> None:
    _text(
        slide,
        spec.get("title", ""),
        Inches(0.5),
        Inches(0.3),
        Inches(12.3),
        Inches(0.95),
        size=24,
        bold=True,
        anchor=MSO_ANCHOR.BOTTOM,
    )
    if spec.get("subtitle"):
        _text(
            slide,
            spec["subtitle"],
            Inches(0.5),
            Inches(1.22),
            Inches(12.3),
            Inches(0.5),
            size=12,
            color=GREY,
        )
    rule = slide.shapes.add_connector(1, Inches(0.5), Inches(1.7), Inches(12.83), Inches(1.7))
    rule.line.color.rgb = LINE


def _footer(slide, spec, number: int) -> None:
    note = " · ".join(part for part in (spec.get("base_text"), spec.get("source")) if part)
    if note:
        _text(slide, note, Inches(0.5), Inches(6.95), Inches(11), Inches(0.4), size=9, color=GREY)
    _text(
        slide,
        str(number),
        Inches(12.3),
        Inches(6.95),
        Inches(0.55),
        Inches(0.4),
        size=9,
        color=GREY,
        align=PP_ALIGN.RIGHT,
    )


def _chart_area(slide, spec) -> None:
    bullets = spec.get("bullets") or []
    width = Inches(8.5) if bullets else Inches(12.3)
    chart = spec["chart"]
    if chart.get("kind") == "table":
        _table(slide, chart["table"], Inches(0.5), Inches(1.85), width, Inches(4.9))
    else:
        _native_chart(slide, chart, Inches(0.5), Inches(1.85), width, Inches(4.95))
    if bullets:
        panel = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE, Inches(9.2), Inches(1.95), Inches(3.63), Inches(4.75)
        )
        panel.fill.solid()
        panel.fill.fore_color.rgb = LIGHT
        panel.line.fill.background()
        _bullets(slide, bullets, Inches(9.35), Inches(2.1), Inches(3.35), Inches(4.5), size=13)


def _native_chart(slide, chart: dict[str, Any], left, top, width, height) -> None:
    kind = chart.get("kind", "bar")
    series = chart.get("series") or []
    if kind == "xy":
        data = XyChartData()
        for item in series:
            s = data.add_series(item.get("name") or "Series")
            for x, y in zip(item.get("x") or [], item.get("y") or [], strict=False):
                if x is not None and y is not None:
                    s.add_data_point(x, y)
        frame = slide.shapes.add_chart(
            XL_CHART_TYPE.XY_SCATTER_LINES_NO_MARKERS, left, top, width, height, data
        )
        _style(
            frame.chart,
            len(series),
            labels=False,
            number_format=_FORMATS.get(chart.get("number_format"), "General"),
        )
        return
    data = CategoryChartData()
    data.categories = list(chart.get("categories") or [])
    for item in series:
        data.add_series(
            item.get("name") or "Value",
            [None if v is None else float(v) for v in item.get("values") or []],
        )
    chart_type = {
        "bar": XL_CHART_TYPE.BAR_CLUSTERED,
        "column": XL_CHART_TYPE.COLUMN_CLUSTERED,
        "stacked": XL_CHART_TYPE.BAR_STACKED_100,
        "stacked_column": XL_CHART_TYPE.COLUMN_STACKED,
        "line": XL_CHART_TYPE.LINE_MARKERS,
    }.get(kind, XL_CHART_TYPE.BAR_CLUSTERED)
    frame = slide.shapes.add_chart(chart_type, left, top, width, height, data)
    fmt = _FORMATS.get(chart.get("number_format"), "General")
    _style(
        frame.chart, len(series), labels=len(data.categories) * len(series) <= 60, number_format=fmt
    )
    if kind in {"bar", "stacked"}:
        frame.chart.category_axis.reverse_order = True


def _style(chart, n_series: int, *, labels: bool, number_format: str) -> None:
    chart.font.size = Pt(11)
    chart.font.name = "Segoe UI"
    chart.has_legend = n_series > 1
    if chart.has_legend:
        chart.legend.position = XL_LEGEND_POSITION.BOTTOM
        chart.legend.include_in_layout = False
    for index, series in enumerate(chart.series):
        fill = series.format.fill
        fill.solid()
        fill.fore_color.rgb = RGBColor.from_string(PALETTE[index % len(PALETTE)])
        try:
            series.format.line.color.rgb = RGBColor.from_string(PALETTE[index % len(PALETTE)])
        except Exception:
            pass
    plot = chart.plots[0]
    if hasattr(plot, "gap_width"):
        plot.gap_width = 60
    if labels:
        plot.has_data_labels = True
        data_labels = plot.data_labels
        data_labels.number_format = number_format
        data_labels.number_format_is_linked = False
        data_labels.font.size = Pt(10)
        try:
            data_labels.position = (
                XL_LABEL_POSITION.OUTSIDE_END if n_series == 1 else XL_LABEL_POSITION.CENTER
            )
        except Exception:
            pass
    try:
        axis = chart.value_axis
        axis.has_major_gridlines = False
        axis.tick_labels.number_format = number_format
        axis.tick_labels.number_format_is_linked = False
        axis.tick_labels.font.size = Pt(10)
    except Exception:
        pass


def _bullets(slide, items: list[str], left, top, width, height, *, size: int) -> None:
    box = slide.shapes.add_textbox(left, top, width, height)
    frame = box.text_frame
    frame.word_wrap = True
    for index, item in enumerate(items):
        para = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        para.space_after = Pt(10)
        run = para.add_run()
        run.text = f"• {item}"
        run.font.size, run.font.color.rgb, run.font.name = Pt(size), NAVY, "Segoe UI"


def _table(slide, table: dict[str, Any], left, top, width, height) -> None:
    columns = [str(c) for c in table.get("columns") or []]
    rows = table.get("rows") or []
    if not columns:
        return
    shape = slide.shapes.add_table(
        len(rows) + 1,
        len(columns),
        left,
        top,
        width,
        Emu(min(int(height), int(Inches(0.36)) * (len(rows) + 1))),
    )
    grid = shape.table
    for j, name in enumerate(columns):
        cell = grid.cell(0, j)
        cell.text = name
        _cell(cell, bold=True, fill=NAVY, color=WHITE)
    for i, row in enumerate(rows, start=1):
        for j, value in enumerate(row[: len(columns)]):
            cell = grid.cell(i, j)
            cell.text = _fmt(value)
            _cell(cell, fill=LIGHT if i % 2 else WHITE, color=NAVY)


def _cell(cell, *, bold=False, fill=WHITE, color=NAVY) -> None:
    cell.fill.solid()
    cell.fill.fore_color.rgb = fill
    for para in cell.text_frame.paragraphs:
        for run in para.runs:
            run.font.size, run.font.bold, run.font.color.rgb = Pt(11), bold, color


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.2f}".rstrip("0").rstrip(".") if abs(value) < 100 else f"{value:.0f}"
    return "" if value is None else str(value)
