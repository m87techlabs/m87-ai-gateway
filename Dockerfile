FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY config.example.yaml ./config.example.yaml

RUN pip install --no-cache-dir .

EXPOSE 8080

CMD ["uvicorn", "m87_gateway.main:app", "--host", "0.0.0.0", "--port", "8080"]
