FROM mitmproxy/mitmproxy:11.1.3

COPY stamp.py /stamp.py

CMD ["mitmdump", "-q", "--listen-port", "8081", \
     "--set", "block_global=false", "-s", "/stamp.py"]
