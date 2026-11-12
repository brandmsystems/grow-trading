-- Virtual paper account and the risk calculation behind every paper trade.
-- The active account is the latest row with closed_at NULL. Its balance is the starting
-- capital plus the net P&L of the closed paper trades booked to it (running balance).
CREATE TABLE paper_accounts (
    id         SERIAL PRIMARY KEY,
    capital    DOUBLE PRECISION NOT NULL CHECK (capital > 0),
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at  TIMESTAMPTZ,
    note       TEXT
);

-- risk: the full pre-trade calculation (capital, risk percentage, risk amount, premium, stop,
-- risk per lot, lots, quantity, investment, charges, maximum loss, checks).
-- stop_premium is enforced for paper trades; target_premium is shown for risk/reward only.
ALTER TABLE live_trades
    ADD COLUMN risk JSONB,
    ADD COLUMN stop_premium DOUBLE PRECISION,
    ADD COLUMN target_premium DOUBLE PRECISION,
    ADD COLUMN paper_account_id INTEGER REFERENCES paper_accounts (id);
