import os
import io
from transformers import TrOCRProcessor, VisionEncoderDecoderModel
from PIL import Image
import fitz  # PyMuPDF

# Load model and processor
processor = TrOCRProcessor.from_pretrained("microsoft/trocr-base-handwritten")
model = VisionEncoderDecoderModel.from_pretrained("microsoft/trocr-base-handwritten")

def extract_physician_name_from_pdf(pdf_path, page_num=0, region=(100, 1200, 500, 1300), save_preview=True):
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"❌ File not found: {pdf_path}")

    doc = fitz.open(pdf_path)
    if page_num >= len(doc):
        raise ValueError(f"❌ Page {page_num} does not exist in PDF with {len(doc)} pages.")

    page = doc[page_num]
    print("📐 PDF Page Size (pts):", page.rect)

    clip_rect = fitz.Rect(*region)
    pix = page.get_pixmap(dpi=300, clip=clip_rect)
    img = Image.open(io.BytesIO(pix.tobytes())).convert("RGB")

    if save_preview:
        img.save("physician_crop_preview.jpg")
        print("✅ Saved crop preview as 'physician_crop_preview.jpg'")

    # Inference with TrOCR
    pixel_values = processor(images=img, return_tensors="pt").pixel_values
    generated_ids = model.generate(pixel_values)
    predicted_text = processor.batch_decode(generated_ids, skip_special_tokens=True)[0]

    return predicted_text.strip()

# ---------- MAIN ----------
if __name__ == "__main__":
    # Absolute or relative to working dir
    pdf_file = "uploads/04242025 NIANEQUA CIARA BRACKEN PPA.pdf"

    try:
        physician_name = extract_physician_name_from_pdf(pdf_file, region=(100, 700, 500, 770))
        print("\n✅ Extracted Physician Name:", physician_name)
    except Exception as e:
        print(f"\n❌ Error: {e}")
