-- Candles outside 09:15-15:29 (pre-open, after close, evening Muhurat sessions) are real
-- but not part of the regular session. Count them apart from invalid candles.
ALTER TABLE data_downloads ADD COLUMN rows_outside_session INTEGER NOT NULL DEFAULT 0;
ALTER TABLE data_day_quality ADD COLUMN outside_session INTEGER NOT NULL DEFAULT 0;
