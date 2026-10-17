ARG KALI_PRESS_PACK=360c018b5cf65179ad3883d393b8ccbdfa674bc7

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

ARG KALI_PRESS_PACK
ARG KALI_DRAGON_SHA256=083264e7b60e5249fe77b91786bca093b9c530597d28c134bd5e9a7fdccfb1d8
RUN mkdir -p /dragon \
 && curl -fsSL "https://gitlab.com/kalilinux/documentation/press-pack/-/raw/${KALI_PRESS_PACK}/Kali/Logomark/kali-dragon-black.svg" -o /dragon/kali-dragon-black.svg \
 && echo "${KALI_DRAGON_SHA256}  /dragon/kali-dragon-black.svg" | sha256sum -c -

FROM python:3.13-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends libmagic1 libpcap0.8t64 libcap2-bin gosu qemu-system-x86 busybox-static docker-cli \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir "gns3-server[ai-features]==3.1.0a6" \
 && useradd --system --create-home --uid 10002 gns3

RUN skills="$(python -c 'import gns3server, pathlib; print(pathlib.Path(gns3server.__file__).parent)')/agent/gns3_copilot/configs/skills_config.py" \
 && sed -i 's/"enabled": True,/"enabled": False,/' "$skills" \
 && grep -q '"enabled": False,' "$skills"

COPY --from=ubridge /usr/local/bin/ubridge /usr/local/bin/ubridge
COPY --from=ubridge /symbols /opt/fsl-gns3/symbols
RUN setcap cap_net_admin,cap_net_raw+ep /usr/local/bin/ubridge

COPY entrypoint.sh provision.py auditor.html symbols.py /opt/fsl-gns3/
COPY --from=ubridge /dragon/kali-dragon-black.svg /opt/fsl-gns3/kali-dragon-black.svg
ARG KALI_PRESS_PACK
RUN python /opt/fsl-gns3/symbols.py /opt/fsl-gns3/kali-dragon-black.svg "${KALI_PRESS_PACK}" /opt/fsl-gns3/symbols

EXPOSE 3080

ENTRYPOINT ["/opt/fsl-gns3/entrypoint.sh"]
