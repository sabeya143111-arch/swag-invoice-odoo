import os
import json
import re
from io import BytesIO

import streamlit as st
import pdfplumber
import pandas as pd
from openai import OpenAI
from openpyxl.styles import PatternFill, Font, Alignment
from openpyxl.utils import get_column_letter

# ---------- CONFIG ----------

st.set_page_config(layout="wide")

# HF token directly set (demo ke liye)
HF_TOKEN = "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"

client = OpenAI(
    base_url="https://router.huggingface.co/v1",
    api_key=HF_TOKEN,
)

if "history" not in st.session_state:
    st.session_state["history"] = []
if "ai_cache" not in st.session_state:
    st.session_state["ai_cache"] = {}

# ---------- UI: LOGO + CSS ----------

logo_col1, logo_col2, logo_col3 = st.columns([1, 2, 1])
with logo_col2:
    st.image(
        "https://raw.githubusercontent.com/sabeya143111-arch/swag-invoice-odoo/main/swag-invoice-odoo/logo.png",
        use_column_width=False,
        width=420,
    )

st.markdown(
    """
    <style>
    .stApp {
        background: radial-gradient(circle at top left, #0f172a 0, #020617 45%, #000000 100%);
        color: #e5e7eb;
    }
    .block-container { padding-top: 0rem; padding-bottom: 0rem; }

    .main-title {
        font-size: 2.6rem;
        font-weight: 800;
        background: linear-gradient(90deg, #22c55e, #eab308, #f97316);
        -webkit-background-clip: text;
        color: transparent;
        letter-spacing: 0.04em;
    }
    .sub-text { font-size: 0.98rem; color: #ffffff; }

    .glass-card {
        background: rgba(15, 23, 42, 0.92);
        border-radius: 18px;
        padding: 22px 24px;
        border: 1px solid rgba(148, 163, 184, 0.35);
        box-shadow: 0 18px 40px rgba(0, 0, 0, 0.6);
        backdrop-filter: blur(18px);
    }
    .pill-badge {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        font-size: 0.78rem;
        padding: 4px 10px;
        border-radius: 999px;
        border: 1px solid rgba(52, 211, 153, 0.45);
        color: #ffffff;
        background: rgba(22, 101, 52, 0.35);
    }
    .stat-card {
        background: rgba(15, 23, 42, 0.95);
        border-radius: 16px;
        padding: 16px 18px;
        border: 1px solid rgba(55, 65, 81, 0.8);
        transition: all 0.3s ease;
    }
    .stat-card:hover {
        border-color: rgba(52, 211, 153, 0.6);
        box-shadow: 0 8px 16px rgba(52, 211, 153, 0.2);
    }
    .stat-label {
        font-size: 0.7rem;
        text-transform: uppercase;
        color: #9ca3af;
        letter-spacing: 0.08em;
    }
    .stat-value {
        font-size: 1.6rem;
        font-weight: 700;
        color: #22c55e;
        margin-top: 4px;
    }
    .dataframe-container {
        border-radius: 14px;
        border: 1px solid rgba(148, 163, 184, 0.5);
        overflow: hidden;
    }
    .success-badge {
        background: rgba(34, 197, 94, 0.15);
        color: #22c55e;
        padding: 12px 16px;
        border-radius: 10px;
        border-left: 4px solid #22c55e;
        font-size: 0.9rem;
        margin: 12px 0;
    }
    .warning-badge {
        background: rgba(248, 171, 89, 0.10);
        color: #fdba74;
        padding: 10px 14px;
        border-radius: 10px;
        border-left: 4px solid #f97316;
        font-size: 0.85rem;
        margin: 8px 0;
    }
    .footer-note {
        font-size: 0.78rem;
        color: #6b7280;
        text-align: center;
        margin-top: 18px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------- HELPERS: PDF PARSE ----------

def detect_pdf_structure(text: str):
    lines = [" ".join(ln.split()) for ln in text.split("\n") if ln.strip()]
    structure = {
        "has_sr": any("SR" in ln for ln in lines[:50]),
        "has_model": any(re.search(r"[A-Z]{2,}\-\d+", ln) for ln in lines[:50]),
        "has_qty": any(re.search(r"\bQty\b|\bQuantity\b|\bQTY\b", ln, re.I) for ln in lines[:50]),
        "has_price": any(re.search(r"\bPrice\b|\bAmount\b|\bCost\b", ln, re.I) for ln in lines[:50]),
        "total_lines": len(lines),
    }
    return structure, lines


def extract_item_lines_generic(text: str, structure: dict):
    lines = [" ".join(ln.split()) for ln in text.split("\n") if ln.strip()]
    item_lines = []

    if structure["has_sr"]:
        for ln in lines:
            if "SR" in ln:
                sr_amounts = re.findall(r"SR\s*([\d,]+\.\d+)", ln)
                if len(sr_amounts) >= 1 and re.search(r"[A-Za-z0-9\-]+\s+\d+$", ln):
                    item_lines.append(("sr_format", ln))
    else:
        for ln in lines:
            if re.search(r"\d+", ln) and any(c.isalpha() for c in ln):
                if not re.search(r"(total|subtotal|invoice|date)", ln, re.I):
                    item_lines.append(("generic_format", ln))

    return item_lines


def parse_line_sr_format(ln: str):
    sr_amounts = re.findall(r"SR\s*([\d,]+\.\d+)", ln)
    unit_price = float(sr_amounts[-1].replace(",", "")) if sr_amounts else 0.0

    after_last_sr = re.split(r"SR\s*[\d,]+\.\d+", ln)[-1].strip()
    qty_match = re.search(r"(\d+)", after_last_sr)
    qty = float(qty_match.group(1)) if qty_match else 0.0

    model_line_match = re.search(r"([A-Za-z0-9\-]+)\s+(\d+)$", after_last_sr)
    model = model_line_match.group(1) if model_line_match else ""

    tmp = after_last_sr
    if qty_match:
        tmp = re.sub(rf"^{qty_match.group(1)}\s*", "", tmp)
    if model_line_match:
        tmp = tmp.replace(model_line_match.group(0), "")
    desc = " ".join(tmp.split())

    return model.strip(), desc.strip(), qty, unit_price


def parse_line_generic(ln: str):
    numbers = re.findall(r"[\d,]+\.?\d*", ln)
    model_match = re.search(r"([A-Z]{2,}\-?\d+)", ln)
    model = model_match.group(1) if model_match else ""

    desc = re.sub(r"[A-Z]{2,}\-?\d+", "", ln).strip()
    desc = re.sub(r"[\d,]+\.?\d*", "", desc).strip()
    desc = " ".join(desc.split())

    qty = float(numbers[-2].replace(",", "")) if len(numbers) >= 2 else 0.0
    unit_price = float(numbers[-1].replace(",", "")) if len(numbers) >= 1 else 0.0

    return model, desc, qty, unit_price


def pdf_to_odoo_df(pdf_file, vendor_name="SWAG TRADING CO.", discount_pct=0.0, vat_pct=0.0):
    with pdfplumber.open(pdf_file) as pdf:
        full_text = ""
        for page in pdf.pages:
            full_text += (page.extract_text() or "") + "\n"

    structure, lines = detect_pdf_structure(full_text)
    item_lines = extract_item_lines_generic(full_text, structure)

    records = []
    discount_factor = 1 - (discount_pct / 100)
    vat_factor = 1 + (vat_pct / 100)

    for fmt, ln in item_lines:
        if fmt == "sr_format":
            model, desc, qty, price = parse_line_sr_format(ln)
        else:
            model, desc, qty, price = parse_line_generic(ln)

        if not model:
            continue

        line_base = qty * price
        line_total = line_base * discount_factor * vat_factor
        records.append(
            {
                "partner_id/name": vendor_name,
                "order_line/product_id": model,
                "order_line/name": desc,
                "order_line/product_uom_qty": qty,
                "order_line/price_unit": price,
                "order_line/price_subtotal": line_total,
            }
        )

    df = pd.DataFrame(records)
    return df, full_text, item_lines, structure


def style_excel_file(buffer):
    from openpyxl import load_workbook

    wb = load_workbook(buffer)
    ws = wb.active

    header_fill = PatternFill(start_color="22C55E", end_color="22C55E", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF", size=11)

    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    light_fill = PatternFill(start_color="F0F9FF", end_color="F0F9FF", fill_type="solid")
    for row_idx, row in enumerate(ws.iter_rows(min_row=2, max_row=ws.max_row), start=2):
        if row_idx % 2 == 0:
            for cell in row:
                cell.fill = light_fill
                cell.alignment = Alignment(horizontal="left", vertical="center")

    for col in ws.columns:
        max_length = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            try:
                if len(str(cell.value)) > max_length:
                    max_length = len(str(cell.value))
            except:
                pass
        ws.column_dimensions[col_letter].width = max_length + 2

    wb.save(buffer)
    buffer.seek(0)

# ---------- AI HELPER ----------

def analyze_invoice_with_ai(df: pd.DataFrame, vendor: str, discount: float, vat: float) -> str:
    if not HF_TOKEN:
        return "❌ HF_TOKEN missing. Streamlit secrets me set karo."

    sample = df.head(60).to_dict(orient="records")

    prompt = f"""
You are a purchase & inventory analyst for a fashion retail company in Saudi Arabia.

Vendor: {vendor}
Global discount: {discount} %
VAT: {vat} %

Below is invoice line data as JSON list. Each line has:
product_id, description, quantity, unit_price, subtotal.

DATA:
{json.dumps(sample, ensure_ascii=False)}

Tasks (answer in short bullet points, simple English + little Hindi/Urdu mix):
1) Overall summary: total items, total quantity, total amount (approx).
2) Top 5 high-value models with qty & amount.
3) Any suspicious points: very high qty, strange price, duplicates, etc.
4) Suggestions: stock planning / reorder / price check ideas.

