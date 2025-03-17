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

    for consent in selected_consents:
        pdf_path = f"static/pdfs/{consent}.pdf"
        if not os.path.exists(pdf_path):
            return jsonify({"error": f"PDF 파일이 존재하지 않습니다: {pdf_path}"}), 404

        doc = fitz.open(pdf_path)
        consent_signatures = [sig for sig in signatures if sig["consentId"] == consent]
        
        for area in consent_signatures:
            page_num = area["page"] - 1
            if page_num >= doc.page_count:
                print(f"⚠️ 페이지 번호 {page_num + 1}이 PDF 총 페이지 수({doc.page_count})를 초과합니다.")
                continue
                
            page = doc[page_num]
            pdf_width = page.rect.width
            pdf_height = page.rect.height

            # 클라이언트에서 받은 원본 좌표 (Fabric 캔버스 기준)
            canvas_left = area["left"]
            canvas_top = area["top"]
            canvas_width = area["width"]
            canvas_height = area["height"]
            canvas_scale_x = area.get("scaleFactor", 1.0)  # x축 스케일 (클라이언트 제공)
            canvas_render_height = area.get("pdfHeight", pdf_height)  # 클라이언트에서 받은 렌더링 높이

            # 스케일링 비율 계산
            scale_x = pdf_width / (800 * canvas_scale_x)  # 800은 기본 캔버스 너비
            scale_y = pdf_height / canvas_render_height  # PDF 높이 / 클라이언트 렌더링 높이

            # PDF 좌표계로 변환
            left_scaled = canvas_left * scale_x
            width_scaled = canvas_width * scale_x * 0.7  # 기존 방식 유지
            # y축 변환: Fabric 캔버스의 top을 PDF 좌표계의 상단 기준으로 매핑
            top_scaled = (canvas_top / canvas_render_height) * pdf_height - 2  # 기존 조정값 유지
            height_scaled = canvas_height * scale_y

            # 최종 사각형 좌표
            rect = fitz.Rect(left_scaled, top_scaled, left_scaled + width_scaled, top_scaled + height_scaled)
            print(f"[DEBUG] 원본 좌표: left={canvas_left}, top={canvas_top}, width={canvas_width}, height={canvas_height}")
            print(f"[DEBUG] 스케일링: scale_x={scale_x}, scale_y={scale_y}, pdf_height={pdf_height}, canvas_render_height={canvas_render_height}")
            print(f"[DEBUG] PDF 좌표: left={left_scaled}, top={top_scaled}, width={width_scaled}, height={height_scaled}, rect={rect}")

            # 서명 데이터 디코딩 및 삽입
            sig_img_data = base64.b64decode(signature_data.split(',')[1])
            signature_image = Image.open(io.BytesIO(sig_img_data))

            # 리사이징 품질 개선: 중간 해상도에서 리사이징
            high_res_width = int(width_scaled * 2)  # 2배 크기로 임시 확대
            high_res_height = int(height_scaled * 2)
            signature_high_res = signature_image.resize((high_res_width, high_res_height), Image.LANCZOS)

            # 최종 크기로 리사이징
            signature_resized = signature_high_res.resize((int(width_scaled), int(height_scaled)), Image.LANCZOS)

            # PNG 저장 시 압축 최소화
            img_stream = io.BytesIO()
            signature_resized.save(img_stream, format="PNG", optimize=False, compress_level=0)  # 압축 비활성화
            img_stream.seek(0)

            # DPI 대신 크기 보정으로 품질 개선
            page.insert_image(rect, stream=img_stream, keep_proportion=True)
            print(f"✅ 서명 이미지 삽입 완료: 동의서 {consent}, 페이지 {page_num + 1}")

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