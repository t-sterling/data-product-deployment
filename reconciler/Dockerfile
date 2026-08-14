FROM python:3.13-alpine
RUN apk add --no-cache ca-certificates git
WORKDIR /app
COPY reconciler/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY reconciler/reconcile.py .
USER 65532:65532
ENTRYPOINT ["python", "/app/reconcile.py"]
