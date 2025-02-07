from flask import Flask, render_template, request, send_from_directory
import os

app = Flask(__name__, template_folder="templates", static_folder="static")

@app.route('/')
def index():
    return render_template("index.html")

@app.route('/consent')
def consent():
    selected = request.args.get("selected", "").split(",")
    return render_template("consent.html", selected=selected)

# 정적 파일 (PDF) 제공 라우트
@app.route('/static/pdfs/<filename>')
def serve_pdf(filename):
    return send_from_directory('static/pdfs', filename)

if __name__ == '__main__':
    app.run(debug=True)