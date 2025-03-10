from flask import Flask, render_template, request, send_from_directory, jsonify
import os
import fitz
import base64
import io
import json
from PIL import Image 
from urllib.parse import unquote

app = Flask(__name__, template_folder="templates", static_folder="static")

@app.route('/')
def index():
    return render_template("index.html")

@app.route('/consent')
def consent():
    # selected = request.args.get("selected", "").split(",")
    return render_template("consent.html")

# 정적 파일 (PDF) 제공 라우트
@app.route('/static/pdfs/<filename>')
def serve_pdf(filename):
    return send_from_directory('static/pdfs', filename)

SIGNATURE_DIR = os.path.join(app.root_path,'get_signature_areas')


@app.route('/backend/get_signature_areas/<path:filename>')
def get_signature_areas(filename):
    decoded_filename = unquote(filename)
    file_path = os.path.join(SIGNATURE_DIR, decoded_filename)

    if os.path.exists(file_path):
        return send_from_directory(SIGNATURE_DIR, decoded_filename)
    else:
        print(f"🚨 파일을 찾을 수 없음: {file_path}")
        return jsonify({"error": "파일을 찾을 수 없습니다."}), 404

# 관리자 페이지 제공
@app.route('/admin')
def admin():
    return render_template('admin.html')  # 위의 admin.html 파일을 templates 폴더에 저장

# 서명 영역 저장 엔드포인트
@app.route('/save_signature_area', methods=['POST'])
def save_signature_area():
    data = request.get_json()
    template = data.get("template")  # 예: 'sample'
    areas = data.get("areas")        # 서명 영역 리스트
    # 여기서 DB에 저장하거나 파일로 저장하는 코드를 추가합니다.
    # 예: JSON 파일로 저장
    with open(f"{template}_signature_areas.json", "w", encoding="utf-8") as f:
        json.dump(areas, f, ensure_ascii=False, indent=2)
    return jsonify({"message": "서명 영역이 저장되었습니다."})
    
@app.route('/upload_signature', methods=['POST'])
def upload_signature():
    data = request.json
    signature_b64 = data['signature']
    area = data['area']
    consent_id = data.get("consent_id", "basic_consent")  # ✅ 동의서 ID 가져오기 (기본값: basic_consent)

    # ✅ 동의서별 PDF 파일 경로 설정
    pdf_path = f"static/pdfs/{consent_id}.pdf"
    signed_pdf_path = f"static/pdfs/{consent_id}_signed.pdf"

    if not os.path.exists(pdf_path):
        return jsonify({"error": f"PDF 파일이 존재하지 않습니다: {pdf_path}"}), 404

    # 서명 데이터 디코딩
    signature_data = base64.b64decode(signature_b64.split(',')[1])
    signature_image = Image.open(io.BytesIO(signature_data))

    # 서명 크기 자동 조정
    signature_resized = signature_image.resize((int(area["width"]), int(area["height"])))

    # PDF에 서명 삽입
    doc = fitz.open(pdf_path)
    page_number = area.get("page", 1)  # page 정보가 없으면 1페이지 사용
    page = doc[page_number - 1]
    img_rect = fitz.Rect(area["left"], area["top"], area["left"] + area["width"], area["top"] + area["height"])

    img_stream = io.BytesIO()
    signature_resized.save(img_stream, format="PNG")
    img_stream.seek(0)

    page.insert_image(img_rect, stream=img_stream, keep_proportion=True)

    # ✅ 서명된 PDF를 동의서별로 저장
    doc.save(signed_pdf_path)

    return jsonify({"message": "서명 추가 완료!", "signed_pdf": signed_pdf_path})


if __name__ == '__main__':
    app.run(debug=True)