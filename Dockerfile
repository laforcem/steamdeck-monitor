FROM alpine:3.21

RUN apk add --no-cache python3 tzdata

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

WORKDIR /app
COPY steamdeck_monitor ./steamdeck_monitor

# Nothing to write to disk; run as nobody.
USER 65534:65534
ENTRYPOINT ["python3", "-m", "steamdeck_monitor"]
