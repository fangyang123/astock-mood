-- 在 Supabase SQL Editor 中执行（用 publishable/anon 也可，建表需项目 owner 权限）
-- 交易记录表（对齐本地 trades）
CREATE TABLE IF NOT EXISTS public.trades (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    stock_code    TEXT,
    stock_name    TEXT NOT NULL,
    sector        TEXT,
    open_date     TEXT NOT NULL,
    open_price    DOUBLE PRECISION NOT NULL,
    shares        DOUBLE PRECISION NOT NULL,
    position_pct  DOUBLE PRECISION,
    strategy      TEXT,
    emotion       TEXT,
    open_reason   TEXT,
    close_date    TEXT,
    close_price   DOUBLE PRECISION,
    close_reason  TEXT,
    pnl           DOUBLE PRECISION,
    pnl_pct       DOUBLE PRECISION,
    status        TEXT DEFAULT 'open',
    cycle_phase   TEXT,
    notes         TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    local_id      TEXT
);

CREATE INDEX IF NOT EXISTS idx_trades_status ON public.trades(status);

-- 每日复盘表
CREATE TABLE IF NOT EXISTS public.daily_records (
    date         TEXT PRIMARY KEY,
    auto_json    TEXT,
    manual_json  TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

-- 明日验证条件表
CREATE TABLE IF NOT EXISTS public.verify_conditions (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    written_date  TEXT NOT NULL,
    metric        TEXT NOT NULL,
    base          TEXT,
    threshold     TEXT NOT NULL,
    if_hit        TEXT,
    direction     TEXT,
    signal_type   TEXT,
    actual        TEXT,
    auto_result   TEXT DEFAULT 'pending',
    final_result  TEXT,
    override_reason TEXT,
    confirmed_at  TEXT
);

-- RLS：允许匿名（publishable key）读写，方便前端直连
ALTER TABLE public.trades ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.daily_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.verify_conditions ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies WHERE tablename='trades' AND policyname='allow all anon'
  ) THEN
    CREATE POLICY "allow all anon" ON public.trades FOR ALL TO anon USING (true) WITH CHECK (true);
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies WHERE tablename='daily_records' AND policyname='allow all anon'
  ) THEN
    CREATE POLICY "allow all anon" ON public.daily_records FOR ALL TO anon USING (true) WITH CHECK (true);
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies WHERE tablename='verify_conditions' AND policyname='allow all anon'
  ) THEN
    CREATE POLICY "allow all anon" ON public.verify_conditions FOR ALL TO anon USING (true) WITH CHECK (true);
  END IF;
END $$;
