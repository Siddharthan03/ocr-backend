from flask import Flask, request, jsonify
from flask_cors import CORS
import os, json
from extract_fields_from_pdf import extract_fields_from_pdf, flatten_metadata
from google.cloud import vision
from google.oauth2 import service_account

# Initialize Flask app
app = Flask(__name__)
CORS(app)

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

# ✅ Root route to verify backend is running
@app.route("/")
def home():
    return "✅ Flask OCR backend is running"

# ✅ App Entrypoint
if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8000)
