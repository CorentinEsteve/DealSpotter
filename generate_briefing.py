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
        "SELECT lbc_id, title, price, flip_margin, ai_brand, status, category "
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
        "ELSE '500+' END AS bucket, "
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

    # Per-category stats
    cat_rows = conn.execute(
        "SELECT category, COUNT(*) total, "
        "SUM(CASE WHEN status IN ('evaluated', 'alerted', 'interested') THEN 1 ELSE 0 END) evaluated, "
        "SUM(CASE WHEN status = 'alerted' OR status = 'interested' THEN 1 ELSE 0 END) alerted "
        "FROM listings GROUP BY category"
    ).fetchall()
    category_stats = {row["category"]: dict(row) for row in cat_rows}

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
        "category_stats": category_stats,
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
    date_str = REPORT_DATE_LONG or "March 16, 2026"
    canvas_obj.drawString(2*cm, H - 222, f"CTO Report  |  {date_str}")
    # Footer line
    canvas_obj.setFillColor(TEXT_MUTED)
    canvas_obj.setFont('Helvetica', 8)
    canvas_obj.drawString(2*cm, 2*cm, "Confidential  |  DealSpotter v2.0")
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
    date_str = REPORT_DATE_SHORT or "Mar 16, 2026"
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

    # Key stats on cover — use separate rows with explicit spacing to avoid overlap
    kpi_number_style = lambda name, color: ParagraphStyle(
        name, fontName='Helvetica-Bold', fontSize=28,
        textColor=color, alignment=TA_CENTER, leading=32,
    )
    kpi_label_style = lambda name: ParagraphStyle(
        name, fontName='Helvetica', fontSize=9,
        textColor=TEXT_MUTED, alignment=TA_CENTER, leading=12,
    )

    kpi_data = [
        [
            Paragraph(f"<b>{metrics['total']}</b>", kpi_number_style('kpi_n1', ACCENT)),
            Paragraph(f"<b>{metrics['evaluated_total']}</b>", kpi_number_style('kpi_n2', SUCCESS)),
            Paragraph(f"<b>{stats.get('margin_positive', 0)}</b>", kpi_number_style('kpi_n3', INFO_BLUE)),
            Paragraph(f"<b>+{int(stats.get('margin_best', 0))}€</b>", kpi_number_style('kpi_n4', TEXT_DARK)),
        ],
        [
            Paragraph('Listings<br/>Processed', kpi_label_style('kpi_l1')),
            Paragraph('AI Evaluated<br/>(incl. alerts)', kpi_label_style('kpi_l2')),
            Paragraph('Positive<br/>Margins', kpi_label_style('kpi_l3')),
            Paragraph('Best<br/>Margin', kpi_label_style('kpi_l4')),
        ],
    ]
    kpi_table = Table(kpi_data, colWidths=[3.8*cm]*4, rowHeights=[44, 28])
    kpi_table.setStyle(TableStyle([
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,0), 'BOTTOM'),
        ('VALIGN', (0,1), (-1,1), 'TOP'),
        ('TOPPADDING', (0,0), (-1,0), 10),
        ('BOTTOMPADDING', (0,0), (-1,0), 2),
        ('TOPPADDING', (0,1), (-1,1), 2),
        ('BOTTOMPADDING', (0,1), (-1,1), 10),
        ('BOX', (0,0), (-1,-1), 0.5, HexColor("#dee2e6")),
        ('BACKGROUND', (0,0), (-1,-1), white),
        ('ROUNDEDCORNERS', [4,4,4,4]),
    ]))
    story.append(kpi_table)

    # Active categories badge
    cat_labels = " + ".join(config.CATEGORIES[c]["label"] for c in config.ACTIVE_CATEGORIES)
    story.append(Spacer(1, 12))
    story.append(Paragraph(
        f'<font color="{TEXT_MUTED.hexval()}" size="9">Active categories: {cat_labels}</font>',
        ParagraphStyle('cat_badge', alignment=TA_CENTER)
    ))

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
        ("4", "Scraping: How It Works and Why"),
        ("5", "Search Configuration"),
        ("6", "Key Insights from the Data"),
        ("7", "Recommendations"),
        ("8", "Risks & Limitations"),
        ("9", "Operating Snapshot"),
        ("10", "How to Operate"),
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
        "undervalued items across multiple categories. It runs autonomously and sends Telegram alerts "
        "only when there's an actionable flip opportunity."
    ))
    story.append(Spacer(1, 6))

    # Active categories
    story.append(Paragraph("Active Categories", styles['SubSection']))
    for cat_key in config.ACTIVE_CATEGORIES:
        cat = config.CATEGORIES[cat_key]
        n_queries = len(cat.get("search_queries", []))
        price_range = f"{cat['min_price']}-{cat['max_price']}€"
        min_margin = cat["min_flip_margin"]
        story.append(bullet(
            f"<b>{cat['label']}</b> — {n_queries} search queries, price range {price_range}, "
            f"min margin {min_margin}€"
        ))
    story.append(Spacer(1, 8))

    story.append(body_bold("The pipeline:"))
    story.append(numbered(1, f"<b>Preflight checks</b> — tests LBC API and Anthropic API before starting"))
    story.append(numbered(2, f"Scrapes search results every <b>{int(config.POLL_INTERVAL_SECONDS/60)} minutes</b> via the leboncoin JSON API"))
    story.append(numbered(3, "Filters out junk (wrong prices, keywords, pro sellers) — free, no API cost"))
    story.append(numbered(4, "Uses <b>Claude AI</b> to identify items and estimate resale value (2-tier system)"))
    story.append(numbered(5, "Calculates net flip margin (buy + 8% fee + transport + time vs. resale)"))
    story.append(numbered(6, "Sends a <b>Telegram alert</b> with buy/sell analysis when margin threshold is met"))
    story.append(Spacer(1, 6))

    # Separate Telegram bots
    story.append(callout_box(
        None,
        [Paragraph(
            'Each category has its own <b>dedicated Telegram bot</b>. '
            'You receive alerts in separate chats and can run categories independently.',
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
        ["User feedback", f"{stats.get('good_feedback', 0)} good / {stats.get('bad_feedback', 0)} bad", ""],
    ]
    story.append(make_table(
        ["Metric", "Count", "Rate"],
        status_data,
        col_widths=[8*cm, 3*cm, 4*cm]
    ))

    # Per-category breakdown
    if metrics.get("category_stats"):
        story.append(Spacer(1, 10))
        story.append(Paragraph("Per-Category Breakdown", styles['SubSection']))
        cat_rows = []
        for cat_key in config.ACTIVE_CATEGORIES:
            cs = metrics["category_stats"].get(cat_key, {})
            label = config.CATEGORIES.get(cat_key, {}).get("label", cat_key)
            cat_rows.append([
                label,
                str(cs.get("total", 0)),
                str(cs.get("evaluated", 0)),
                str(cs.get("alerted", 0)),
            ])
        story.append(make_table(
            ["Category", "Total", "Evaluated", "Alerted"],
            cat_rows,
            col_widths=[5*cm, 3*cm, 3.5*cm, 3.7*cm]
        ))

    story.append(Spacer(1, 12))
    story.append(Paragraph("AI Usage", styles['SubSection']))
    tier1 = metrics["tier_counts"].get(1, 0)
    tier2 = metrics["tier_counts"].get(2, 0)
    story.append(bullet(f"Tier 1 (Claude Haiku, text-only) evaluations: <b>{tier1}</b> — ~$0.001/eval"))
    story.append(bullet(f"Tier 2 (Claude Sonnet + 2 photos) evaluations: <b>{tier2}</b> — ~$0.01/eval"))
    story.append(bullet(
        "Smart escalation: Haiku evaluates first. "
        "Only escalates to Sonnet+vision when the listing looks promising or uncertain."
    ))
    story.append(Spacer(1, 12))

    story.append(Paragraph("Top Opportunities (by predicted margin)", styles['SubSection']))
    alerts_data = []
    for row in metrics["top_listings"]:
        margin = f"{int(row['flip_margin'])}€" if row.get("flip_margin") is not None else "—"
        price = f"{int(row['price'])}€" if row.get("price") is not None else "—"
        brand = row.get("ai_brand") or "—"
        cat = row.get("category") or "—"
        title = row.get("title") or "—"
        alerts_data.append([margin, price, brand, cat, title])

    if not alerts_data:
        alerts_data = [["—", "—", "—", "—", "No evaluated listings yet"]]

    story.append(make_table(
        ["Margin", "Buy", "Brand", "Category", "Listing"],
        alerts_data,
        col_widths=[2.0*cm, 1.8*cm, 2.5*cm, 2.3*cm, 7.1*cm]
    ))

    story.append(PageBreak())

    # ═══════════════════════════════════════
    # 3. HOW THE PIPELINE WORKS
    # ═══════════════════════════════════════
    story.append(section_title("How the Pipeline Works", "3"))
    story.append(section_line())

    bikes_cfg = config.CATEGORIES["bikes"]
    pipeline_text = f"""Preflight Checks ---- Test LBC API + Anthropic API (fail fast)
       |
       v
  Search API --------- POST api.leboncoin.fr/finder/search
       |                35 listings/page x {config.MAX_SEARCH_PAGES} pages per query
       |                Early abort if first query blocked
       v
  Dedup -------------- SQLite: skip already-seen listings
       | new only
       v
  Pre-Filter --------- FREE: price range, keywords, seller type
       |                No API cost (removes ~50% of junk)
       v
  AI Evaluation ------ Tier 1: Claude Haiku (text-only, ~$0.001)
       |                Tier 2: Claude Sonnet + 2 photos (~$0.01)
       |                Smart escalation: skip Tier 2 if Haiku says "not worth it"
       v
  Flip Calculator ---- margin = resale - (buy + 8% fee + transport + time)
       |
       v
  Alert? ------------- If margin >= threshold --> Telegram notification
       |                With: price, resale estimate, ROI, AI reasoning
       v
  Pending Retry ------ Re-evaluate DB listings from previous failed runs"""

    for line in pipeline_text.split('\n'):
        story.append(Paragraph(line.replace(' ', '&nbsp;').replace('<', '&lt;').replace('>', '&gt;'), styles['PipelineCode']))

    story.append(Spacer(1, 14))
    story.append(Paragraph("Tech Stack", styles['SubSection']))
    tech_data = [
        ["Scraping", "Python + curl_cffi (Chrome TLS fingerprint impersonation)"],
        ["API", "leboncoin JSON API (POST api.leboncoin.fr/finder/search)"],
        ["AI", "Claude Haiku (text) + Sonnet (vision) — smart 2-tier routing"],
        ["Database", "SQLite (dedup, tracking, per-category stats)"],
        ["Alerts", "python-telegram-bot (per-category bots + /stats command)"],
        ["Scheduling", f"schedule library (polling every {int(config.POLL_INTERVAL_SECONDS/60)} min)"],
        ["CLI", "argparse — python main.py --category bikes|furniture|all"],
    ]
    story.append(make_table(
        ["Component", "Technology"],
        tech_data,
        col_widths=[3.5*cm, 11.7*cm]
    ))

    story.append(PageBreak())

    # ═══════════════════════════════════════
    # 4. SCRAPING: HOW IT WORKS AND WHY
    # ═══════════════════════════════════════
    story.append(section_title("Scraping: How It Works and Why", "4"))
    story.append(section_line())

    story.append(body(
        "Leboncoin is protected by <b>DataDome</b>, an anti-bot system that blocks automated requests. "
        "DealSpotter uses a multi-layered approach to access listing data reliably."
    ))
    story.append(Spacer(1, 8))

    story.append(Paragraph("The JSON Search API", styles['SubSection']))
    story.append(body(
        "Instead of scraping HTML pages, DealSpotter uses leboncoin's internal <b>JSON search API</b> "
        "(<font face='Courier' size='8'>POST api.leboncoin.fr/finder/search</font>). "
        "This is the same API the website's frontend calls when you search."
    ))
    story.append(bullet("Returns <b>structured JSON</b>: title, price, full description, all photo URLs, location, seller info"))
    story.append(bullet("Up to <b>35 listings per page</b>, paginated (we fetch up to 3 pages per query)"))
    story.append(bullet("Descriptions from the API are typically <b>500-1200+ characters</b> — usually enough for AI evaluation without fetching individual listing pages"))
    story.append(Spacer(1, 8))

    story.append(Paragraph("Why It Works", styles['SubSection']))
    story.append(body(
        "The JSON API endpoint uses <b>different anti-bot rules</b> than the HTML pages:"
    ))
    story.append(bullet("<b>curl_cffi</b> with Chrome TLS fingerprint — the request looks identical to a real Chrome browser at the TLS level"))
    story.append(bullet("<b>DataDome cookies</b> from a real Chrome session — auto-refreshed from the local Chrome browser when expired"))
    story.append(bullet("Proper <b>Origin/Referer/API-key headers</b> — mimics the exact request the leboncoin frontend makes"))
    story.append(bullet("Polite <b>rate limiting</b> — 2-5 second delays between requests, respecting the site"))
    story.append(Spacer(1, 8))

    story.append(Paragraph("Resilience Mechanisms", styles['SubSection']))
    story.append(bullet("<b>Preflight check</b>: tests the API with a single request before starting the full pipeline"))
    story.append(bullet("<b>Early abort</b>: if the first query is blocked (403), remaining queries are skipped immediately instead of retrying each one"))
    story.append(bullet("<b>Cookie auto-refresh</b>: on a 403 block, cookies are automatically re-read from Chrome and the request is retried"))
    story.append(bullet("<b>HTML fallback</b>: if the JSON API fails, attempts to scrape the HTML search page via __NEXT_DATA__ JSON blob"))
    story.append(bullet("<b>API-first evaluation</b>: since the search API returns full descriptions + photos, individual listing pages are <b>rarely needed</b> (only when API description is &lt; 50 chars)"))
    story.append(Spacer(1, 8))

    story.append(callout_box(
        "Key insight",
        [Paragraph(
            'DataDome heavily blocks individual listing page requests (HTML), but the search API '
            'is less restrictive. By using the search API data directly for AI evaluation, '
            'we avoid the most common blocking scenario entirely.',
            styles['CalloutText']
        )],
        border_color=INFO_BLUE
    ))

    story.append(PageBreak())

    # ═══════════════════════════════════════
    # 5. SEARCH CONFIGURATION
    # ═══════════════════════════════════════
    story.append(section_title("Search Configuration", "5"))
    story.append(section_line())

    for cat_key in config.ACTIVE_CATEGORIES:
        cat = config.CATEGORIES[cat_key]
        story.append(Paragraph(f"{cat['label']}", styles['SubSection']))

        # Search queries table
        query_rows = []
        for q in cat.get("search_queries", []):
            query_rows.append([q["text"], q.get("tier", "A")])
        if query_rows:
            story.append(make_table(
                ["Search Query", "Tier"],
                query_rows,
                col_widths=[10*cm, 5.2*cm]
            ))

        # Config summary
        base = cat["search_base"]
        story.append(Spacer(1, 4))
        story.append(bullet(f"Price range: <b>{cat['min_price']}-{cat['max_price']}€</b>"))
        story.append(bullet(f"Min flip margin: <b>{cat['min_flip_margin']}€</b>"))
        story.append(bullet(f"Costs: {int(cat['platform_fee_pct']*100)}% platform fee + {cat['transport_cost']}€ transport + {cat['time_cost']}€ time"))
        story.append(bullet(f"Location: Sartrouville area, {cat.get('max_distance_km', 40)}km radius"))

        # Query rotation
        qpc = cat.get("queries_per_cycle", {})
        tier_info = []
        for tier, n in sorted(qpc.items()):
            if n is None:
                tier_info.append(f"Tier {tier}: all every cycle")
            else:
                tier_info.append(f"Tier {tier}: rotate {n}")
        if tier_info:
            story.append(bullet(f"Rotation: {', '.join(tier_info)}"))

        story.append(Spacer(1, 8))

        # Skip keywords
        skip_kw = ", ".join(cat.get("skip_keywords", []))
        if skip_kw:
            story.append(body(f'<font color="#dc3545" size="8"><i>Auto-skip: {skip_kw}</i></font>'))
        story.append(Spacer(1, 10))

    story.append(bullet(f"Pages per query: <b>{config.MAX_SEARCH_PAGES}</b> (~{config.MAX_SEARCH_PAGES * 35} listings max)"))
    story.append(bullet(f"Poll interval: <b>{int(config.POLL_INTERVAL_SECONDS/60)} minutes</b>"))

    story.append(PageBreak())

    # ═══════════════════════════════════════
    # 6. KEY INSIGHTS
    # ═══════════════════════════════════════
    story.append(section_title("Key Insights from the Data", "6"))
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
    # 7. RECOMMENDATIONS
    # ═══════════════════════════════════════
    story.append(section_title("Recommendations", "7"))
    story.append(section_line())

    # Immediate
    story.append(callout_box(
        "IMMEDIATE (this week)",
        [
            Paragraph('<b>A. Collect user feedback</b>', styles['CalloutText']),
            Paragraph('Tap "Interested" or "Pass" on every alert. We need 20+ labels to understand which alerts are actually useful and tune the system.', styles['CalloutText']),
            Spacer(1, 6),
            Paragraph('<b>B. Monitor AI accuracy</b>', styles['CalloutText']),
            Paragraph('Check a few alerts manually against real resale prices on Selency/eBay. If estimates are consistently off, adjust prompts.', styles['CalloutText']),
        ],
        border_color=ACCENT
    ))
    story.append(Spacer(1, 10))

    # Short-term
    story.append(callout_box(
        "SHORT-TERM (next 2 weeks)",
        [
            Paragraph('<b>C. Tune search queries</b>', styles['CalloutText']),
            Paragraph('Based on alert feedback, add or remove keywords. Remove queries that generate mostly noise.', styles['CalloutText']),
            Spacer(1, 6),
            Paragraph('<b>D. Track actual flips</b>', styles['CalloutText']),
            Paragraph('Record actual buy/sell prices to calibrate AI estimates and validate the margin calculation.', styles['CalloutText']),
        ],
        border_color=INFO_BLUE
    ))
    story.append(Spacer(1, 10))

    # Medium-term
    story.append(callout_box(
        "MEDIUM-TERM (next month)",
        [
            Paragraph('<b>E. Expand categories</b>', styles['CalloutText']),
            Paragraph('Add new product categories (electronics, watches, etc.) once current categories are proven profitable.', styles['CalloutText']),
            Spacer(1, 6),
            Paragraph('<b>F. Proxy / cookie rotation</b>', styles['CalloutText']),
            Paragraph('If DataDome blocking increases, add residential proxy support and automatic cookie rotation.', styles['CalloutText']),
        ],
        border_color=SUCCESS
    ))

    story.append(PageBreak())

    # ═══════════════════════════════════════
    # 8. RISKS
    # ═══════════════════════════════════════
    story.append(section_title("Risks & Limitations", "8"))
    story.append(section_line())

    risk_data = [
        ['DataDome blocks scraping', 'Medium', 'JSON API + cookie auto-refresh works today. Preflight check + early abort avoid wasted time.'],
        ['AI resale estimates inaccurate', 'Medium', 'Track actual flips to calibrate. Per-unit pricing can be misread (improved via prompt).'],
        ['leboncoin changes API', 'Medium', 'HTML fallback exists. API structure rarely changes drastically.'],
        ['Cookie expiration', 'Low', 'Auto-refreshed from Chrome. Rare — only when Chrome cookies themselves expire.'],
        ['Anthropic API cost spikes', 'Low', 'Smart escalation: Haiku first, Sonnet only for promising listings. 2 photos max.'],
        ['False positives (bad alerts)', 'Medium', 'User feedback loop needed. Tune prompts and skip-keywords based on data.'],
    ]
    story.append(make_table(
        ["Risk", "Severity", "Mitigation"],
        risk_data,
        col_widths=[4.5*cm, 2*cm, 8.7*cm]
    ))

    story.append(Spacer(1, 20))

    # ═══════════════════════════════════════
    # 9. OPERATING SNAPSHOT
    # ═══════════════════════════════════════
    story.append(section_title("Operating Snapshot", "9"))
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
        ["Active categories", str(len(config.ACTIVE_CATEGORIES)), ", ".join(config.ACTIVE_CATEGORIES)],
        ["Telegram bots", str(len(config.ACTIVE_CATEGORIES)), "1 per category"],
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
            'The main constraint is <b>your time reviewing alerts</b>, not infra cost. '
            'Anthropic API costs are minimized via smart Haiku-first escalation.',
            styles['CalloutText']
        )],
        border_color=SUCCESS
    ))

    story.append(PageBreak())

    # ═══════════════════════════════════════
    # 10. HOW TO OPERATE
    # ═══════════════════════════════════════
    story.append(section_title("How to Operate", "10"))
    story.append(section_line())

    story.append(Paragraph("Running the System", styles['SubSection']))
    story.append(bullet('Run everything: <font face="Courier" size="9">python main.py</font>'))
    story.append(bullet('Bikes only: <font face="Courier" size="9">python run_bikes.py</font>'))
    story.append(bullet('Furniture only: <font face="Courier" size="9">python run_furniture.py</font>'))
    story.append(bullet('Or with flag: <font face="Courier" size="9">python main.py --category bikes|furniture|all</font>'))
    story.append(Spacer(1, 8))

    story.append(Paragraph("Daily", styles['SubSection']))
    story.append(bullet('Check Telegram alerts &mdash; tap <b>"Interested"</b> or <b>"Pass"</b> on each'))
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

    story.append(Paragraph("Adding a New Category", styles['SubSection']))
    story.append(numbered(1, 'Add a new entry in <b>config.py</b> <font face="Courier" size="9">CATEGORIES</font> dict'))
    story.append(numbered(2, 'Add prompts in <b>prompts.py</b> <font face="Courier" size="9">PROMPTS</font> registry'))
    story.append(numbered(3, 'Set Telegram bot credentials in <b>.env</b>'))
    story.append(numbered(4, 'Add category to <font face="Courier" size="9">ACTIVE_CATEGORIES</font>'))
    story.append(Spacer(1, 8))

    story.append(Paragraph("To Adjust Sensitivity", styles['SubSection']))
    story.append(bullet('Edit <b>config.py</b>: <font face="Courier" size="9">min_flip_margin</font> per category'))
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
