FROM python:3.13-slim

# suricata -T 와 리로드를 IDS 컨테이너 안에서 실행하기 위한 Docker CLI.
# 데몬은 필요 없고 클라이언트만 있으면 된다.
COPY --from=docker:27-cli /usr/local/bin/docker /usr/local/bin/docker

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

EXPOSE 8000
CMD ["sh", "-c", "python manage.py migrate --noinput && python manage.py runserver 0.0.0.0:8000"]
