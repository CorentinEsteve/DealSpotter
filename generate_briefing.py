"""Generate the DealSpotter CEO Briefing PDF."""

import sqlite3
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs, unquote

import config
import db

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm, cm
from reportlab.lib.colors import HexColor, white, black
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, KeepTogether, HRFlowable
)
from reportlab.pdfgen import canvas
from reportlab.lib import colors

REPORT_DATE_LONG = None
REPORT_DATE_SHORT = None

# ── Colors ──
DARK_BG = HexColor("#1a1a2e")
ACCENT = HexColor("#e94560")
ACCENT_LIGHT = HexColor("#fce4ec")
HEADER_BG = HexColor("#16213e")
SECTION_BG = HexColor("#f8f9fa")
TABLE_HEADER_BG = HexColor("#1a1a2e")
TABLE_ALT_ROW = HexColor("#f5f5f5")
TEXT_DARK = HexColor("#212529")
TEXT_MUTED = HexColor("#6c757d")
SUCCESS = HexColor("#28a745")
WARNING = HexColor("#ffc107")
DANGER = HexColor("#dc3545")
INFO_BLUE = HexColor("#0d6efd")

W, H = A4

# ── Styles ──
styles = getSampleStyleSheet()

styles.add(ParagraphStyle(
    'SectionTitle', fontName='Helvetica-Bold', fontSize=16,
    textColor=DARK_BG, spaceAfter=8, spaceBefore=16,
    borderPadding=(0, 0, 4, 0),
))
styles.add(ParagraphStyle(
    'SubSection', fontName='Helvetica-Bold', fontSize=12,
    textColor=HEADER_BG, spaceAfter=6, spaceBefore=12,
))
styles.add(ParagraphStyle(
    'BodyText2', fontName='Helvetica', fontSize=10,
    textColor=TEXT_DARK, spaceAfter=6, leading=14,
))
styles.add(ParagraphStyle(
    'BodyBold', fontName='Helvetica-Bold', fontSize=10,
    textColor=TEXT_DARK, spaceAfter=6, leading=14,
))
styles.add(ParagraphStyle(
    'SmallMuted', fontName='Helvetica', fontSize=8,
    textColor=TEXT_MUTED, spaceAfter=4,
))
styles.add(ParagraphStyle(
    'BulletItem', fontName='Helvetica', fontSize=10,
    textColor=TEXT_DARK, spaceAfter=4, leading=14,
    leftIndent=16, bulletIndent=4,
))
styles.add(ParagraphStyle(
    'NumberedItem', fontName='Helvetica', fontSize=10,
    textColor=TEXT_DARK, spaceAfter=4, leading=14,
    leftIndent=20,
))
styles.add(ParagraphStyle(
    'CodeStyle', fontName='Courier', fontSize=8,
    textColor=TEXT_DARK, spaceAfter=6, leading=11,
    leftIndent=12, backColor=HexColor("#f4f4f4"),
))
styles.add(ParagraphStyle(
    'CalloutText', fontName='Helvetica', fontSize=10,
    textColor=DARK_BG, spaceAfter=4, leading=14,
    leftIndent=12, rightIndent=12,
))
styles.add(ParagraphStyle(
    'TableCell', fontName='Helvetica', fontSize=9,
    textColor=TEXT_DARK, leading=12,
))
styles.add(ParagraphStyle(
    'TableCellBold', fontName='Helvetica-Bold', fontSize=9,
    textColor=TEXT_DARK, leading=12,
))
styles.add(ParagraphStyle(
    'TableHeader', fontName='Helvetica-Bold', fontSize=9,
    textColor=white, leading=12,
))
styles.add(ParagraphStyle(
    'RecommendTitle', fontName='Helvetica-Bold', fontSize=11,
    textColor=ACCENT, spaceAfter=4, spaceBefore=8,
))
styles.add(ParagraphStyle(
    'PipelineCode', fontName='Courier', fontSize=7.5,
    textColor=TEXT_DARK, leading=10,
))

# ── Helpers ──

def section_title(text, number=None):
    if number:
        return Paragraph(f'<font color="{ACCENT.hexval()}">{number}.</font>  {text}', styles['SectionTitle'])
    return Paragraph(text, styles['SectionTitle'])

def section_line():
    return HRFlowable(width="100%", thickness=1, color=HexColor("#dee2e6"), spaceAfter=8, spaceBefore=4)

def body(text):
    return Paragraph(text, styles['BodyText2'])

def body_bold(text):
    return Paragraph(text, styles['BodyBold'])

def bullet(text):
    return Paragraph(f'<bullet>&bull;</bullet> {text}', styles['BulletItem'])

