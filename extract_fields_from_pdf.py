import fitz  # PyMuPDF
import io
import re
from PIL import Image
from datetime import datetime
from google.cloud import vision  # ✅ Required for `vision.Image`

# ✅ OCR single page
def ocr_page(page, vision_client):
    pix = page.get_pixmap(dpi=300)
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG")
    content = buffer.getvalue()

    image = vision.Image(content=content)  # ✅ FIXED: use vision.Image, not image_annotator_pb2
    response = vision_client.document_text_detection(image=image)

    if response.error.message:
        raise Exception(f"Vision API error: {response.error.message}")

    return response.full_text_annotation.text if response.full_text_annotation.text else ""

# ✅ Utility functions
def extract_after(label, text, max_chars=100):
    pattern = re.escape(label) + r'\s*:?[\s\n]*(.*)'
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        value = match.group(1).strip()
        return value[:max_chars].strip()
    return ""

def find_line_containing(keywords, text):
    lines = text.splitlines()
    for line in lines:
        for keyword in keywords:
            if keyword.lower() in line.lower():
                return line.strip()
    return ""

# ✅ PDF field extraction
def extract_fields_from_pdf(file_storage_obj, vision_client):
    doc = fitz.open(stream=file_storage_obj.read(), filetype="pdf")

    # OCR pages 1, 2, 3
    text1 = ocr_page(doc[0], vision_client) if len(doc) > 0 else ""
    text2 = ocr_page(doc[1], vision_client) if len(doc) > 1 else ""
    text3 = ocr_page(doc[2], vision_client) if len(doc) > 2 else ""

    metadata = {
        "Patient Name": extract_after("Patient Name", text2) or find_line_containing(["Patient Name", "Name:"], text2),
        "Date of Birth": extract_after("Date of Birth", text2),
        "Sex": extract_after("Sex", text2),
        "SSN": extract_after("SSN", text2),
        "MRN": extract_after("MRN", text2),
        "Procedure Date": extract_after("Procedure Date", text2),
        "Order Date": extract_after("Order Date", text1),
        "Delivery Date": extract_after("Delivery/Receipt Date", text1),
        "Order Description": extract_after("Order Description", text2),
        "Diagnosis Code (ICD-10)": extract_after("Diagnosis Code", text2),
        "Phone (Home)": find_line_containing(["Phone (Home)", "Phone"], text3),
        "Address": find_line_containing(["Address"], text2),

        # Physician / Provider
        "Physician Name": extract_after("Physician", text1),
        "Authorizing Provider": extract_after("Authorizing Provider", text2),
        "Clinic Name": extract_after("Clinic Name", text2),
        "Department": extract_after("Department", text2),

        # Guarantor Info (from page 3)
        "Guarantor Name": extract_after("Guarantor Name", text3),
        "Guarantor DOB": extract_after("Guarantor Date of Birth", text3),
        "Guarantor Phone": extract_after("Guarantor Phone", text3),
        "Guarantor Address": find_line_containing(["Guarantor Address", "Address"], text3),

        # Insurance Info
        "Insurance Company": extract_after("Insurance Company", text3),
        "Member ID": extract_after("Member ID", text3),
        "Group Number": extract_after("Group Number", text3),
        "Subscriber ID": extract_after("Member ID", text3),  # Same as Member ID
        "Insurance Address": find_line_containing(["Insurance Address", "Address"], text3),
        "Insurance Phone": extract_after("Insurance Phone", text3),
        "Insurance Authorization Number": extract_after("Authorization Number", text3),

        # Employer / Payer
        "Employer": extract_after("Employer", text2),
        "Payer": extract_after("Payer", text3),
        "Authorization Number": extract_after("Authorization Number", text2),
    }

    return metadata

# ✅ Optional: Flatten nested metadata
def flatten_metadata(metadata):
    flat = {}
    for key, value in metadata.items():
        if isinstance(value, dict):
            for sub_key, sub_value in value.items():
                flat[f"{key}.{sub_key}"] = sub_value
        else:
            flat[key] = value
    return flat
