FROM python:3.13-slim AS ubridge

ARG UBRIDGE=1.2.3
RUN apt-get update \
 && apt-get install -y --no-install-recommends gcc make libc6-dev libpcap-dev curl ca-certificates \
 && curl -fsSL "https://github.com/GNS3/ubridge/archive/refs/tags/v${UBRIDGE}.tar.gz" | tar -xz -C /tmp \
 && make -C "/tmp/ubridge-${UBRIDGE}" \
 && install -m 0755 "/tmp/ubridge-${UBRIDGE}/ubridge" /usr/local/bin/ubridge

ARG REGISTRY=fddde6574a46904f709ecb89c5bea383de6bbecf
RUN mkdir -p /symbols \
 && for name in ubuntu.svg ubuntu.txt; do \
      curl -fsSL "https://raw.githubusercontent.com/GNS3/gns3-registry/${REGISTRY}/symbols/${name}" -o "/symbols/${name}"; \
    done

ARG KALI_PRESS_PACK=360c018b5cf65179ad3883d393b8ccbdfa674bc7
ARG KALI_DRAGON_SHA256=083264e7b60e5249fe77b91786bca093b9c530597d28c134bd5e9a7fdccfb1d8
RUN curl -fsSL "https://gitlab.com/kalilinux/documentation/press-pack/-/raw/${KALI_PRESS_PACK}/Kali/Logomark/kali-dragon-black.svg" -o /tmp/kali-dragon-black.svg \
 && echo "${KALI_DRAGON_SHA256}  /tmp/kali-dragon-black.svg" | sha256sum -c - \
 && sed 's/^<svg /<svg width="60" height="60" /' /tmp/kali-dragon-black.svg > /symbols/kali.svg \
 && grep -q '^<svg width="60" height="60" viewBox=' /symbols/kali.svg \
 && printf '%s\n' "KALI LINUX is a trademark of OffSec. Kali/Logomark/kali-dragon-black.svg from https://gitlab.com/kalilinux/documentation/press-pack at ${KALI_PRESS_PACK}, unmodified but for width and height. Policy: https://www.kali.org/docs/policy/trademark/" > /symbols/kali.txt

FROM python:3.13-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends libmagic1 libpcap0.8t64 libcap2-bin gosu qemu-system-x86 busybox-static \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir "gns3-server[ai-features]==3.1.0a6" \
 && useradd --system --create-home --uid 10002 gns3

COPY --from=ubridge /usr/local/bin/ubridge /usr/local/bin/ubridge
COPY --from=ubridge /symbols /opt/fsl-gns3/symbols
RUN setcap cap_net_admin,cap_net_raw+ep /usr/local/bin/ubridge

COPY entrypoint.sh provision.py auditor.html /opt/fsl-gns3/

EXPOSE 3080

ENTRYPOINT ["/opt/fsl-gns3/entrypoint.sh"]
