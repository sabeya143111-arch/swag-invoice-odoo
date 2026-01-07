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

# HF token - directly set
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
        border: 1px solid rgba(255, 255, 255, 0.08);
        box-shadow: 0 10px 40px rgba(0,0,0,0.7);
    }
    .invoice-preview {
        background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
        padding: 20px;
        border-radius: 12px;
        border-left: 4px solid #22c55e;
    }
    </style>
    """,
    unsafe_allow_html=True
)

st.markdown("<h1 class='main-title'>📄 SWAG Invoice Processor — Odoo</h1>", unsafe_allow_html=True)
st.markdown(
    "<p class='sub-text'>بارگزاری فایل‌های صورتحساب PDF ، با تحلیل هوش مصنوعی (OCR) و تبدیل آن به Odoo Excel در یک لحظه ✨</p>",
    unsafe_allow_html=True
)

st.markdown("---")

# ---------- HELPER FUNCTIONS ----------

def parse_ai_json(text: str):
    """Extract JSON from AI response (handle markdown code fences)."""
    text = text.strip()
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]
    text = re.sub(r"```(json)?\s*", "", text)
    text = re.sub(r"```\s*$", "", text)
    return json.loads(text.strip())

def extract_pdf_text(file):
    """Extract all text from PDF pages using pdfplumber."""
    text = ""
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
    return text

def call_llm_once_with_cache(user_prompt: str, system_prompt: str) -> str:
    """Call the LLM once (with session cache)."""
    cache_key = (user_prompt, system_prompt)
    if cache_key in st.session_state["ai_cache"]:
        return st.session_state["ai_cache"][cache_key]

    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]

    resp = client.chat.completions.create(
        model="meta-llama/Llama-3.3-70B-Instruct",
        messages=messages,
        max_tokens=4000,
        temperature=0.0
    )
    answer = resp.choices[0].message.content
    st.session_state["ai_cache"][cache_key] = answer
    return answer

def extract_invoice_data_ai(pdf_text: str) -> dict:
    """Use AI to extract structured invoice data from raw PDF text."""
    system_prompt = (
        "You are a highly accurate data extraction assistant. "
        "Extract invoice details as valid JSON only. "
        "No extra text or explanations. "
        "Return a JSON object with: invoice_number, invoice_date, total_amount, vat_amount, vendor_name, line_items. "
        "line_items should be a list of objects with: description, quantity, unit_price, total."
    )
    user_prompt = (
        "Below is the text extracted from a PDF invoice. "
        "Parse it carefully and output JSON with the invoice header & all line items.\n\n"
        f"{pdf_text}\n\n"
        "Output only the JSON."
    )

    raw_resp = call_llm_once_with_cache(user_prompt, system_prompt)
    return parse_ai_json(raw_resp)

def show_json_preview(data: dict):
    """Display structured invoice data in a styled preview."""
    with st.container():
        st.markdown("<div class='invoice-preview'>", unsafe_allow_html=True)
        st.markdown("### 🧾 Extracted Invoice Data")

        col1, col2, col3 = st.columns(3)
        col1.metric("Invoice #", data.get("invoice_number", "N/A"))
        col2.metric("Date", data.get("invoice_date", "N/A"))
        col3.metric("Total", f"${data.get('total_amount', 0):,.2f}")

        st.markdown("**Vendor:** " + str(data.get("vendor_name", "N/A")))
        st.markdown("**VAT Amount:** " + str(data.get("vat_amount", "N/A")))

        if "line_items" in data and data["line_items"]:
            st.markdown("#### Line Items")
            df = pd.DataFrame(data["line_items"])
            st.dataframe(df, use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)

def convert_to_odoo_excel(data: dict) -> BytesIO:
    """Convert structured invoice data into Odoo-compatible Excel."""
    records = []
    for item in data.get("line_items", []):
        records.append({
            "Invoice Number": data.get("invoice_number", ""),
            "Invoice Date": data.get("invoice_date", ""),
            "Vendor": data.get("vendor_name", ""),
            "Description": item.get("description", ""),
            "Quantity": item.get("quantity", 0),
            "Unit Price": item.get("unit_price", 0.0),
            "Line Total": item.get("total", 0.0),
            "VAT": data.get("vat_amount", 0.0),
            "Total Amount": data.get("total_amount", 0.0)
        })

    df = pd.DataFrame(records)

    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Odoo Import")

        workbook = writer.book
        worksheet = writer.sheets["Odoo Import"]

        # Header styling
        header_fill = PatternFill(start_color="22c55e", end_color="22c55e", fill_type="solid")
        header_font = Font(bold=True, color="FFFFFF", size=11)
        for cell in worksheet[1]:
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center")

        # Auto-adjust column widths
        for col in worksheet.columns:
            max_length = 0
            col_letter = get_column_letter(col[0].column)
            for cell in col:
                if cell.value:
                    max_length = max(max_length, len(str(cell.value)))
            worksheet.column_dimensions[col_letter].width = max_length + 3

    output.seek(0)
    return output

# ---------- MAIN APP ----------

st.markdown("<div class='glass-card'>", unsafe_allow_html=True)
st.markdown("### 📤 Upload Invoice PDF")
uploaded_file = st.file_uploader("Choose a PDF file", type="pdf", label_visibility="collapsed")
st.markdown("</div>", unsafe_allow_html=True)

if uploaded_file:
    st.success(f"✅ Uploaded: **{uploaded_file.name}**")

    with st.spinner("🔍 Extracting text from PDF..."):
        pdf_text = extract_pdf_text(uploaded_file)

    if not pdf_text.strip():
        st.error("⚠️ No text found in PDF. Please check the file.")
        st.stop()

    with st.expander("📄 Raw PDF Text", expanded=False):
        st.text(pdf_text[:2000] + ("..." if len(pdf_text) > 2000 else ""))

    with st.spinner("🤖 Using AI to extract invoice data..."):
        invoice_data = extract_invoice_data_ai(pdf_text)

    st.success("✅ AI extraction complete!")

    show_json_preview(invoice_data)

    st.markdown("---")

    st.markdown("<div class='glass-card'>", unsafe_allow_html=True)
    st.markdown("### 📊 Export to Odoo Excel")
    if st.button("💾 Generate Odoo Excel", use_container_width=True):
        excel_file = convert_to_odoo_excel(invoice_data)
        st.download_button(
            label="⬇️ Download Odoo Excel",
            data=excel_file,
            file_name=f"odoo_invoice_{invoice_data.get('invoice_number', 'export')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
        st.balloons()
    st.markdown("</div>", unsafe_allow_html=True)

else:
    st.info("👆 Please upload a PDF invoice to begin.")

st.markdown("---")
st.markdown(
    "<p style='text-align:center; color:#64748b; font-size:0.85rem;'>Powered by OpenAI + Hugging Face 🚀</p>",
    unsafe_allow_html=True
)
