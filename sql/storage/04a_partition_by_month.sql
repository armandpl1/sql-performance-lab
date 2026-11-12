-- Step 4a: date partitioning plus clustering.
--
-- transactions_by_month holds the same rows as transactions, split into one
-- partition per month on transaction_timestamp. Inside each partition, rows
-- are written in (account_id, transaction_timestamp) order, so one account's
-- history sits in a few neighbouring pages instead of being scattered.
--
-- A query that filters on transaction_timestamp only reads the partitions
-- its range overlaps; the planner removes the rest ("partition pruning").

DROP TABLE IF EXISTS transactions_by_month;

CREATE TABLE transactions_by_month (
    transaction_id        bigint        NOT NULL,
    account_id            integer       NOT NULL,
    amount                numeric(12,2) NOT NULL,
    transaction_timestamp timestamp     NOT NULL,
    status                text          NOT NULL
) PARTITION BY RANGE (transaction_timestamp);

-- One partition per month, January 2025 to October 2026
DO $$
DECLARE
    month_start date := DATE '2025-01-01';
BEGIN
    WHILE month_start < DATE '2026-11-01' LOOP
        EXECUTE format(
            'CREATE TABLE %I PARTITION OF transactions_by_month FOR VALUES FROM (%L) TO (%L)',
            'transactions_' || to_char(month_start, 'YYYY_MM'),
            month_start,
            month_start + INTERVAL '1 month'
        );
        month_start := month_start + INTERVAL '1 month';
    END LOOP;
END $$;

-- Rows that don't fit any month land here instead of failing the insert
CREATE TABLE transactions_by_month_default PARTITION OF transactions_by_month DEFAULT;

-- Clustering: write each partition in account, then time, order
INSERT INTO transactions_by_month
SELECT * FROM transactions
ORDER BY account_id, transaction_timestamp;

-- One index definition, created on every partition
CREATE INDEX ON transactions_by_month (account_id, transaction_timestamp);

VACUUM ANALYZE transactions_by_month;
