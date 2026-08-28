window.__ModuleLoader__.load({
	id: "@astock/dsh-trade-entry",
	factory: (require) => {
		var module = { exports: {} };
		var exports = module.exports;
		Object.defineProperty(exports, Symbol.toStringTag, { value: "Module" });
		let react = require("react");
		let react_jsx_runtime = require("react/jsx-runtime");
		let primitives = require("@deepseek-ai/dsh-client-ui-primitives");

		//#region styles
		const css = [
			".astock-te-root{--astock-te-accent:var(--dsw-alias-state-info-primary, #4f8cff)}",
			".astock-te-btn{display:inline-flex;align-items:center;gap:6px;width:100%;min-height:30px;color:var(--dsw-alias-label-secondary);background:transparent;border:0;border-radius:8px;padding:5px 10px;font-size:12.5px;line-height:18px;cursor:pointer;text-align:left}",
			".astock-te-btn:hover{background:var(--dsw-alias-interactive-bg-hover);color:var(--dsw-alias-label-primary)}",
			".astock-te-btn span{flex:none}",
			".astock-te-mask{position:fixed;inset:0;z-index:900;background:var(--dsw-alias-bg-mask-1, rgba(0,0,0,.4))}",
			".astock-te-panel{position:fixed;top:0;right:0;bottom:0;z-index:901;width:min(560px,100vw - 24px);background:var(--dsw-specific-menu, var(--dsw-alias-bg-base));border-left:1px solid var(--dsw-alias-border-l2);box-shadow:var(--dsw-shadow-lv3);display:flex;flex-direction:column;font-size:13px;line-height:20px;color:var(--dsw-alias-label-primary)}",
			".astock-te-head{display:flex;align-items:center;gap:8px;padding:14px 16px;border-bottom:1px solid var(--dsw-alias-border-l1);flex:none}",
			".astock-te-head h2{margin:0;font-size:15px;font-weight:600;flex:1}",
			".astock-te-iconbtn{display:inline-flex;align-items:center;justify-content:center;width:26px;height:26px;color:var(--dsw-alias-label-secondary);background:transparent;border:0;border-radius:6px;cursor:pointer;padding:0}",
			".astock-te-iconbtn:hover{background:var(--dsw-alias-interactive-bg-hover);color:var(--dsw-alias-label-primary)}",
			".astock-te-body{flex:1;overflow:auto;padding:14px 16px;display:flex;flex-direction:column;gap:16px;--dsh-scrollbar-thumb:var(--dsw-alias-scrollbar-bg-l2);--dsh-scrollbar-thumb-hover:var(--dsw-alias-scrollbar-hover-l2)}",
			".astock-te-cash{display:flex;align-items:baseline;gap:8px;padding:12px 14px;border:1px solid var(--dsw-alias-border-l1);border-radius:12px;background:var(--dsw-alias-bg-layer-2)}",
			".astock-te-cash b{font-size:20px;font-variant-numeric:tabular-nums}",
			".astock-te-cash span{color:var(--dsw-alias-label-tertiary);font-size:12px}",
			".astock-te-sec-title{font-size:12px;color:var(--dsw-alias-label-tertiary);margin:0 0 6px;display:flex;align-items:center;gap:6px}",
			".astock-te-table{width:100%;border-collapse:collapse;font-size:12.5px}",
			".astock-te-table th{color:var(--dsw-alias-label-tertiary);font-weight:500;text-align:left;padding:4px 6px;border-bottom:1px solid var(--dsw-alias-border-l1);white-space:nowrap}",
			".astock-te-table td{padding:6px;border-bottom:1px solid var(--dsw-alias-border-l1);font-variant-numeric:tabular-nums}",
			".astock-te-table tr.astock-te-row{cursor:pointer}",
			".astock-te-table tr.astock-te-row:hover td{background:var(--dsw-alias-interactive-bg-hover)}",
			".astock-te-empty{color:var(--dsw-alias-label-tertiary);padding:12px 0;text-align:center}",
			".astock-te-form{display:flex;flex-direction:column;gap:10px;padding:12px 14px;border:1px solid var(--dsw-alias-border-l1);border-radius:12px;background:var(--dsw-alias-bg-layer-2)}",
			".astock-te-row2{display:grid;grid-template-columns:1fr 1fr;gap:10px}",
			".astock-te-row3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px}",
			".astock-te-field{display:flex;flex-direction:column;gap:4px}",
			".astock-te-field label{font-size:11.5px;color:var(--dsw-alias-label-tertiary)}",
			".astock-te-field input,.astock-te-field select{box-sizing:border-box;width:100%;min-height:30px;padding:4px 8px;font-size:13px;color:var(--dsw-alias-label-primary);background:var(--dsw-alias-bg-base);border:1px solid var(--dsw-alias-border-l2);border-radius:8px;outline:none}",
			".astock-te-field input:focus,.astock-te-field select:focus{border-color:var(--astock-te-accent)}",
			".astock-te-check{display:flex;align-items:center;gap:6px;font-size:12.5px;cursor:pointer;color:var(--dsw-alias-label-secondary)}",
			".astock-te-check input{accent-color:var(--astock-te-accent)}",
			".astock-te-note{display:flex;flex-direction:column;gap:4px}",
			".astock-te-note label{font-size:11.5px;color:var(--dsw-alias-label-tertiary)}",
			".astock-te-note input{box-sizing:border-box;width:100%;min-height:30px;padding:4px 8px;font-size:13px;color:var(--dsw-alias-label-primary);background:var(--dsw-alias-bg-base);border:1px solid var(--dsw-alias-border-l2);border-radius:8px;outline:none}",
			".astock-te-actions{display:flex;gap:8px;align-items:center}",
			".astock-te-submit{flex:1;min-height:32px;border:0;border-radius:8px;background:var(--astock-te-accent);color:#fff;font-size:13px;font-weight:600;cursor:pointer;padding:0 12px}",
			".astock-te-submit:disabled{opacity:.6;cursor:default}",
			".astock-te-submit.buy{background:var(--dsw-alias-state-error-primary, #e5484d)}",
			".astock-te-undo{min-height:32px;border:1px solid var(--dsw-alias-border-l2);border-radius:8px;background:transparent;color:var(--dsw-alias-label-secondary);font-size:12.5px;cursor:pointer;padding:0 10px}",
			".astock-te-undo:hover{background:var(--dsw-alias-interactive-bg-hover)}",
			".astock-te-msg{font-size:12.5px;border-radius:8px;padding:8px 10px;line-height:18px}",
			".astock-te-msg.ok{color:var(--dsw-alias-state-success-primary, #30a46c);background:var(--dsw-alias-bg-layer-2)}",
			".astock-te-msg.err{color:var(--dsw-alias-state-error-primary, #e5484d);background:var(--dsw-alias-bg-layer-2)}",
			".astock-te-tag{display:inline-block;border-radius:4px;padding:0 5px;font-size:11px;line-height:16px}",
			".astock-te-tag.buy{color:#e5484d;background:rgba(229,72,77,.12)}",
			".astock-te-tag.sell{color:#30a46c;background:rgba(48,164,108,.12)}",
			".astock-te-tag.t0{color:var(--astock-te-accent);background:color-mix(in srgb, var(--astock-te-accent) 14%, transparent)}",
			".astock-te-trades{display:flex;flex-direction:column;gap:2px}",
			".astock-te-trade{display:grid;grid-template-columns:76px 44px 1fr auto;gap:8px;align-items:center;padding:5px 6px;border-radius:6px;font-size:12px;font-variant-numeric:tabular-nums}",
			".astock-te-trade:hover{background:var(--dsw-alias-interactive-bg-hover)}",
			".astock-te-trade .note{color:var(--dsw-alias-label-tertiary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}"
		].join("");
		const tagId = "@astock/dsh-trade-entry/styles";
		if (typeof document !== "undefined" && document.querySelector("style[data-plugin-css=" + JSON.stringify(tagId) + "]") === null) {
			const tag = document.createElement("style");
			tag.dataset.plugin = "@astock/dsh-trade-entry";
			tag.dataset.pluginCss = tagId;
			tag.textContent = css;
			document.head.appendChild(tag);
		}
		//#endregion

		const NS = "astockTradeEntry";
		const zh = {
			"button.label": "持仓 / 资产",
			"panel.title": "持仓 / 资产",
			"cash.label": "可用金额（元）",
			"sec.positions": "当前持仓",
			"sec.entry": "录入交易",
			"sec.recent": "最近调仓",
			"col.name": "名称",
			"col.code": "代码",
			"col.qty": "数量(份)",
			"col.cost": "成本价",
			"col.date": "日期",
			"col.side": "方向",
			"col.price": "价格",
			"col.note": "备注",
			"empty.positions": "暂无持仓",
			"empty.trades": "暂无调仓记录",
			"field.date": "日期",
			"field.name": "名称",
			"field.code": "代码",
			"field.side": "方向",
			"field.side.buy": "买入",
			"field.side.sell": "卖出",
			"field.qty": "数量（份）",
			"field.price": "价格（元）",
			"field.note": "备注（如信号ID / 做T / 打新底仓）",
			"ttrade": "做T",
			"submit": "录入",
			"undo": "撤销最近一笔",
			"refresh": "刷新",
			"close": "关闭",
			"loading": "加载中…",
			"load.fail": "无法读取持仓数据",
			"busy": "处理中…",
			"click.hint": "点击持仓行可快速填入",
			"t0.hint": "T+0品种",
		};
		const en = zh;

		function today() {
			const d = new Date();
			const p = (n) => String(n).padStart(2, "0");
			return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
		}

		function TradeEntryButton({ wide, t }) {
			const [open, setOpen] = react.useState(false);
			const label = t("button.label");
			return react_jsx_runtime.jsxs(react_jsx_runtime.Fragment, {
				children: [
					react_jsx_runtime.jsx("button", {
						type: "button",
						className: "astock-te-btn",
						title: label,
						"aria-expanded": open,
						onClick: () => setOpen((v) => !v),
						children: [
							react_jsx_runtime.jsx(primitives.IconListPenOutline16, { size: 16 }),
							wide ? react_jsx_runtime.jsx("span", { children: label }) : null
						]
					}),
					open ? react_jsx_runtime.jsx(TradeEntryPanel, { t, onClose: () => setOpen(false) }) : null
				]
			});
		}

		function TradeEntryPanel({ t, onClose }) {
			const [data, setData] = react.useState(null);
			const [error, setError] = react.useState(null);
			const [busy, setBusy] = react.useState(false);
			const [msg, setMsg] = react.useState(null);
			const [date, setDate] = react.useState(today);
			const [code, setCode] = react.useState("");
			const [name, setName] = react.useState("");
			const [side, setSide] = react.useState("买入");
			const [isT, setIsT] = react.useState(false);
			const [qty, setQty] = react.useState("");
			const [price, setPrice] = react.useState("");
			const [note, setNote] = react.useState("");
			const [t0, setT0] = react.useState(new Set());

			const fetchState = react.useCallback(async () => {
				setError(null);
				try {
					const res = await fetch("/api/astock-trade-entry/state", { headers: { accept: "application/json" } });
					const body = await res.json();
					if (!res.ok || !body.ok) throw new Error(body.error || t("load.fail"));
					setData(body);
					setT0(new Set((body.trades || []).filter((tr) => /^(51[13]|159|511|501|502)/.test(tr.code)).map((tr) => tr.code)));
				} catch (e) {
					setError(e instanceof Error ? e.message : String(e));
					setData(null);
				}
			}, [t]);

			react.useEffect(() => { fetchState(); }, [fetchState]);

			const positions = data?.positions ?? [];
			const trades = data?.trades ?? [];

			const pickPosition = (p) => {
				setCode(p.code);
				setName(p.name);
			};

			const submit = async () => {
				if (busy) return;
				const qtyNum = Number(qty);
				const priceNum = Number(price);
				if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) { setMsg({ kind: "err", text: "日期格式应为 YYYY-MM-DD" }); return; }
				if (!code.trim() || !/^\d{6}$/.test(code.trim())) { setMsg({ kind: "err", text: "请输入 6 位股票代码" }); return; }
				if (!name.trim()) { setMsg({ kind: "err", text: "请输入股票名称" }); return; }
				if (!Number.isInteger(qtyNum) || qtyNum <= 0) { setMsg({ kind: "err", text: "数量必须为正整数" }); return; }
				if (!Number.isFinite(priceNum) || priceNum <= 0) { setMsg({ kind: "err", text: "价格必须为正数" }); return; }
				setBusy(true);
				setMsg(null);
				try {
					const res = await fetch("/api/astock-trade-entry/append", {
						method: "POST",
						headers: { "content-type": "application/json" },
						body: JSON.stringify({
							date: date.trim(),
							code: code.trim(),
							name: name.trim(),
							side,
							qty: qtyNum,
							price: priceNum,
							note: (isT ? "【做T】" : "") + note.trim(),
						}),
					});
					const body = await res.json();
					if (!res.ok || !body.ok) throw new Error(body.error || "录入失败");
					setData(body);
					setMsg({ kind: "ok", text: body.message });
					setQty("");
					setPrice("");
					setNote("");
					setIsT(false);
					if (body.trades) setT0(new Set(body.trades.filter((tr) => /^(51[13]|159|511|501|502)/.test(tr.code)).map((tr) => tr.code)));
				} catch (e) {
					setMsg({ kind: "err", text: e instanceof Error ? e.message : String(e) });
				} finally {
					setBusy(false);
				}
			};

			const undo = async () => {
				if (busy) return;
				setBusy(true);
				setMsg(null);
				try {
					const res = await fetch("/api/astock-trade-entry/undo", { method: "POST" });
					const body = await res.json();
					if (!res.ok || !body.ok) throw new Error(body.error || "撤销失败");
					setData(body);
					setMsg({ kind: "ok", text: body.message });
				} catch (e) {
					setMsg({ kind: "err", text: e instanceof Error ? e.message : String(e) });
				} finally {
					setBusy(false);
				}
			};

			return react_jsx_runtime.jsxs(react_jsx_runtime.Fragment, {
				children: [
					react_jsx_runtime.jsx("div", {
						className: "astock-te-mask",
						onClick: onClose
					}),
					react_jsx_runtime.jsxs("div", {
						className: "astock-te-panel",
						role: "dialog",
						"aria-label": t("panel.title"),
						children: [
							react_jsx_runtime.jsxs("div", {
								className: "astock-te-head",
								children: [
									react_jsx_runtime.jsx("h2", { children: t("panel.title") }),
									react_jsx_runtime.jsx("button", {
										type: "button",
										className: "astock-te-iconbtn",
										title: t("refresh"),
										"aria-label": t("refresh"),
										onClick: fetchState,
										children: react_jsx_runtime.jsx(primitives.IconRefreshOutline14, { size: 15 })
									}),
									react_jsx_runtime.jsx("button", {
										type: "button",
										className: "astock-te-iconbtn",
										title: t("close"),
										"aria-label": t("close"),
										onClick: onClose,
										children: react_jsx_runtime.jsx(primitives.IconCloseOutline16, { size: 16 })
									})
								]
							}),
							react_jsx_runtime.jsxs("div", {
								className: "astock-te-body",
								children: [
									error ? react_jsx_runtime.jsx("div", { className: "astock-te-msg err", children: error }) : null,
									msg ? react_jsx_runtime.jsx("div", { className: "astock-te-msg " + msg.kind, children: msg.text }) : null,
									!data && !error ? react_jsx_runtime.jsx("div", { className: "astock-te-empty", children: t("loading") }) : null,
									data ? react_jsx_runtime.jsxs(react_jsx_runtime.Fragment, {
										children: [
											react_jsx_runtime.jsxs("div", {
												className: "astock-te-cash",
												children: [
													react_jsx_runtime.jsx("span", { children: t("cash.label") }),
													react_jsx_runtime.jsx("b", { children: data.cashText })
												]
											}),
											react_jsx_runtime.jsx("h3", { className: "astock-te-sec-title", children: t("sec.positions") }),
											positions.length === 0
												? react_jsx_runtime.jsx("div", { className: "astock-te-empty", children: t("empty.positions") })
												: react_jsx_runtime.jsxs("table", {
													className: "astock-te-table",
													children: [
														react_jsx_runtime.jsx("thead", {
															children: react_jsx_runtime.jsxs("tr", {
																children: [
																	react_jsx_runtime.jsx("th", { children: t("col.name") }),
																	react_jsx_runtime.jsx("th", { children: t("col.code") }),
																	react_jsx_runtime.jsx("th", { children: t("col.qty") }),
																	react_jsx_runtime.jsx("th", { children: t("col.cost") })
																]
															})
														}),
														react_jsx_runtime.jsx("tbody", {
															children: positions.map((p) => react_jsx_runtime.jsxs("tr", {
																className: "astock-te-row",
																title: t("click.hint"),
																onClick: () => pickPosition(p),
																children: [
																	react_jsx_runtime.jsxs("td", {
																		children: [
																			p.name,
																			t0.has(p.code) ? react_jsx_runtime.jsx("span", { className: "astock-te-tag t0", style: { marginLeft: 6 }, children: "T+0" }) : null
																		]
																	}),
																	react_jsx_runtime.jsx("td", { children: p.code }),
																	react_jsx_runtime.jsx("td", { children: p.qtyText }),
																	react_jsx_runtime.jsx("td", { children: p.cost })
																]
															}, p.code))
														})
													]
												}),
											react_jsx_runtime.jsx("h3", { className: "astock-te-sec-title", children: t("sec.entry") }),
											react_jsx_runtime.jsxs("div", {
												className: "astock-te-form",
												children: [
													react_jsx_runtime.jsxs("div", {
														className: "astock-te-row3",
														children: [
															react_jsx_runtime.jsxs("div", {
																className: "astock-te-field",
																children: [
																	react_jsx_runtime.jsx("label", { children: t("field.date") }),
																	react_jsx_runtime.jsx("input", { type: "date", value: date, onChange: (e) => setDate(e.target.value) })
																]
															}),
															react_jsx_runtime.jsxs("div", {
																className: "astock-te-field",
																children: [
																	react_jsx_runtime.jsx("label", { children: t("field.side") }),
																	react_jsx_runtime.jsx("select", {
																		value: side,
																		onChange: (e) => setSide(e.target.value),
																		children: [
																			react_jsx_runtime.jsx("option", { value: "买入", children: t("field.side.buy") }),
																			react_jsx_runtime.jsx("option", { value: "卖出", children: t("field.side.sell") })
																		]
																	})
																]
															}),
															react_jsx_runtime.jsxs("div", {
																className: "astock-te-field",
																children: [
																	react_jsx_runtime.jsx("label", { children: t("field.code") }),
																	react_jsx_runtime.jsx("input", {
																		list: "astock-te-codes",
																		value: code,
																		placeholder: "如 512480",
																		onChange: (e) => {
																			const v = e.target.value;
																			setCode(v);
																			const hit = positions.find((p) => p.code === v);
																			if (hit) setName(hit.name);
																		}
																	})
																]
															})
														]
													}),
													react_jsx_runtime.jsx("datalist", {
														id: "astock-te-codes",
														children: positions.map((p) => react_jsx_runtime.jsx("option", { value: p.code, children: `${p.name}（${p.code}）` }, p.code))
													}),
													react_jsx_runtime.jsxs("div", {
														className: "astock-te-row2",
														children: [
															react_jsx_runtime.jsxs("div", {
																className: "astock-te-field",
																children: [
																	react_jsx_runtime.jsx("label", { children: t("field.name") }),
																	react_jsx_runtime.jsx("input", { value: name, placeholder: "如 半导体ETF", onChange: (e) => setName(e.target.value) })
																]
															}),
															react_jsx_runtime.jsxs("div", {
																className: "astock-te-field",
																children: [
																	react_jsx_runtime.jsx("label", { children: t("field.qty") }),
																	react_jsx_runtime.jsx("input", { type: "number", min: "1", step: "100", value: qty, placeholder: "如 6100", onChange: (e) => setQty(e.target.value) })
																]
															})
														]
													}),
													react_jsx_runtime.jsxs("div", {
														className: "astock-te-row2",
														children: [
															react_jsx_runtime.jsxs("div", {
																className: "astock-te-field",
																children: [
																	react_jsx_runtime.jsx("label", { children: t("field.price") }),
																	react_jsx_runtime.jsx("input", { type: "number", min: "0.001", step: "0.001", value: price, placeholder: "如 1.044", onChange: (e) => setPrice(e.target.value) })
																]
															}),
															react_jsx_runtime.jsxs("label", {
																className: "astock-te-check",
																children: [
																	react_jsx_runtime.jsx("input", { type: "checkbox", checked: isT, onChange: (e) => setIsT(e.target.checked) }),
																	react_jsx_runtime.jsx("span", { children: t("ttrade") })
																]
															})
														]
													}),
													react_jsx_runtime.jsxs("div", {
														className: "astock-te-note",
														children: [
															react_jsx_runtime.jsx("label", { children: t("field.note") }),
															react_jsx_runtime.jsx("input", { value: note, onChange: (e) => setNote(e.target.value) })
														]
													}),
													react_jsx_runtime.jsxs("div", {
														className: "astock-te-actions",
														children: [
															react_jsx_runtime.jsx("button", {
																type: "button",
																className: "astock-te-submit " + (side === "卖出" ? "sell" : "buy"),
																disabled: busy,
																onClick: submit,
																children: busy ? t("busy") : (side === "卖出" ? t("field.side.sell") : t("field.side.buy")) + " · " + t("submit")
															}),
															react_jsx_runtime.jsx("button", {
																type: "button",
																className: "astock-te-undo",
																disabled: busy,
																onClick: undo,
																children: t("undo")
															})
														]
													})
												]
											}),
											react_jsx_runtime.jsx("h3", { className: "astock-te-sec-title", children: t("sec.recent") }),
											trades.length === 0
												? react_jsx_runtime.jsx("div", { className: "astock-te-empty", children: t("empty.trades") })
												: react_jsx_runtime.jsx("div", {
													className: "astock-te-trades",
													children: trades.slice(0, 10).map((tr) => react_jsx_runtime.jsxs("div", {
														className: "astock-te-trade",
														children: [
															react_jsx_runtime.jsx("span", { children: tr.date }),
															react_jsx_runtime.jsx("span", { className: "astock-te-tag " + (tr.side === "卖出" ? "sell" : "buy"), children: tr.side }),
															react_jsx_runtime.jsx("span", { children: `${tr.name} ${tr.qtyText}份 @ ${tr.price}` }),
															react_jsx_runtime.jsx("span", { className: "note", title: tr.note || "", children: tr.note || "" })
														]
													}, tr.date + tr.code + tr.qty + tr.price))
												})
										]
									}) : null
								]
							})
						]
					})
				]
			});
		}

		const inject = ["sessions", "slots", "locale"];

		function apply(ctx) {
			ctx.effect(() => ctx.locale.register(NS, { zh, en }), "astock-trade-entry: dictionaries");
			ctx.slots.inject("sidebar.footer.action", () => ctx.slots.register({
				name: "sidebar.footer.action",
				id: "astock-trade-entry",
				order: 30,
				locale: NS
			}, TradeEntryButton));
		}

		exports.TradeEntryButton = TradeEntryButton;
		exports.apply = apply;
		exports.inject = inject;
		return module.exports;
	}
});
