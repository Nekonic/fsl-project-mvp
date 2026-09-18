# Red team external tools. When a case declares `tool:`, the harness runs this
# image one-shot on the fsl network.
#
# Built here rather than pulled: most published sqlmap images are amd64-only and
# will not start on an arm64 host.
FROM python:3.13-slim

RUN pip install --no-cache-dir sqlmap==1.9.2

ENTRYPOINT []
CMD ["sqlmap", "--version"]
