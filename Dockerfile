# OCS Flask deployment preparation. Local Docker build/run is still required.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    FLASK_ENV=production \
    FLASK_PORT=8630
WORKDIR /app
RUN groupadd --gid 10001 pnec && useradd --uid 10001 --gid pnec --no-create-home pnec
COPY requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir -r requirements.txt && python -m pip check
COPY app ./app
COPY migrations ./migrations
COPY main.py ./main.py
COPY scripts/container-entrypoint.sh scripts/check-container-readiness.py scripts/container-healthcheck.py scripts/docker_local_app.py scripts/check-docker-local.py scripts/sqlite_snapshot.py ./scripts/
RUN chmod 0555 scripts/container-entrypoint.sh && mkdir -p /var/lib/pnec && chown pnec:pnec /var/lib/pnec
USER 10001:10001
EXPOSE 8630
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 CMD ["python", "scripts/container-healthcheck.py"]
ENTRYPOINT ["sh", "scripts/container-entrypoint.sh"]
CMD ["gunicorn", "--bind", "0.0.0.0:8630", "--workers", "2", "--timeout", "120", "--access-logfile", "-", "--error-logfile", "-", "main:app"]