def numbered(n, text):
    return Paragraph(f'<b>{n}.</b> {text}', styles['NumberedItem'])

def make_table(headers, rows, col_widths=None):
    """Create a styled table."""
    header_row = [Paragraph(h, styles['TableHeader']) for h in headers]
    data = [header_row]
    for row in rows:
        data.append([Paragraph(str(c), styles['TableCell']) for c in row])

    t = Table(data, colWidths=col_widths, repeatRows=1)
    style_cmds = [
        ('BACKGROUND', (0, 0), (-1, 0), TABLE_HEADER_BG),
        ('TEXTCOLOR', (0, 0), (-1, 0), white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('TOPPADDING', (0, 0), (-1, 0), 8),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, HexColor("#dee2e6")),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 1), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
    ]
    for i in range(1, len(data)):
        if i % 2 == 0:
            style_cmds.append(('BACKGROUND', (0, i), (-1, i), TABLE_ALT_ROW))
    t.setStyle(TableStyle(style_cmds))
    return t

def callout_box(title_text, content_elements, border_color=INFO_BLUE):
    """Create a colored callout box."""
    inner = []
    if title_text:
        inner.append(Paragraph(f'<b>{title_text}</b>', styles['CalloutText']))
    inner.extend(content_elements)

    data = [[inner]]
    t = Table(data, colWidths=[W - 4*cm])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), HexColor("#f8f9ff")),
        ('LEFTPADDING', (0, 0), (-1, -1), 12),
        ('RIGHTPADDING', (0, 0), (-1, -1), 12),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('LINEBEFOREDECOR', (0, 0), (0, -1), 3, border_color),
        ('BOX', (0, 0), (-1, -1), 0.5, HexColor("#dee2e6")),
    ]))
    return t

def euro(value, decimals=0):
    try:
        return f"{float(value):.{decimals}f}€"
    except Exception:
        return "—"

def pct(value, decimals=0):
    try:
        return f"{value * 100:.{decimals}f}%"
    except Exception:
        return "—"

def _is_prefilter_reason(reason: str) -> bool:
    if not reason:
        return False
    return (
        reason.startswith("prix_trop_bas")
        or reason.startswith("prix_trop_haut")
        or reason.startswith("mot_clé_bloqué")
        or reason.startswith("annonce_épave")
        or reason.startswith("vendeur_pro")
    )

def parse_search_url(url: str) -> dict:
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    text = unquote(qs.get("text", [""])[0]).replace("+", " ").strip()
    price = qs.get("price", [""])[0]
    owner_type = qs.get("owner_type", [""])[0]
    sort = qs.get("sort", [""])[0]
    order = qs.get("order", [""])[0]
    category = qs.get("category", [""])[0]
    locations = qs.get("locations", [""])[0]

    return {
        "text": text or "—",
        "price": price or "—",
        "owner_type": owner_type or "—",
        "sort": f"{sort} {order}".strip() if sort or order else "—",
        "category": category or "—",
        "locations": locations or "All France",
    }

def load_metrics() -> dict:
    stats = db.get_detailed_stats()
    total = stats.get("total", 0)
    alerted = stats.get("alerted", 0)
    evaluated_total = stats.get("evaluated", 0) + alerted
    skip_reasons = stats.get("skip_reasons", {})

    prefiltered = sum(count for reason, count in skip_reasons.items() if _is_prefilter_reason(reason))
    skipped_other = max(0, stats.get("skipped", 0) - prefiltered)

    margin_total = stats.get("margin_positive", 0) + stats.get("margin_negative", 0)
    positive_rate = (stats.get("margin_positive", 0) / margin_total) if margin_total else 0
    alert_rate = (alerted / total) if total else 0

    conn = sqlite3.connect(db.DB_PATH)
    conn.row_factory = sqlite3.Row

    tier_rows = conn.execute(
        "SELECT eval_tier, COUNT(*) c FROM listings "
        "WHERE eval_tier IS NOT NULL GROUP BY eval_tier"
    ).fetchall()
    tier_counts = {row["eval_tier"]: row["c"] for row in tier_rows}

    top_rows = conn.execute(
        "SELECT lbc_id, title, price, flip_margin, ai_brand, status "
        "FROM listings WHERE flip_margin IS NOT NULL "
        "ORDER BY flip_margin DESC LIMIT 8"
    ).fetchall()
    top_listings = [dict(r) for r in top_rows]

    brand_rows = conn.execute(
        "SELECT ai_brand, COUNT(*) c, AVG(flip_margin) avg_margin "
        "FROM listings WHERE ai_brand IS NOT NULL AND flip_margin IS NOT NULL "
        "GROUP BY ai_brand HAVING c >= 2 ORDER BY avg_margin DESC"
    ).fetchall()
    brand_stats = [dict(r) for r in brand_rows]

    price_rows = conn.execute(
        "SELECT "
        "CASE "
        "WHEN price < 100 THEN '50-99' "
        "WHEN price < 250 THEN '100-249' "
        "WHEN price < 500 THEN '250-499' "
        "ELSE '500-1000' END AS bucket, "
        "COUNT(*) c, AVG(flip_margin) avg_margin "
        "FROM listings WHERE flip_margin IS NOT NULL "
        "GROUP BY bucket ORDER BY bucket"
    ).fetchall()
    price_buckets = [dict(r) for r in price_rows]

    since = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    last_24h = conn.execute(
        "SELECT COUNT(*) c FROM listings WHERE first_seen_at >= ?",
        (since,)
    ).fetchone()["c"]

    conn.close()

    return {
        "stats": stats,
        "total": total,
        "alerted": alerted,
        "evaluated_total": evaluated_total,
        "prefiltered": prefiltered,
        "skipped_other": skipped_other,
        "positive_rate": positive_rate,
        "alert_rate": alert_rate,
        "tier_counts": tier_counts,
        "top_listings": top_listings,
        "brand_stats": brand_stats,
        "price_buckets": price_buckets,
        "last_24h": last_24h,
    }

