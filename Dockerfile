FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY .streamlit/ .streamlit/
COPY src/ src/
COPY tests/ tests/
ENV PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "-m", "epiextract.cli"]
CMD ["--help"]
