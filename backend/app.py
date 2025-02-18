from flask import Flask, render_template, request, send_from_directory
import os

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

if __name__ == '__main__':
    app.run(debug=True)