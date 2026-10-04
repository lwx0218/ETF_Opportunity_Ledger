-- Frozen src/data/db.py SCHEMA at ab64650, before the explicit date constraint upgrade.

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS runs (
    run_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind            TEXT NOT NULL CHECK (kind IN ('probe', 'backfill', 'update', 'package', 'calendar')),
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    end_date        TEXT CHECK (end_date IS NULL OR date(end_date) IS end_date),
    args            TEXT,
    git_commit      TEXT,
    universe_sha256 TEXT,
    status          TEXT
);

CREATE TABLE IF NOT EXISTS bars (
    code       TEXT NOT NULL CHECK (length(code) > 0),
    adj        TEXT NOT NULL CHECK (adj IN ('raw', 'hfq')),
    date       TEXT NOT NULL CHECK (date(date) IS date),
    open       REAL, high REAL, low REAL, close REAL, volume REAL, amount REAL,
    source     TEXT NOT NULL CHECK (length(source) > 0),
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (code, adj, date),
    CHECK ((adj = 'hfq') = (source = 'eastmoney_etf_hfq'))
) WITHOUT ROWID;

CREATE TRIGGER IF NOT EXISTS bars_one_source BEFORE INSERT ON bars
BEGIN
    -- 同一序列的行来源一致（本触发器保证），看任意一行即可：走主键前缀，O(log n)
    SELECT RAISE(ABORT, '一条序列只来自一个路由：已有序列来自别的来源，拒绝拼接')
     WHERE (SELECT source FROM bars WHERE code = NEW.code AND adj = NEW.adj LIMIT 1) <> NEW.source;
END;

-- 行情只整行写入（backfill 先删后插、update 按日 INSERT OR REPLACE）：UPDATE 一律拒绝，免得绕过上面那条把来源改混
CREATE TRIGGER IF NOT EXISTS bars_no_update BEFORE UPDATE ON bars
BEGIN
    SELECT RAISE(ABORT, 'bars 不允许 UPDATE：整行重写（同一来源）');
END;

CREATE TABLE IF NOT EXISTS coverage (
    run_id   INTEGER NOT NULL REFERENCES runs(run_id),
    theme_id TEXT NOT NULL,
    container TEXT NOT NULL DEFAULT '', code TEXT NOT NULL DEFAULT '', route_used TEXT NOT NULL DEFAULT '', first_date TEXT NOT NULL DEFAULT '', last_date TEXT NOT NULL DEFAULT '', rows TEXT NOT NULL DEFAULT '', tr_code_used TEXT NOT NULL DEFAULT '', price_only TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT '', series_code TEXT NOT NULL DEFAULT '', series_adj TEXT NOT NULL DEFAULT '', series_name TEXT NOT NULL DEFAULT '', max_gap_days TEXT NOT NULL DEFAULT '', price_first_date TEXT NOT NULL DEFAULT '', ohlc_missing_rows TEXT NOT NULL DEFAULT '', volume_missing_rows TEXT NOT NULL DEFAULT '', exec_code TEXT NOT NULL DEFAULT '', exec_route TEXT NOT NULL DEFAULT '', exec_first_date TEXT NOT NULL DEFAULT '', exec_last_date TEXT NOT NULL DEFAULT '', exec_rows TEXT NOT NULL DEFAULT '', exec_error TEXT NOT NULL DEFAULT '', checked_at TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (run_id, theme_id)
);

CREATE TABLE IF NOT EXISTS requests (
    run_id     INTEGER NOT NULL REFERENCES runs(run_id),
    seq        INTEGER NOT NULL,
    url        TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    bytes      INTEGER,
    sha256     TEXT,
    error      TEXT,
    file       TEXT,
    PRIMARY KEY (run_id, seq)
);

CREATE TABLE IF NOT EXISTS update_results (
    run_id    INTEGER NOT NULL REFERENCES runs(run_id),
    seq       INTEGER NOT NULL,
    theme_id  TEXT NOT NULL,
    kind      TEXT NOT NULL,
    code      TEXT NOT NULL,
    adj       TEXT NOT NULL,
    route     TEXT,
    ok        INTEGER NOT NULL CHECK (ok IN (0, 1)),
    since     TEXT, added INTEGER, revised INTEGER, last_date TEXT, error TEXT,
    PRIMARY KEY (run_id, seq)
);

CREATE TABLE IF NOT EXISTS calendar (
    date TEXT PRIMARY KEY CHECK (date(date) IS date AND strftime('%w', date) NOT IN ('0', '6'))
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS universe (
    ord      INTEGER NOT NULL,
    theme_id TEXT PRIMARY KEY,
    row      TEXT NOT NULL
) WITHOUT ROWID;

CREATE VIEW IF NOT EXISTS coverage_latest AS
SELECT c.* FROM coverage c
 WHERE c.run_id = (SELECT max(run_id) FROM coverage x WHERE x.theme_id = c.theme_id);
