# ---- build stage: install dependencies into an isolated prefix ----
FROM python:3.12-alpine AS builder
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --no-compile --prefix=/install -r requirements.txt \
 && find /install -type d \( -name tests -o -name test \) -prune -exec rm -rf {} +

# ---- runtime stage: Python + deps + the one script, nothing else ----
FROM python:3.12-alpine
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
COPY --from=builder /install /usr/local
WORKDIR /app
COPY run.py .
RUN adduser -D -H app
USER app
CMD ["python", "run.py"]