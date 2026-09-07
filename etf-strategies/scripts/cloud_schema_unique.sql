-- 补唯一约束：防止双进程并发 select-then-insert 产生重复（云权威多进程架构的关键保障）
-- 幂等：已存在约束则跳过（DO NOTHING 语义由 IF NOT EXISTS / 异常容错处理）

-- daily_signals：(strategy_id, signal_date, asset_code) 唯一
CREATE UNIQUE INDEX IF NOT EXISTS uq_daily_signals_strat_date_asset
  ON daily_signals(strategy_id, signal_date, asset_code);

-- daily_reports：(report_date, report_type) 唯一
CREATE UNIQUE INDEX IF NOT EXISTS uq_daily_reports_date_type
  ON daily_reports(report_date, report_type);

-- portfolio_holdings：code 唯一（快照替换语义也受益于唯一约束防并发重复）
CREATE UNIQUE INDEX IF NOT EXISTS uq_portfolio_holdings_code
  ON portfolio_holdings(code);

-- agent_knowledge：url 唯一（knowledge_upsert 去重依赖）
CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_knowledge_url
  ON agent_knowledge(url);

-- agent_sources：name 唯一（来源列表防并发重复）
CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_sources_name
  ON agent_sources(name);
