/**
 * astock-trade-entry — 宿主端入口
 *
 * 在 dsh web 进程中挂载 /api/astock-trade-entry/* 路由：
 *   GET  /state   读取当前持仓/可用金额/最近调仓（供界面展示）
 *   POST /append  录入一笔交易 → 更新 每日调仓.md + config/持仓.md（原子、快照可撤销）
 *   POST /undo    撤销最近一笔录入（快照回滚）
 *
 * 一致性保证：
 *   - 唯一写入路径：所有文件变更都经由 writeLedger()，先写 每日调仓.md，
 *     成功后再写 config/持仓.md；任一步失败则回滚前一步，绝不产生半更新状态。
 *   - 写入前生成快照（两个文件的完整文本），undo 直接回滚快照，不依赖"调仓记录
 *     是否完整可重放"（历史 log 早于 2026-07-08，不可重放）。
 *   - 校验（T+1 / 卖出超持仓 / 可用金额不足）在 ledger.validateTrade 中完成。
 */
import { readFile, writeFile, mkdir, rename, readdir, unlink } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { join } from 'node:path';
import {
  buildState, validateTrade, applyTrade,
  serializeDailyLedger, serializePositionsConfig,
  DAILY_LEDGER_REL, POSITIONS_REL, formatQty, formatCash,
} from './ledger.mjs';

export const name = 'astock-trade-entry';

function sameOrigin(request) {
  const origin = request.headers.origin;
  const host = request.headers.host;
  if (origin === undefined || host === undefined) return false;
  try {
    return new URL(origin).host === host;
  } catch {
    return false;
  }
}

async function readJsonBody(request, maxBytes = 16384) {
  const chunks = [];
  let size = 0;
  for await (const chunk of request) {
    const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    size += buffer.length;
    if (size > maxBytes) throw new Error('request body too large');
    chunks.push(buffer);
  }
  return JSON.parse(Buffer.concat(chunks).toString('utf8'));
}

function sendJson(response, status, payload) {
  response.writeHead(status, {
    'cache-control': 'no-store',
    'content-type': 'application/json; charset=utf-8',
  });
  response.end(JSON.stringify(payload));
}

