-- Tables for the performance lab. Created without indexes so the bulk load is
-- fast; sql/indexes.sql adds them afterwards.

DROP TABLE IF EXISTS transactions;
DROP TABLE IF EXISTS user_events;

CREATE TABLE transactions (
    transaction_id        bigint        NOT NULL,
    account_id            integer       NOT NULL,
    amount                numeric(12,2) NOT NULL,
    transaction_timestamp timestamp     NOT NULL,
    status                text          NOT NULL
        CHECK (status IN ('completed', 'pending', 'failed', 'reversed'))
);

-- App clickstream. user_id N owns account_id N.
CREATE TABLE user_events (
    event_id        bigint    NOT NULL,
    user_id         integer   NOT NULL,
    event_type      text      NOT NULL,
    event_timestamp timestamp NOT NULL
);
