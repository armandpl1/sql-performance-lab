-- Step 5b: the baseline rewritten with a window function and a time-based frame.
--
-- Must return exactly the same rows as 01_baseline_rolling_30d.sql.
--
-- Same single pass over each table as 5a, but no range join at all: daily
-- totals for transactions and events are combined into one row per
-- account-day, and a window frame sums the 30 days ending on each day:
--     RANGE BETWEEN INTERVAL '29 days' PRECEDING AND CURRENT ROW
-- RANGE works on the value of day, not on row count, so days with no
-- activity don't need a row. Only account-days with a transaction in the
-- report window are returned.

WITH bounds AS (
    SELECT
        max_date - :report_days + 1  AS report_start,
        max_date - :report_days - 28 AS history_start
    FROM (SELECT MAX(transaction_timestamp)::date AS max_date FROM transactions) m
),

daily_txn AS (
    SELECT
        account_id,
        transaction_timestamp::date                     AS day,
        COUNT(*)                                        AS txn_cnt,
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

-- Days with events but no transactions still count toward the 30-day sums
daily AS (
    SELECT
        account_id,
        day,
        COALESCE(t.txn_cnt, 0)       AS txn_cnt,
        COALESCE(t.completed_cnt, 0) AS completed_cnt,
        t.completed_amt,
        COALESCE(t.failed_cnt, 0)    AS failed_cnt,
        COALESCE(e.event_cnt, 0)     AS event_cnt
    FROM daily_txn t
    FULL JOIN daily_events e USING (account_id, day)
),

rolling AS (
    SELECT
        account_id,
        day,
        txn_cnt,
        SUM(completed_cnt) OVER last_30_days AS completed_cnt,
        SUM(completed_amt) OVER last_30_days AS completed_amt,
        SUM(failed_cnt)    OVER last_30_days AS failed_cnt,
        SUM(event_cnt)     OVER last_30_days AS event_cnt
    FROM daily
    WINDOW last_30_days AS (
        PARTITION BY account_id ORDER BY day
        RANGE BETWEEN INTERVAL '29 days' PRECEDING AND CURRENT ROW
    )
)

SELECT
    account_id,
    day                                                AS metric_date,
    completed_cnt                                      AS completed_txn_count_30d,
    COALESCE(completed_amt, 0)                         AS completed_amount_30d,
    ROUND(completed_amt / NULLIF(completed_cnt, 0), 2) AS avg_completed_amount_30d,
    failed_cnt                                         AS failed_txn_count_30d,
    event_cnt                                          AS event_count_30d
FROM rolling
WHERE txn_cnt > 0
  AND day >= (SELECT report_start FROM bounds)
ORDER BY account_id, metric_date;
