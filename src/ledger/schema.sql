-- 机会卡片台账 · SQLite 存储（docs/etf-card-schema-v1.md；replan §3 P3）
-- 时间一律北京时间、不带时区后缀：时刻 'YYYY-MM-DDTHH:MM'，日期 'YYYY-MM-DD'。百分数存为数值（12.5 = 12.5%）。
-- 卡片上的价格（失效位、进场、出场、每日收盘、止损）都在该卡的研究序列（后复权 / 全收益点位）上，与信号同一口径。
-- ledger_now() 由 store.py 注册（数据库时钟）；没注册这个函数的裸连接写不进任何行——fail closed。
-- 冻结纪律由本文件的 CHECK 与触发器强制；cards 的「只许 sealed 0→1」触发器由 store.py 按列清单生成。

-- 固定源清单按版本只追加：每次载入 CSV 记一行 source_loads，当前版本 = 最后载入的那个 sha256
CREATE TABLE IF NOT EXISTS source_loads (
    csv_sha256  TEXT PRIMARY KEY CHECK (length(csv_sha256) = 64),
    loaded_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS fixed_sources (
    source_id   TEXT NOT NULL,
    csv_sha256  TEXT NOT NULL REFERENCES source_loads(csv_sha256),
    name        TEXT,
    grade       TEXT NOT NULL CHECK (grade IN ('A', 'B', 'C')),
    PRIMARY KEY (source_id, csv_sha256)
);
CREATE VIEW IF NOT EXISTS current_sources AS
SELECT source_id, grade FROM fixed_sources
 WHERE csv_sha256 = (SELECT csv_sha256 FROM source_loads ORDER BY rowid DESC LIMIT 1);

-- §2.1 创建时锁死
CREATE TABLE IF NOT EXISTS cards (
    id                    TEXT PRIMARY KEY CHECK (id GLOB 'T-[0-9][0-9][0-9][0-9]-[0-9][0-9][0-9]*'),
    created_at            TEXT NOT NULL CHECK (strftime('%Y-%m-%dT%H:%M', created_at) IS created_at),
    close_date            TEXT NOT NULL CHECK (date(close_date) IS close_date),
    scan_key              TEXT UNIQUE,          -- 扫描器的自然键（如 收盘日|容器|触发类型），同一候选重跑不重复立卡
    container             TEXT NOT NULL CHECK (length(trim(container)) > 0),
    instrument_code       TEXT NOT NULL CHECK (length(trim(instrument_code)) > 0),
    instrument_name       TEXT NOT NULL CHECK (length(trim(instrument_name)) > 0),
    research_index_code   TEXT,
    trigger_type          TEXT NOT NULL CHECK (trigger_type IN ('形态突破', '恐慌下轨', '事件驱动')),
    state_at_entry        TEXT NOT NULL CHECK (state_at_entry IN ('POP', 'XB', 'BNB', 'REV', 'EXH', 'DROP', 'XBD', 'BNBD',
                                                                   'TREND_UP', 'TREND_DOWN', 'NEUTRAL')),
    thesis                TEXT NOT NULL CHECK (length(trim(thesis)) BETWEEN 1 AND 80),
    expectation_horizon_days      INTEGER NOT NULL CHECK (typeof(expectation_horizon_days) = 'integer' AND expectation_horizon_days > 0),
    expectation_target_excess_pct REAL NOT NULL CHECK (typeof(expectation_target_excess_pct) IN ('integer', 'real')),
    expectation_benchmark         TEXT NOT NULL CHECK (expectation_benchmark IN ('等权组合', '沪深300')),
    invalidation_price            REAL NOT NULL CHECK (typeof(invalidation_price) IN ('integer', 'real') AND invalidation_price > 0),
    invalidation_atr_value        REAL NOT NULL CHECK (typeof(invalidation_atr_value) IN ('integer', 'real') AND invalidation_atr_value > 0),
    invalidation_atr_multiple     REAL NOT NULL CHECK (typeof(invalidation_atr_multiple) IN ('integer', 'real') AND invalidation_atr_multiple > 0),
    r_unit_per_share      REAL NOT NULL CHECK (typeof(r_unit_per_share) IN ('integer', 'real') AND r_unit_per_share > 0),
    r_unit_pct_of_nav     REAL NOT NULL CHECK (typeof(r_unit_pct_of_nav) IN ('integer', 'real') AND r_unit_pct_of_nav > 0),
    planned_size_pct      REAL NOT NULL CHECK (typeof(planned_size_pct) IN ('integer', 'real') AND planned_size_pct > 0 AND planned_size_pct <= 25),
    scoring_rule          TEXT NOT NULL CHECK (scoring_rule IN ('schema-v1-§3')),        -- 固定菜单，目前只有一项
    tracking_days         INTEGER NOT NULL DEFAULT 20 CHECK (tracking_days IS 20),        -- A2：统一 20 个交易日
    cf_ew_level           REAL NOT NULL CHECK (typeof(cf_ew_level) IN ('integer', 'real')),       -- counterfactual：等权组合点位
    cf_hs300_level        REAL NOT NULL CHECK (typeof(cf_hs300_level) IN ('integer', 'real')),    --                 沪深300 点位
    cf_container_price    REAL NOT NULL CHECK (typeof(cf_container_price) IN ('integer', 'real')), --                该容器价格
    crowd_rs_1m_rank      INTEGER CHECK (crowd_rs_1m_rank IS NULL OR typeof(crowd_rs_1m_rank) = 'integer'),   -- crowding_at_entry
    crowd_rs_3m_rank      INTEGER CHECK (crowd_rs_3m_rank IS NULL OR typeof(crowd_rs_3m_rank) = 'integer'),
    crowd_vol_ratio_20    REAL CHECK (crowd_vol_ratio_20 IS NULL OR typeof(crowd_vol_ratio_20) IN ('integer', 'real')),
    crowd_premium_pct     REAL CHECK (crowd_premium_pct IS NULL OR typeof(crowd_premium_pct) IN ('integer', 'real')),
    crowd_share_chg_20d   REAL CHECK (crowd_share_chg_20d IS NULL OR typeof(crowd_share_chg_20d) IN ('integer', 'real')),
    thesis_inval_source_id TEXT,                -- A3：事件卡的论点失效条件（固定源 + 判定日 + 可证伪陈述）
    thesis_inval_deadline  TEXT CHECK (thesis_inval_deadline IS NULL OR date(thesis_inval_deadline) IS thesis_inval_deadline),
    thesis_inval_statement TEXT,
    owner_score_deadline  TEXT NOT NULL CHECK (strftime('%Y-%m-%dT%H:%M', owner_score_deadline) IS owner_score_deadline
                                               AND substr(owner_score_deadline, 12) = '09:30'),   -- A1：下一交易日开盘
    supersedes            TEXT UNIQUE REFERENCES cards(id),
    sealed                INTEGER NOT NULL DEFAULT 0 CHECK (sealed IN (0, 1)),
    recorded_at           TEXT NOT NULL,        -- 数据库时钟，写入时由触发器核对
    CHECK (created_at >= close_date || 'T15:00'),                    -- 收盘后才能用该日收盘
    CHECK (owner_score_deadline > created_at),                       -- 创建必须在下一次开盘之前
    CHECK (substr(owner_score_deadline, 1, 10) > close_date
           AND julianday(substr(owner_score_deadline, 1, 10)) - julianday(close_date) <= 10),   -- 下一交易日：最长覆盖国庆长假
    CHECK ((trigger_type = '事件驱动' AND thesis_inval_source_id IS NOT NULL AND thesis_inval_deadline IS NOT NULL
            AND length(trim(coalesce(thesis_inval_statement, ''))) > 0)
        OR (trigger_type <> '事件驱动' AND thesis_inval_source_id IS NULL AND thesis_inval_deadline IS NULL
            AND thesis_inval_statement IS NULL))
);

-- §2.1 evidence[] + fixed-sources §4 的时点与快照字段。只能在卡片封存前写入（= 与卡片同一事务）
CREATE TABLE IF NOT EXISTS evidence (
    card_id          TEXT NOT NULL REFERENCES cards(id),
    seq              INTEGER NOT NULL CHECK (typeof(seq) = 'integer' AND seq >= 1),
    source_id        TEXT NOT NULL,
    source_grade     TEXT NOT NULL CHECK (source_grade IN ('A', 'B')),      -- 写入时的等级快照
    published_at     TEXT NOT NULL CHECK (date(published_at) IS published_at
                                          OR strftime('%Y-%m-%dT%H:%M', published_at) IS published_at),
    summary          TEXT NOT NULL CHECK (length(trim(summary)) > 0),
    url              TEXT NOT NULL CHECK (length(trim(url)) > 0),
    first_seen_at    TEXT NOT NULL CHECK (strftime('%Y-%m-%dT%H:%M', first_seen_at) IS first_seen_at),
    available_at     TEXT NOT NULL CHECK (strftime('%Y-%m-%dT%H:%M', available_at) IS available_at),
    snapshot_path    TEXT NOT NULL CHECK (length(trim(snapshot_path)) > 0),
    snapshot_sha256  TEXT NOT NULL CHECK (length(snapshot_sha256) = 64 AND snapshot_sha256 NOT GLOB '*[^0-9a-f]*'),
    PRIMARY KEY (card_id, seq),
    CHECK (available_at >= published_at)
);

-- A1：evidence_strength 两栏（agent、owner）各自锁定；agent 随卡片创建，owner 在截止前（按数据库时钟）补一次，缺失即无行
CREATE TABLE IF NOT EXISTS strength_scores (
    card_id      TEXT NOT NULL REFERENCES cards(id),
    rater        TEXT NOT NULL CHECK (rater IN ('agent', 'owner')),
    score        INTEGER NOT NULL CHECK (typeof(score) = 'integer' AND score BETWEEN 0 AND 5),
    reason       TEXT NOT NULL CHECK (length(trim(reason)) > 0),
    scored_at    TEXT NOT NULL CHECK (strftime('%Y-%m-%dT%H:%M', scored_at) IS scored_at),
    recorded_at  TEXT NOT NULL,
    PRIMARY KEY (card_id, rater)
);

-- 候选 → 当下：实际成交（write-once）
CREATE TABLE IF NOT EXISTS entries (
    card_id      TEXT PRIMARY KEY REFERENCES cards(id),
    entry_date   TEXT NOT NULL CHECK (date(entry_date) IS entry_date),
    entry_price  REAL NOT NULL CHECK (typeof(entry_price) IN ('integer', 'real') AND entry_price > 0),
    size_pct     REAL NOT NULL CHECK (typeof(size_pct) IN ('integer', 'real') AND size_pct > 0 AND size_pct <= 25),
    recorded_at  TEXT NOT NULL
);

-- §2.2 每日追加（append-only，日期严格递增；出场后继续追加到跟踪期满）
CREATE TABLE IF NOT EXISTS daily (
    card_id      TEXT NOT NULL REFERENCES cards(id),
    date         TEXT NOT NULL CHECK (date(date) IS date),
    close        REAL NOT NULL CHECK (typeof(close) IN ('integer', 'real') AND close > 0),
    state        TEXT NOT NULL CHECK (state IN ('POP', 'XB', 'BNB', 'REV', 'EXH', 'DROP', 'XBD', 'BNBD', 'TREND_UP', 'TREND_DOWN', 'NEUTRAL')),
    z            REAL CHECK (z IS NULL OR typeof(z) IN ('integer', 'real')),
    rs_1m_rank   INTEGER CHECK (rs_1m_rank IS NULL OR typeof(rs_1m_rank) = 'integer'),
    r_current    REAL CHECK (r_current IS NULL OR typeof(r_current) IN ('integer', 'real')),
    mfe          REAL CHECK (mfe IS NULL OR typeof(mfe) IN ('integer', 'real')),
    mae          REAL CHECK (mae IS NULL OR typeof(mae) IN ('integer', 'real')),
    stop_now     REAL CHECK (stop_now IS NULL OR typeof(stop_now) IN ('integer', 'real')),
    bench_close  REAL CHECK (bench_close IS NULL OR typeof(bench_close) IN ('integer', 'real')),
    note         TEXT,
    recorded_at  TEXT NOT NULL,
    PRIMARY KEY (card_id, date)
);

-- §2.3 出场（write-once）
CREATE TABLE IF NOT EXISTS exits (
    card_id              TEXT PRIMARY KEY REFERENCES cards(id),
    exit_date            TEXT NOT NULL CHECK (date(exit_date) IS exit_date),
    exit_price           REAL NOT NULL CHECK (typeof(exit_price) IN ('integer', 'real') AND exit_price > 0),
    exit_reason          TEXT NOT NULL CHECK (exit_reason IN ('失效位', '移动止盈', '论点作废', '跟踪期满', '手动')),
    manual_reason        TEXT,
    realized_r           REAL NOT NULL CHECK (typeof(realized_r) IN ('integer', 'real')),
    realized_excess_pct  REAL NOT NULL CHECK (typeof(realized_excess_pct) IN ('integer', 'real')),
    holding_days         INTEGER NOT NULL CHECK (typeof(holding_days) = 'integer' AND holding_days >= 0),
    recorded_at          TEXT NOT NULL,
    CHECK ((exit_reason = '手动') = (length(trim(coalesce(manual_reason, ''))) > 0))
);

-- §2.4 + §3 跟踪期满（write-once）；final_score 必须等于按锁定规则机械算出的档
CREATE TABLE IF NOT EXISTS finals (
    card_id                TEXT PRIMARY KEY REFERENCES cards(id),
    post_exit_return_pct   REAL NOT NULL CHECK (typeof(post_exit_return_pct) IN ('integer', 'real')),
    post_exit_r            REAL NOT NULL CHECK (typeof(post_exit_r) IN ('integer', 'real')),
    final_score            TEXT NOT NULL CHECK (final_score IN ('达标', '部分', '未达', '证伪')),
    missed_r               REAL NOT NULL CHECK (typeof(missed_r) IN ('integer', 'real')),
    stop_quality           INTEGER NOT NULL CHECK (stop_quality IN (0, 1)),
    trail_quality          INTEGER CHECK (trail_quality IS NULL OR trail_quality IN (0, 1)),   -- 未启用移动止盈时为空
    benchmark_beat         INTEGER NOT NULL CHECK (benchmark_beat IN (0, 1)),
    recorded_at            TEXT NOT NULL
);

-- 作废（write-once）：只有候选（未进场）能作废；作废卡留在库里并计入分母
CREATE TABLE IF NOT EXISTS voids (
    card_id      TEXT PRIMARY KEY REFERENCES cards(id),
    voided_at    TEXT NOT NULL CHECK (strftime('%Y-%m-%dT%H:%M', voided_at) IS voided_at),
    reason       TEXT NOT NULL CHECK (length(trim(reason)) > 0),
    recorded_at  TEXT NOT NULL
);

-- ------------------------------------------------------------------ 触发器：写入条件
CREATE TRIGGER IF NOT EXISTS cards_insert BEFORE INSERT ON cards
BEGIN
    SELECT RAISE(ABORT, '卡片 id 已存在（REPLACE 也不行）') WHERE EXISTS (SELECT 1 FROM cards WHERE id = NEW.id);
    SELECT RAISE(ABORT, 'scan_key 已立过卡') WHERE NEW.scan_key IS NOT NULL AND EXISTS (SELECT 1 FROM cards WHERE scan_key = NEW.scan_key);
    SELECT RAISE(ABORT, '卡片须先以未封存状态写入，证据与 agent 评分写完后再封存') WHERE NEW.sealed <> 0;
    SELECT RAISE(ABORT, 'recorded_at 必须是数据库时钟') WHERE NEW.recorded_at IS NOT ledger_now();
    SELECT RAISE(ABORT, 'created_at 晚于当前时刻') WHERE NEW.created_at > ledger_now();
    SELECT RAISE(ABORT, '已过下一次开盘：不能补立这张卡') WHERE ledger_now() >= NEW.owner_score_deadline;
    SELECT RAISE(ABORT, 'supersedes 必须引用一张已作废且尚未被取代的卡')
     WHERE NEW.supersedes IS NOT NULL AND (
           NOT EXISTS (SELECT 1 FROM voids v WHERE v.card_id = NEW.supersedes AND v.voided_at <= NEW.created_at)
           OR EXISTS (SELECT 1 FROM cards WHERE supersedes = NEW.supersedes));
    SELECT RAISE(ABORT, '论点失效条件的来源必须是固定源清单里的 A / B 级')
     WHERE NEW.thesis_inval_source_id IS NOT NULL
       AND NOT EXISTS (SELECT 1 FROM current_sources s WHERE s.source_id = NEW.thesis_inval_source_id AND s.grade IN ('A', 'B'));
END;

CREATE TRIGGER IF NOT EXISTS cards_seal_needs_agent BEFORE UPDATE OF sealed ON cards WHEN OLD.sealed = 0 AND NEW.sealed = 1
BEGIN
    SELECT RAISE(ABORT, '封存前必须有 agent 的 evidence_strength 评分')
     WHERE NOT EXISTS (SELECT 1 FROM strength_scores WHERE card_id = NEW.id AND rater = 'agent');
END;

CREATE TRIGGER IF NOT EXISTS evidence_insert BEFORE INSERT ON evidence
BEGIN
    SELECT RAISE(ABORT, '证据行已存在（REPLACE 也不行）') WHERE EXISTS (SELECT 1 FROM evidence WHERE card_id = NEW.card_id AND seq = NEW.seq);
    SELECT RAISE(ABORT, '不允许事后添加证据（卡片已封存）')
     WHERE (SELECT sealed FROM cards WHERE id = NEW.card_id) IS NOT 0;
    SELECT RAISE(ABORT, 'source_id 必须在固定源清单中且等级为 A 或 B')
     WHERE NOT EXISTS (SELECT 1 FROM current_sources s WHERE s.source_id = NEW.source_id AND s.grade = NEW.source_grade);
    SELECT RAISE(ABORT, '证据的 available_at 晚于卡片 created_at')
     WHERE NEW.available_at > (SELECT created_at FROM cards WHERE id = NEW.card_id);
    SELECT RAISE(ABORT, '证据的 first_seen_at 晚于卡片 created_at')
     WHERE NEW.first_seen_at > (SELECT created_at FROM cards WHERE id = NEW.card_id);
END;

CREATE TRIGGER IF NOT EXISTS strength_insert BEFORE INSERT ON strength_scores
BEGIN
    SELECT RAISE(ABORT, '评分已存在（每栏只锁一次，REPLACE 也不行）')
     WHERE EXISTS (SELECT 1 FROM strength_scores WHERE card_id = NEW.card_id AND rater = NEW.rater);
    SELECT RAISE(ABORT, 'recorded_at 必须是数据库时钟') WHERE NEW.recorded_at IS NOT ledger_now();
    SELECT RAISE(ABORT, 'agent 评分只能随卡片创建写入')
     WHERE NEW.rater = 'agent' AND (SELECT sealed FROM cards WHERE id = NEW.card_id) IS NOT 0;
    SELECT RAISE(ABORT, 'owner 评分只能在卡片封存后写入')
     WHERE NEW.rater = 'owner' AND (SELECT sealed FROM cards WHERE id = NEW.card_id) IS NOT 1;
    SELECT RAISE(ABORT, 'owner 评分超过截止时刻（次日开盘前），记为缺失')
     WHERE NEW.rater = 'owner' AND ledger_now() >= (SELECT owner_score_deadline FROM cards WHERE id = NEW.card_id);
    SELECT RAISE(ABORT, '评分时刻不在卡片创建与当前时刻之间')
     WHERE NEW.scored_at < (SELECT created_at FROM cards WHERE id = NEW.card_id) OR NEW.scored_at > ledger_now();
END;

CREATE TRIGGER IF NOT EXISTS entries_insert BEFORE INSERT ON entries
BEGIN
    SELECT RAISE(ABORT, '已有进场记录（REPLACE 也不行）') WHERE EXISTS (SELECT 1 FROM entries WHERE card_id = NEW.card_id);
    SELECT RAISE(ABORT, 'recorded_at 必须是数据库时钟') WHERE NEW.recorded_at IS NOT ledger_now();
    SELECT RAISE(ABORT, '卡片未封存或已作废') WHERE (SELECT sealed FROM cards WHERE id = NEW.card_id) IS NOT 1
        OR EXISTS (SELECT 1 FROM voids WHERE card_id = NEW.card_id);
    SELECT RAISE(ABORT, '成交日必须晚于卡片创建日（不能倒填进场）')
     WHERE NEW.entry_date <= substr((SELECT created_at FROM cards WHERE id = NEW.card_id), 1, 10);
    SELECT RAISE(ABORT, '成交日晚于当前日期') WHERE NEW.entry_date > substr(ledger_now(), 1, 10);
    SELECT RAISE(ABORT, '进场价不高于失效位：应按「未进场而失效」作废')
     WHERE NEW.entry_price <= (SELECT invalidation_price FROM cards WHERE id = NEW.card_id);
END;

CREATE TRIGGER IF NOT EXISTS daily_insert BEFORE INSERT ON daily
BEGIN
    SELECT RAISE(ABORT, 'recorded_at 必须是数据库时钟') WHERE NEW.recorded_at IS NOT ledger_now();
    SELECT RAISE(ABORT, '卡片未封存、已作废或已跟踪期满') WHERE (SELECT sealed FROM cards WHERE id = NEW.card_id) IS NOT 1
        OR EXISTS (SELECT 1 FROM voids WHERE card_id = NEW.card_id)
        OR EXISTS (SELECT 1 FROM finals WHERE card_id = NEW.card_id);
    SELECT RAISE(ABORT, '每日行只能按日期向后追加') WHERE NEW.date <= coalesce((SELECT max(date) FROM daily WHERE card_id = NEW.card_id), '')
        OR NEW.date < (SELECT close_date FROM cards WHERE id = NEW.card_id);
    SELECT RAISE(ABORT, '每日行日期晚于当前日期') WHERE NEW.date > substr(ledger_now(), 1, 10);
END;

CREATE TRIGGER IF NOT EXISTS exits_insert BEFORE INSERT ON exits
BEGIN
    SELECT RAISE(ABORT, '已有出场记录（REPLACE 也不行）') WHERE EXISTS (SELECT 1 FROM exits WHERE card_id = NEW.card_id);
    SELECT RAISE(ABORT, 'recorded_at 必须是数据库时钟') WHERE NEW.recorded_at IS NOT ledger_now();
    SELECT RAISE(ABORT, '没有进场记录') WHERE NOT EXISTS (SELECT 1 FROM entries WHERE card_id = NEW.card_id);
    SELECT RAISE(ABORT, '出场日早于进场日') WHERE NEW.exit_date < (SELECT entry_date FROM entries WHERE card_id = NEW.card_id);
    SELECT RAISE(ABORT, '出场日晚于当前日期') WHERE NEW.exit_date > substr(ledger_now(), 1, 10);
END;

CREATE TRIGGER IF NOT EXISTS finals_insert BEFORE INSERT ON finals
BEGIN
    SELECT RAISE(ABORT, '已有期满记录（REPLACE 也不行）') WHERE EXISTS (SELECT 1 FROM finals WHERE card_id = NEW.card_id);
    SELECT RAISE(ABORT, 'recorded_at 必须是数据库时钟') WHERE NEW.recorded_at IS NOT ledger_now();
    SELECT RAISE(ABORT, '没有出场记录') WHERE NOT EXISTS (SELECT 1 FROM exits WHERE card_id = NEW.card_id);
    SELECT RAISE(ABORT, '跟踪期未满：出场后的每日行少于 tracking_days')
     WHERE (SELECT count(*) FROM daily d JOIN exits x ON x.card_id = d.card_id WHERE d.card_id = NEW.card_id AND d.date > x.exit_date)
         < (SELECT tracking_days FROM cards WHERE id = NEW.card_id);
    SELECT RAISE(ABORT, 'final_score 与锁定的评分规则（schema §3）机械结果不符')
     WHERE NEW.final_score IS NOT (
        SELECT CASE WHEN x.exit_reason = '失效位' THEN '证伪'
                    WHEN x.realized_excess_pct >= c.expectation_target_excess_pct THEN '达标'
                    WHEN x.realized_excess_pct > 0 THEN '部分'
                    ELSE '未达' END
          FROM exits x JOIN cards c ON c.id = x.card_id WHERE x.card_id = NEW.card_id);
END;

CREATE TRIGGER IF NOT EXISTS voids_insert BEFORE INSERT ON voids
BEGIN
    SELECT RAISE(ABORT, '已作废（REPLACE 也不行）') WHERE EXISTS (SELECT 1 FROM voids WHERE card_id = NEW.card_id);
    SELECT RAISE(ABORT, 'recorded_at 必须是数据库时钟') WHERE NEW.recorded_at IS NOT ledger_now();
    SELECT RAISE(ABORT, '卡片未封存') WHERE (SELECT sealed FROM cards WHERE id = NEW.card_id) IS NOT 1;
    SELECT RAISE(ABORT, '只有未进场的候选能作废；已进场的卡按「论点作废 / 手动」出场')
     WHERE EXISTS (SELECT 1 FROM entries WHERE card_id = NEW.card_id);
    SELECT RAISE(ABORT, '作废时刻不在卡片创建与当前时刻之间')
     WHERE NEW.voided_at < (SELECT created_at FROM cards WHERE id = NEW.card_id) OR NEW.voided_at > ledger_now();
END;

CREATE TRIGGER IF NOT EXISTS source_loads_insert BEFORE INSERT ON source_loads
BEGIN
    SELECT RAISE(ABORT, '该版本清单已载入') WHERE EXISTS (SELECT 1 FROM source_loads WHERE csv_sha256 = NEW.csv_sha256);
END;

CREATE TRIGGER IF NOT EXISTS fixed_sources_insert BEFORE INSERT ON fixed_sources
BEGIN
    SELECT RAISE(ABORT, '固定源版本行已存在') WHERE EXISTS (SELECT 1 FROM fixed_sources WHERE source_id = NEW.source_id AND csv_sha256 = NEW.csv_sha256);
END;

-- ------------------------------------------------------------------ 状态与统计
CREATE VIEW IF NOT EXISTS card_status AS
SELECT c.id, c.container, c.trigger_type, c.created_at, c.supersedes,
       CASE WHEN v.card_id IS NOT NULL THEN '作废'
            WHEN f.card_id IS NOT NULL THEN '已结'
            WHEN x.card_id IS NOT NULL THEN '过去'
            WHEN e.card_id IS NOT NULL THEN '当下'
            ELSE '候选' END AS status,
       f.final_score, x.exit_reason, x.realized_r,
       (SELECT score FROM strength_scores s WHERE s.card_id = c.id AND s.rater = 'agent') AS agent_strength,
       (SELECT score FROM strength_scores s WHERE s.card_id = c.id AND s.rater = 'owner') AS owner_strength
  FROM cards c
  LEFT JOIN voids v ON v.card_id = c.id
  LEFT JOIN finals f ON f.card_id = c.id
  LEFT JOIN exits x ON x.card_id = c.id
  LEFT JOIN entries e ON e.card_id = c.id
 WHERE c.sealed = 1;
