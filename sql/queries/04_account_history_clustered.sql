-- Step 4 point lookup on `transactions_by_account`: one busy account's last three months, by day.
-- The same query runs on each storage layout (04_account_history_*.sql).

SELECT
    transaction_timestamp::date AS day,
    COUNT(*)                    AS transactions,
    SUM(amount)                 AS total_amount
FROM transactions_by_account
WHERE account_id = 42
  AND transaction_timestamp >= TIMESTAMP '2026-08-01'
GROUP BY day
ORDER BY day;
