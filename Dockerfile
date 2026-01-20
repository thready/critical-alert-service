FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY critical_alert_service ./critical_alert_service

ENV PORT=8080
EXPOSE 8080

ENTRYPOINT ["python", "-m", "critical_alert_service"]
