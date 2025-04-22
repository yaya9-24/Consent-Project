from flask import Flask, render_template, request, send_from_directory, jsonify, send_file
import os
import fitz
import base64
import io
import json
import time
import secrets
import requests
from PIL import Image
from urllib.parse import unquote

app = Flask(__name__, template_folder="templates", static_folder="static")
TEMP_DIR = "/app/temp_files"
if not os.path.exists(TEMP_DIR):
    os.makedirs(TEMP_DIR)
app.config['TEMPLATES_AUTO_RELOAD'] = True  # 템플릿 자동 리로드 활성화

SIGNATURE_DIR = os.path.join(app.root_path, 'get_signature_areas')
FINAL_PDF_PATH = os.path.join(SIGNATURE_DIR, "final_signed_consent.pdf")
TEMP_SIGNATURES = {}
temp_tokens = {}  # 다운로드 토큰 저장용

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

@app.route('/generate_consent', methods=['POST'])
def generate_consent():
    data = request.get_json()
    selected_consents = data.get("selectedConsents", [])
    signatures = data.get("signatures", [])
    signature_data = data.get("signatureData")
    canvas_images = data.get("canvasImages", [])
    patient_id = data.get("patient_id", "unknown")
    patient_birthdate = data.get("birthdate", "19900101")

    if not selected_consents:
        return jsonify({"error": "선택된 동의서가 없습니다."}), 400
    if not signature_data:
        return jsonify({"error": "서명 데이터가 없습니다."}), 400

    timestamp = time.strftime("%Y%m%d%H%M%S")
    final_pdf_filename = f"{patient_id}_{timestamp}_final_consent.pdf"
    final_pdf_path = os.path.join(SIGNATURE_DIR, final_pdf_filename)

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

            for area in consent_signatures:
                if area["page"] - 1 != page_num:
                    continue

                canvas_scale_x = area.get("scaleFactor", 1.0)
                canvas_render_height = area.get("pdfHeight", pdf_height)

                scale_x = pdf_width / (800 * canvas_scale_x)
                scale_y = pdf_height / canvas_render_height

                left_scaled = area["left"] * scale_x - 5
                top_scaled = (area["top"] / canvas_render_height) * pdf_height - 2
                if "width" not in area or "height" not in area:
                    continue
                width_scaled = area["width"] * scale_x * 0.7                
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

    merged_pdf.save(final_pdf_path, deflate=False, garbage=0)
    print(f"✅ 최종 PDF 저장 완료: {final_pdf_path}")

    # PDF 암호화
    #encrypted_pdf_path = final_pdf_path.replace('.pdf', '_encrypted.pdf')
    #doc = fitz.open(final_pdf_path)
    #doc.save(encrypted_pdf_path, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw=patient_birthdate)

    # 다운로드 토큰 생성
    token = secrets.token_urlsafe(16)
    final_filename = os.path.basename(final_pdf_path)  # 암호화된 파일 X
    temp_tokens[token] = {"filename": final_filename, "expires": time.time() + 3600}
    download_url = f"http://210.110.80.5:5000/download?token={token}"

    print(f"✅ 다운로드 링크 생성됨: {download_url}")  # <- 콘솔 확인용 출력

    return jsonify({"url": download_url})

@app.route('/finalize_signatures', methods=['POST'])
def finalize_signatures():
    data = request.get_json()
    selected_consents = data.get("selectedConsents", [])
    signatures = data.get("signatures", [])
    signature_data = data.get("signatureData", None)
    canvas_images = data.get("canvasImages", [])
    patient_id = data.get("patient_id", "unknown")
    patient_birthdate = data.get("birthdate", "19900101")

    if not selected_consents:
        return jsonify({"error": "선택된 동의서가 없습니다."}), 400
    if not signature_data:
        return jsonify({"error": "서명 데이터가 없습니다."}), 400

    # `/generate_consent` 호출
    consent_data = {
        "selectedConsents": selected_consents,
        "signatures": signatures,
        "signatureData": signature_data,
        "canvasImages": canvas_images,
        "patient_id": patient_id,
        "birthdate": patient_birthdate
    }
    response = app.test_client().post('/generate_consent', json=consent_data)
    response_data = response.get_json()

    if "error" in response_data:
        return jsonify(response_data), 404

    download_url = response_data["url"]

    print(f"✅ 다운로드 링크 생성됨: {download_url}")  # <- 콘솔 확인용 출력

    # ✅ 카카오 전송 실패 시 무시
    try:
        send_kakao_friendtalk(patient_id, patient_birthdate, download_url)
    except Exception as e:
        print(f"🚨 카카오톡 전송 실패: {e}")

    return jsonify({"message": "동의서 생성 완료!", "url": download_url})

def send_kakao_friendtalk(patient_id, birthdate, download_url):
    api_url = "https://api-biz.kakao.com/v1/api/talk/friends/message/default/send"
    access_token = "YOUR_KAKAO_BIZ_ACCESS_TOKEN"  # 실제 카카오 비즈니스 API 토큰으로 교체
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    payload = {
        "template_object": {
            "object_type": "text",
            "text": f"환자 {patient_id}님, 동의서를 다운로드하세요.\n비밀번호: {birthdate}",
            "buttons": [{"title": "동의서 다운받기", "link": {"web_url": download_url}}]
        }
    }
    response = requests.post(api_url, headers=headers, json=payload)
    print(f"카톡 전송: {response.status_code}, URL: {download_url}")

@app.route('/download', methods=['GET'])
def download_file():
    token = request.args.get('token')
    if not token or token not in temp_tokens:
        return jsonify({"error": "유효하지 않은 링크"}), 403
    token_info = temp_tokens[token]
    if time.time() > token_info["expires"]:
        del temp_tokens[token]
        return jsonify({"error": "링크 만료"}), 403
    filename = token_info["filename"]
    return send_from_directory(SIGNATURE_DIR, filename, mimetype='application/pdf')

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
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=True)