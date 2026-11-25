# ATS System: Streamlit app with Tesseract OCR.
# Build:  docker build -t ats-system --build-arg LLM_PACKAGE=langchain-groq .
# Run:    docker run --rm -p 8501:8501 --env-file .env ats-system
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    STREAMLIT_SERVER_FILE_WATCHER_TYPE=none \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

# Tesseract is used for the OCR checks (scanned resumes and the text-layer comparison).
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

# Run as a normal user, not as root.
RUN useradd --create-home --uid 10001 app
WORKDIR /app

# Install the Python packages first so Docker can reuse this layer when only the code changes.
# LLM_PACKAGE is the LangChain package for your provider: langchain-groq, langchain-google-genai,
# langchain-openai or langchain-anthropic.
ARG LLM_PACKAGE=langchain-groq
COPY requirements.txt .
RUN pip install -r requirements.txt \
    && pip install reportlab python-dotenv "${LLM_PACKAGE}"

COPY --chown=app:app . .
USER app

EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=4).status == 200 else 1)"

CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
