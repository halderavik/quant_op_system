"""Build the Quant OS capabilities PDF.

Usage: python build.py <asset_dir> <output.pdf>

The asset directory holds logo_full.svg and logo_mark.svg (this folder). Needs
reportlab and svglib, and the Segoe UI fonts that ship with Windows:

    uv run --no-project --with reportlab --with svglib python build.py . ../Quant_OS_Capabilities.pdf
"""

import sys
from pathlib import Path

from reportlab.graphics import renderPDF
from reportlab.graphics.shapes import Drawing, Line, Polygon, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    CondPageBreak,
    Flowable,
    Frame,
    KeepTogether,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from svglib.svglib import svg2rlg

ASSETS = Path(sys.argv[1])
OUT = Path(sys.argv[2])

pdfmetrics.registerFont(TTFont("Sans", "C:/Windows/Fonts/segoeui.ttf"))
pdfmetrics.registerFont(TTFont("Sans-Bold", "C:/Windows/Fonts/segoeuib.ttf"))
pdfmetrics.registerFontFamily("Sans", normal="Sans", bold="Sans-Bold", italic="Sans", boldItalic="Sans-Bold")

NAVY = colors.HexColor("#0c1640")
BLUE = colors.HexColor("#1f6892")
TEAL = colors.HexColor("#0f5f58")
TEAL_SOFT = colors.HexColor("#e3f1ee")
BLUE_SOFT = colors.HexColor("#e8f0f6")
INK = colors.HexColor("#1b1f24")
INK2 = colors.HexColor("#4a525b")
LINE = colors.HexColor("#d5dade")
SUNKEN = colors.HexColor("#f4f6f7")

PAGE_W, PAGE_H = letter
MARGIN = 0.85 * inch

body = ParagraphStyle("body", fontName="Sans", fontSize=10, leading=14.5, textColor=INK, spaceAfter=6)
lead = ParagraphStyle("lead", parent=body, fontSize=11.5, leading=17, textColor=INK2, spaceAfter=10)
small = ParagraphStyle("small", parent=body, fontSize=8.5, leading=12, textColor=INK2, spaceAfter=0)
h1 = ParagraphStyle("h1", fontName="Sans-Bold", fontSize=20, leading=25, textColor=NAVY, spaceBefore=0, spaceAfter=8)
h2 = ParagraphStyle("h2", fontName="Sans-Bold", fontSize=12.5, leading=17, textColor=NAVY, spaceBefore=12, spaceAfter=4)
kicker = ParagraphStyle("kicker", fontName="Sans-Bold", fontSize=8.5, leading=11, textColor=TEAL, spaceAfter=3)
bullet = ParagraphStyle("bullet", parent=body, leftIndent=12, bulletIndent=0, spaceAfter=3)
cell = ParagraphStyle("cell", parent=body, fontSize=9.2, leading=13, spaceAfter=0)
cell_bullet = ParagraphStyle("cellb", parent=cell, leftIndent=10, bulletIndent=0, spaceAfter=2)
cell_head = ParagraphStyle("cellh", parent=cell, fontName="Sans-Bold", textColor=NAVY, fontSize=10.5, leading=14)
tile_num = ParagraphStyle("tnum", fontName="Sans-Bold", fontSize=24, leading=28, textColor=TEAL, alignment=TA_LEFT)
tile_txt = ParagraphStyle("ttxt", parent=small, textColor=INK)


def logo(name: str, width: float) -> Drawing:
    drawing = svg2rlg(str(ASSETS / name))
    scale = width / drawing.width
    drawing.scale(scale, scale)
    drawing.width *= scale
    drawing.height *= scale
    return drawing


FULL_LOGO = logo("logo_full.svg", 3.3 * inch)
MARK = logo("logo_mark.svg", 0.3 * inch)


