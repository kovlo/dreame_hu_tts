FROM debian:bookworm-slim

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        ffmpeg \
        php-cli \
        php-xml \
        python-is-python3 \
        python3 \
        vorbis-tools \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

ENTRYPOINT ["python3", "ttscreate.py"]
