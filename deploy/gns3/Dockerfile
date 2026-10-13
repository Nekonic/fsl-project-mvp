FROM python:3.13-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends libmagic1 \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir "gns3-server[ai-features]==3.1.0a6"

COPY entrypoint.sh provision.py auditor.html /opt/fsl-gns3/

EXPOSE 3080
VOLUME /data

ENTRYPOINT ["/opt/fsl-gns3/entrypoint.sh"]
