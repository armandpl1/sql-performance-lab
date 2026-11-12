-- Step 1 baseline: rolling 30-day account metrics, written the slow way on purpose.
--
-- Output: one row per account per day on which the account had a transaction,
-- for the last :report_days days of data. Each row has metrics over the 30 days
-- ending on that day (that day and the 29 before it):
--   completed_txn_count_30d   completed transactions
--   completed_amount_30d      total amount of completed transactions
--   avg_completed_amount_30d  average completed amount, 2 decimals
--   failed_txn_count_30d      failed transactions
--   event_count_30d           app events by the account's user
--
-- :report_days is replaced by scripts/benchmark.py (or set it in psql with
-- \set report_days 7).
--
-- Anti-patterns, each fixed in a later step:
--   1. Correlated subqueries. Five separate subqueries run once for every
--      transaction in the window, and each one re-reads the account's entire
--      history through the account_id index. Busy accounts get re-read
--      hundreds of times.
--   2. Functions on indexed columns. DATE(transaction_timestamp) and
--      DATE(event_timestamp) hide the timestamp indexes, so the window filter
--      can't use them: the outer query scans the whole table, and every
--      subquery filters the account's rows one by one.
--   3. Computing per row, then deduplicating. Metrics are computed for every
--      transaction and only then collapsed to one row per account-day with
--      DISTINCT, which also has to sort all the results.
--   4. MAX over a function. MAX(DATE(transaction_timestamp)) reads the whole
--      table, where MAX(transaction_timestamp) could read one index entry.

SELECT DISTINCT
    t.account_id,
    DATE(t.transaction_timestamp) AS metric_date,

    (SELECT COUNT(*)
       FROM transactions t2
      WHERE t2.account_id = t.account_id
        AND t2.status = 'completed'
        AND DATE(t2.transaction_timestamp)
            BETWEEN DATE(t.transaction_timestamp) - 29 AND DATE(t.transaction_timestamp)
    ) AS completed_txn_count_30d,

    (SELECT COALESCE(SUM(t2.amount), 0)
       FROM transactions t2
      WHERE t2.account_id = t.account_id
        AND t2.status = 'completed'
        AND DATE(t2.transaction_timestamp)
            BETWEEN DATE(t.transaction_timestamp) - 29 AND DATE(t.transaction_timestamp)
    ) AS completed_amount_30d,

    (SELECT ROUND(AVG(t2.amount), 2)
       FROM transactions t2
      WHERE t2.account_id = t.account_id
        AND t2.status = 'completed'
        AND DATE(t2.transaction_timestamp)
            BETWEEN DATE(t.transaction_timestamp) - 29 AND DATE(t.transaction_timestamp)
    ) AS avg_completed_amount_30d,

    (SELECT COUNT(*)
       FROM transactions t2
      WHERE t2.account_id = t.account_id
        AND t2.status = 'failed'
        AND DATE(t2.transaction_timestamp)
            BETWEEN DATE(t.transaction_timestamp) - 29 AND DATE(t.transaction_timestamp)
    ) AS failed_txn_count_30d,

    (SELECT COUNT(*)
       FROM user_events e
      WHERE e.user_id = t.account_id
        AND DATE(e.event_timestamp)
            BETWEEN DATE(t.transaction_timestamp) - 29 AND DATE(t.transaction_timestamp)
    ) AS event_count_30d

FROM transactions t
WHERE DATE(t.transaction_timestamp)
      > (SELECT MAX(DATE(transaction_timestamp)) FROM transactions) - :report_days
ORDER BY t.account_id, metric_date;
