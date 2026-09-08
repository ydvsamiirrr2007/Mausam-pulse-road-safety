FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MAUSAM_DATABASE=/data/mausam-pulse.db

WORKDIR /opt/mausam-pulse
RUN useradd --create-home --uid 10001 mausam && mkdir -p /data && chown mausam:mausam /data
COPY --chown=mausam:mausam app ./app

USER mausam
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=2)" || exit 1

CMD ["python", "-m", "app"]
