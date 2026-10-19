# Fixture candidate only: upstream security findings remain an explicit production blocker.
# Tag verified 2026-10-17: 5.26.32-community; registry index pinned below.
FROM neo4j:5.26.32-community@sha256:0a6e7aedf54a531f76286032d4365ead65b11cca05e4a15cdf23b8e53d6db02b
USER root
# Apply the signed Debian security update without changing the vendor's Java libraries.
# Remove only compiler headers left by the vendor build; reject any wider APT plan.
# Preserve package metadata and vendor JARs so remaining findings stay visible.
RUN set -eu; \
    apt-get -o Acquire::Retries=2 -o Acquire::http::Timeout=30 update; \
    apt-get install -y --no-install-recommends liblzma5=5.8.1-1+deb13u2; \
    native_arch="$(dpkg --print-architecture)"; \
    plan="$(LC_ALL=C apt-get --simulate purge libc6-dev linux-libc-dev)"; \
    printf '%s\n' "$plan"; \
    printf '%s\n' "$plan" | awk -v arch="$native_arch" ' \
        $1 == "Inst" || $1 == "Conf" { rejected = 1 } \
        $1 == "Remv" || $1 == "Purg" { \
            name = $2; sub(":" arch "$", "", name); \
            if (name != "libc6-dev" && name != "linux-libc-dev") rejected = 1; \
            removed[name] = 1; \
        } \
        END { exit (rejected || !("libc6-dev" in removed) || !("linux-libc-dev" in removed)) }'; \
    apt-get purge -y libc6-dev linux-libc-dev; \
    apt-get check; \
    audit="$(dpkg --audit)"; \
    test -z "$audit"; \
    for package in libc6-dev linux-libc-dev; do \
        if dpkg-query -W -f '${db:Status-Status}\n' "$package" 2>/dev/null | grep -qx installed; then exit 1; fi; \
    done; \
    test ! -e /usr/include/linux; \
    test ! -e /usr/include/stdlib.h; \
    test -s /var/lib/dpkg/status; \
    rm -rf /var/lib/apt/lists/*
RUN mkdir -p /conf \
    && cp /var/lib/neo4j/conf/* /conf/ \
    && chown -R 7474:7474 /conf \
    && chmod 0750 /conf
# Install the unmodified matching vendor JNA native resource into the immutable image.
# This avoids extracting executable libraries into /tmp at runtime; no jar is modified.
RUN set -eu; \
    case "$(uname -m)" in x86_64) platform=linux-x86-64 ;; aarch64) platform=linux-aarch64 ;; *) exit 1 ;; esac; \
    mkdir -p /opt/pv-native; \
    cd /opt/pv-native; \
    jar -xf /var/lib/neo4j/lib/jna-5.15.0.jar "com/sun/jna/$platform/libjnidispatch.so"; \
    mv "com/sun/jna/$platform/libjnidispatch.so" ./libjnidispatch.so; \
    rm -r com; \
    chmod 0444 libjnidispatch.so; \
    sha256sum libjnidispatch.so > libjnidispatch.sha256
# neo4j-admin (initial auth/dump/load) does not inherit server.jvm.additional.
# This pinned vendor image has no existing options; fail rather than silently discard future ones.
RUN test -z "${JAVA_TOOL_OPTIONS:-}"
ENV JAVA_TOOL_OPTIONS="-Djna.boot.library.path=/opt/pv-native -Djna.nounpack=true"
COPY --chown=7474:7474 infra/docker/neo4j/neo4j.conf /conf/neo4j.conf
COPY --chown=7474:7474 LICENSE NOTICE.md /usr/share/licenses/pequeverso-assistant-api/
USER 7474:7474
# TCP liveness only. Application readiness also verifies the active canonical PG/graph version.
HEALTHCHECK --interval=10s --timeout=3s --start-period=60s --retries=3 \
    CMD ["bash", "-c", "exec 3<>/dev/tcp/127.0.0.1/7687"]