export function apply(ctx, config = {}) {
  const root = config.root ?? process.cwd();
  const dailyPath = join(root, ...DAILY_LEDGER_REL);
  const positionsPath = join(root, ...POSITIONS_REL);
  const snapshotDir = join(root, '.dsh', 'trade-entry', 'undo');

  function ensureFiles() {
    if (!existsSync(dailyPath)) {
      throw new Error(`每日调仓.md 不存在：${dailyPath}（请检查插件 config.root / dsh 工作目录）`);
    }
    if (!existsSync(positionsPath)) {
      throw new Error(`config/持仓.md 不存在：${positionsPath}`);
    }
  }

  async function readLedger() {
    ensureFiles();
    const [dailyText, positionsText] = await Promise.all([
      readFile(dailyPath, 'utf8'),
      readFile(positionsPath, 'utf8'),
    ]);
    return buildState(dailyText, positionsText);
  }

  /** 写两个文件：原子 + 快照 + 失败回滚 */
  async function writeLedger(state) {
    ensureFiles();
    await mkdir(snapshotDir, { recursive: true });
    const beforeDaily = await readFile(dailyPath, 'utf8');
    const beforePositions = await readFile(positionsPath, 'utf8');
    const snapshotId = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const dailyTmp = `${dailyPath}.${snapshotId}.tmp`;
    const positionsTmp = `${positionsPath}.${snapshotId}.tmp`;
    const nextDaily = serializeDailyLedger(state);
    const nextPositions = serializePositionsConfig(state);
    try {
      await writeFile(dailyTmp, nextDaily, 'utf8');
      await rename(dailyTmp, dailyPath);
    } catch (error) {
      try { await unlink(dailyTmp); } catch { /* 忽略 */ }
      throw error;
    }
    try {
      await writeFile(positionsTmp, nextPositions, 'utf8');
      await rename(positionsTmp, positionsPath);
    } catch (error) {
      // 回滚每日调仓.md，保持两文件一致
      try {
        const rollbackTmp = `${dailyPath}.${snapshotId}.rollback`;
        await writeFile(rollbackTmp, beforeDaily, 'utf8');
        await rename(rollbackTmp, dailyPath);
      } catch { /* 忽略 */ }
      try { await unlink(positionsTmp); } catch { /* 忽略 */ }
      throw error;
    }
    // 快照落盘（供 /undo），只保留最近 20 份
    await writeFile(join(snapshotDir, `${snapshotId}.json`), JSON.stringify({
      daily: beforeDaily,
      positions: beforePositions,
      note: state.trades.length > 0 ? state.trades[state.trades.length - 1] : null,
    }), 'utf8');
    const snapshots = await readdir(snapshotDir).catch(() => []);
    snapshots.sort();
    for (const old of snapshots.slice(0, Math.max(0, snapshots.length - 20))) {
      try { await unlink(join(snapshotDir, old)); } catch { /* 忽略 */ }
    }
  }

  function stateView(state, extra = {}) {
    return {
      ok: true,
      root,
      cash: state.cash,
      cashText: formatCash(state.cash),
      positions: [...state.positions.values()]
        .sort((a, b) => a.code.localeCompare(b.code))
        .map((p) => ({ name: p.name, code: p.code, qty: p.qty, qtyText: formatQty(p.qty), cost: p.cost })),
      trades: state.trades.slice(-30).reverse(),
      ...extra,
    };
  }

  ctx.inject(['webServer'], (host) => {
    host.effect(() => {
      const disposers = [
        host.webServer.register({
          kind: 'exact',
          path: '/api/astock-trade-entry/state',
          handler: async (request, response) => {
            if (request.method !== 'GET') { response.writeHead(405, { allow: 'GET' }); response.end(); return; }
            try {
              const state = await readLedger();
              sendJson(response, 200, stateView(state));
            } catch (error) {
              sendJson(response, 500, { ok: false, error: error instanceof Error ? error.message : String(error) });
            }
          },
        }),
        host.webServer.register({
          kind: 'exact',
          path: '/api/astock-trade-entry/append',
          handler: async (request, response) => {
            if (request.method !== 'POST') { response.writeHead(405, { allow: 'POST' }); response.end(); return; }
            if (!sameOrigin(request)) return sendJson(response, 403, { ok: false, error: 'untrusted origin' });
            try {
              const body = await readJsonBody(request);
              const trade = {
                date: String(body.date ?? '').trim(),
                name: String(body.name ?? '').trim(),
                code: String(body.code ?? '').trim(),
                qty: Number(body.qty),
                price: Number(body.price),
                side: body.side === '卖出' ? '卖出' : '买入',
                note: String(body.note ?? '').trim(),
              };
              const state = await readLedger();
              const check = validateTrade(state, trade, { allowOverdraft: !!config.allowOverdraft });
              if (!check.ok) return sendJson(response, 400, { ok: false, error: check.error });
              const next = applyTrade(state, trade);
              await writeLedger(next);
              const entry = next.trades[next.trades.length - 1];
              sendJson(response, 200, stateView(next, {
                entry: {
                  ...entry,
                  qtyText: formatQty(entry.qty),
                  noteText: entry.note ?? '',
                },
                message: `已录入 ${entry.date} ${entry.side} ${entry.name}(${entry.code}) ${formatQty(entry.qty)} 份 @ ${entry.price}`,
              }));
            } catch (error) {
              sendJson(response, 400, { ok: false, error: error instanceof Error ? error.message : String(error) });
            }
          },
        }),
        host.webServer.register({
          kind: 'exact',
          path: '/api/astock-trade-entry/undo',
          handler: async (request, response) => {
            if (request.method !== 'POST') { response.writeHead(405, { allow: 'POST' }); response.end(); return; }
            if (!sameOrigin(request)) return sendJson(response, 403, { ok: false, error: 'untrusted origin' });
            try {
              const snapshots = await readdir(snapshotDir).catch(() => []);
              if (snapshots.length === 0) return sendJson(response, 400, { ok: false, error: '没有可撤销的录入' });
              const latest = [...snapshots].sort().at(-1);
              const snapshot = JSON.parse(await readFile(join(snapshotDir, latest), 'utf8'));
              await writeFile(dailyPath, snapshot.daily, 'utf8');
              await writeFile(positionsPath, snapshot.positions, 'utf8');
              await unlink(join(snapshotDir, latest));
              const state = await readLedger();
              sendJson(response, 200, stateView(state, {
                message: snapshot.note
                  ? `已撤销最近一笔：${snapshot.note.date} ${snapshot.note.side} ${snapshot.note.name}(${snapshot.note.code}) ${formatQty(snapshot.note.qty)} 份`
                  : '已撤销最近一笔录入',
              }));
            } catch (error) {
              sendJson(response, 400, { ok: false, error: error instanceof Error ? error.message : String(error) });
            }
          },
        }),
      ];
      return () => {
        for (const dispose of disposers) {
          try { dispose(); } catch { /* 忽略 */ }
        }
      };
    }, 'astock-trade-entry: http routes');
  });
}
