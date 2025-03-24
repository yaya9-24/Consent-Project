# Python 3.12 기반 이미지 사용
FROM python:3.10-slim

# 작업 디렉토리 설정
WORKDIR /app

# 의존성 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 프로젝트 파일 전체 복사
COPY . .

# Flask 환경 변수 설정
ENV FLASK_ENV=production

# 앱 실행
CMD ["python", "app.py"]