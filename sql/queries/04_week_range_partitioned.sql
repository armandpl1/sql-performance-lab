-- Step 4 range filter on `transactions_by_month`: one week of transactions by status.
-- The same query runs on each storage layout (04_week_range_*.sql). All
-- versions must return the same rows (same checksum).

SELECT
    status,
    COUNT(*)    AS transactions,
    SUM(amount) AS total_amount
FROM transactions_by_month
WHERE transaction_timestamp >= TIMESTAMP '2026-10-19'
  AND transaction_timestamp <  TIMESTAMP '2026-10-26'
GROUP BY status
ORDER BY status;
