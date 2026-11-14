-- 5-minute scalping in paper mode (13 Nov 2026): which strategy and which tested analyzer
-- configuration (strategy|contract|exit) opened each engine trade. NULL for the other modes.
ALTER TABLE live_trades ADD COLUMN IF NOT EXISTS strategy TEXT;
ALTER TABLE live_trades ADD COLUMN IF NOT EXISTS scalp_config TEXT;
CREATE INDEX IF NOT EXISTS live_trades_scalp_idx ON live_trades (scalp_config) WHERE scalp_config IS NOT NULL;