def wordmark(canvas, text: str, x: float, y: float, size: float, spacing: float, color) -> None:
    """Letter-spaced wordmark, like the app's 'Quant OS' under the logo."""
    canvas.setFont("Sans-Bold", size)
    canvas.setFillColor(color)
    for char in text:
        canvas.drawString(x, y, char)
        x += pdfmetrics.stringWidth(char, "Sans-Bold", size) + spacing


def cover(canvas, _doc) -> None:
    canvas.saveState()
    canvas.setFillColor(colors.white)
    canvas.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    renderPDF.draw(FULL_LOGO, canvas, MARGIN - 4, PAGE_H - 3.0 * inch)
    wordmark(canvas, "QUANT OS", MARGIN + 2, PAGE_H - 3.55 * inch, 22, 7, NAVY)
    # Title block
    canvas.setFillColor(NAVY)
    canvas.setFont("Sans-Bold", 34)
    canvas.drawString(MARGIN, PAGE_H - 5.0 * inch, "What Quant OS does")
    canvas.setFont("Sans", 15)
    canvas.setFillColor(INK2)
    canvas.drawString(MARGIN, PAGE_H - 5.4 * inch, "From client brief to client-ready deck in one workspace,")
    canvas.drawString(MARGIN, PAGE_H - 5.68 * inch, "and how it gets better with every study.")
    # Accent band
    canvas.setFillColor(TEAL)
    canvas.rect(MARGIN, PAGE_H - 6.05 * inch, 1.1 * inch, 5, fill=1, stroke=0)
    canvas.setFillColor(BLUE)
    canvas.rect(MARGIN + 1.1 * inch, PAGE_H - 6.05 * inch, 0.45 * inch, 5, fill=1, stroke=0)
    # Footer
    canvas.setStrokeColor(LINE)
    canvas.line(MARGIN, 1.15 * inch, PAGE_W - MARGIN, 1.15 * inch)
    canvas.setFont("Sans-Bold", 10)
    canvas.setFillColor(NAVY)
    canvas.drawString(MARGIN, 0.85 * inch, "b3 Intelligence")
    canvas.setFont("Sans", 10)
    canvas.setFillColor(INK2)
    canvas.drawRightString(PAGE_W - MARGIN, 0.85 * inch, "Capabilities overview  ·  November 2026")
    canvas.restoreState()


def inner(canvas, doc) -> None:
    canvas.saveState()
    renderPDF.draw(MARK, canvas, MARGIN, PAGE_H - 0.68 * inch)
    wordmark(canvas, "QUANT OS", MARGIN + 0.42 * inch, PAGE_H - 0.6 * inch, 9, 2.4, NAVY)
    canvas.setFont("Sans", 8.5)
    canvas.setFillColor(INK2)
    canvas.drawRightString(PAGE_W - MARGIN, PAGE_H - 0.6 * inch, "Capabilities overview")
    canvas.setStrokeColor(LINE)
    canvas.setLineWidth(0.6)
    canvas.line(MARGIN, PAGE_H - 0.78 * inch, PAGE_W - MARGIN, PAGE_H - 0.78 * inch)
    canvas.line(MARGIN, 0.7 * inch, PAGE_W - MARGIN, 0.7 * inch)
    canvas.drawString(MARGIN, 0.5 * inch, "b3 Intelligence")
    canvas.drawRightString(PAGE_W - MARGIN, 0.5 * inch, str(doc.page))
    canvas.restoreState()


def bullets(items: list[str], style: ParagraphStyle = bullet) -> list[Paragraph]:
    return [Paragraph(text, style, bulletText="•") for text in items]


def stage_card(number: str, title: str, summary: str, items: list[str]) -> KeepTogether:
    """One stage of the workflow: a numbered label on the left, what it does on the right."""
    left = [
        Paragraph(number, ParagraphStyle("n", parent=kicker, fontSize=9)),
        Paragraph(title, cell_head),
    ]
    right = [Paragraph(summary, cell), Spacer(1, 4), *bullets(items, cell_bullet)]
    table = Table([[left, right]], colWidths=[1.55 * inch, PAGE_W - 2 * MARGIN - 1.55 * inch])
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BACKGROUND", (0, 0), (0, 0), SUNKEN),
                ("LINEABOVE", (0, 0), (-1, 0), 1.2, TEAL),
                ("LEFTPADDING", (0, 0), (-1, -1), 9),
                ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
            ]
        )
    )
    return KeepTogether([table, Spacer(1, 9)])


