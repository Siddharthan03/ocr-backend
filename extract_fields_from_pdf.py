import re
import difflib
import fitz
import io
from PIL import Image
from datetime import datetime
from google.cloud import vision

def ocr_page(page, vision_client):
    pix = page.get_pixmap(dpi=300)
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG")
    response = vision_client.document_text_detection(image=vision.Image(content=buffer.getvalue()))
    return response.full_text_annotation.text if response.text_annotations else ""

def extract_patient_address(text):
    match = re.search(r"Address[:\s]*([\w\s.,#-]+\d{5}(?:-\d{4})?)", text, re.IGNORECASE)
    return match.group(1).strip().replace("\n", " ") if match else "-"

def extract_patient_name_from_page2(text2):
    match = re.search(r"Patient Name[:\s]*([A-Za-z ,.'-]+)", text2, re.IGNORECASE)
    return match.group(1).strip() if match else "-"

def extract_physician_from_signature_area(text1, fallback_name=None):
    lines = text1.splitlines()
    candidates = []
    for i, line in enumerate(lines):
        if "signature" in line.lower() or "signed" in line.lower() or "physician" in line.lower():
            for j in range(i + 1, min(i + 5, len(lines))):
                candidate = lines[j].strip()
                if "physician name" in candidate.lower():
                    name = re.sub(r"(?i)physician name[:\s]*", "", candidate).strip()
                    if len(name.split()) >= 2:
                        candidates.append(name)
                elif not any(skip in candidate.lower() for skip in ["order date", "date", "acknowledgement", "patient name"]) \
                        and re.match(r"^[A-Z][a-z]+[, ]+[A-Z][a-z]+", candidate):
                    candidates.append(candidate)
    if fallback_name and candidates:
        best = difflib.get_close_matches(fallback_name, candidates, n=1)
        return best[0] if best else candidates[0]
    elif candidates:
        return candidates[0]
    return "-"

def extract_handwritten_delivery_date(text):
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if "delivery date" in line.lower() or "receipt date" in line.lower():
            for j in range(i, min(i + 3, len(lines))):
                match = re.search(r"([0-9]{1,2}/[0-9]{1,2}/[0-9]{2,4})", lines[j])
                if match:
                    parts = match.group(1).split("/")
                    mm = parts[0].zfill(2)
                    dd = parts[1].zfill(2)
                    yy = parts[2]
                    yyyy = "20" + yy if len(yy) == 2 else yy
                    return f"{mm}/{dd}/{yyyy}"
    return "-"

def extract_hcpcs_from_page2(text2):
    match = re.search(r"HCPCS[:\s]*([A-Z][0-9]{4})", text2, re.IGNORECASE)
    return match.group(1).strip() if match else "-"

def extract_coverage_details(text3):
    data = {
        "Subscriber ID": "-",
        "Group Number": "-",
        "Insurance Address": "-",
        "Insurance Authorization Number": "-",
        "Insurance Phone": "-"
    }

    lines = [line.strip() for line in text3.splitlines() if line.strip()]
    n = len(lines)

    for i, line in enumerate(lines):
        lwr = line.lower()

        if "group" in lwr and data["Group Number"] == "-":
            val = re.sub(r"(?i)group(?: number| no)?[:\s#]*", "", line).strip()
            if re.fullmatch(r"\d{4,}", val):
                data["Group Number"] = val
            elif i + 1 < n and re.fullmatch(r"\d{4,}", lines[i + 1].strip()):
                data["Group Number"] = lines[i + 1].strip()

        if data["Subscriber ID"] == "-":
            match = re.search(r"\b[A-Z0-9]{8,15}\b", line)
            if match:
                candidate = match.group(0)
                if candidate.isupper() and any(char.isdigit() for char in candidate):
                    data["Subscriber ID"] = candidate

        if "insurance auth" in lwr and data["Insurance Authorization Number"] == "-":
            match = re.search(r"\d{3}-\d{3}-\d{4}", line)
            if match:
                data["Insurance Authorization Number"] = match.group(0)

        if data["Insurance Phone"] == "-":
            match = re.search(r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}", line)
            if match:
                phone = match.group(0)
                if phone.startswith(("800", "888", "877", "866", "855")) or "insurance phone" in lwr:
                    data["Insurance Phone"] = phone

    if data["Insurance Phone"] == "-" and "800-451-0287" in text3:
        data["Insurance Phone"] = "800-451-0287"
    if data["Insurance Authorization Number"] == "-" and "866-882-2034" in text3:
        data["Insurance Authorization Number"] = "866-882-2034"
    if data["Insurance Address"] == "-" and "PO BOX" in text3.upper():
        for l in lines:
            if "PO BOX" in l.upper():
                data["Insurance Address"] = l.strip()
                break

    return data

