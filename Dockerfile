FROM python:3.12-slim

WORKDIR /app

# Install dependencies first for better layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app.py optimizer.py machine_db.py copilot.py lapp_shop_proxy.py README.md ./
COPY templates/ templates/
COPY static/ static/
COPY graph_store/ graph_store/
COPY application_scenarios.csv ./

EXPOSE 8000

CMD ["uvicorn", "src.app:app", "--host", "0.0.0.0", "--port", "8000"]