def tiles(data: list[tuple[str, str]]) -> Table:
    width = (PAGE_W - 2 * MARGIN) / len(data)
    row = [[Paragraph(num, tile_num), Spacer(1, 2), Paragraph(text, tile_txt)] for num, text in data]
    table = Table([row], colWidths=[width] * len(data))
    style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, -1), TEAL_SOFT),
        ("LEFTPADDING", (0, 0), (-1, -1), 11),
        ("RIGHTPADDING", (0, 0), (-1, -1), 11),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 11),
    ]
    for i in range(1, len(data)):
        style.append(("LINEBEFORE", (i, 0), (i, 0), 2, colors.white))
    table.setStyle(TableStyle(style))
    return table


def callout(text: str) -> Table:
    table = Table([[Paragraph(text, ParagraphStyle("c", parent=body, spaceAfter=0))]], colWidths=[PAGE_W - 2 * MARGIN])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), BLUE_SOFT),
                ("LINEBEFORE", (0, 0), (0, -1), 3, BLUE),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
                ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                ("TOPPADDING", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )
    return table


class Flywheel(Flowable):
    """The learning loop: use, corrections, rules, better first drafts, back to use."""

    STEPS = [
        ("1  Researchers use it", "import, plan, program, edit"),
        ("2  People correct it", "fix wording, logic, codes"),
        ("3  Rules are written", "general, with the example"),
        ("4  Next study is better", "matching rules are applied"),
    ]

    def __init__(self, width: float) -> None:
        super().__init__()
        self.width = width
        self.height = 1.55 * inch

    def wrap(self, *_args):
        return self.width, self.height

    def draw(self) -> None:
        d = Drawing(self.width, self.height)
        gap = 16
        box_w = (self.width - gap * 3) / 4
        box_h = 0.72 * inch
        top = self.height - box_h - 4
        for index, (title, sub) in enumerate(self.STEPS):
            x = index * (box_w + gap)
            fill = TEAL if index == 3 else colors.white
            d.add(Rect(x, top, box_w, box_h, rx=6, ry=6, fillColor=fill, strokeColor=TEAL, strokeWidth=1.2))
            ink = colors.white if index == 3 else NAVY
            sub_ink = colors.white if index == 3 else INK2
            d.add(String(x + 9, top + box_h - 21, title, fontName="Sans-Bold", fontSize=8.6, fillColor=ink))
            d.add(String(x + 9, top + box_h - 37, sub, fontName="Sans", fontSize=8, fillColor=sub_ink))
            if index < 3:
                ax = x + box_w + 2
                ay = top + box_h / 2
                d.add(Line(ax, ay, ax + gap - 6, ay, strokeColor=BLUE, strokeWidth=1.4))
                d.add(Polygon([ax + gap - 6, ay + 3.5, ax + gap - 1, ay, ax + gap - 6, ay - 3.5], fillColor=BLUE, strokeColor=BLUE))
        # Return path from step 4 back to step 1, under the boxes.
        y = top - 22
        x_end = 3 * (box_w + gap) + box_w / 2
        x_start = box_w / 2
        d.add(Line(x_end, top, x_end, y, strokeColor=BLUE, strokeWidth=1.4))
        d.add(Line(x_end, y, x_start, y, strokeColor=BLUE, strokeWidth=1.4))
        d.add(Line(x_start, y, x_start, top - 6, strokeColor=BLUE, strokeWidth=1.4))
        d.add(Polygon([x_start - 3.5, top - 6, x_start, top - 1, x_start + 3.5, top - 6], fillColor=BLUE, strokeColor=BLUE))
        d.add(
            String(
                (x_start + x_end) / 2,
                y - 13,
                "fewer corrections each time round",
                fontName="Sans",
                fontSize=8.5,
                fillColor=INK2,
                textAnchor="middle",
            )
        )
        renderPDF.draw(d, self.canv, 0, 0)


