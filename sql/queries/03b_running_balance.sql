-- Step 3b: running balances and moving averages with window frames, no self-joins.
--
-- For every transaction in the last :report_days days, with each account's
-- full history behind it:
--   txn_number                 ROW_NUMBER: the account's nth transaction
--   running_completed_amount   all completed spend up to this moment.
--                              RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
--                              includes every transaction at the same timestamp
--                              (its "peers"), so two transactions at the same
--                              second show the same point-in-time balance.
--                              ROWS would give them different balances
--                              depending on arbitrary order.
--   moving_avg_last_3          average of this and the 2 previous transactions:
--                              ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
--   completed_amount_30d       completed spend in the 30 days up to this
--                              moment: RANGE BETWEEN INTERVAL '30 days'
--                              PRECEDING AND CURRENT ROW, a time-based frame
--
-- The window functions must see the full history, so the date filter is
-- applied after them (in the outer query), not before.

WITH history AS (
    SELECT
        account_id,
        transaction_id,
        transaction_timestamp,
        amount,
        status,
        ROW_NUMBER() OVER by_time AS txn_number,
        SUM(CASE WHEN status = 'completed' THEN amount ELSE 0 END) OVER (
            PARTITION BY account_id ORDER BY transaction_timestamp
            RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS running_completed_amount,
        ROUND(AVG(amount) OVER (
            by_time ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
        ), 2) AS moving_avg_last_3,
        SUM(CASE WHEN status = 'completed' THEN amount ELSE 0 END) OVER (
            PARTITION BY account_id ORDER BY transaction_timestamp
            RANGE BETWEEN INTERVAL '30 days' PRECEDING AND CURRENT ROW
        ) AS completed_amount_30d
    FROM transactions
    WINDOW by_time AS (PARTITION BY account_id ORDER BY transaction_timestamp, transaction_id)
)

SELECT *
FROM history
WHERE transaction_timestamp >=
      (SELECT MAX(transaction_timestamp) FROM transactions) - make_interval(days => :report_days)
ORDER BY account_id, transaction_timestamp, transaction_id;
