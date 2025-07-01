from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import os, fitz, io, json
from PIL import Image
from fpdf import FPDF
from extract_fields_from_pdf import extract_fields_from_pdf, flatten_metadata
from google.cloud import vision
from google.oauth2 import service_account

# Initialize Flask app
app = Flask(__name__)
CORS(app)

# Output folder for PDF export
OUTPUT_FOLDER = "output"
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# Read the JSON string from Railway environment variable
credentials_json = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON")

if not credentials_json:
    raise ValueError("GOOGLE_APPLICATION_CREDENTIALS_JSON env variable is missing")

# Convert JSON string to dictionary
credentials_dict = json.loads(credentials_json)

# Create credentials object from the dict
credentials = service_account.Credentials.from_service_account_info(credentials_dict)

# Create the Vision API client with the loaded credentials
vision_client = vision.ImageAnnotatorClient(credentials=credentials)

# ✅ OCR helper (currently unused, but kept for extensibility)
def ocr_with_google_vision(image: Image.Image) -> str:
    buffered = io.BytesIO()
    image.save(buffered, format="JPEG")
    content = buffered.getvalue()
    response = vision_client.document_text_detection(image=vision.Image(content=content))
    return response.full_text_annotation.text if response.full_text_annotation.text else ""

# ✅ OCR and Metadata Extraction Endpoint
@app.route("/api/ocr", methods=["POST"])
def ocr_pdf():
    file = request.files.get("file")
    if not file or not file.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Please upload a valid PDF file"}), 400

    try:
        extracted = extract_fields_from_pdf(file)
        flattened = flatten_metadata(extracted)
        return jsonify({"metadata": flattened})
    except Exception as e:
        print("[ERROR] OCR processing failed:", e)
        return jsonify({"error": "OCR processing failed"}), 500

# ✅ PDF Report Class for Export
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

# ✅ PDF Export Endpoint
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

# ✅ Root Route
@app.route("/")
def home():
    return "Flask OCR backend running"

# ✅ App Entrypoint
if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8000)
