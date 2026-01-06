import streamlit as st
import pdfplumber
import pandas as pd
import re
from io import BytesIO

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
        records.append({
            "partner_id/name": vendor_name,
            "order_line/product_id": model,
            "order_line/name": desc,
            "order_line/product_uom_qty": qty,
            "order_line/price_unit": price,
        })

    return pd.DataFrame(records)

# ---------- Streamlit UI ----------

st.set_page_config(page_title="SWAG Invoice → Odoo", page_icon="🧾", layout="centered")

st.title("🧾 SWAG Invoice → Odoo Excel")
st.write("PDF invoice upload karo, ye app Odoo import Excel bana dega.")

vendor_name = st.text_input("Vendor / Partner name", value="SWAG TRADING CO.")

uploaded_pdf = st.file_uploader("Invoice PDF upload karein", type=["pdf"])

if uploaded_pdf is not None:
    if st.button("Convert to Odoo Excel"):
        with st.spinner("Processing PDF..."):
            df_odoo = pdf_to_odoo_df(uploaded_pdf, vendor_name)

        if df_odoo.empty:
            st.error("Koi item line detect nahi hui. Invoice format ya parser check karein.")
        else:
            st.success(f"Conversion done! Total items: {len(df_odoo)}")
            st.subheader("Preview")
            st.dataframe(df_odoo)

            # Excel in memory
            buffer = BytesIO()
            with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
                df_odoo.to_excel(writer, index=False, sheet_name="Lines")
            buffer.seek(0)

            st.download_button(
                label="⬇️ Download Odoo Excel",
                data=buffer,
                file_name="odoo_purchase_lines.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
else:
    st.info("Upar se PDF select karo start karne ke liye.")
