FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app app
COPY frontend frontend
RUN useradd -m app && chown -R app /srv
USER app
EXPOSE 8000
# init only creates missing tables / departments / admin logins; existing data is never overwritten
CMD ["sh","-c","python -m app.manage init && exec gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w ${WORKERS:-4} -b 0.0.0.0:8000 --timeout 60 --graceful-timeout 30 --max-requests 5000 --max-requests-jitter 500 --access-logfile -"]