story: list = [NextPageTemplate("inner"), PageBreak()]

# --- Page 2: overview -------------------------------------------------------
story += [
    Paragraph("AT A GLANCE", kicker),
    Paragraph("One workspace for the whole quantitative study", h1),
    Paragraph(
        "Quant OS is a research workspace where specialist agents do the work a quant team does: "
        "writing or importing the questionnaire, programming it in Decipher, pricing sample, checking "
        "respondent quality, building tables, running advanced analytics, coding open ends and producing "
        "the client deck. A researcher asks in plain language in a project chat, and the right specialist picks up the request.",
        lead,
    ),
    Spacer(1, 4),
    tiles(
        [
            ("Brief → deck", "One project carries a study from the client brief to an editable PowerPoint."),
            ("In code", "Every figure is computed in code and checked, never typed by a language model."),
            ("Every step", "Is editable by the researcher, and nothing leaves the building without approval."),
        ]
    ),
    Spacer(1, 14),
    Paragraph("Built on four principles", h2),
    *bullets(
        [
            "<b>Specialists, not one generalist.</b> Questionnaire, programming, sample, cleaning, tables, "
            "analytics, coding and reporting each have their own agent with its own checks.",
            "<b>Numbers come from code.</b> Models plan and write. Statistics are calculated in Python, and any "
            "sentence quoting a number that wasn't computed is rejected.",
            "<b>The researcher stays in control.</b> Questionnaires, logic, tab plans, codeframes and report plans "
            "are all editable. Anything that spends money, changes Decipher or posts outside Quant OS waits for a person to approve it.",
            "<b>It learns from the team.</b> Corrections become rules that improve the next study (see page 7).",
        ]
    ),
    Spacer(1, 6),
    Paragraph("How a study flows", h2),
    Paragraph(
        "Survey design  →  Decipher programming  →  Fieldwork and live quality  →  Data cleaning  →  "
        "Tables  →  Advanced analytics  →  Open-end coding  →  Client report  →  Delivery to the team's tools",
        ParagraphStyle("flow", parent=body, textColor=TEAL, fontName="Sans-Bold", fontSize=9.5, leading=15),
    ),
    Paragraph(
        "Each output is versioned. When an earlier step changes, such as an edited questionnaire, the outputs built "
        "on the old version are marked stale so nothing out of date reaches a client.",
        body,
    ),
]

