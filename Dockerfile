# PeerCheck with every check, as a command line tool. GitHub Actions builds the image as
# ghcr.io/aalramadan/peercheck.
FROM python:3.12-slim

# Java runs the SIGSOFT checker, and Perl with poppler runs banal, the format analyzer of HotCRP.
RUN apt-get update \
    && apt-get install -y --no-install-recommends default-jre-headless perl poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/peercheck
COPY . .
# The editable install keeps src/ beside external/, where the checks find the tools of other authors. The CPU build
# of PyTorch keeps the image small.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -e ".[reviews]"

# One volume at /cache keeps the models, the DBLP database, and Hallucinator between runs. Any user may write
# there, for a run with --user.
ENV XDG_CACHE_HOME=/cache HF_HOME=/cache/huggingface
RUN mkdir -m 1777 /cache
# peercheck gui listens on every address of the container at a fixed port, which docker run -p publishes.
ENV PEERCHECK_GUI_HOST=0.0.0.0 PEERCHECK_GUI_PORT=8765
EXPOSE 8765
WORKDIR /data
ENTRYPOINT ["peercheck"]
CMD ["--help"]
