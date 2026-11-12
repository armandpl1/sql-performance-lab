-- Step 5a: the baseline rewritten as set-based CTEs (no correlated subqueries).
--
-- Must return exactly the same rows as 01_baseline_rolling_30d.sql.
--
-- What changed:
--   * Each table is read once. Daily totals per account are computed in one
--     pass with FILTER, instead of four subqueries re-reading the same rows.
--   * Date filters compare the bare timestamp column with a constant
--     (sargable), so the timestamp index can be used. The constant comes from
--     a scalar subquery, which runs once (an InitPlan).
--   * Rolling windows are a range join from each account-day to its previous
--     29 days of daily totals: at most 30 rows per account-day, instead of
--     the account's whole history.
--   * Grouping replaces DISTINCT: one row per account-day from the start.
--
-- CTE materialization (PostgreSQL 12+): a CTE used once is inlined into the
-- main query, like a subquery, so filters can be pushed into it. A CTE used
-- more than once is materialized: computed once and stored. account_days is
-- used twice, so it is computed once; the others are inlined.

WITH bounds AS (
    SELECT
        max_date - :report_days + 1  AS report_start,   -- first output day
        max_date - :report_days - 28 AS history_start   -- 29 days before that
    FROM (SELECT MAX(transaction_timestamp)::date AS max_date FROM transactions) m
),

-- Output rows: each account-day with a transaction in the report window
account_days AS (
    SELECT DISTINCT account_id, transaction_timestamp::date AS day
    FROM transactions
    WHERE transaction_timestamp >= (SELECT report_start FROM bounds)
),

daily_txn AS (
    SELECT
        account_id,
        transaction_timestamp::date                     AS day,
        COUNT(*) FILTER (WHERE status = 'completed')    AS completed_cnt,
        SUM(amount) FILTER (WHERE status = 'completed') AS completed_amt,
        COUNT(*) FILTER (WHERE status = 'failed')       AS failed_cnt
    FROM transactions
    WHERE transaction_timestamp >= (SELECT history_start FROM bounds)
    GROUP BY account_id, day
),

daily_events AS (
    SELECT user_id AS account_id, event_timestamp::date AS day, COUNT(*) AS event_cnt
    FROM user_events
    WHERE event_timestamp >= (SELECT history_start FROM bounds)
    GROUP BY user_id, day
),

txn_rolling AS (
    SELECT
        ad.account_id,
        ad.day,
        SUM(d.completed_cnt)              AS completed_cnt,
        COALESCE(SUM(d.completed_amt), 0) AS completed_amt,
        SUM(d.failed_cnt)                 AS failed_cnt
    FROM account_days ad
    JOIN daily_txn d
      ON d.account_id = ad.account_id
     AND d.day BETWEEN ad.day - 29 AND ad.day
    GROUP BY ad.account_id, ad.day
),

event_rolling AS (
    SELECT ad.account_id, ad.day, SUM(e.event_cnt) AS event_cnt
    FROM account_days ad
    JOIN daily_events e
      ON e.account_id = ad.account_id
     AND e.day BETWEEN ad.day - 29 AND ad.day
    GROUP BY ad.account_id, ad.day
)

SELECT
    t.account_id,
    t.day                                                  AS metric_date,
    t.completed_cnt                                        AS completed_txn_count_30d,
    t.completed_amt                                        AS completed_amount_30d,
    ROUND(t.completed_amt / NULLIF(t.completed_cnt, 0), 2) AS avg_completed_amount_30d,
    t.failed_cnt                                           AS failed_txn_count_30d,
    COALESCE(e.event_cnt, 0)                               AS event_count_30d
FROM txn_rolling t
LEFT JOIN event_rolling e USING (account_id, day)
ORDER BY t.account_id, metric_date;