# --- Capabilities -----------------------------------------------------------
story += [
    PageBreak(),
    Paragraph("CAPABILITIES", kicker),
    Paragraph("What it can do, stage by stage", h1),
    Spacer(1, 4),
    stage_card(
        "01",
        "Questionnaire",
        "Draft a new questionnaire from a brief, or bring in one the client has already written.",
        [
            "Drafts screeners, funnel, image grids, NPS and open ends mapped to each research objective, and shows which questions answer which objective.",
            "Imports a finished Word, PDF or text questionnaire <b>exactly as written</b>. Every question, answer and instruction is checked word for word against the file; anything that doesn't match is read again or reported, never quietly changed.",
            "<b>Show in the file</b> opens the passage each question came from, with its wording highlighted.",
            "Edit in the questionnaire editor or by chat. Export to Word or PDF with programming notes kept separate.",
            "<b>Languages:</b> translates what respondents see into each market's language, keeping brand names and piping as written. A reviewer edits and signs off each language; if the questionnaire changes, only the changed text is translated again.",
        ],
    ),
    stage_card(
        "02",
        "Decipher programming",
        "Turns written programming instructions into working Decipher XML in the house style our programmers use.",
        [
            "Plans the logic: who sees each question, piped rows, number ranges, totals, terminates, rotations, hidden and derived variables, sums and range midpoints, A–Z lists, images and country-specific rows.",
            "A reviewer reads each question's instructions next to its XML, and the planner fixes what's missing. This repeats until nothing is left or nothing more changes, re-reading only what changed.",
            "House rules are applied in code: None and Don't know are exclusive and anchored, Other gets a text box, piped rows are matched by wording, and lists named in the notes are copied.",
            "Shows each question's logic in plain words, with <b>Edit logic</b> to change it in a form. What it can't settle goes to the <b>To-dos</b> tab, where each one can be fixed with AI (and re-checked) or marked done.",
            "A <b>Logic test</b> runs simulated respondents through the XML and checks every base and terminate against the questionnaire, showing the answers behind each problem. <b>Compare XML</b> lines up each question with a hand-edited or reference XML, side by side.",
            "Preview the survey as a respondent. Upload to Decipher only when a person confirms; if Decipher rejects the file, the structure it names is repaired. Live surveys are never replaced.",
        ],
    ),
    stage_card(
        "03",
        "Fieldwork and sample",
        "Price real sample, or generate realistic test data before fieldwork starts.",
        [
            "Prolific quotes: audience, quota cells, eligibility, reward and total. Nothing is bought until a person confirms the total.",
            "Synthetic respondents that walk the programmed survey's routing, terminates and quotas, with personas and linked attitudes, delivered as an SPSS file.",
            "<b>Tracking studies:</b> start the next wave with the questionnaire, its planned logic, tab spec, weighting and report plan already in place, and see which questionnaire changes break the trend.",
        ],
    ),
    stage_card(
        "04",
        "Live bot and fraud detection",
        "Watches respondents while a Decipher survey is in field.",
        [
            "A tracker added at programming time checks typing, mouse and touch behaviour, timing, open-end quality, device and network signals.",
            "Each respondent gets a verdict with reasons (looks human, needs review, bot-like), written into the Decipher data file as hidden questions.",
            "A live dashboard per survey and across surveys, editable quality rules, and the option to end the survey early for clear bot signals.",
        ],
    ),
    stage_card(
        "05",
        "Data cleaning",
        "Recommends who to keep, review or remove, with the reason for each.",
        [
            "Speeders, straight-liners and patterned grids, duplicates, failed attention checks, item non-response and gibberish or copied open ends.",
            "Counts are computed in code. Removals are applied to a new copy of the dataset; the original file is never changed.",
        ],
    ),
    stage_card(
        "06",
        "Tables and weighting",
        "From a single crosstab to the full tab book, weighted to the population.",
        [
            "Crosstabs with bases and significance letters, downloadable to Excel. Percentages are tested with a z-test and means with a Welch t-test; weighted tables use the effective base.",
            "Census targets found by web search, each with its source and arithmetic, edited by the researcher and used to build a rim weight that every table and deck uses.",
            "Trend tables across tracking waves, testing each wave against the one before.",
            "Builds the tab plan from the questionnaire with your banners, dry-runs it so every table has a base, and exports it in the analyst workbook format.",
            "Runs the full tab book, or imports an existing Excel tab spec.",
        ],
    ),
    stage_card(
        "07",
        "Advanced analytics",
        "Standard methods with research guardrails, plus custom methods written on demand.",
        [
            "Key driver analysis with relative importance, collinearity and base checks.",
            "Segmentation that tests 4 to 8 solutions across several clustering methods and rejects a segment too small to act on, with profiles.",
            "A guided <b>Segments</b> tool compares solutions on separation, stability and smallest segment, recommends one, names the segments from what sets them apart, adds them to the data, and gives an Excel typing tool that classifies new respondents from a few questions.",
            "A method that isn't built in is written as Python, run in an isolated sandbox with no network or keys, and checked before results are shown. Charts, script and workbook are downloadable.",
        ],
    ),
    stage_card(
        "08",
        "Open-end coding",
        "Builds a codeframe and codes every response.",
        [
            "Discovers nets, subnets and codes from the question and the answers, then codes all responses in one pass.",
            "A review queue keeps both the initial and final code for every change. Existing codeframes can be imported.",
        ],
    ),
    stage_card(
        "09",
        "Client report",
        "Plans the deck from the moment a questionnaire exists, and builds it when the data is in.",
        [
            "The report plan follows the study's objectives: who we spoke to, one chapter per objective, drivers, takeaways. Each slide lists its questions, banner, statistic and base, and is fully editable.",
            "Generates a PowerPoint with native, editable charts and tables. Headlines are written from computed results only.",
        ],
    ),
    stage_card(
        "10",
        "Delivery to the team's tools",
        "Works with Google Drive, Slack, Microsoft 365, or any MCP server.",
        [
            "Import a brief or data file, save decks and tab books, post key takeaways to a channel.",
            "Steps that only read run at once. Anything that uploads or posts shows an approval card with the exact file or message first.",
        ],
    ),
]

