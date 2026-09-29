-- 机会卡片台账 · SQLite 存储（docs/etf-card-schema-v1.md；replan §3 P3）
-- 时间一律北京时间、不带时区后缀：时刻 'YYYY-MM-DDTHH:MM'，日期 'YYYY-MM-DD'。百分数存为数值（12.5 = 12.5%）。
-- 冻结与追加的纪律由本文件的 CHECK 与触发器在存储层强制；cards 的「只许 sealed 0→1」触发器由 store.py 按列清单生成。

CREATE TABLE IF NOT EXISTS fixed_sources (          -- docs/etf-fixed-sources-v1.csv 的镜像，只有 A / B 级能进卡片
    source_id  TEXT PRIMARY KEY,
    name       TEXT,
    grade      TEXT NOT NULL CHECK (grade IN ('A', 'B', 'C')),
    loaded_at  TEXT NOT NULL
);

-- §2.1 创建时锁死
CREATE TABLE IF NOT EXISTS cards (
    id                    TEXT PRIMARY KEY CHECK (id GLOB 'T-[0-9][0-9][0-9][0-9]-[0-9][0-9][0-9]*'),
    created_at            TEXT NOT NULL CHECK (created_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]'),
    close_date            TEXT NOT NULL CHECK (close_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    container             TEXT NOT NULL CHECK (length(trim(container)) > 0),
    instrument_code       TEXT NOT NULL CHECK (length(trim(instrument_code)) > 0),
    instrument_name       TEXT NOT NULL CHECK (length(trim(instrument_name)) > 0),
    research_index_code   TEXT,
    trigger_type          TEXT NOT NULL CHECK (trigger_type IN ('形态突破', '恐慌下轨', '事件驱动')),
    state_at_entry        TEXT NOT NULL CHECK (state_at_entry IN ('POP', 'XB', 'BNB', 'REV', 'EXH', 'DROP', 'XBD', 'BNBD',
                                                                   'TREND_UP', 'TREND_DOWN', 'NEUTRAL')),
    thesis                TEXT NOT NULL CHECK (length(trim(thesis)) BETWEEN 1 AND 80),
    expectation_horizon_days      INTEGER NOT NULL CHECK (expectation_horizon_days > 0),
    expectation_target_excess_pct REAL NOT NULL,
    expectation_benchmark         TEXT NOT NULL CHECK (expectation_benchmark IN ('等权组合', '沪深300')),
    invalidation_price            REAL NOT NULL CHECK (invalidation_price > 0),
    invalidation_atr_value        REAL NOT NULL CHECK (invalidation_atr_value > 0),
    invalidation_atr_multiple     REAL NOT NULL CHECK (invalidation_atr_multiple > 0),
    r_unit_per_share      REAL NOT NULL CHECK (r_unit_per_share > 0),
    r_unit_pct_of_nav     REAL NOT NULL CHECK (r_unit_pct_of_nav > 0),
    planned_size_pct      REAL NOT NULL CHECK (planned_size_pct > 0 AND planned_size_pct <= 25),
    scoring_rule          TEXT NOT NULL CHECK (scoring_rule IN ('schema-v1-§3')),        -- 固定菜单，目前只有一项
    tracking_days         INTEGER NOT NULL DEFAULT 20 CHECK (tracking_days > 0),        -- A2：统一 20 个交易日
    cf_ew_level           REAL NOT NULL,        -- counterfactual：创建当日等权组合点位
    cf_hs300_level        REAL NOT NULL,        --                 沪深300 点位
    cf_container_price    REAL NOT NULL,        --                 该容器价格
    crowd_rs_1m_rank      INTEGER,              -- crowding_at_entry：观测快照，缺失可为空
    crowd_rs_3m_rank      INTEGER,
    crowd_vol_ratio_20    REAL,
    crowd_premium_pct     REAL,
    crowd_share_chg_20d   REAL,
    thesis_inval_source_id TEXT,                -- A3：事件卡的论点失效条件（固定源 + 判定日 + 可证伪陈述）
    thesis_inval_deadline  TEXT CHECK (thesis_inval_deadline IS NULL OR thesis_inval_deadline GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    thesis_inval_statement TEXT,
    owner_score_deadline  TEXT NOT NULL CHECK (owner_score_deadline GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]'),
    supersedes            TEXT UNIQUE REFERENCES cards(id),
    sealed                INTEGER NOT NULL DEFAULT 0 CHECK (sealed IN (0, 1)),
    CHECK (created_at >= close_date || 'T15:00'),                    -- 收盘后才能用该日收盘
    CHECK (owner_score_deadline > created_at),
    CHECK ((trigger_type = '事件驱动' AND thesis_inval_source_id IS NOT NULL AND thesis_inval_deadline IS NOT NULL
            AND length(trim(coalesce(thesis_inval_statement, ''))) > 0)
        OR (trigger_type <> '事件驱动' AND thesis_inval_source_id IS NULL AND thesis_inval_deadline IS NULL
            AND thesis_inval_statement IS NULL))
);

-- §2.1 evidence[] + fixed-sources §4 的时点与快照字段。只能在卡片封存前写入（= 与卡片同一事务）
CREATE TABLE IF NOT EXISTS evidence (
    card_id          TEXT NOT NULL REFERENCES cards(id),
    seq              INTEGER NOT NULL CHECK (seq >= 1),
    source_id        TEXT NOT NULL,
    published_at     TEXT NOT NULL CHECK (published_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]*'),
    summary          TEXT NOT NULL CHECK (length(trim(summary)) > 0),
    url              TEXT NOT NULL CHECK (length(trim(url)) > 0),
    first_seen_at    TEXT NOT NULL CHECK (first_seen_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]'),
    available_at     TEXT NOT NULL CHECK (available_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]'),
    snapshot_path    TEXT NOT NULL CHECK (length(trim(snapshot_path)) > 0),
    snapshot_sha256  TEXT NOT NULL CHECK (length(snapshot_sha256) = 64 AND snapshot_sha256 NOT GLOB '*[^0-9a-f]*'),
    PRIMARY KEY (card_id, seq),
    CHECK (available_at >= published_at)
);

-- A1：evidence_strength 两栏（agent、owner）各自锁定；agent 随卡片创建，owner 在截止前补一次，缺失即无行
CREATE TABLE IF NOT EXISTS strength_scores (
    card_id    TEXT NOT NULL REFERENCES cards(id),
    rater      TEXT NOT NULL CHECK (rater IN ('agent', 'owner')),
    score      INTEGER NOT NULL CHECK (score BETWEEN 0 AND 5),
    reason     TEXT NOT NULL CHECK (length(trim(reason)) > 0),
    scored_at  TEXT NOT NULL CHECK (scored_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]'),
    PRIMARY KEY (card_id, rater)
);

-- 候选 → 当下：实际成交（write-once）
CREATE TABLE IF NOT EXISTS entries (
    card_id      TEXT PRIMARY KEY REFERENCES cards(id),
    entry_date   TEXT NOT NULL CHECK (entry_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    entry_price  REAL NOT NULL CHECK (entry_price > 0),
    size_pct     REAL NOT NULL CHECK (size_pct > 0 AND size_pct <= 25),
    recorded_at  TEXT NOT NULL
);

-- §2.2 每日追加（append-only，日期严格递增）
CREATE TABLE IF NOT EXISTS daily (
    card_id      TEXT NOT NULL REFERENCES cards(id),
    date         TEXT NOT NULL CHECK (date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    close        REAL NOT NULL CHECK (close > 0),
    state        TEXT NOT NULL CHECK (state IN ('POP', 'XB', 'BNB', 'REV', 'EXH', 'DROP', 'XBD', 'BNBD', 'TREND_UP', 'TREND_DOWN', 'NEUTRAL')),
    z            REAL,
    rs_1m_rank   INTEGER,
    r_current    REAL,
    mfe          REAL,
    mae          REAL,
    stop_now     REAL,
    bench_close  REAL,
    note         TEXT,
    PRIMARY KEY (card_id, date)
);

-- §2.3 出场（write-once）
CREATE TABLE IF NOT EXISTS exits (
    card_id              TEXT PRIMARY KEY REFERENCES cards(id),
    exit_date            TEXT NOT NULL CHECK (exit_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    exit_price           REAL NOT NULL CHECK (exit_price > 0),
    exit_reason          TEXT NOT NULL CHECK (exit_reason IN ('失效位', '移动止盈', '论点作废', '跟踪期满', '手动')),
    manual_reason        TEXT,
    realized_r           REAL NOT NULL,
    realized_excess_pct  REAL NOT NULL,
    holding_days         INTEGER NOT NULL CHECK (holding_days >= 0),
    recorded_at          TEXT NOT NULL,
    CHECK ((exit_reason = '手动') = (length(trim(coalesce(manual_reason, ''))) > 0))
);

-- §2.4 + §3 跟踪期满（write-once）；final_score 必须等于按锁定规则机械算出的档
CREATE TABLE IF NOT EXISTS finals (
    card_id                TEXT PRIMARY KEY REFERENCES cards(id),
    post_exit_return_pct   REAL NOT NULL,
    post_exit_r            REAL NOT NULL,
    final_score            TEXT NOT NULL CHECK (final_score IN ('达标', '部分', '未达', '证伪')),
    missed_r               REAL NOT NULL,
    stop_quality           INTEGER NOT NULL CHECK (stop_quality IN (0, 1)),
    trail_quality          INTEGER CHECK (trail_quality IN (0, 1)),       -- 未启用移动止盈时为空
    benchmark_beat         INTEGER NOT NULL CHECK (benchmark_beat IN (0, 1)),
    recorded_at            TEXT NOT NULL
);

-- 作废（write-once）：作废卡留在库里并计入分母
CREATE TABLE IF NOT EXISTS voids (
    card_id    TEXT PRIMARY KEY REFERENCES cards(id),
    voided_at  TEXT NOT NULL CHECK (voided_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]'),
    reason     TEXT NOT NULL CHECK (length(trim(reason)) > 0)
);

-- ------------------------------------------------------------------ 触发器：写入条件
CREATE TRIGGER IF NOT EXISTS cards_supersedes BEFORE INSERT ON cards WHEN NEW.supersedes IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'supersedes 必须引用一张已作废的卡')
     WHERE NOT EXISTS (SELECT 1 FROM voids v WHERE v.card_id = NEW.supersedes AND v.voided_at <= NEW.created_at);
END;

CREATE TRIGGER IF NOT EXISTS cards_thesis_source BEFORE INSERT ON cards WHEN NEW.thesis_inval_source_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, '论点失效条件的来源必须是固定源清单里的 A / B 级')
     WHERE NOT EXISTS (SELECT 1 FROM fixed_sources s WHERE s.source_id = NEW.thesis_inval_source_id AND s.grade IN ('A', 'B'));
END;

CREATE TRIGGER IF NOT EXISTS cards_insert_unsealed BEFORE INSERT ON cards WHEN NEW.sealed <> 0
BEGIN
    SELECT RAISE(ABORT, '卡片须先以未封存状态写入，证据与 agent 评分写完后再封存');
END;

CREATE TRIGGER IF NOT EXISTS cards_seal_needs_agent BEFORE UPDATE OF sealed ON cards WHEN OLD.sealed = 0 AND NEW.sealed = 1
BEGIN
    SELECT RAISE(ABORT, '封存前必须有 agent 的 evidence_strength 评分')
     WHERE NOT EXISTS (SELECT 1 FROM strength_scores WHERE card_id = NEW.id AND rater = 'agent');
END;

CREATE TRIGGER IF NOT EXISTS evidence_insert BEFORE INSERT ON evidence
BEGIN
    SELECT RAISE(ABORT, '不允许事后添加证据（卡片已封存）')
     WHERE (SELECT sealed FROM cards WHERE id = NEW.card_id) IS NOT 0;
    SELECT RAISE(ABORT, 'source_id 必须在固定源清单中且等级为 A 或 B')
     WHERE NOT EXISTS (SELECT 1 FROM fixed_sources s WHERE s.source_id = NEW.source_id AND s.grade IN ('A', 'B'));
    SELECT RAISE(ABORT, '证据的 available_at 晚于卡片 created_at')
     WHERE NEW.available_at > (SELECT created_at FROM cards WHERE id = NEW.card_id);
    SELECT RAISE(ABORT, '证据的 first_seen_at 晚于卡片 created_at')
     WHERE NEW.first_seen_at > (SELECT created_at FROM cards WHERE id = NEW.card_id);
END;

CREATE TRIGGER IF NOT EXISTS strength_insert BEFORE INSERT ON strength_scores
BEGIN
    SELECT RAISE(ABORT, 'agent 评分只能随卡片创建写入')
     WHERE NEW.rater = 'agent' AND (SELECT sealed FROM cards WHERE id = NEW.card_id) IS NOT 0;
    SELECT RAISE(ABORT, 'owner 评分只能在卡片封存后写入')
     WHERE NEW.rater = 'owner' AND (SELECT sealed FROM cards WHERE id = NEW.card_id) IS NOT 1;
    SELECT RAISE(ABORT, 'owner 评分超过截止时刻（次日开盘前），记为缺失')
     WHERE NEW.rater = 'owner' AND NEW.scored_at > (SELECT owner_score_deadline FROM cards WHERE id = NEW.card_id);
    SELECT RAISE(ABORT, '评分时刻早于卡片创建')
     WHERE NEW.scored_at < (SELECT created_at FROM cards WHERE id = NEW.card_id);
END;

CREATE TRIGGER IF NOT EXISTS entries_insert BEFORE INSERT ON entries
BEGIN
    SELECT RAISE(ABORT, '卡片未封存或已作废') WHERE (SELECT sealed FROM cards WHERE id = NEW.card_id) IS NOT 1
        OR EXISTS (SELECT 1 FROM voids WHERE card_id = NEW.card_id);
    SELECT RAISE(ABORT, '成交日必须晚于信号收盘日') WHERE NEW.entry_date <= (SELECT close_date FROM cards WHERE id = NEW.card_id);
END;

CREATE TRIGGER IF NOT EXISTS daily_insert BEFORE INSERT ON daily
BEGIN
    SELECT RAISE(ABORT, '卡片未封存、已作废或已跟踪期满') WHERE (SELECT sealed FROM cards WHERE id = NEW.card_id) IS NOT 1
        OR EXISTS (SELECT 1 FROM voids WHERE card_id = NEW.card_id)
        OR EXISTS (SELECT 1 FROM finals WHERE card_id = NEW.card_id);
    SELECT RAISE(ABORT, '每日行只能按日期向后追加') WHERE NEW.date <= coalesce((SELECT max(date) FROM daily WHERE card_id = NEW.card_id), '')
        OR NEW.date < (SELECT close_date FROM cards WHERE id = NEW.card_id);
END;

CREATE TRIGGER IF NOT EXISTS exits_insert BEFORE INSERT ON exits
BEGIN
    SELECT RAISE(ABORT, '没有进场记录或卡片已作废') WHERE NOT EXISTS (SELECT 1 FROM entries WHERE card_id = NEW.card_id)
        OR EXISTS (SELECT 1 FROM voids WHERE card_id = NEW.card_id);
    SELECT RAISE(ABORT, '出场日早于进场日') WHERE NEW.exit_date < (SELECT entry_date FROM entries WHERE card_id = NEW.card_id);
END;

CREATE TRIGGER IF NOT EXISTS finals_insert BEFORE INSERT ON finals
BEGIN
    SELECT RAISE(ABORT, '没有出场记录') WHERE NOT EXISTS (SELECT 1 FROM exits WHERE card_id = NEW.card_id);
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
    SELECT RAISE(ABORT, '卡片未封存') WHERE (SELECT sealed FROM cards WHERE id = NEW.card_id) IS NOT 1;
    SELECT RAISE(ABORT, '已出场的卡片不能作废') WHERE EXISTS (SELECT 1 FROM exits WHERE card_id = NEW.card_id);
    SELECT RAISE(ABORT, '作废时刻早于卡片创建') WHERE NEW.voided_at < (SELECT created_at FROM cards WHERE id = NEW.card_id);
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
