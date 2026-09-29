FROM python:3.11-slim-bookworm

WORKDIR /app

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 libx11-6 \
        libxrandr2 libxtst6 libxi6 libxkbcommon0 libxinerama1 \
        libportaudio2 python3-tk xauth xvfb \
    && rm -rf /var/lib/apt/lists/*

# The Compose build context is the project root.  Only Python and browser
# assets are copied; package.json, node_modules and Vite are not part of this image.
COPY ["Mouse_updated (1)/Mouse_extracted/requirements.txt", "./"]
RUN pip install --no-cache-dir -r requirements.txt
COPY ["Mouse_updated (1)/Mouse_extracted/backend", "./backend"]
COPY ["Mouse_updated (1)/Mouse_extracted/models", "./models"]
COPY ["Mouse_updated (1)/Mouse_extracted/Aeris", "./Aeris"]
COPY ["Mouse_updated (1)/Mouse_extracted/calibration_points.json", "./calibration_points.json"]
COPY ["Mouse_updated (1)/Mouse_extracted/modern-frontend", "./modern-frontend"]
COPY ["Mouse_updated (1)/Mouse_extracted/docker-entrypoint.sh", "/usr/local/bin/docker-entrypoint.sh"]
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
