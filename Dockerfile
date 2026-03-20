# 1. Use a standard Python image
FROM python:3.11-slim

# 2. Set the working directory INSIDE the container to the Root
WORKDIR /app


COPY requirements.txt .

# 4. Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 6. Set the Python path so it can find your modules inside DragonFolder
ENV PYTHONPATH="/app:/app/DragonFolder"


CMD ["python", "DragonFolder/main.py"]