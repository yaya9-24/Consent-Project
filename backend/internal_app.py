import os
import time
import fitz
import secrets
from flask import Flask, request, jsonify, send_from_directory, abort
from io import BytesIO
from PIL import Image
import base64

app = Flask(__name__)
SIGNATURE_DIR = "./get_signature_areas"  # 로컬 테스트용 경로
if not os.path.exists(SIGNATURE_DIR):
    os.makedirs(SIGNATURE_DIR)

temp_tokens = {}

@app.route('/generate_consent', methods=['POST'])
def generate_consent():
    data = request.get_json()
    selected_consents = data.get("selectedConsents", [])
    signatures = data.get("signatures", [])
    signature_data = data.get("signatureData")
    canvas_images = data.get("canvasImages", [])
    patient_id = data.get("patient_id", "unknown")
    patient_birthdate = data.get("birthdate", "19900101")

    timestamp = time.strftime("%Y%m%d%H%M%S")
    final_pdf_filename = f"{patient_id}_{timestamp}_final_consent.pdf"
    final_pdf_path = os.path.join(SIGNATURE_DIR, final_pdf_filename)

    merged_pdf = fitz.open()

    for consent in selected_consents:
        pdf_path = f"./static/pdfs/{consent}.pdf"
        if not os.path.exists(pdf_path):
            return jsonify({"error": f"PDF 파일 없음: {pdf_path}"}), 404

        doc = fitz.open(pdf_path)
        consent_signatures = [sig for sig in signatures if sig["consentId"] == consent]

        for page_num in range(doc.page_count):
            page = doc[page_num]
            pdf_width = page.rect.width
            pdf_height = page.rect.height

            canvas_image = next((item for item in canvas_images if item["consentId"] == consent and item["page"] == page_num + 1), None)
            if canvas_image and canvas_image["canvasImage"]:
                canvas_img_data = base64.b64decode(canvas_image["canvasImage"].split(',')[1])
                canvas_image = Image.open(BytesIO(canvas_img_data))
                canvas_resized = canvas_image.resize((int(pdf_width), int(pdf_height)))
                img_stream = BytesIO()
                canvas_resized.save(img_stream, format="PNG")
                img_stream.seek(0)
                page.insert_image(fitz.Rect(0, 0, pdf_width, pdf_height), stream=img_stream)

            for area in consent_signatures:
                if area["page"] - 1 != page_num:
                    continue
                scale_x = pdf_width / (800 * area.get("scaleFactor", 1.0))
                scale_y = pdf_height / area.get("pdfHeight", pdf_height)
                left_scaled = area["left"] * scale_x - 5
                width_scaled = area["width"] * scale_x * 0.7
                top_scaled = (area["top"] / area.get("pdfHeight", pdf_height)) * pdf_height - 2
                height_scaled = area["height"] * scale_y

                rect = fitz.Rect(left_scaled, top_scaled, left_scaled + width_scaled, top_scaled + height_scaled)
                sig_img_data = base64.b64decode(signature_data.split(',')[1])
                signature_image = Image.open(BytesIO(sig_img_data))
                signature_resized = signature_image.resize((int(width_scaled), int(height_scaled)))
                img_stream = BytesIO()
                signature_resized.save(img_stream, format="PNG")
                img_stream.seek(0)
                page.insert_image(rect, stream=img_stream)

        merged_pdf.insert_pdf(doc)

    merged_pdf.save(final_pdf_path)
    encrypted_pdf_path = final_pdf_path.replace('.pdf', '_encrypted.pdf')
    doc = fitz.open(final_pdf_path)
    doc.save(encrypted_pdf_path, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw=patient_birthdate)

    token = secrets.token_urlsafe(16)
    temp_tokens[token] = {"filename": final_pdf_filename, "expires": time.time() + 3600}
    internal_url = f"http://210.110.85.40:5001/download?token={token}"
    return jsonify({"url": internal_url})

@app.route('/download', methods=['GET'])
def download_file():
    token = request.args.get('token')
    if not token or token not in temp_tokens:
        abort(403, "유효하지 않은 링크")
    token_info = temp_tokens[token]
    if time.time() > token_info["expires"]:
        del temp_tokens[token]
        abort(403, "링크 만료")
    filename = token_info["filename"]
    return send_from_directory(SIGNATURE_DIR, filename, mimetype='application/pdf')

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)