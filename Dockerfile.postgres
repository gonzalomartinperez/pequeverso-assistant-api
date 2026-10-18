# Assistant schemas/roles remain separate from backoffice IAM in its own project database.
# Official PG18.6 OCI index; linux/amd64 child 8859531 verified on2026-10-18.
FROM postgres:18.6-trixie@sha256:74935e72241653ca55e0414067e6d8763aceb8a810eb51b452253ec3dcfc4336
USER root
# Signed PGDG extension package; no compiler, source builds or extra vector service.
# Explicit Debian security fixes retain XML support; open libxml2 findings remain deploy gates.
RUN apt-get -o Acquire::Retries=2 -o Acquire::http::Timeout=30 update \
    && apt-get install -y --no-install-recommends \
        postgresql-18-pgvector=0.8.7-1.pgdg13+1 \
        liblzma5=5.8.1-1+deb13u2 xz-utils=5.8.1-1+deb13u2 \
        libpcre2-8-0=10.46-1~deb13u3 \
        libperl5.40=5.40.1-6+deb13u1 perl=5.40.1-6+deb13u1 \
        perl-base=5.40.1-6+deb13u1 perl-modules-5.40=5.40.1-6+deb13u1 \
        libssl3t64=3.5.7-1~deb13u3 openssl=3.5.7-1~deb13u3 \
        tzdata=2026c-0+deb13u1 \
    && apt-get purge -y gpg \
    && rm -rf /var/lib/apt/lists/* /usr/local/bin/gosu \
    && command -v sqv \
    && test "$(id -u postgres)" = 999 && test "$(id -g postgres)" = 999 \
    && test -f /usr/share/postgresql/18/extension/vector--0.8.7.sql
COPY --chown=999:999 LICENSE NOTICE.md /usr/share/licenses/pequeverso-assistant-api/
USER 999:999
ARG SERVICE_REVISION=
LABEL org.opencontainers.image.source="https://github.com/gonzalomartinperez/pequeverso-assistant-api"
LABEL org.opencontainers.image.revision=${SERVICE_REVISION}
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 CMD ["pg_isready", "-q", "-h", "127.0.0.1"]
# Preserve operational errors without private row details, bind values or failing SQL.
CMD ["postgres", "-c", "log_error_verbosity=terse", "-c", "log_parameter_max_length=0", "-c", "log_parameter_max_length_on_error=0", "-c", "log_statement=none", "-c", "log_min_error_statement=panic"]
