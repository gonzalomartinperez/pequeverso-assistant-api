-- Project-specific NOLOGIN capability groups. vps-ops provisions independent LOGIN identities,
-- secrets and membership; these groups never reuse the backoffice IAM database or users.
DO $$ BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='pequeverso_knowledge_runtime') THEN
        CREATE ROLE pequeverso_knowledge_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='pequeverso_knowledge_indexer') THEN
        CREATE ROLE pequeverso_knowledge_indexer NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
    END IF;
END $$;
REVOKE ALL ON SCHEMA knowledge FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA knowledge FROM PUBLIC;
GRANT USAGE ON SCHEMA knowledge TO pequeverso_knowledge_runtime,pequeverso_knowledge_indexer;
GRANT SELECT ON ALL TABLES IN SCHEMA knowledge TO pequeverso_knowledge_runtime,pequeverso_knowledge_indexer;
GRANT INSERT,UPDATE ON knowledge.revisions TO pequeverso_knowledge_indexer;
GRANT INSERT ON knowledge.chunks TO pequeverso_knowledge_indexer;
GRANT UPDATE ON knowledge.state TO pequeverso_knowledge_indexer;
GRANT UPDATE(active_version,verified_at,last_attempt_at,last_failure,last_failure_at)
    ON knowledge.state TO pequeverso_knowledge_runtime;