# --- Trust ------------------------------------------------------------------
story += [
    CondPageBreak(3.5 * inch),
    Spacer(1, 6),
    Paragraph("TRUST AND CONTROL", kicker),
    Paragraph("Built so a researcher can stand behind every number", h1),
    *bullets(
        [
            "<b>Checked outputs.</b> A validator checks schemas, bases, exports and every numeric claim. Each analysis shows its provenance and the claims tied to computed results.",
            "<b>Approval before anything irreversible.</b> Buying sample, uploading to Decipher, saving to Drive or posting to Slack each wait for a person.",
            "<b>Data stays protected.</b> Models see the questionnaire, variable labels and aggregated results, not respondent rows. Custom analysis code runs in a sandbox with no network access and no API keys.",
            "<b>Resilient.</b> If one AI provider fails, the call is retried once on a backup model from another provider, and the reply says so. Long tasks can be stopped, and sending the same request again reuses the parts already finished.",
            "<b>Tested before fieldwork.</b> The Logic test runs simulated respondents through the survey XML and checks each base and terminate against the questionnaire, so a wrong base is found before real respondents see it.",
            "<b>Honest about limits.</b> MaxDiff and conjoint are refused rather than approximated. Programming leaves what it can't do as a visible to-do.",
        ]
    ),
]

# --- Roadmap / limits -------------------------------------------------------
story += [
    Spacer(1, 6),
    Paragraph("Today's limits and what's next", h2),
    *bullets(
        [
            "Decipher loops (a block repeated per brand) are next for programming. Quotas and sample-source logic are left for the programmer as to-dos.",
            "Each language is built as its own survey XML; one Decipher survey holding several languages isn't generated yet.",
            "The Logic test simulates the XML locally rather than driving Decipher's own test link, and doesn't check logic that depends on select-all grids.",
            "Advanced analyses, including segmentation, run unweighted. Tables, tab books and the deck are weighted.",
            "Prolific is the connected sample panel today; other panels are not yet connected.",
            "Images, embedded spreadsheets and comments inside Word questionnaires aren't read.",
            "MaxDiff and conjoint are out of scope by design.",
        ]
    ),
]

