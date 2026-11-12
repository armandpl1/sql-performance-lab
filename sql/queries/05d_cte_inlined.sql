-- Step 5 CTE behavior: AS NOT MATERIALIZED.
--
-- 05c and 05d differ only in that keyword and return the same rows.
--   MATERIALIZED      PostgreSQL computes the CTE first (all 10M rows),
--                     stores the result, then filters it. The filter on
--                     account_id can't reach the table or its index.
--   NOT MATERIALIZED  The CTE is inlined like a subquery, so the filter is
--                     pushed down and the account_id index is used.
-- Since PostgreSQL 12, a CTE used once is inlined by default, and one used
-- more than once is materialized. Before 12, every CTE was materialized
-- (an "optimization fence"), a common source of slow queries after upgrades.

WITH all_transactions AS NOT MATERIALIZED (
    SELECT account_id, transaction_timestamp, amount, status
    FROM transactions
)

SELECT
    date_trunc('month', transaction_timestamp)::date AS month,
    COUNT(*)                                         AS transactions,
    SUM(amount)                                      AS total_amount
FROM all_transactions
WHERE account_id = 42
GROUP BY month
ORDER BY month;
