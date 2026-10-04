FROM wordpress:6.6.2-php8.2-apache

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends unzip default-mysql-client; \
    rm -rf /var/lib/apt/lists/*; \
    curl -fsSL -o /usr/local/bin/wp https://github.com/wp-cli/wp-cli/releases/download/v2.11.0/wp-cli-2.11.0.phar; \
    chmod +x /usr/local/bin/wp

RUN set -eux; \
    mkdir -p /tmp/plugins; \
    for pv in ultimate-member/2.6.6 wp-gdpr-compliance/1.4.2 easy-post-submission/2.3.0; do \
      slug="${pv%%/*}"; ver="${pv##*/}"; \
      curl -fsSL -o "/tmp/${slug}.zip" "https://downloads.wordpress.org/plugin/${slug}.${ver}.zip"; \
      unzip -q "/tmp/${slug}.zip" -d /usr/src/wordpress/wp-content/plugins/; \
    done

COPY entrypoint.sh /usr/local/bin/fsl-entrypoint.sh
RUN chmod +x /usr/local/bin/fsl-entrypoint.sh

ENTRYPOINT ["/usr/local/bin/fsl-entrypoint.sh"]
CMD ["apache2-foreground"]
