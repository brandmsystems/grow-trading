-- Existing values are IST wall-clock times; store them as real instants.
ALTER TABLE candles_1m    ALTER COLUMN ts         TYPE TIMESTAMPTZ USING ts         AT TIME ZONE 'Asia/Kolkata';
ALTER TABLE fetch_log     ALTER COLUMN fetched_at TYPE TIMESTAMPTZ USING fetched_at AT TIME ZONE 'Asia/Kolkata';
ALTER TABLE live_sessions ALTER COLUMN started_at TYPE TIMESTAMPTZ USING started_at AT TIME ZONE 'Asia/Kolkata';
ALTER TABLE live_sessions ALTER COLUMN stopped_at TYPE TIMESTAMPTZ USING stopped_at AT TIME ZONE 'Asia/Kolkata';
ALTER TABLE live_trades   ALTER COLUMN signal_ts  TYPE TIMESTAMPTZ USING signal_ts  AT TIME ZONE 'Asia/Kolkata';
ALTER TABLE live_trades   ALTER COLUMN entry_ts   TYPE TIMESTAMPTZ USING entry_ts   AT TIME ZONE 'Asia/Kolkata';
ALTER TABLE live_trades   ALTER COLUMN exit_ts    TYPE TIMESTAMPTZ USING exit_ts    AT TIME ZONE 'Asia/Kolkata';
ALTER TABLE live_events   ALTER COLUMN ts         TYPE TIMESTAMPTZ USING ts         AT TIME ZONE 'Asia/Kolkata';
ALTER TABLE bt_runs       ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at AT TIME ZONE 'Asia/Kolkata';
