-- Baseline indexes: what a typical team adds by default. Primary keys, plus
-- one single-column index on each foreign key and timestamp column.
-- Later steps replace these with indexes designed for the workload.

ALTER TABLE transactions ADD PRIMARY KEY (transaction_id);
CREATE INDEX transactions_account_id_idx ON transactions (account_id);
CREATE INDEX transactions_timestamp_idx  ON transactions (transaction_timestamp);

ALTER TABLE user_events ADD PRIMARY KEY (event_id);
CREATE INDEX user_events_user_id_idx   ON user_events (user_id);
CREATE INDEX user_events_timestamp_idx ON user_events (event_timestamp);
