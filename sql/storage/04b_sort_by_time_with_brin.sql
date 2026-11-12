-- Step 4b: micro-partitioning with zone maps (BRIN).
--
-- transactions_by_time holds the same rows, written in time order. A BRIN
-- index stores only the minimum and maximum transaction_timestamp for each
-- block range (here 32 pages, about 2,000 rows). A range filter skips every
-- block range whose min/max can't match: the same idea as zone maps in
-- Snowflake, Databricks (data skipping) or Parquet row-group statistics.
--
-- BRIN is tiny (kilobytes instead of hundreds of megabytes for a B-tree) but
-- only works when the table is physically sorted by the column.

DROP TABLE IF EXISTS transactions_by_time;

CREATE TABLE transactions_by_time AS
SELECT * FROM transactions
ORDER BY transaction_timestamp;

CREATE INDEX transactions_by_time_brin
    ON transactions_by_time USING brin (transaction_timestamp)
    WITH (pages_per_range = 32);

VACUUM ANALYZE transactions_by_time;
