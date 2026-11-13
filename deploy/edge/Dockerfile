FROM alpine:3.20

RUN apk add --no-cache nftables iproute2

COPY edge.nft /etc/edge.nft

CMD ["sh", "-c", "nft -f /etc/edge.nft || exit 1; trap 'exit 0' TERM; sleep 2147483647 & wait"]
