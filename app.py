from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import os, fitz, io, json, base64
from PIL import Image
from fpdf import FPDF
from extract_fields_from_pdf import extract_fields_from_pdf, flatten_metadata
from google.cloud import vision
from google.oauth2 import service_account

app = Flask(__name__)
CORS(app)

# Output folder for exported PDFs
OUTPUT_FOLDER = "output"
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# ✅ Decode base64-encoded Google service credentials
encoded_json = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_B64")

if not encoded_json:
    raise RuntimeError("❌ Missing GOOGLE_APPLICATION_CREDENTIALS_B64 environment variable")

try:
    # Remove spaces/newlines if present
    encoded_json_clean = encoded_json.strip().replace('\n', '')
    decoded_json = base64.b64decode(encoded_json_clean).decode("utf-8")
    credentials_dict = json.loads(decoded_json)
    credentials = service_account.Credentials.from_service_account_info(credentials_dict)
    vision_client = vision.ImageAnnotatorClient(credentials=credentials)
except Exception as e:
    raise RuntimeError(f"❌ Failed to decode credentials: {e}")

# ✅ OCR Endpoint
@app.route("/api/ocr", methods=["POST"])
def ocr_pdf():
    file = request.files.get("file")
    if not file or not file.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Please upload a valid PDF file"}), 400

    try:
        extracted = extract_fields_from_pdf(file, vision_client=vision_client)
        flattened = flatten_metadata(extracted)
        return jsonify({"metadata": flattened})
    except Exception as e:
        print("[ERROR] OCR processing failed:", e)
        return jsonify({"error": "OCR processing failed"}), 500

# ✅ PDF Export Class (Optional)
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
            value_str = str(value).replace("Address:", "").replace("Employer:", "").strip()
            self.cell(90, 10, key, 1)
            self.multi_cell(100, 10, value_str, 1)

# ✅ Export to PDF Endpoint
@app.route("/api/export-pdf", methods=["POST"])
def export_pdf():
    content = request.json
    if not content or "metadata" not in content:
        return jsonify({"error": "Missing metadata"}), 400

    pdf = PDFReport()
    pdf.add_page()
    pdf.add_metadata_table(content["metadata"])

    pdf_path = os.path.join(OUTPUT_FOLDER, "metadata_output.pdf")
    pdf.output(pdf_path)
    return send_file(pdf_path, as_attachment=True)

# ✅ Root
@app.route("/")
def home():
    return "✅ Flask OCR backend running."

# ✅ Start App
if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8000)
