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
TEMP_SIGNATURES = {}  # ✅ 모든 서명을 메모리에 저장하는 딕셔너리

@app.route('/')
def index():
    return render_template("index.html")

@app.route('/consent')
def consent():
    return render_template("consent.html")

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

    # 서명 데이터 디코딩
    signature_data = base64.b64decode(signature_b64.split(',')[1])
    signature_image = Image.open(io.BytesIO(signature_data))

    # 서명 크기 자동 조정
    signature_resized = signature_image.resize((int(area["width"]), int(area["height"])))

    # PDF에 서명 삽입
    doc = fitz.open(pdf_path)
    page_number = area.get("page", 1)
    page = doc[page_number - 1]
    img_rect = fitz.Rect(area["left"], area["top"], area["left"] + area["width"], area["top"] + area["height"])

    img_stream = io.BytesIO()
    signature_resized.save(img_stream, format="PNG")
    img_stream.seek(0)

    page.insert_image(img_rect, stream=img_stream, keep_proportion=True)

    doc.save(signed_pdf_path)

    # ✅ 서명된 PDF가 생성되었는지 확인
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

    if not selected_consents:
        return jsonify({"error": "선택된 동의서가 없습니다."}), 400

    if not signature_data:
        return jsonify({"error": "서명 데이터가 없습니다."}), 400

    merged_pdf = fitz.open()

    # 각 동의서별 처리
    for consent in selected_consents:
        pdf_path = f"static/pdfs/{consent}.pdf"
        if not os.path.exists(pdf_path):
            return jsonify({"error": f"PDF 파일이 존재하지 않습니다: {pdf_path}"}), 404

        doc = fitz.open(pdf_path)
        # 각 서명 영역에 대해 처리
        for sig in signatures:
            if sig["consentId"] == consent:
                page_num = sig.get("page", 1)
                try:
                    page = doc[page_num - 1]
                except IndexError:
                    continue  # 해당 페이지가 없으면 건너뜁니다.
                # 클라이언트에서 전달한 좌표 값들
                left = sig["left"]
                top = sig["top"]
                width = sig["width"]
                height = sig["height"]

                # PDF 페이지의 실제 높이
                pdf_height = page.rect.height

                # 클라이언트 캔버스 높이는 각 페이지마다 다를 수 있으므로, sig에서 전달한 값을 사용 (없으면 기본 1126)
                client_canvas_height = sig.get("canvasHeight", 1126.0)

                # 스케일 계수 계산: PDF의 실제 높이에 대한 클라이언트 캔버스 높이 비율
                scale_factor = pdf_height / client_canvas_height
                left_scaled = left * scale_factor
                top_scaled = top * scale_factor
                width_scaled = width * scale_factor
                height_scaled = height * scale_factor

                # PDF 좌표는 하단 기준이므로 top 변환
                new_top = pdf_height - top_scaled - height_scaled

                # 디버깅 로그
                print(f"[DEBUG] Consent: {consent}, Page: {page_num}")
                print(f"[DEBUG] PDF 페이지 높이: {pdf_height}")
                print(f"[DEBUG] 원본 좌표: left={left}, top={top}, width={width}, height={height}")
                print(f"[DEBUG] 스케일 적용 후: left={left_scaled}, top={top_scaled}, width={width_scaled}, height={height_scaled}")
                print(f"[DEBUG] 변환된 top: {new_top}")
                rect = fitz.Rect(left_scaled, new_top, left_scaled + width_scaled, new_top + height_scaled)
                print(f"[DEBUG] 삽입될 Rect: {rect}")

                try:
                    # 서명 데이터 디코딩
                    sig_img_data = base64.b64decode(signature_data.split(',')[1])
                    # 이미지 생성 및 크기 조정
                    signature_image = Image.open(io.BytesIO(sig_img_data))
                    signature_resized = signature_image.resize((int(width_scaled), int(height_scaled)))
                    img_stream = io.BytesIO()
                    signature_resized.save(img_stream, format="PNG")
                    img_stream.seek(0)
                    page.insert_image(rect, stream=img_stream, keep_proportion=True, overlay=True)
                except Exception as e:
                    print(f"서명 삽입 중 오류 발생: {e}")
        merged_pdf.insert_pdf(doc)

    merged_pdf.save(FINAL_PDF_PATH)
    return jsonify({"message": "서명 저장 완료!", "signed_pdf": FINAL_PDF_PATH})

# ✅ 여러 개의 PDF를 병합하는 함수
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