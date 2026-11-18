-- ROLLBACK for 0018_drop_orphan_tables.up.sql: recreates the six tables (empty).
-- Data: pg_restore --data-only -d groww_trading -t <table> data/backups/orphan_tables_2026-11-18.dump
CREATE TABLE public.app_settings (
    key text NOT NULL,
    value jsonb NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.candle_forecasts (
    id integer NOT NULL,
    source text NOT NULL,
    session_id integer,
    timeframe integer NOT NULL,
    bar_ts timestamp with time zone NOT NULL,
    target_start timestamp with time zone NOT NULL,
    target_end timestamp with time zone NOT NULL,
    model text,
    nifty double precision,
    atr double precision,
    direction text NOT NULL,
    p_bull double precision,
    p_bear double precision,
    p_side double precision,
    confidence double precision,
    recommendation text NOT NULL,
    est_high double precision,
    est_low double precision,
    close_lo double precision,
    close_hi double precision,
    slot text,
    regime text,
    vol_state text,
    data_state text,
    analysis jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    actual_open double precision,
    actual_high double precision,
    actual_low double precision,
    actual_close double precision,
    actual_dir text,
    dir_hit boolean,
    move_hit boolean,
    range_hit boolean,
    close_hit boolean,
    evaluated_at timestamp with time zone
);
CREATE SEQUENCE public.candle_forecasts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE public.candle_forecasts_id_seq OWNED BY public.candle_forecasts.id;
CREATE TABLE public.pattern_events (
    id integer NOT NULL,
    session_id integer,
    trade_mode text NOT NULL,
    day date NOT NULL,
    pattern text NOT NULL,
    bias text,
    pattern_ts timestamp with time zone NOT NULL,
    confirm_ts timestamp with time zone,
    status text NOT NULL,
    reason text,
    action text,
    confidence double precision,
    trade_id integer,
    exit_reason text,
    net double precision,
    detail jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE SEQUENCE public.pattern_events_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE public.pattern_events_id_seq OWNED BY public.pattern_events.id;
CREATE TABLE public.prediction_log (
    id integer NOT NULL,
    session_id integer,
    trade_mode text NOT NULL,
    day date NOT NULL,
    bar_ts timestamp with time zone NOT NULL,
    timeframe integer NOT NULL,
    nifty double precision,
    decision text NOT NULL,
    net_score double precision,
    confidence double precision,
    action text,
    outcome text NOT NULL,
    reason text,
    detail jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE SEQUENCE public.prediction_log_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE public.prediction_log_id_seq OWNED BY public.prediction_log.id;
CREATE TABLE public.smc_setups (
    id integer NOT NULL,
    session_id integer,
    trade_mode text NOT NULL,
    day date NOT NULL,
    setup_key text NOT NULL,
    direction text NOT NULL,
    sweep_ts timestamp with time zone NOT NULL,
    status text NOT NULL,
    stage text,
    reason text,
    action text,
    confidence double precision,
    entry double precision,
    sl double precision,
    t1 double precision,
    t2 double precision,
    t3 double precision,
    rr double precision,
    signal_ts timestamp with time zone,
    trade_id integer,
    exit_reason text,
    net double precision,
    detail jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE SEQUENCE public.smc_setups_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE public.smc_setups_id_seq OWNED BY public.smc_setups.id;
CREATE TABLE public.strategy_signals (
    id integer NOT NULL,
    session_id integer,
    trade_mode text NOT NULL,
    day date NOT NULL,
    bar_ts timestamp with time zone NOT NULL,
    decision text NOT NULL,
    trend text NOT NULL,
    reason text NOT NULL,
    action text NOT NULL,
    action_note text,
    trade_id integer,
    detail jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE SEQUENCE public.strategy_signals_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE public.strategy_signals_id_seq OWNED BY public.strategy_signals.id;
ALTER TABLE ONLY public.candle_forecasts ALTER COLUMN id SET DEFAULT nextval('public.candle_forecasts_id_seq'::regclass);
ALTER TABLE ONLY public.pattern_events ALTER COLUMN id SET DEFAULT nextval('public.pattern_events_id_seq'::regclass);
ALTER TABLE ONLY public.prediction_log ALTER COLUMN id SET DEFAULT nextval('public.prediction_log_id_seq'::regclass);
ALTER TABLE ONLY public.smc_setups ALTER COLUMN id SET DEFAULT nextval('public.smc_setups_id_seq'::regclass);
ALTER TABLE ONLY public.strategy_signals ALTER COLUMN id SET DEFAULT nextval('public.strategy_signals_id_seq'::regclass);
ALTER TABLE ONLY public.app_settings
    ADD CONSTRAINT app_settings_pkey PRIMARY KEY (key);
ALTER TABLE ONLY public.candle_forecasts
    ADD CONSTRAINT candle_forecasts_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.pattern_events
    ADD CONSTRAINT pattern_events_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.prediction_log
    ADD CONSTRAINT prediction_log_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.prediction_log
    ADD CONSTRAINT prediction_log_session_id_bar_ts_key UNIQUE (session_id, bar_ts);
ALTER TABLE ONLY public.smc_setups
    ADD CONSTRAINT smc_setups_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.strategy_signals
    ADD CONSTRAINT strategy_signals_pkey PRIMARY KEY (id);
CREATE UNIQUE INDEX candle_forecasts_once ON public.candle_forecasts USING btree (source, timeframe, bar_ts, COALESCE(session_id, 0));
CREATE INDEX candle_forecasts_pending ON public.candle_forecasts USING btree (evaluated_at) WHERE (evaluated_at IS NULL);
CREATE INDEX pattern_events_day ON public.pattern_events USING btree (trade_mode, day);
CREATE UNIQUE INDEX pattern_events_once ON public.pattern_events USING btree (COALESCE(session_id, 0), pattern, pattern_ts);
CREATE INDEX prediction_log_day_idx ON public.prediction_log USING btree (trade_mode, day, bar_ts);
CREATE INDEX smc_setups_day ON public.smc_setups USING btree (trade_mode, day);
CREATE UNIQUE INDEX smc_setups_once ON public.smc_setups USING btree (COALESCE(session_id, 0), setup_key);
CREATE INDEX strategy_signals_day ON public.strategy_signals USING btree (trade_mode, day, bar_ts);
CREATE UNIQUE INDEX strategy_signals_once ON public.strategy_signals USING btree (COALESCE(session_id, 0), bar_ts);
