# Common Pequeverso engine; API schemas and backoffice IAM remain separate databases.
# Official PostgreSQL18.6 Alpine3.24 index; amd64 child d8703cd7 verified2026-10-18.
FROM postgres:18.6-alpine3.24@sha256:77f585114c32fbca283dc835b0596f4e52b51b4c6662d7810b2f4084f60a1873 AS vector-build
RUN apk add --no-cache build-base=0.5-r4 clang21=21.1.8-r3 llvm21-dev=21.1.8-r1 \
    && wget -O /tmp/pgvector.tar.gz https://codeload.github.com/pgvector/pgvector/tar.gz/refs/tags/v0.8.7 \
    && echo 'cac0b10c360f05b2d521200105ba3697e773d4cd3731f5a915a7e37ebe0bea85  /tmp/pgvector.tar.gz' | sha256sum -c - \
    && tar -xzf /tmp/pgvector.tar.gz -C /tmp \
    && cd /tmp/pgvector-0.8.7 \
    && make -j1 OPTFLAGS="" \
    && make DESTDIR=/extension install \
    && mkdir -p /extension/usr/share/doc/pgvector \
    && cp LICENSE README.md /extension/usr/share/doc/pgvector/ \
    && apk info -v > /extension/usr/share/doc/pgvector/build-packages.txt

FROM postgres:18.6-alpine3.24@sha256:77f585114c32fbca283dc835b0596f4e52b51b4c6662d7810b2f4084f60a1873
# Retain XML/ICU and the official entrypoint; compiler/toolchain files stay in vector-build.
COPY --from=vector-build /extension/ /
RUN apk add --no-cache libxml2=2.13.9-r2 \
    && rm /usr/local/bin/gosu \
    && test "$(id -u postgres)" = 70 && test "$(id -g postgres)" = 70 \
    && test -f /usr/local/share/postgresql/extension/vector--0.8.7.sql \
    && apk info -v > /usr/share/postgres-runtime-packages.txt
COPY --chown=70:70 LICENSE NOTICE.md /usr/share/licenses/pequeverso-assistant-api/
# New volumes only. Existing Debian UID999 data requires an explicit logical restore.
USER 70:70
ARG SERVICE_REVISION=
LABEL org.opencontainers.image.source="https://github.com/gonzalomartinperez/pequeverso-assistant-api"
LABEL org.opencontainers.image.revision=${SERVICE_REVISION}
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 CMD ["pg_isready", "-q", "-h", "127.0.0.1"]
# Preserve operational errors without private row details, bind values or failing SQL.
CMD ["postgres", "-c", "log_error_verbosity=terse", "-c", "log_parameter_max_length=0", "-c", "log_parameter_max_length_on_error=0", "-c", "log_statement=none", "-c", "log_min_error_statement=panic"]