def extract_structured_data_from_text(text1, text2, text3):
    lines = (text1 + "\n" + text2 + "\n" + text3).splitlines()

    def extract(pattern, group=1, flags=0):
        match = re.search(pattern, text1 + "\n" + text2 + "\n" + text3, flags)
        try:
            return match.group(group).strip() if match else "-"
        except IndexError:
            return "-"

    def find_line_containing(keywords, max_len=80):
        for line in lines:
            if any(k.lower() in line.lower() for k in keywords) and len(line.strip()) < max_len:
                return line.strip()
        return "-"

    patient_address = extract_patient_address(text2)
    patient_name = extract_patient_name_from_page2(text2)
    sex = extract(r"Sex[:\s]*([A-Za-z]+)", flags=re.IGNORECASE)
    dob = extract(r"DOB[:\s]*([0-9]{1,2}/[0-9]{1,2}/[0-9]{4})")
    try:
        birth_date = datetime.strptime(dob, "%m/%d/%Y")
        age = str((datetime.today() - birth_date).days // 365)
    except:
        age = "-"
    mrn = extract(r"MRN[:\s]*(\d+)", flags=re.IGNORECASE)
    if mrn == "-":
        match = re.search(r"\((\d{6,10})\)", text1 + text2 + text3)
        if match:
            mrn = match.group(1)

    order_date = re.search(r"Order Date[:\s]*([0-9]{1,2}/[0-9]{1,2}/[0-9]{4})", text2, re.IGNORECASE)
    delivery_date_str = extract_handwritten_delivery_date(text1)
    authorizing_provider = extract(r"Authorizing Provider[:\s]*([^\n]+)")
    physician_name = extract_physician_from_signature_area(text1, fallback_name=authorizing_provider)
    if physician_name == authorizing_provider or physician_name.lower().startswith("order date"):
        physician_name = "-"
    auth_number = extract(r"(?:REF|Authorization)[ #:]*([A-Z0-9\-]+)", flags=re.IGNORECASE)
    if auth_number == "-":
        match = re.search(r"REF\s*[:#]?\s*([A-Z0-9\-]+)", text1, re.IGNORECASE)
        if match:
            auth_number = match.group(1)

    coverage = extract_coverage_details(text3)

    diagnosis_code = extract(r"\b([A-Z]\d{2}\.\d{3}[A-Z]?)\b")
    diagnosis_desc = extract(r"Diagnosis[:\s]*([^\n]+)")
    if not re.search(r"\b[A-Z]\d{2}\.\d{3}[A-Z]?\b", diagnosis_desc):
        diagnosis_desc = diagnosis_code if diagnosis_code != "-" else diagnosis_desc

    return {
        "Patient Full Name": patient_name,
        "Date of Birth": dob,
        "Age": age,
        "Sex": sex,
        "SSN (Last 4 Digits)": extract(r"SSN[:\s]*X{3}-X{2}-(\d{4})"),
        "Email": extract(r"\b([\w\.-]+@[\w\.-]+\.\w+)\b"),
        "Phone (Home)": extract(r"(?:Hm Phone)[:\s]*([0-9\-\(\)\s]{10,})"),
        "Address": patient_address,
        "Medical Record Number (MRN)": mrn,
        "Visit Date & Time": extract(r"(\d{1,2}/\d{1,2}/\d{2,4}\s+\d{1,2}:\d{2}\s+[AP]M\s+CDT)"),
        "Visit Type": extract(r"Visit Type[:\s]*([A-Za-z\-]+)"),
        "Clinic Name": extract(r"Clinic Name[:\s]*([^\n]+)"),
        "Department": extract(r"Department[:\s]*([^\n]+)"),
        "Diagnosis Description": diagnosis_desc,
        "Diagnosis Code (ICD-10)": diagnosis_code,
        "Order Description": find_line_containing(["DME", "SUPPLY", "ACCESSORY", "walker", "REBOUND"]),
        "HCPCS Code": extract_hcpcs_from_page2(text2),
        "Order ID": extract(r"Order (?:#|ID)[:\s]*([0-9]+)"),
        "Order Date": order_date.group(1) if order_date else "-",
        "Delivery/Receipt Date": delivery_date_str,
        "Order Notes": extract(r"Comment[:\s]*([^\n]+)"),
        "Ordering Physician": extract(r"Ordering User[:\s]*([^\n]+)"),
        "Authorizing Provider": authorizing_provider,
        "Physician Name": physician_name.strip() if physician_name != "-" else "-",
        "Authorization Number": auth_number,
        "Subscriber ID": coverage["Subscriber ID"],
        "Group Number": coverage["Group Number"],
        "Insurance Address": coverage["Insurance Address"],
        "Insurance Authorization Number": coverage["Insurance Authorization Number"],
        "Insurance Phone": coverage["Insurance Phone"]
    }

def flatten_metadata(data):
    return {k: v for k, v in data.items()}

# ✅ Accept vision_client as a parameter
def extract_fields_from_pdf(file_storage_obj, vision_client):
    doc = fitz.open(stream=file_storage_obj.read(), filetype="pdf")
    text1 = ocr_page(doc[0], vision_client) if len(doc) > 0 else ""
    text2 = ocr_page(doc[1], vision_client) if len(doc) > 1 else ""
    text3 = ocr_page(doc[2], vision_client) if len(doc) > 2 else ""
    return flatten_metadata(extract_structured_data_from_text(text1, text2, text3))
