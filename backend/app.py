from flask import Flask, render_template, request, send_from_directory, jsonify
import os
import fitz
import base64
import io
import json
from PIL import Image
from urllib.parse import unquote

app = Flask(__name__, template_folder="templates", static_folder="static")

SIGNATURE_DIR = os.path.join(app.root_path, 'get_signature_areas')
FINAL_PDF_PATH = os.path.join(SIGNATURE_DIR, "final_signed_consent.pdf")
TEMP_SIGNATURES = {}

@app.route('/')
def index():
    return render_template("index.html")

@app.route('/consent')
def consent():
    return render_template("consent.html")

@app.route('/admin')
def admin():
    return render_template("admin.html")

@app.route('/static/pdfs/<filename>')
def serve_pdf(filename):
    return send_from_directory('static/pdfs', filename, mimetype='application/pdf')

@app.route('/backend/get_signature_areas/<path:filename>')
def get_signature_areas(filename):
    decoded_filename = unquote(filename)
    file_path = os.path.join(SIGNATURE_DIR, decoded_filename)
    if os.path.exists(file_path):
        return send_from_directory(SIGNATURE_DIR, decoded_filename)
    else:
        print(f"🚨 파일을 찾을 수 없음: {file_path}")
        return jsonify({"error": "파일을 찾을 수 없습니다."}), 404

@app.route('/upload_signature', methods=['POST'])
def upload_signature():
    data = request.json
    signature_b64 = data['signature']
    area = data['area']
    consent_id = data.get("consent_id", "basic_consent")

    pdf_path = f"static/pdfs/{consent_id}.pdf"
    signed_pdf_path = f"static/pdfs/{consent_id}_signed.pdf"

    if not os.path.exists(pdf_path):
        print(f"🚨 [오류] PDF 파일이 존재하지 않습니다: {pdf_path}")
        return jsonify({"error": f"PDF 파일이 존재하지 않습니다: {pdf_path}"}), 404

    print(f"📌 [서명 요청] 동의서 ID = {consent_id}")
    print(f"📌 원본 PDF 경로 = {pdf_path}")
    print(f"📌 저장될 서명 PDF 경로 = {signed_pdf_path}")

    signature_data = base64.b64decode(signature_b64.split(',')[1])
    signature_image = Image.open(io.BytesIO(signature_data))
    signature_resized = signature_image.resize((int(area["width"]), int(area["height"])))

    doc = fitz.open(pdf_path)
    page_number = area.get("page", 1)
    page = doc[page_number - 1]
    img_rect = fitz.Rect(area["left"], area["top"], area["left"] + area["width"], area["top"] + area["height"])

    img_stream = io.BytesIO()
    signature_resized.save(img_stream, format="PNG")
    img_stream.seek(0)

    page.insert_image(img_rect, stream=img_stream, keep_proportion=True)
    doc.save(signed_pdf_path)

    if os.path.exists(signed_pdf_path):
        print(f"✅ [성공] 서명된 PDF 저장 완료: {signed_pdf_path}")
    else:
        print(f"🚨 [오류] 서명된 PDF 생성 실패: {signed_pdf_path}")

    return jsonify({"message": "서명 추가 완료!", "signed_pdf": signed_pdf_path})

