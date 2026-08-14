FROM python:3.13-alpine
WORKDIR /app
COPY deployer/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY deployer/fetch_and_extract.py .
USER 65532:65532
ENTRYPOINT ["python", "/app/fetch_and_extract.py"]
