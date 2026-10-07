FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY tvdata tvdata

# Set TVDATA_PASSWORD where this runs. Without it the page is open to anyone who can reach it.
ENV PORT=8770
EXPOSE 8770
USER nobody
CMD ["sh", "-c", "exec python -m uvicorn tvdata.web:app --host 0.0.0.0 --port ${PORT}"]