Keep answer concise, max 20 bullets.
"""

    try:
        completion = client.chat.completions.create(
            model="moonshotai/Kimi-K2-Instruct-0905",
            messages=[{"role": "user", "content": prompt}],
        )
        return completion.choices[0].message.content
    except Exception as e:
        return f"❌ AI request failed: {e}"

# ---------- LAYOUT TOP ----------

left, right = st.columns([1.3, 1])

with left:
    st.markdown(
        """
        <div class="glass-card">
            <div class="pill-badge">
                🧾 Auto Invoice → Odoo
                <span style="opacity:0.7;">• SWAG internal tool</span>
            </div>
            <div style="margin-top: 8px;"></div>
            <div class="main-title">
                SWAG Invoice → Odoo Excel + AI
            </div>
            <p class="sub-text">
                Kisi bhi PDF invoice upload karo, app automatically structure detect karke 
                clean Excel bana dega jo direct Odoo import me use ho sakta hai.
                Upar se AI tumhare data ke hisaab se summary, issues aur suggestions bhi dega.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.write("")
    vendor_name = st.text_input(
        "Vendor / Partner name",
        value="SWAG TRADING CO.",
        help="Odoo ka vendor / partner name likho.",
    )

    uploaded_pdf = st.file_uploader(
        "Invoice PDF upload karein (kisi bhi format)",
        type=["pdf"],
        help="SWAG ya kisi aur supplier ka invoice (PDF).",
    )

    with st.expander("⚙️ Advanced settings", expanded=False):
        discount_pct = st.number_input("Global discount %", 0.0, 100.0, 0.0, 0.5)
        vat_pct = st.number_input("VAT %", 0.0, 30.0, 0.0, 0.5)

    convert_clicked = st.button("🔁 Convert to Odoo Excel")

