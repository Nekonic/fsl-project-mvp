# Stamps the case marker onto the attacker's traffic, so free-form attacks can
# be scored by marker as well as by time and source.
FROM mitmproxy/mitmproxy:11.1.3

COPY stamp.py /stamp.py

# block_global is off because the attacker container is not on a local subnet
# mitmproxy trusts by default, and it would refuse to forward at all.
CMD ["mitmdump", "-q", "--listen-port", "8081", \
     "--set", "block_global=false", "-s", "/stamp.py"]