# ── Page Templates ──

def cover_page(canvas_obj, doc):
    """Draw the cover page background."""
    canvas_obj.saveState()
    # Dark header block
    canvas_obj.setFillColor(DARK_BG)
    canvas_obj.rect(0, H - 280, W, 280, fill=True, stroke=False)
    # Accent stripe
    canvas_obj.setFillColor(ACCENT)
    canvas_obj.rect(0, H - 284, W, 4, fill=True, stroke=False)
    # Title
    canvas_obj.setFillColor(white)
    canvas_obj.setFont('Helvetica-Bold', 36)
    canvas_obj.drawString(2*cm, H - 120, "DealSpotter")
    # Subtitle
    canvas_obj.setFont('Helvetica', 16)
    canvas_obj.setFillColor(HexColor("#adb5bd"))
    canvas_obj.drawString(2*cm, H - 150, "Automated Deal Detection on leboncoin.fr")
    # Report info
    canvas_obj.setFillColor(ACCENT)
    canvas_obj.setFont('Helvetica-Bold', 14)
    canvas_obj.drawString(2*cm, H - 200, "Project Briefing")
    canvas_obj.setFillColor(HexColor("#adb5bd"))
    canvas_obj.setFont('Helvetica', 12)
    date_str = REPORT_DATE_LONG or "March 15, 2026"
    canvas_obj.drawString(2*cm, H - 222, f"CTO Report  |  {date_str}")
    # Footer line
    canvas_obj.setFillColor(TEXT_MUTED)
    canvas_obj.setFont('Helvetica', 8)
    canvas_obj.drawString(2*cm, 2*cm, "Confidential  |  DealSpotter v1.0")
    canvas_obj.restoreState()

def normal_page(canvas_obj, doc):
    """Header and footer for content pages."""
    canvas_obj.saveState()
    # Top bar
    canvas_obj.setFillColor(DARK_BG)
    canvas_obj.rect(0, H - 28, W, 28, fill=True, stroke=False)
    canvas_obj.setFillColor(ACCENT)
    canvas_obj.rect(0, H - 30, W, 2, fill=True, stroke=False)
    canvas_obj.setFillColor(white)
    canvas_obj.setFont('Helvetica-Bold', 9)
    canvas_obj.drawString(2*cm, H - 20, "DealSpotter  |  Project Briefing")
    canvas_obj.setFont('Helvetica', 8)
    date_str = REPORT_DATE_SHORT or "Mar 15, 2026"
    canvas_obj.drawRightString(W - 2*cm, H - 20, date_str)
    # Footer
    canvas_obj.setFillColor(HexColor("#dee2e6"))
    canvas_obj.rect(2*cm, 1.5*cm, W - 4*cm, 0.5, fill=True, stroke=False)
    canvas_obj.setFillColor(TEXT_MUTED)
    canvas_obj.setFont('Helvetica', 8)
    canvas_obj.drawString(2*cm, 1*cm, "Confidential")
    canvas_obj.drawRightString(W - 2*cm, 1*cm, f"Page {doc.page}")
    canvas_obj.restoreState()

# ── Build Document ──

