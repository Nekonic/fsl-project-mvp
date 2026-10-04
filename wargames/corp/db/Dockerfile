FROM mysql@sha256:0744ee5ef89ce6ccfa13de3e579fe6b9e27f93dd70da9c06d2c908b1b193fb8d

RUN set -eux; \
    rpm="mysql-community-client-8.4.11-1.el9.x86_64.rpm"; \
    curl -fsSL -o "/tmp/${rpm}" "https://repo.mysql.com/yum/mysql-8.4-community/el/9/x86_64/${rpm}"; \
    rpm --import /etc/pki/rpm-gpg/RPM-GPG-KEY-mysql; \
    rpm -K "/tmp/${rpm}"; \
    rpm2archive - < "/tmp/${rpm}" | tar -xz -C / ./usr/bin/mysqlbinlog; \
    rm -f "/tmp/${rpm}"; \
    mysqlbinlog --version
