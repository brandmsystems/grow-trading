-- Prediction-mode paper/live trades keep the score and the NIFTY stop/target they were opened with.
ALTER TABLE live_trades ADD COLUMN signal_mode TEXT NOT NULL DEFAULT 'cross';
ALTER TABLE live_trades ADD COLUMN score DOUBLE PRECISION;
ALTER TABLE live_trades ADD COLUMN stop_ref DOUBLE PRECISION;
ALTER TABLE live_trades ADD COLUMN target_ref DOUBLE PRECISION;
ALTER TABLE live_trades ADD COLUMN atr_ref DOUBLE PRECISION;
