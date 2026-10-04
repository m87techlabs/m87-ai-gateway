FROM python:3.11-slim-bookworm AS builder
WORKDIR /build
COPY pyproject.toml README.md LICENSE NOTICE ./
COPY src ./src
RUN pip wheel --no-cache-dir --wheel-dir /wheels .

FROM python:3.11-slim-bookworm
ARG SOURCE_REVISION=unknown
LABEL org.opencontainers.image.title="M87 AI Gateway" \
      org.opencontainers.image.source="https://github.com/m87techlabs/m87-ai-gateway" \
      org.opencontainers.image.revision="$SOURCE_REVISION" \
      org.opencontainers.image.licenses="Apache-2.0"
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links=/wheels m87-ai-gateway \
    && rm -rf /wheels \
    && groupadd --gid 10001 gateway \
    && useradd --uid 10001 --gid gateway --no-create-home gateway \
    && mkdir -p /data/gateway \
    && chown -R gateway:gateway /data \
    && chmod 700 /data /data/gateway
WORKDIR /data
USER 10001:10001
VOLUME ["/data"]
EXPOSE 8087
HEALTHCHECK --interval=15s --timeout=3s --start-period=15s --retries=3 \
    CMD python -c "from urllib.request import urlopen; urlopen('http://127.0.0.1:8087/health', timeout=2)" || exit 1
ENTRYPOINT ["m87-gateway"]
CMD ["--data-dir", "/data/gateway", "--host", "0.0.0.0", "--port", "8087", "--hide-admin-key"]
