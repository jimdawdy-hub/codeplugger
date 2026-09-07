FROM python:3.12-slim

# Dependencies first, so editing application code does not invalidate the
# (slow) pip layer.
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Only what the app loads at runtime — see .dockerignore.
COPY codeplug/ ./codeplug/
COPY web/ ./web/
COPY data/ ./data/
COPY main.py launcher.py ./
COPY ["Talkgroups BrandMeister.csv", "./"]

# Run unprivileged. The BrandMeister device/talkgroup caches live under
# $HOME/.config, so that directory has to belong to the runtime user;
# mount a volume there to keep the cache across container restarts.
RUN useradd --create-home --uid 10001 codeplugger \
 && mkdir -p /home/codeplugger/.config \
 && chown -R codeplugger:codeplugger /home/codeplugger /app
USER codeplugger
ENV HOME=/home/codeplugger \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "web.app:app", "--host", "0.0.0.0", "--port", "8000"]