# --- Learning ---------------------------------------------------------------
story += [
    PageBreak(),
    Paragraph("GETTING BETTER WITH USE", kicker),
    Paragraph("How Quant OS improves as we use it", h1),
    Paragraph(
        "Every study teaches the system something about how our clients write questionnaires and how our "
        "researchers and programmers want them built. Those lessons are captured as plain-language rules, "
        "applied to the next study, and kept under the team's control.",
        lead,
    ),
    Flywheel(PAGE_W - 2 * MARGIN),
    Spacer(1, 6),
    Paragraph("Three ways it learns", h2),
    Paragraph(
        "<b>1. Learning to read questionnaires.</b> Questionnaires lay out questions, codes and instructions in "
        "many different ways. When part of a file is misread and the automatic retry reads it correctly, the first "
        "mistake becomes a general reading rule, for example \"copy inline piping directives inside an option "
        "exactly\". Changes researchers make to wording, question types, answer lists or notes before programming "
        "become reading rules too. The importer receives the rules whose examples resemble the file it's reading, "
        "so each questionnaire it reads improves the next. Rules never relax the requirement to copy the file word for word.",
        body,
    ),
    Paragraph(
        "<b>2. Learning how we program.</b> When a survey is programmed, the approved questionnaire is compared with "
        "what the system planned. Each change a person made to the logic is written as a general rule, for example "
        "\"ASK BRANDS AWARE IN &lt;question&gt; means show only the brands marked Yes at that question\". A rule seen "
        "again gains support. Later plans and reviews receive the rules that match their instructions, plus the most-confirmed ones.",
        body,
    ),
    Paragraph(
        "<b>3. Capturing what researchers think of the output.</b> Every edit, correction and rating is recorded, "
        "including what a researcher says should be different. That record is the base for the next steps of learning.",
        body,
    ),
    Paragraph("What gets better, and how we can see it", h2),
    *bullets(
        [
            "<b>Fewer re-reads</b> when importing a new questionnaire layout.",
            "<b>Fewer corrections</b> to logic before a survey is programmed.",
            "<b>Fewer open to-dos</b> left for a programmer, and XML that looks more like our programmers' own.",
            "The <b>Progress</b> tab on the Learned rules page charts import retries and corrections over time, so the trend is visible, not assumed.",
        ]
    ),
]

story += [
    CondPageBreak(3.2 * inch),
    Paragraph("Measured against our own programmers", h2),
    Paragraph(
        "Each change to the system is re-checked on real client questionnaires: the Word file is imported and "
        "programmed from scratch, and the result is compared with the Decipher XML a programmer built by hand for "
        "the same survey. The comparison covers question types, answer rows and columns, wording, who sees each "
        "question, terminates, piping, ranges and randomisation. A change that makes any survey worse by more than "
        "2 points is flagged before it's used.",
        body,
    ),
    Spacer(1, 4),
    tiles(
        [
            ("14", "client questionnaires in the benchmark, kept private and out of the codebase"),
            ("85.4%", "of checks matched on the first set of 7 surveys (November 2026)"),
            ("85.2%", "on the 3 newest surveys, up from 79.3% when first measured"),
        ]
    ),
    Spacer(1, 8),
    Paragraph(
        "A second set of 4 surveys matched 89.8% when last measured. New questionnaires feed this loop too. In "
        "November, the 3 newest surveys surfaced new layouts and patterns, such as question ids written as \"BM1.\", "
        "derived variables built from other derived variables, and lists described only in the notes (\"same list as "
        "Q1\"). Each was fixed, added to the tests, and re-measured. Across the 10 surveys of the first and newest "
        "sets, the to-dos left for a programmer fell from 880 to 749.",
        body,
    ),
    Paragraph("The team stays in charge of what it learns", h2),
    *bullets(
        [
            "The <b>Learned rules</b> page lists every rule with the example it came from, what was read or planned against what was correct, and how often it's been confirmed.",
            "Any rule can be switched off. A project can opt out of learning altogether.",
            "Only questionnaire instructions and logic are stored as rules, never respondent data.",
            "Ticking off a to-do isn't treated as a correction; only real changes teach the system.",
        ]
    ),
    Spacer(1, 10),
    callout(
        "<b>The more studies go through Quant OS, the more of our house style it carries into the next one.</b> "
        "Early on, researchers correct more. Each correction is made once and then applied automatically, so the "
        "effort per study should fall as usage grows, and the Progress tab shows whether it does."
    ),
]

def build() -> None:
    doc = BaseDocTemplate(
        str(OUT),
        pagesize=letter,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=1.05 * inch,
        bottomMargin=0.95 * inch,
        title="Quant OS: Capabilities overview",
        author="b3 Intelligence",
        subject="What Quant OS does and how it improves with use",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="f", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates(
        [
            PageTemplate(id="cover", frames=[frame], onPage=cover),
            PageTemplate(id="inner", frames=[frame], onPage=inner),
        ]
    )
    doc.build(story)


build()
print("built", OUT)
