# 1. Official Microsoft image with Python 3.11 + Playwright/Chromium pre-installed
FROM mcr.microsoft.com/playwright/python:v1.61.0-jammy

# 2. Set working directory
WORKDIR /app

# 3. Copy & install requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. Copy the rest of your code
COPY . .

# 5. Set PYTHONPATH
ENV PYTHONPATH="/app:/app/src"

# 6. Start the bot
CMD ["python", "src/main.py"]