def build():
    global REPORT_DATE_LONG, REPORT_DATE_SHORT
    now = datetime.now()
    REPORT_DATE_LONG = now.strftime("%B %d, %Y")
    REPORT_DATE_SHORT = now.strftime("%b %d, %Y")

    metrics = load_metrics()
    stats = metrics["stats"]
    searches = [parse_search_url(u) for u in config.SEARCH_URLS]

    doc = SimpleDocTemplate(
        "/Users/corentinesteve/Downloads/DealSpotter/BRIEFING.pdf",
        pagesize=A4,
        topMargin=3*cm,
        bottomMargin=2.5*cm,
        leftMargin=2*cm,
        rightMargin=2*cm,
    )

    story = []

    # ═══════════════════════════════════════
    # COVER PAGE
    # ═══════════════════════════════════════
    story.append(Spacer(1, 200))

    # Key stats on cover
    kpi_data = [
        [
            Paragraph(f"<b>{metrics['total']}</b>", ParagraphStyle('kpi', fontName='Helvetica-Bold', fontSize=24, textColor=ACCENT, alignment=TA_CENTER)),
            Paragraph(f"<b>{metrics['evaluated_total']}</b>", ParagraphStyle('kpi2', fontName='Helvetica-Bold', fontSize=24, textColor=SUCCESS, alignment=TA_CENTER)),
            Paragraph(f"<b>{stats.get('margin_positive', 0)}</b>", ParagraphStyle('kpi3', fontName='Helvetica-Bold', fontSize=24, textColor=INFO_BLUE, alignment=TA_CENTER)),
            Paragraph(f"<b>+{int(stats.get('margin_best', 0))}€</b>", ParagraphStyle('kpi4', fontName='Helvetica-Bold', fontSize=24, textColor=TEXT_DARK, alignment=TA_CENTER)),
        ],
        [
            Paragraph('Listings<br/>Processed', ParagraphStyle('kpilbl', fontName='Helvetica', fontSize=8, textColor=TEXT_MUTED, alignment=TA_CENTER)),
            Paragraph('AI Evaluated<br/>(incl. alerts)', ParagraphStyle('kpilbl2', fontName='Helvetica', fontSize=8, textColor=TEXT_MUTED, alignment=TA_CENTER)),
            Paragraph('Positive<br/>Margins', ParagraphStyle('kpilbl3', fontName='Helvetica', fontSize=8, textColor=TEXT_MUTED, alignment=TA_CENTER)),
            Paragraph('Best<br/>Margin', ParagraphStyle('kpilbl4', fontName='Helvetica', fontSize=8, textColor=TEXT_MUTED, alignment=TA_CENTER)),
        ],
    ]
    kpi_table = Table(kpi_data, colWidths=[3.8*cm]*4)
    kpi_table.setStyle(TableStyle([
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,0), 12),
        ('BOTTOMPADDING', (0,0), (-1,0), 4),
        ('TOPPADDING', (0,1), (-1,1), 0),
        ('BOTTOMPADDING', (0,1), (-1,1), 12),
        ('BOX', (0,0), (-1,-1), 0.5, HexColor("#dee2e6")),
        ('LINEBELOW', (0,0), (-1,0), 0, white),
        ('BACKGROUND', (0,0), (-1,-1), white),
        ('ROUNDEDCORNERS', [4,4,4,4]),
    ]))
    story.append(kpi_table)

    story.append(PageBreak())

    # ═══════════════════════════════════════
    # TABLE OF CONTENTS
    # ═══════════════════════════════════════
    story.append(Spacer(1, 10))
    story.append(Paragraph("Contents", styles['SectionTitle']))
    story.append(section_line())
    toc_items = [
        ("1", "What DealSpotter Does"),
        ("2", "Current Status"),
        ("3", "How the Pipeline Works"),
        ("4", "Current Search Configuration"),
        ("5", "Key Insights from the Data"),
        ("6", "Recommendations"),
        ("7", "Risks & Limitations"),
        ("8", "Cost Projections"),
        ("9", "How to Operate"),
    ]
    for num, title in toc_items:
        story.append(Paragraph(
            f'<font color="{ACCENT.hexval()}"><b>{num}.</b></font>  {title}',
            ParagraphStyle('toc', fontName='Helvetica', fontSize=12, textColor=DARK_BG, spaceAfter=8, leading=16, leftIndent=10)
        ))
    story.append(Spacer(1, 20))

    # ═══════════════════════════════════════
    # 1. WHAT DEALSPOTTER DOES
    # ═══════════════════════════════════════
    story.append(section_title("What DealSpotter Does", "1"))
    story.append(section_line())
    story.append(body(
        "DealSpotter monitors <b>leboncoin.fr</b> (France's largest classifieds platform) for "
        "undervalued road bikes. It runs autonomously and sends you a Telegram alert only when "
        "there's an actionable opportunity."
    ))
    story.append(Spacer(1, 6))
    story.append(body_bold("The pipeline:"))
    story.append(numbered(1, "Scrapes search results every <b>5 minutes</b> (~105 listings per run)"))
    story.append(numbered(2, "Filters out junk (kids bikes, electric, broken, pro sellers, wrong prices)"))
    story.append(numbered(3, "Fetches full listing details for promising candidates"))
    story.append(numbered(4, "Uses <b>Claude AI</b> to identify the bike (brand, model, condition) and estimate resale value"))
    story.append(numbered(5, "Calculates net flip margin (buy + 8% fee + transport + time vs. resale)"))
    story.append(numbered(6, f'Sends a <b>Telegram alert</b> when expected profit <font color="#28a745"><b>&ge; {config.MIN_FLIP_MARGIN_EUR}</b></font>'))
    story.append(Spacer(1, 10))

    story.append(callout_box(
        None,
        [Paragraph(
            'You get a Telegram notification <b>only when there\'s money to be made</b>. '
            'Everything else is handled automatically.',
            styles['CalloutText']
        )],
        border_color=SUCCESS
    ))

    story.append(PageBreak())

    # ═══════════════════════════════════════
    # 2. CURRENT STATUS
    # ═══════════════════════════════════════
    story.append(section_title("Current Status", "2"))
    story.append(section_line())
    story.append(Paragraph("Pipeline Numbers (as of today)", styles['SubSection']))

    total = metrics["total"]
    status_data = [
        ["Total listings processed", str(total), ""],
        ["Listings in last 24h", str(metrics["last_24h"]), ""],
        ["Pre-filtered (price/keyword/pro)", str(metrics["prefiltered"]), pct(metrics["prefiltered"] / total) if total else "—"],
        ["Skipped (scrape/eval failures)", str(metrics["skipped_other"]), pct(metrics["skipped_other"] / total) if total else "—"],
        ["AI evaluated (incl. alerts)", str(metrics["evaluated_total"]), pct(metrics["evaluated_total"] / total) if total else "—"],
        ["Alerts sent", str(metrics["alerted"]), pct(metrics["alert_rate"])],
        ["Positive margins", str(stats.get("margin_positive", 0)), pct(metrics["positive_rate"])],
        ["Average margin", euro(stats.get("margin_avg", 0)), ""],
        ["User feedback", f"{stats.get('good_feedback', 0)} good / {stats.get('bad_feedback', 0)} bad", "Needs labels"],
    ]
    story.append(make_table(
        ["Metric", "Count", "Rate"],
        status_data,
        col_widths=[8*cm, 3*cm, 4*cm]
    ))

    story.append(Spacer(1, 12))
    story.append(Paragraph("AI Usage", styles['SubSection']))
    tier1 = metrics["tier_counts"].get(1, 0)
    tier2 = metrics["tier_counts"].get(2, 0)
    story.append(bullet(f"Tier 1 (text-only) evaluations: <b>{tier1}</b>"))
    story.append(bullet(f"Tier 2 (vision) evaluations: <b>{tier2}</b>"))
    story.append(bullet("Costs are not tracked yet — add logging to estimate monthly API spend."))
    story.append(Spacer(1, 12))

    story.append(Paragraph("Top Opportunities (by predicted margin)", styles['SubSection']))
    alerts_data = []
    for row in metrics["top_listings"]:
        margin = f"{int(row['flip_margin'])}€" if row.get("flip_margin") is not None else "—"
        price = f"{int(row['price'])}€" if row.get("price") is not None else "—"
        brand = row.get("ai_brand") or "—"
        status = row.get("status") or "—"
        title = row.get("title") or "—"
        alerts_data.append([margin, price, brand, status, title])

    if not alerts_data:
        alerts_data = [["—", "—", "—", "—", "No evaluated listings yet"]]

    story.append(make_table(
        ["Margin", "Buy Price", "Brand", "Status", "Listing"],
        alerts_data,
        col_widths=[2.0*cm, 2.2*cm, 2.5*cm, 2.3*cm, 6.7*cm]
    ))

    story.append(PageBreak())

    # ═══════════════════════════════════════
    # 3. HOW THE PIPELINE WORKS
    # ═══════════════════════════════════════
    story.append(section_title("How the Pipeline Works", "3"))
    story.append(section_line())

    pipeline_text = f"""Search URLs (leboncoin)
       |
       v
  Scrape Search -------- JSON API + pagination (35/page x 3 pages)
       |                 Auto-retry with cookie refresh on block
       | ~105 listings
       v
  Dedup ---------------- SQLite: skip already-seen listings
       | new only
       v
  Pre-Filter ----------- FREE: price range, keywords, seller type
       |                 (removes ~53% of junk)
       v
  Fetch Full Listing --- Get description + photos from listing page
       |                 curl_cffi + __NEXT_DATA__
       v
  AI Evaluation -------- Tier 1: Claude Haiku (text, ~$0.001)
       |                 Tier 2: Claude Sonnet + photos (~$0.01)
       |                 Identifies brand, model, condition, resale
       v
  Flip Calculator ------ margin = resale - (buy + {int(config.PLATFORM_FEE_PERCENT * 100)}% fee + {config.TRANSPORT_COST_EUR} transport + {config.TIME_COST_EUR} time)
       |
       v
  Alert? --------------- If margin >= {config.MIN_FLIP_MARGIN_EUR} --> Telegram notification
                         With: buy price, resale estimate, ROI, reasoning"""

    for line in pipeline_text.split('\n'):
        story.append(Paragraph(line.replace(' ', '&nbsp;').replace('<', '&lt;').replace('>', '&gt;'), styles['PipelineCode']))

    story.append(Spacer(1, 14))
    story.append(Paragraph("Tech Stack", styles['SubSection']))
    tech_data = [
        ["Scraping", "Python + curl_cffi (TLS fingerprint impersonation)"],
        ["API", "leboncoin JSON API (POST api.leboncoin.fr/finder/search)"],
        ["AI", "Claude Haiku (text) / Sonnet (vision)"],
        ["Database", "SQLite (dedup + tracking)"],
        ["Alerts", "python-telegram-bot (notifications + commands)"],
        ["Scheduling", "schedule library (polling every 5 min)"],
    ]
    story.append(make_table(
        ["Component", "Technology"],
        tech_data,
        col_widths=[3.5*cm, 11.7*cm]
    ))

    story.append(PageBreak())

    # ═══════════════════════════════════════
    # 4. SEARCH CONFIGURATION
    # ═══════════════════════════════════════
    story.append(section_title("Current Search Configuration", "4"))
    story.append(section_line())

    search_rows = []
    for idx, s in enumerate(searches, 1):
        search_rows.append([
            f"Search {idx}",
            s["text"],
            s["price"],
            s["owner_type"],
            s["locations"],
            s["sort"],
        ])
    if not search_rows:
        search_rows = [["—", "—", "—", "—", "—", "—"]]

    story.append(make_table(
        ["Search", "Keywords", "Price", "Owner", "Location", "Sort"],
        search_rows,
        col_widths=[2.1*cm, 4.1*cm, 2.2*cm, 2.1*cm, 3.3*cm, 2.4*cm]
    ))
    story.append(Spacer(1, 10))
    story.append(bullet(f"Pages per run: <b>{config.MAX_SEARCH_PAGES}</b> (~{config.MAX_SEARCH_PAGES * 35} listings max)"))
    story.append(bullet(f"Poll interval: <b>{int(config.POLL_INTERVAL_SECONDS/60)} minutes</b>"))
    story.append(bullet(f"Distance cap configured: <b>{config.MAX_DISTANCE_KM} km</b> (not enforced in code yet)"))

    story.append(Spacer(1, 12))
    story.append(Paragraph("Pre-filter Keywords (auto-skip)", styles['SubSection']))
    skip_kw = ", ".join(config.SKIP_KEYWORDS)
    junk_kw = ", ".join(config.JUNK_INDICATORS)
    story.append(body(
        f'<font color="#dc3545"><i>{skip_kw}</i></font>'
    ))
    story.append(Spacer(1, 4))
    story.append(body(
        f'<font color="#dc3545"><i>Junk indicators: {junk_kw}</i></font>'
    ))

    # ═══════════════════════════════════════
    # 5. KEY INSIGHTS
    # ═══════════════════════════════════════
    story.append(Spacer(1, 10))
    story.append(section_title("Key Insights from the Data", "5"))
    story.append(section_line())

    story.append(Paragraph("Signal Summary", styles['SubSection']))
    price_buckets = metrics["price_buckets"]
    best_bucket = max(price_buckets, key=lambda x: x["avg_margin"]) if price_buckets else None
    worst_bucket = min(price_buckets, key=lambda x: x["avg_margin"]) if price_buckets else None

    story.append(bullet(
        f"Overall average margin is <b>{euro(stats.get('margin_avg', 0))}</b> "
        f"with a positive-margin rate of <b>{pct(metrics['positive_rate'])}</b>."
    ))
    if best_bucket:
        story.append(bullet(
            f"Best price band: <b>{best_bucket['bucket']}€</b> "
            f"(avg margin {euro(best_bucket['avg_margin'], 1)} across {best_bucket['c']} listings)."
        ))
    if worst_bucket:
        story.append(bullet(
            f"Worst price band: <b>{worst_bucket['bucket']}€</b> "
            f"(avg margin {euro(worst_bucket['avg_margin'], 1)} across {worst_bucket['c']} listings)."
        ))
    story.append(bullet(
        f"Alerts sent: <b>{metrics['alerted']}</b> "
        f"(alert rate {pct(metrics['alert_rate'])})."
    ))

    story.append(Spacer(1, 10))
    story.append(Paragraph("Brand Performance (min 2 listings)", styles['SubSection']))
    brand_data = []
    top_brands = metrics["brand_stats"][:3]
    bottom_brands = metrics["brand_stats"][-3:] if len(metrics["brand_stats"]) >= 3 else []

    for row in top_brands:
        brand_data.append([row["ai_brand"], str(row["c"]), euro(row["avg_margin"], 1), "Positive signal"])
    for row in bottom_brands:
        brand_data.append([row["ai_brand"], str(row["c"]), euro(row["avg_margin"], 1), "Negative signal"])

    if not brand_data:
        brand_data = [["—", "—", "—", "No brand signal yet"]]

    story.append(make_table(
        ["Brand", "Count", "Avg Margin", "Signal"],
        brand_data,
        col_widths=[4*cm, 2*cm, 2.5*cm, 6.7*cm]
    ))

    story.append(PageBreak())

    # ═══════════════════════════════════════
    # 6. RECOMMENDATIONS
    # ═══════════════════════════════════════
    story.append(section_title("Recommendations", "6"))
    story.append(section_line())

    # Immediate
    story.append(callout_box(
        "IMMEDIATE (this week)",
        [
            Paragraph('<b>A. Tighten location</b>', styles['CalloutText']),
            Paragraph('Current search has no location filter. Add a Paris/Sartrouville radius in the URL and/or enforce <b>MAX_DISTANCE_KM</b> in code.', styles['CalloutText']),
            Spacer(1, 6),
            Paragraph('<b>B. Split searches by intent</b>', styles['CalloutText']),
            Paragraph('Create separate URLs for "velo route", "velo course", "cadre velo", and "velo carbone". This reduces noise and makes tuning easier.', styles['CalloutText']),
            Spacer(1, 6),
            Paragraph('<b>C. Use feedback buttons</b>', styles['CalloutText']),
            Paragraph('Every alert should get a "good/bad" label. We need 20+ labels to tune prompts and filters.', styles['CalloutText']),
        ],
        border_color=ACCENT
    ))
    story.append(Spacer(1, 10))

    # Short-term
    story.append(callout_box(
        "SHORT-TERM (next 2 weeks)",
        [
            Paragraph('<b>D. Add negative brand filter</b>', styles['CalloutText']),
            Paragraph('Auto-skip Decathlon/B\'Twin/Rockrider/Nakamura based on current margin data.', styles['CalloutText']),
            Spacer(1, 6),
            Paragraph('<b>E. Fix alert delivery</b>', styles['CalloutText']),
            Paragraph('Queued alerts during quiet hours are only sent on restart. Add a scheduled flush after quiet hours.', styles['CalloutText']),
            Spacer(1, 6),
            Paragraph('<b>F. Improve pre-filter quality</b>', styles['CalloutText']),
            Paragraph('Detect "frames only" vs full bikes, and require key attributes (size, group) before AI evaluation.', styles['CalloutText']),
        ],
        border_color=INFO_BLUE
    ))
    story.append(Spacer(1, 10))

    # Medium-term
    story.append(callout_box(
        "MEDIUM-TERM (next month)",
        [
            Paragraph('<b>G. Implement distance scoring</b>', styles['CalloutText']),
            Paragraph('Use location coordinates from the API to compute distance from your base and down-rank far listings.', styles['CalloutText']),
            Spacer(1, 6),
            Paragraph('<b>H. Calibrate predictions</b>', styles['CalloutText']),
            Paragraph('Track actual buy/sell results to calibrate AI estimates and adjust margin thresholds.', styles['CalloutText']),
            Spacer(1, 6),
            Paragraph('<b>I. Expand scope carefully</b>', styles['CalloutText']),
            Paragraph('Only expand to VTT/parts once road-bike searches are consistently profitable.', styles['CalloutText']),
        ],
        border_color=SUCCESS
    ))

    story.append(PageBreak())

    # ═══════════════════════════════════════
    # 7. RISKS
    # ═══════════════════════════════════════
    story.append(section_title("Risks & Limitations", "7"))
    story.append(section_line())

    risk_data = [
        ['Search noise / low margin', 'High', 'Average margin is negative; tighten search + filters.'],
        ['Location filter missing', 'Medium', 'No radius in search URL; MAX_DISTANCE_KM not enforced.'],
        ['Quiet-hours alerts delayed', 'Medium', 'Queued alerts only send on restart; add scheduled flush.'],
        ['Config mismatch', 'Low', 'README says min margin 80€, config uses 50€ — align docs.'],
        ['DataDome blocks scraping', 'Medium', 'JSON API + cookie refresh works now, but can fail.'],
        ['leboncoin changes API', 'Medium', 'Fallback HTML exists; still fragile.'],
    ]
    story.append(make_table(
        ["Risk", "Severity", "Mitigation"],
        risk_data,
        col_widths=[4.5*cm, 2*cm, 8.7*cm]
    ))

    story.append(Spacer(1, 20))

    # ═══════════════════════════════════════
    # 8. COST PROJECTIONS
    # ═══════════════════════════════════════
    story.append(section_title("Operating Snapshot", "8"))
    story.append(section_line())

    eval_total = metrics["evaluated_total"]
    tier1 = metrics["tier_counts"].get(1, 0)
    tier2 = metrics["tier_counts"].get(2, 0)
    vision_share = (tier2 / (tier1 + tier2)) if (tier1 + tier2) else 0

    snapshot_data = [
        ["Listings processed (total)", str(metrics["total"]), ""],
        ["Listings in last 24h", str(metrics["last_24h"]), ""],
        ["Evaluations (total)", str(eval_total), ""],
        ["Vision share", pct(vision_share), f"{tier2} of {tier1 + tier2} evals"],
        ["Alert rate", pct(metrics["alert_rate"]), f"{metrics['alerted']} alerts"],
        ["Positive margin rate", pct(metrics["positive_rate"]), f"{stats.get('margin_positive', 0)} positive"],
        ["Max alerts/day", "unlimited", ""],
    ]
    story.append(make_table(
        ["Metric", "Value", "Notes"],
        snapshot_data,
        col_widths=[6*cm, 3*cm, 6.2*cm]
    ))

    story.append(Spacer(1, 12))
    story.append(callout_box(
        None,
        [Paragraph(
            'Once search quality improves, the main constraint will be <b>your time reviewing alerts</b>, not infra cost.',
            styles['CalloutText']
        )],
        border_color=SUCCESS
    ))

    story.append(PageBreak())

    # ═══════════════════════════════════════
    # 9. HOW TO OPERATE
    # ═══════════════════════════════════════
    story.append(section_title("How to Operate", "9"))
    story.append(section_line())

    story.append(Paragraph("Daily", styles['SubSection']))
    story.append(bullet('Check Telegram alerts &mdash; tap <b>"Intéressé"</b> or <b>"Passer"</b> on each'))
    story.append(bullet('Use <b>/stats</b> for a quick performance overview'))
    story.append(Spacer(1, 8))

    story.append(Paragraph("When Cookies Expire (rare)", styles['SubSection']))
    story.append(bullet('Browse leboncoin.fr in Chrome, then close Chrome'))
    story.append(Paragraph(
        '&nbsp;&nbsp;&nbsp;&nbsp;<font face="Courier" size="8">'
        'python -c "from scraper import export_chrome_cookies; export_chrome_cookies()"'
        '</font>',
        styles['BodyText2']
    ))
    story.append(Spacer(1, 8))

    story.append(Paragraph("To Add Search URLs", styles['SubSection']))
    story.append(bullet('Edit <b>.env</b>, add comma-separated URLs to <b>SEARCH_URLS</b>'))
    story.append(bullet('Restart: <font face="Courier" size="9">python main.py</font>'))
    story.append(Spacer(1, 8))

    story.append(Paragraph("To Adjust Sensitivity", styles['SubSection']))
    story.append(bullet('Edit <b>config.py</b>: <font face="Courier" size="9">MIN_FLIP_MARGIN_EUR</font> (currently 50)'))
    story.append(bullet('Lower = more alerts, more noise. Higher = fewer but higher quality.'))

    story.append(Spacer(1, 40))
    story.append(HRFlowable(width="100%", thickness=1, color=ACCENT, spaceAfter=10))
    story.append(Paragraph(
        '<i>End of briefing. Questions? Check /stats on Telegram or review the codebase.</i>',
        ParagraphStyle('footer_note', fontName='Helvetica-Oblique', fontSize=9, textColor=TEXT_MUTED, alignment=TA_CENTER)
    ))

    # Build with page templates
    doc.build(
        story,
        onFirstPage=cover_page,
        onLaterPages=normal_page,
    )
    print("PDF generated: /Users/corentinesteve/Downloads/DealSpotter/BRIEFING.pdf")

if __name__ == "__main__":
    build()
