import streamlit as st
import pdfplumber
import pandas as pd
import re
from io import BytesIO

# ---------- Page Config & Theme ----------


# ========== Logo Display ==========
# ---- HERO / LOGO SECTION ----
col1, col2, col3 = st.columns([1, 3, 1])

with col2:
    st.image(
        "https://raw.githubusercontent.com/sabeya143111-arch/swag-invoice-odoo/main/swag-invoice-odoo/logo.jpeg",
        use_column_width=True,
    )


# Custom CSS for better UI
st.markdown(
    """
    <style>
    /* Background gradient */
    .stApp {
        background: radial-gradient(circle at top left, #0f172a 0, #020617 45%, #000000 100%);
        color: #e5e7eb;
)

  }
    

    /* Main title */
    .main-title {
        font-size: 2.6rem;
        font-weight: 800;
        background: linear-gradient(90deg, #22c55e, #eab308, #f97316);
        -webkit-background-clip: text;
        color: transparent;
        letter-spacing: 0.04em;
    }

    .sub-text {
        font-size: 0.98rem;
        color: #ffffff ;
    }

    /* Card style */
    .glass-card {
        background: rgba(15, 23, 42, 0.92);
        border-radius: 18px;
        padding: 18px 20px;
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
        color: #ffffff ;
        background: rgba(22, 101, 52, 0.35);
    }

    .stat-card {
        background: rgba(15, 23, 42, 0.95);
        border-radius: 16px;
        padding: 14px 16px;
        border: 1px solid rgba(55, 65, 81, 0.8);
    }

    .stat-label {
        font-size: 0.7rem;
        text-transform: uppercase;
        color: #ffffff ;
        letter-spacing: 0.08em;
    }

    .stat-value {
        font-size: 1.4rem;
        font-weight: 700;
        color: #ffffff ;
    }

    /* File uploader tweak */
    .uploadedFile {
        border-radius: 12px !important;
        border: 1px dashed rgba(148, 163, 184, 0.7) !important;
        background: rgba(15, 23, 42, 0.7) !important;
    }

    /* Buttons */
    .stButton>button {
        width: 100%;
        border-radius: 999px;
        background: linear-gradient(90deg, #22c55e, #16a34a);
        color: #0b1120;
        font-weight: 700;
        border: none;
        padding: 0.6rem 1rem;
        box-shadow: 0 10px 24px rgba(22, 163, 74, 0.55);
    }
    .stButton>button:hover {
        background: linear-gradient(90deg, #4ade80, #22c55e);
        box-shadow: 0 18px 36px rgba(34, 197, 94, 0.7);
    }

    /* Dataframe container */
    .dataframe-container {
        border-radius: 14px;
        border: 1px solid rgba(148, 163, 184, 0.5);
        overflow: hidden;
    }

    /* Info text bottom */
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

# ---------- Helpers ----------

def extract_item_lines_from_text(text: str):
    lines = []
    for ln in text.split("\n"):
        ln = " ".join(ln.split())
        if ln:
            lines.append(ln)

    item_lines = []
    for ln in lines:
        if "SR" not in ln:
            continue
        # at least one SR amount
        sr_amounts = re.findall(r"SR\s*([\d,]+\.\d+)", ln)
        if len(sr_amounts) < 1:
            continue
        # end: MODEL + line no
        if re.search(r"[A-Za-z0-9\-]+\s+\d+$", ln):
            item_lines.append(ln)

    return item_lines


def parse_line(ln: str):
    # all SR amounts
    sr_amounts = re.findall(r"SR\s*([\d,]+\.\d+)", ln)
    unit_price = float(sr_amounts[-1].replace(",", "")) if sr_amounts else 0.0

    # part after last SR
    after_last_sr = re.split(r"SR\s*[\d,]+\.\d+", ln)[-1].strip()

    # qty
    qty_match = re.search(r"(\d+)", after_last_sr)
    qty = float(qty_match.group(1)) if qty_match else 0.0

    # model + line no
    model_line_match = re.search(r"([A-Za-z0-9\-]+)\s+(\d+)$", after_last_sr)
    model = model_line_match.group(1) if model_line_match else ""

    # description
    tmp = after_last_sr
    if qty_match:
        tmp = re.sub(rf"^{qty_match.group(1)}\s*", "", tmp)
    if model_line_match:
        tmp = tmp.replace(model_line_match.group(0), "")
    desc = " ".join(tmp.split())

    return model.strip(), desc.strip(), qty, unit_price


def pdf_to_odoo_df(pdf_file, vendor_name="SWAG TRADING CO."):
    with pdfplumber.open(pdf_file) as pdf:
        full_text = ""
        for page in pdf.pages:
            full_text += (page.extract_text() or "") + "\n"

    item_lines = extract_item_lines_from_text(full_text)

    records = []
    for ln in item_lines:
        model, desc, qty, price = parse_line(ln)
        if not model:
            continue
        records.append(
            {
                "partner_id/name": vendor_name,
                "order_line/product_id": model,
                "order_line/name": desc,
                "order_line/product_uom_qty": qty,
                "order_line/price_unit": price,
            }
        )

    return pd.DataFrame(records)


# ---------- Layout ----------

left, right = st.columns([1.1, 1])

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
                SWAG Invoice → Odoo Excel
            </div>
            <p class="sub-text">
                PDF invoice upload karo, app automatically clean Excel bana dega
                jo direct Odoo import me use ho sakta hai. Manual typing khatam.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.write("")
    vendor_name = st.text_input(
        "Vendor / Partner name",
        value="SWAG TRADING CO.",
        help="Yahan Odoo ka vendor / partner name likho.",
    )

    uploaded_pdf = st.file_uploader(
        "Invoice PDF upload karein",
        type=["pdf"],
        help="SWAG supplier invoice (PDF) yahan se choose karein.",
    )

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
        df_odoo = None
    else:
        st.markdown(
            f"""
                <div class="stat-value">Ready to convert</div>
                <div style="font-size:0.8rem;color:#9ca3af;margin-top:4px;">
                    File: <span style="color:#e5e7eb;">{uploaded_pdf.name}</span>
                </div>
            </div>
        """,
            unsafe_allow_html=True,
        )
        df_odoo = None

    st.markdown("</div>", unsafe_allow_html=True)

# ---------- Processing & Output ----------

if uploaded_pdf is not None and convert_clicked:
    with st.spinner("PDF se item lines read ho rahi hain..."):
        df_odoo = pdf_to_odoo_df(uploaded_pdf, vendor_name)

    if df_odoo is None or df_odoo.empty:
        st.error(
            "Koi item line detect nahi hui. Invoice format ya parser ko thoda adjust karna padega."
        )
    else:
        total_items = len(df_odoo)
        total_amount = float(df_odoo["order_line/price_unit"].sum())

        c1, c2 = st.columns(2)
        with c1:
            st.markdown(
                f"""
                <div class="stat-card">
                    <div class="stat-label">Total items</div>
                    <div class="stat-value">{total_items}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with c2:
            st.markdown(
                f"""
                <div class="stat-card">
                    <div class="stat-label">Total unit price sum</div>
                    <div class="stat-value">SR {total_amount:,.2f}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        st.markdown("### Preview (Odoo import lines)")

        st.markdown('<div class="dataframe-container">', unsafe_allow_html=True)
        st.dataframe(df_odoo, use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)

        buffer = BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            df_odoo.to_excel(writer, index=False, sheet_name="Lines")
        buffer.seek(0)

        st.download_button(
            label="⬇️ Download Odoo Excel",
            data=buffer,
            file_name="odoo_purchase_lines.xlsx",
            mime=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
        )

        st.markdown(
            """
            <div class="footer-note">
                Tip: Agar koi line miss ho rahi ho toh sample invoice bhej do,
                parser aur improve kiya ja sakta hai.
            </div>
            """,
            unsafe_allow_html=True,
        )
elif uploaded_pdf is None:
    st.info("Upar se PDF select karo start karne ke liye.")













