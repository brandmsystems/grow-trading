-- NIFTY option lot sizes as set by NSE circulars. A contract's lot size depends on its
-- expiry cycle (weekly or monthly) and expiry date: the row with the latest first_expiry
-- on or before the contract's expiry applies. Values and cutovers are copied from the
-- circulars named in `source`; nothing is estimated.
CREATE TABLE lot_sizes (
    underlying   TEXT NOT NULL,
    cycle        TEXT NOT NULL CHECK (cycle IN ('weekly', 'monthly')),
    first_expiry DATE NOT NULL,    -- first expiry of this cycle trading with this lot size
    lot_size     INTEGER NOT NULL CHECK (lot_size > 0),
    source       TEXT NOT NULL,
    PRIMARY KEY (underlying, cycle, first_expiry)
);

INSERT INTO lot_sizes (underlying, cycle, first_expiry, lot_size, source) VALUES
-- NSE/FAOP/47854 (31 Mar 2021): 75 -> 50; "July 2021 monthly expiry and beyond", "August 2021 Weekly expiry & beyond".
('NIFTY', 'monthly', '2021-07-01', 50, 'NSE/FAOP/47854, 31 Mar 2021'),
('NIFTY', 'weekly',  '2021-08-01', 50, 'NSE/FAOP/47854, 31 Mar 2021'),
-- NSE/FAOP/61415 (2 Apr 2024): 50 -> 25; first weekly 2 May 2024, first monthly 30 May 2024.
('NIFTY', 'weekly',  '2024-05-02', 25, 'NSE/FAOP/61415, 2 Apr 2024'),
('NIFTY', 'monthly', '2024-05-30', 25, 'NSE/FAOP/61415, 2 Apr 2024'),
-- NSE/FAOP/64625 (18 Oct 2024): 25 -> 75; first weekly 2 Jan 2025, first monthly 27 Feb 2025.
('NIFTY', 'weekly',  '2025-01-02', 75, 'NSE/FAOP/64625, 18 Oct 2024'),
('NIFTY', 'monthly', '2025-02-27', 75, 'NSE/FAOP/64625, 18 Oct 2024'),
-- NSE/FAOP/70616 (3 Oct 2025): 75 -> 65; first weekly 6 Jan 2026, first monthly 27 Jan 2026.
('NIFTY', 'weekly',  '2026-01-06', 65, 'NSE/FAOP/70616, 3 Oct 2025'),
('NIFTY', 'monthly', '2026-01-27', 65, 'NSE/FAOP/70616, 3 Oct 2025');
