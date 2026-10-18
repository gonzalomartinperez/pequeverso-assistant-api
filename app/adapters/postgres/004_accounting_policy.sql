-- The offline indexer must see shared totals yet cannot settle/refund a generation reservation.
-- Migration/import owners retain explicit authority; runtime identities must never own tables.
ALTER TABLE assistant_private.spend_ledger ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
    IF NOT EXISTS(SELECT FROM pg_policies WHERE schemaname='assistant_private' AND tablename='spend_ledger' AND policyname='private_runtime_budget') THEN
        CREATE POLICY private_runtime_budget ON assistant_private.spend_ledger
            TO pequeverso_private_runtime USING(true) WITH CHECK(true);
    END IF;
    IF NOT EXISTS(SELECT FROM pg_policies WHERE schemaname='assistant_private' AND tablename='spend_ledger' AND policyname='index_budget_read') THEN
        CREATE POLICY index_budget_read ON assistant_private.spend_ledger FOR SELECT
            TO pequeverso_embedding_accounting USING(true);
    END IF;
    IF NOT EXISTS(SELECT FROM pg_policies WHERE schemaname='assistant_private' AND tablename='spend_ledger' AND policyname='index_budget_insert') THEN
        CREATE POLICY index_budget_insert ON assistant_private.spend_ledger FOR INSERT
            TO pequeverso_embedding_accounting WITH CHECK(run_id LIKE 'embedding:index:%');
    END IF;
    IF NOT EXISTS(SELECT FROM pg_policies WHERE schemaname='assistant_private' AND tablename='spend_ledger' AND policyname='index_budget_update') THEN
        CREATE POLICY index_budget_update ON assistant_private.spend_ledger FOR UPDATE
            TO pequeverso_embedding_accounting USING(run_id LIKE 'embedding:index:%')
            WITH CHECK(run_id LIKE 'embedding:index:%');
    END IF;
END $$;
