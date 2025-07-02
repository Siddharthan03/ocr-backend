from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import os, fitz, io, json, base64
from PIL import Image
from fpdf import FPDF
from extract_fields_from_pdf import extract_fields_from_pdf, flatten_metadata
from google.cloud import vision
from google.oauth2 import service_account

# Initialize Flask app
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "https://ocr-frontend-opal.vercel.app"}})

# Output folder for PDF export
OUTPUT_FOLDER = "output"
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# Read and decode base64-encoded credentials
encoded_json = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_B64")
if not encoded_json:
    raise ValueError("GOOGLE_APPLICATION_CREDENTIALS_B64 env variable is missing")

try:
    decoded_json = base64.b64decode(encoded_json).decode("utf-8")
    credentials_dict = json.loads(decoded_json)
except Exception as e:
    raise RuntimeError(f"Failed to decode credentials: {e}")

# Initialize Google Vision client
credentials = service_account.Credentials.from_service_account_info(credentials_dict)
vision_client = vision.ImageAnnotatorClient(credentials=credentials)

# OCR endpoint
PATIENT_RECT = fitz.Rect(0, 540, 370, 620)
PHYSICIAN_RECT = fitz.Rect(0, 340, 370, 410)

# ✅ Save cropped signature image from PDF
def save_signature_image(pdf_bytes, rect, label):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = doc[0]
    pix = page.get_pixmap(clip=rect, dpi=200)
    filename = f"{label}_{uuid.uuid4().hex}.png"
    path = os.path.join(SIGNATURE_FOLDER, filename)
    pix.save(path)
    return path

# ✅ Serve signature image
@app.route("/signatures/<filename>")
def serve_signature(filename):
    return send_from_directory(SIGNATURE_FOLDER, filename)

# ✅ OCR + Signature Extraction
@app.route("/api/ocr", methods=["POST"])
def ocr_pdf():
    file = request.files.get("file")
    if not file or not file.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Please upload a valid PDF file"}), 400

    try:
        file_bytes = file.read()
        extracted = extract_fields_from_pdf(io.BytesIO(file_bytes))
        flattened = flatten_metadata(extracted)
        flattened["File Name"] = file.filename

        patient_sig = save_signature_image(file_bytes, PATIENT_RECT, "patient")
        physician_sig = save_signature_image(file_bytes, PHYSICIAN_RECT, "physician")

        flattened["Patient Signature"] = f"/signatures/{os.path.basename(patient_sig)}"
        flattened["Physician Signature"] = f"/signatures/{os.path.basename(physician_sig)}"

        return jsonify({
            "metadata": flattened,
            "patient_signature": flattened["Patient Signature"],
            "physician_signature": flattened["Physician Signature"]
        })
    except Exception as e:
        print("[ERROR] OCR failed:", e)
        return jsonify({"error": "OCR processing failed"}), 500

# ✅ Export to Excel with embedded images
@app.route("/api/export-excel", methods=["POST"])
def export_excel():
    global all_metadata
    content = request.json
    if content and "metadata" in content:
        all_metadata.append(content["metadata"])

    if not all_metadata:
        return jsonify({"error": "No metadata to export"}), 400

    all_keys = list({k for d in all_metadata for k in d.keys()})
    ordered = ["File Name"] + sorted(k for k in all_keys if k not in ["File Name", "Patient Signature", "Physician Signature"]) + ["Patient Signature", "Physician Signature"]

    wb = Workbook()
    ws = wb.active
    ws.title = "Metadata"

    header_font = Font(bold=True, size=12)
    for i, key in enumerate(ordered, 1):
        cell = ws.cell(row=1, column=i, value=key)
        cell.font = header_font
        ws.column_dimensions[get_column_letter(i)].width = 30  # wider columns

    for row_idx, data in enumerate(all_metadata, 2):
        row_has_image = False

        for col_idx, key in enumerate(ordered, 1):
            value = data.get(key, "-")
            cell_ref = f"{get_column_letter(col_idx)}{row_idx}"

            if key in ["Patient Signature", "Physician Signature"] and isinstance(value, str):
                relative_path = value.replace("/signatures/", "")
                image_path = os.path.join(SIGNATURE_FOLDER, relative_path)

                if os.path.exists(image_path):
                    try:
                        img = ExcelImage(image_path)
                        img.width = 200
                        img.height = 80
                        ws.add_image(img, cell_ref)
                        row_has_image = True
                    except Exception as e:
                        ws[cell_ref] = "Image error"
                else:
                    ws[cell_ref] = "Not found"
            else:
                ws[cell_ref] = value

        if row_has_image:
            ws.row_dimensions[row_idx].height = 90  # taller row for images

    with NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        wb.save(tmp.name)
        tmp.seek(0)
        return send_file(tmp.name, as_attachment=True, download_name="metadata_output.xlsx")

# ✅ PDF Export Endpoint (unchanged)
@app.route("/api/export-pdf", methods=["POST"])
def export_pdf():
    content = request.json
    if not content or "metadata" not in content:
        return jsonify({"error": "Missing metadata"}), 400

    pdf = PDFReport()
    pdf.add_page()
    pdf.add_metadata_table(content["metadata"])

    path = os.path.join(OUTPUT_FOLDER, "metadata_output.pdf")
    pdf.output(path)
    return send_file(path, as_attachment=True)

class PDFReport(FPDF):
    def header(self):
        self.set_font("Arial", "B", 14)
        self.cell(0, 10, "Patient Metadata Extract", ln=True, align="C")
        self.ln(6)

    def add_metadata_table(self, metadata):
        self.set_font("Arial", "B", 12)
        self.cell(90, 10, "Field", 1)
        self.cell(100, 10, "Value", 1)
        self.ln()
        self.set_font("Arial", "", 11)
        for key, value in metadata.items():
            if key not in ["Patient Signature", "Physician Signature"]:
                val = str(value).replace("Address:", "").replace("Employer:", "").strip()
                self.cell(90, 10, key, 1)
                self.multi_cell(100, 10, val, 1)

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8000)