with right:
    st.markdown(
        """
        <div class="glass-card">
            <div class="stat-card">
                <div class="stat-label">Status</div>
        """,
        unsafe_allow_html=True,
    )

    if uploaded_pdf is None:
        st.markdown(
            """
                <div class="stat-value">No file uploaded</div>
                <div style="font-size:0.8rem;color:#9ca3af;margin-top:4px;">
                    Pehle left side se invoice PDF choose karein.
                </div>
            </div>
        """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f"""
                <div class="stat-value">Ready to convert</div>
                <div style="font-size:0.8rem;color:#9ca3af;margin-top:4px;">
                    File: <span style="color:#22c55e;">{uploaded_pdf.name}</span>
                </div>
            </div>
        """,
            unsafe_allow_html=True,
        )

    st.markdown("</div>", unsafe_allow_html=True)

# ---------- TABS ----------

tab_overview, tab_details, tab_ai, tab_debug = st.tabs(
    ["📊 Overview", "📋 Details", "🤖 AI Insights", "🛠 Debug"]
)

df_odoo = None
full_text = ""
item_lines = []
detected_structure = None

# ---------- MAIN PROCESS ----------

if uploaded_pdf is not None and convert_clicked:
    progress = st.progress(0, text="Step 1/3: PDF read ho raha hai...")

    with st.spinner("📄 PDF parse aur structure detect ho rahi hai..."):
        progress.progress(30, text="Step 2/3: Structure detect + data extract...")
        df_odoo, full_text, item_lines, detected_structure = pdf_to_odoo_df(
            uploaded_pdf, vendor_name, discount_pct, vat_pct
        )
        progress.progress(70, text="Step 3/3: Excel build ho raha hai...")

    if df_odoo is None or df_odoo.empty:
        progress.empty()
        st.error("❌ Koi item line detect nahi hui. PDF format ya structure check karein.")
    else:
        total_items = len(df_odoo)
        total_qty = float(df_odoo["order_line/product_uom_qty"].sum())
        total_subtotal = float(df_odoo["order_line/price_subtotal"].sum())
        total_unit_sum = float(df_odoo["order_line/price_unit"].sum())

        progress.progress(100, text="✅ Ho gaya!")
        progress.empty()

        st.session_state["history"].insert(
            0,
            {
                "File": uploaded_pdf.name,
                "Items": int(total_items),
                "Qty": int(total_qty),
                "Amount": round(total_subtotal, 2),
            },
        )
        st.session_state["history"] = st.session_state["history"][:5]

        # ===== OVERVIEW =====
        with tab_overview:
            format_detected = (
                "SR-based format (SWAG original)" if detected_structure.get("has_sr") else "Generic flexible format"
            )
            st.markdown(
                f"""
                <div class="success-badge">
                    ✅ <strong>{total_items} items successfully extracted</strong> ({format_detected})
                </div>
                """,
                unsafe_allow_html=True,
            )

            dupes = df_odoo["order_line/product_id"].value_counts()
            dupe_models = dupes[dupes > 1]
            if not dupe_models.empty:
                ex_models = ", ".join(dupe_models.index.tolist()[:3])
                st.markdown(
                    f"""
                    <div class="warning-badge">
                        ⚠️ {len(dupe_models)} models repeated in invoice. 
                        Example: {ex_models}
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

            c1, c2, c3, c4 = st.columns(4)
            with c1:
                st.markdown(
                    f"""
                    <div class="stat-card">
                        <div class="stat-label">📦 Total Items</div>
                        <div class="stat-value">{total_items}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            with c2:
                st.markdown(
                    f"""
                    <div class="stat-card">
                        <div class="stat-label">📊 Total Quantity</div>
                        <div class="stat-value">{total_qty:.0f}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            with c3:
                st.markdown(
                    f"""
                    <div class="stat-card">
                        <div class="stat-label">💰 Unit Price Sum</div>
                        <div class="stat-value">SR {total_unit_sum:,.0f}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            with c4:
                st.markdown(
                    f"""
                    <div class="stat-card">
                        <div class="stat-label">✨ Total Amount</div>
                        <div class="stat-value">SR {total_subtotal:,.0f}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

            st.markdown(
                f"""
                <p style="font-size:0.9rem;color:#9ca3af;margin-top:8px;">
                    Vendor <b>{vendor_name}</b> • Discount <b>{discount_pct:.1f}%</b> • VAT <b>{vat_pct:.1f}%</b>
                </p>
                """,
                unsafe_allow_html=True,
            )

            if st.session_state["history"]:
                st.markdown("### 🕒 Recent conversions")
                st.table(st.session_state["history"])

        # ===== DETAILS =====
        with tab_details:
            st.markdown("### 🔍 Filters")
            f1, f2 = st.columns(2)
            with f1:
                min_qty = st.number_input(
                    "Minimum quantity", min_value=0.0, value=0.0, step=1.0, key="min_qty"
                )
            with f2:
                min_amount = st.number_input(
                    "Minimum line amount (SR)", min_value=0.0, value=0.0, step=10.0, key="min_amt"
                )

            filtered_df = df_odoo[
                (df_odoo["order_line/product_uom_qty"] >= min_qty)
                & (df_odoo["order_line/price_subtotal"] >= min_amount)
            ]

            st.markdown("### 📋 Preview (Filtered lines)")
            st.markdown('<div class="dataframe-container">', unsafe_allow_html=True)
            st.dataframe(filtered_df, use_container_width=True)
            st.markdown("</div>", unsafe_allow_html=True)

            top5 = df_odoo.sort_values(
                "order_line/price_subtotal", ascending=False
            ).head(5)
            st.markdown("#### 🔝 Top 5 high value lines")
            st.dataframe(top5, use_container_width=True, height=250)

            buffer = BytesIO()
            with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
                df_odoo.to_excel(writer, index=False, sheet_name="Purchase Orders")
            style_excel_file(buffer)

            st.download_button(
                label="⬇️ Download Styled Excel (Ready for Odoo Import)",
                data=buffer,
                file_name="odoo_purchase_orders.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

            st.markdown(
                """
                <div class="footer-note">
                    💡 Excel file automatically color-coded aur formatted hai, 
                    bilkul Odoo import ke liye ready!
                </div>
                """,
                unsafe_allow_html=True,
            )

        # ===== AI INSIGHTS =====
        with tab_ai:
            st.markdown("### 🤖 AI Insights (invoice ke hisaab se)")

            if not HF_TOKEN:
                st.error("HF_TOKEN set nahi hai. `.streamlit/secrets.toml` me HF_TOKEN daalo.")
            else:
                key = f"{uploaded_pdf.name}_{total_items}_{total_subtotal}"
                generate_clicked = st.button("Generate AI Insights")

                if generate_clicked:
                    if key in st.session_state["ai_cache"]:
                        ai_text = st.session_state["ai_cache"][key]
                    else:
                        with st.spinner("AI soch raha hai... (thoda time lag sakta hai)"):
                            ai_text = analyze_invoice_with_ai(
                                df_odoo, vendor_name, discount_pct, vat_pct
                            )
                            st.session_state["ai_cache"][key] = ai_text
                    st.markdown(ai_text)

                st.markdown(
                    """
                    <div class="footer-note">
                        Note: Ye AI sirf helper hai – final decision hamesha 
                        tumhare business logic ke hisaab se lo.
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

        # ===== DEBUG =====
        with tab_debug:
            st.markdown("### 🔍 Detected PDF Structure")
            st.json(detected_structure)

            st.markdown("#### Raw text (first 2500 chars)")
            st.code(full_text[:2500])

            st.markdown("#### Detected item lines")
            st.write(f"Total lines detected: {len(item_lines)}")
            for fmt, ln in item_lines[:10]:
                st.caption(f"[{fmt}] {ln}")

elif uploaded_pdf is None:
    with tab_overview:
        st.info("📂 Upar se PDF select karo start karne ke liye.")
