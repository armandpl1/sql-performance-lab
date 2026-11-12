-- Step 3a: sessionization (a gaps-and-islands problem).
--
-- A session is a run of a user's events with no gap longer than 30 minutes.
-- Over the last :report_days days of events:
--   1. LAG() puts each event next to the user's previous event.
--   2. An event starts a new session if it's the user's first, or comes more
--      than 30 minutes after the previous one (the "gap").
--   3. A running SUM() of those new-session flags numbers the sessions (the
--      "islands"): every event in a session gets the same number.
--   4. GROUP BY user and session number gives one row per session.
--
-- Sessions that started before the window are cut at the window start.

WITH window_events AS (
    SELECT event_id, user_id, event_type, event_timestamp
    FROM user_events
    WHERE event_timestamp >=
          (SELECT MAX(event_timestamp) FROM user_events) - make_interval(days => :report_days)
),

with_previous AS (
    SELECT
        *,
        LAG(event_timestamp) OVER (
            PARTITION BY user_id ORDER BY event_timestamp, event_id
        ) AS previous_timestamp
    FROM window_events
),

flagged AS (
    SELECT
        *,
        CASE
            WHEN previous_timestamp IS NULL
              OR event_timestamp - previous_timestamp > INTERVAL '30 minutes'
            THEN 1 ELSE 0
        END AS is_new_session
    FROM with_previous
),

numbered AS (
    SELECT
        *,
        SUM(is_new_session) OVER (
            PARTITION BY user_id ORDER BY event_timestamp, event_id
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS session_number
    FROM flagged
)

SELECT
    user_id,
    session_number,
    MIN(event_timestamp)                                AS session_start,
    MAX(event_timestamp)                                AS session_end,
    MAX(event_timestamp) - MIN(event_timestamp)         AS session_duration,
    COUNT(*)                                            AS event_count,
    COUNT(*) FILTER (WHERE event_type = 'page_view')    AS page_views,
    COUNT(*) FILTER (WHERE event_type = 'add_to_cart')  AS add_to_cart_events,
    BOOL_OR(event_type = 'checkout')                    AS reached_checkout
FROM numbered
GROUP BY user_id, session_number
ORDER BY user_id, session_number;
