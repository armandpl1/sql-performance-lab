-- Step 4c: clustering by account.
--
-- transactions_by_account holds the same rows, written in (account_id,
-- transaction_timestamp) order, with a matching composite index. Reading one
-- account's recent history touches a handful of neighbouring pages. In the
-- original table, the same rows are scattered across thousands of pages.
--
-- PostgreSQL's CLUSTER command does the same reordering in place, but it
-- isn't maintained: new rows go wherever there is space. Rebuilding (or
-- CLUSTER) has to be repeated as the table changes.

DROP TABLE IF EXISTS transactions_by_account;

CREATE TABLE transactions_by_account AS
SELECT * FROM transactions
ORDER BY account_id, transaction_timestamp;

CREATE INDEX transactions_by_account_idx
    ON transactions_by_account (account_id, transaction_timestamp);

VACUUM ANALYZE transactions_by_account;