@app.route('/finalize_signatures', methods=['POST'])
def finalize_signatures():
    data = request.get_json()
    selected_consents = data.get("selectedConsents", [])
    signatures = data.get("signatures", [])
    signature_data = data.get("signatureData", None)
    canvas_images = data.get("canvasImages", [])

    if not selected_consents:
        return jsonify({"error": "선택된 동의서가 없습니다."}), 400

    if not signature_data:
        return jsonify({"error": "서명 데이터가 없습니다."}), 400

    merged_pdf = fitz.open()

    for consent in selected_consents:
        pdf_path = f"static/pdfs/{consent}.pdf"
        if not os.path.exists(pdf_path):
            return jsonify({"error": f"PDF 파일이 존재하지 않습니다: {pdf_path}"}), 404

        doc = fitz.open(pdf_path)
        consent_signatures = [sig for sig in signatures if sig["consentId"] == consent]
        
        for page_num in range(doc.page_count):
            page = doc[page_num]
            pdf_width = page.rect.width
            pdf_height = page.rect.height

            # 캔버스 이미지 삽입
            canvas_image_data = next((item for item in canvas_images if item["consentId"] == consent and item["page"] == page_num + 1), None)
            if canvas_image_data and canvas_image_data["canvasImage"]:
                canvas_img_data = base64.b64decode(canvas_image_data["canvasImage"].split(',')[1])
                canvas_image = Image.open(io.BytesIO(canvas_img_data))
                canvas_resized = canvas_image.resize((int(pdf_width), int(pdf_height)), Image.LANCZOS)
                img_stream = io.BytesIO()
                canvas_resized.save(img_stream, format="PNG", optimize=False, compress_level=0)
                img_stream.seek(0)
                canvas_rect = fitz.Rect(0, 0, pdf_width, pdf_height)
                page.insert_image(canvas_rect, stream=img_stream, keep_proportion=True)
                print(f"✅ 캔버스 이미지 삽입 완료: 동의서 {consent}, 페이지 {page_num + 1}")

            # 서명 삽입
            for area in consent_signatures:
                if area["page"] - 1 != page_num:
                    continue

                canvas_scale_x = area.get("scaleFactor", 1.0)
                canvas_render_height = area.get("pdfHeight", pdf_height)

                scale_x = pdf_width / (800 * canvas_scale_x)
                scale_y = pdf_height / canvas_render_height

                left_scaled = area["left"] * scale_x - 5
                width_scaled = area["width"] * scale_x * 0.7
                top_scaled = (area["top"] / canvas_render_height) * pdf_height - 2
                height_scaled = area["height"] * scale_y

                rect = fitz.Rect(left_scaled, top_scaled, left_scaled + width_scaled, top_scaled + height_scaled)
                print(f"[DEBUG] 원본 좌표: left={area['left']}, top={area['top']}, width={area['width']}, height={area['height']}")
                print(f"[DEBUG] 스케일링: scale_x={scale_x}, scale_y={scale_y}, pdf_height={pdf_height}, canvas_render_height={canvas_render_height}")
                print(f"[DEBUG] PDF 좌표: left={left_scaled}, top={top_scaled}, width={width_scaled}, height={height_scaled}, rect={rect}")

                sig_img_data = base64.b64decode(signature_data.split(',')[1])
                signature_image = Image.open(io.BytesIO(sig_img_data))
                high_res_width = int(width_scaled * 3)
                high_res_height = int(height_scaled * 3)
                signature_high_res = signature_image.resize((high_res_width, high_res_height), Image.LANCZOS)
                signature_resized = signature_high_res.resize((int(width_scaled), int(height_scaled)), Image.LANCZOS)

                img_stream = io.BytesIO()
                signature_resized.save(img_stream, format="PNG", optimize=False, compress_level=0)
                img_stream.seek(0)

                page.insert_image(rect, stream=img_stream, keep_proportion=True)
                print(f"✅ 서명 이미지 삽입 완료: 동의서 {consent}, 페이지 {page_num + 1}")

        merged_pdf.insert_pdf(doc)

    merged_pdf.save(FINAL_PDF_PATH, deflate=False, garbage=0)
    return jsonify({"message": "서명 저장 완료!", "signed_pdf": FINAL_PDF_PATH})

def merge_pdfs(pdf_list, output_path):
    try:
        merged_doc = fitz.open()
        for pdf in pdf_list:
            if not os.path.exists(pdf):
                print(f"🚨 [오류] 병합할 PDF가 존재하지 않음: {pdf}")
                continue
            with fitz.open(pdf) as doc:
                merged_doc.insert_pdf(doc)
        if merged_doc.page_count == 0:
            print("🚨 [오류] 병합할 PDF가 없음. 병합 수행 불가.")
            return False
        merged_doc.save(output_path)
        print(f"✅ [성공] 모든 동의서가 병합된 PDF 저장 완료: {output_path}")
        return True
    except Exception as e:
        print(f"🚨 [오류] PDF 병합 중 예외 발생: {str(e)}")
        return False

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000, debug=True)