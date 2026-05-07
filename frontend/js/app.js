/**
 * app.js — Main SPA controller for Agentic Trading Platform.
 * Handles navigation, analysis mode, expert mode, orders, and LLM configuration.
 */

// ── State ────────────────────────────────────────────────────────────
const state = {
    currentPage: 'landing',
    analysisRunning: false,
    currentAnalysisId: null,
    currentAnalysisTicker: null,
    currentVerdict: null,
    providers: [],
    ollamaModels: [],
    allOrders: [],          // cached orders for client-side filtering
    currentFilter: 'all',
    // Strategy chat
    strategyChatHistory: [],
    strategyChatOpen: false,
    strategyChatBusy: false,
};

// ── Navigation ───────────────────────────────────────────────────────
function navigateTo(page) {
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));

    const pageEl = document.getElementById(`page-${page}`);
    const navBtn = document.querySelector(`.nav-btn[data-page="${page}"]`);

    if (pageEl) pageEl.classList.add('active');
    if (navBtn) navBtn.classList.add('active');

    state.currentPage = page;

    if (page === 'expert') loadExpertAgents();
    if (page === 'orders') { loadAccount(); loadPositions(); loadOrders(); }
}

// ── Toast notifications ──────────────────────────────────────────────
function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => toast.remove(), 5000);
}

// ── API helpers ──────────────────────────────────────────────────────
async function api(endpoint, options = {}) {
    const resp = await fetch(endpoint, {
        headers: { 'Content-Type': 'application/json' },
        ...options,
    });
    if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }));
        throw new Error(err.detail || 'Request failed');
    }
    return resp.json();
}

// ── Formatting helpers ───────────────────────────────────────────────
function fmt$(val) {
    if (val == null || isNaN(val)) return '—';
    return '$' + Number(val).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtDate(iso) {
    if (!iso) return '—';
    return new Date(iso).toLocaleString('en-US', {
        month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
    });
}

// ── LLM Config ───────────────────────────────────────────────────────
async function loadProviders() {
    try {
        const data = await api('/api/llm/providers');
        state.providers = data.providers || [];
        updateModelDropdowns();
    } catch (e) {
        console.warn('Could not load providers:', e);
    }
}

function updateModelDropdowns() {
    updateModelSelect('analysis');
    updateModelSelect('agent');
    updateModelSelect('strategy');
}

function updateModelSelect(prefix) {
    const providerEl = document.getElementById(`${prefix}-provider`);
    const modelEl = document.getElementById(`${prefix}-model`);
    if (!providerEl || !modelEl) return;

    const provider = providerEl.value;
    const prov = state.providers.find(p => p.id === provider);

    modelEl.innerHTML = '';
    if (prov && prov.models && prov.models.length > 0) {
        prov.models.forEach(m => {
            const opt = document.createElement('option');
            opt.value = m;
            opt.textContent = m;
            modelEl.appendChild(opt);
        });
    } else {
        const opt = document.createElement('option');
        opt.value = '';
        opt.textContent = provider === 'ollama' ? '(auto-detect)' : '(default)';
        modelEl.appendChild(opt);
    }
}

function onProviderChange(prefix) {
    updateModelSelect(prefix);
}

function getAnalysisLLMConfig() {
    return {
        llm_provider: document.getElementById('analysis-provider')?.value || 'ollama',
        llm_model: document.getElementById('analysis-model')?.value || '',
        llm_think: document.getElementById('analysis-think')?.checked ?? true,
    };
}

// ── Analysis Mode ────────────────────────────────────────────────────

async function suggestStocks() {
    const btn = document.getElementById('btn-suggest');
    btn.disabled = true;
    btn.textContent = '⏳ Thinking...';

    try {
        const config = getAnalysisLLMConfig();
        const data = await api('/api/analysis/suggest-stocks', {
            method: 'POST',
            body: JSON.stringify(config),
        });

        const area = document.getElementById('suggestions-area');
        const cardsEl = document.getElementById('suggestion-cards');
        area.classList.remove('hidden');
        cardsEl.innerHTML = '';

        (data.suggestions || []).forEach(s => {
            const card = document.createElement('div');
            card.className = 'suggestion-card';
            card.onclick = () => {
                document.getElementById('analysis-ticker').value = s.ticker;
                area.classList.add('hidden');
                startAnalysis();
            };
            card.innerHTML = `
                <div class="stock-ticker">${s.ticker}</div>
                <div class="stock-name">${s.name}</div>
                <div class="stock-reason">${s.reason}</div>
            `;
            cardsEl.appendChild(card);
        });
    } catch (e) {
        showToast('Failed to get suggestions: ' + e.message, 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = '🎯 Suggest Stocks';
    }
}

async function startAnalysis() {
    const ticker = document.getElementById('analysis-ticker').value.trim().toUpperCase();
    if (!ticker) {
        showToast('Enter a stock ticker or click "Suggest Stocks"', 'error');
        return;
    }

    // Reset UI
    resetAnalysisUI();
    state.analysisRunning = true;
    state.currentAnalysisTicker = ticker;
    state.currentVerdict = null;

    const btn = document.getElementById('btn-start-analysis');
    btn.disabled = true;
    btn.textContent = '⏳ Running...';
    document.getElementById('btn-cancel-analysis').classList.remove('hidden');

    const config = getAnalysisLLMConfig();

    try {
        const data = await api('/api/analysis/run', {
            method: 'POST',
            body: JSON.stringify({ ticker, ...config }),
        });
        state.currentAnalysisId = data.analysis_id;
        document.getElementById('analysis-progress').classList.remove('hidden');
        setStep(1, 'active');
        updateAgentStatus('Gathering market data for ' + ticker + '...');
        showToast(`Analysis started for ${ticker}`, 'info');
    } catch (e) {
        showToast('Failed to start analysis: ' + e.message, 'error');
        btn.disabled = false;
        btn.textContent = '🚀 Run Analysis';
        document.getElementById('btn-cancel-analysis').classList.add('hidden');
        state.analysisRunning = false;
    }
}

async function cancelAnalysis() {
    if (!state.currentAnalysisId) {
        showToast('No analysis running', 'error');
        return;
    }
    try {
        await api(`/api/analysis/${state.currentAnalysisId}/cancel`, { method: 'POST' });
        showToast('Cancellation requested...', 'info');
        document.getElementById('btn-cancel-analysis').disabled = true;
        document.getElementById('btn-cancel-analysis').textContent = '⏳ Stopping...';
    } catch (e) {
        showToast('Failed to cancel: ' + e.message, 'error');
    }
}

function resetAnalysisUI() {
    // Hide result sections
    ['factors-section', 'research-section', 'debate-section', 'verdict-section', 'analysis-history-section'].forEach(id => {
        document.getElementById(id)?.classList.add('hidden');
    });
    // Hide trade action bar
    const actionBar = document.getElementById('trade-action-bar');
    if (actionBar) actionBar.classList.add('hidden');
    // Clear stream
    clearAnalysisStream();
    // Clear content
    document.getElementById('factors-list').innerHTML = '';
    document.getElementById('research-reports').innerHTML = '';
    document.getElementById('debate-bull-args').innerHTML = '';
    document.getElementById('debate-bear-args').innerHTML = '';
    // Reset progress
    document.querySelectorAll('.progress-step').forEach(s => {
        s.classList.remove('active', 'done');
    });
    document.getElementById('suggestions-area')?.classList.add('hidden');
}

function setStep(num, status) {
    document.querySelectorAll('.progress-step').forEach(s => {
        const sNum = parseInt(s.dataset.step);
        if (sNum < num) {
            s.classList.remove('active');
            s.classList.add('done');
        } else if (sNum === num) {
            s.classList.remove('done');
            s.classList.toggle('active', status === 'active');
            if (status === 'done') {
                s.classList.remove('active');
                s.classList.add('done');
            }
        } else {
            s.classList.remove('active', 'done');
        }
    });
}

function updateAgentStatus(text) {
    const el = document.getElementById('agent-status-text');
    if (el) el.textContent = text;
}

// ── WebSocket Handlers for Analysis ──────────────────────────────────

// Live token stream display
WS.on('analysis_token', (msg) => {
    const box = document.getElementById('analysis-stream-box');
    const content = document.getElementById('analysis-stream-content');
    const label = document.getElementById('stream-agent-label');
    if (!box || !content) return;

    // Show the stream box
    box.classList.remove('hidden');

    // Update agent label
    const agentName = msg.agent || msg.step || '';
    if (label && agentName) label.textContent = agentName;

    // Append token
    content.textContent += msg.token;

    // Auto-scroll and keep visible
    content.scrollTop = content.scrollHeight;
});

function clearAnalysisStream() {
    const box = document.getElementById('analysis-stream-box');
    const content = document.getElementById('analysis-stream-content');
    if (content) content.textContent = '';
    if (box) box.classList.add('hidden');
}

WS.on('analysis_started', (msg) => {
    setStep(1, 'done');
    setStep(2, 'active');
    clearAnalysisStream();
    updateAgentStatus(`Factor Identifier Agent analyzing ${msg.ticker}...`);
});

WS.on('factors_identified', (msg) => {
    setStep(2, 'done');
    setStep(3, 'active');
    clearAnalysisStream();
    updateAgentStatus(`Spawning ${(msg.factors || []).length} research agents...`);

    const section = document.getElementById('factors-section');
    const list = document.getElementById('factors-list');
    section.classList.remove('hidden');
    list.innerHTML = '';

    (msg.factors || []).forEach((f, i) => {
        const chip = document.createElement('div');
        chip.className = 'factor-chip';
        chip.id = `factor-chip-${i}`;
        chip.innerHTML = `<span class="chip-icon">🔬</span> ${f.factor_name}`;
        chip.title = f.description;
        list.appendChild(chip);
    });
});

WS.on('research_started', (msg) => {
    document.getElementById('research-section').classList.remove('hidden');
});

WS.on('research_report', (msg) => {
    clearAnalysisStream();
    const report = msg.report;
    const idx = msg.report_index;

    // Mark factor chip as done
    const chip = document.getElementById(`factor-chip-${idx}`);
    if (chip) {
        chip.classList.remove('active');
        chip.classList.add('done');
    }

    // Mark next as active
    const nextChip = document.getElementById(`factor-chip-${idx + 1}`);
    if (nextChip) nextChip.classList.add('active');

    // Mark current as active
    if (idx === 0) {
        const firstChip = document.getElementById('factor-chip-0');
        if (firstChip) firstChip.classList.add('done');
    }

    updateAgentStatus(`Research Agent completed: ${report.factor_name}`);

    const container = document.getElementById('research-reports');
    const card = document.createElement('div');
    card.className = 'research-card';

    const impactClass = report.impact || 'neutral';
    const impactIcon = { bullish: '📈', bearish: '📉', neutral: '➡️' }[impactClass] || '❓';

    card.innerHTML = `
        <div class="report-header">
            <span class="report-factor">${report.factor_name}</span>
            <div>
                <span class="impact-indicator ${impactClass}">${impactIcon} ${(report.impact || 'neutral').toUpperCase()}</span>
                <span class="badge badge-${impactClass === 'bullish' ? 'buy' : impactClass === 'bearish' ? 'sell' : 'hold'}" style="margin-left:8px">
                    ${report.confidence || 'medium'}
                </span>
            </div>
        </div>
        <div class="report-findings">${report.findings || report.summary || 'No findings available.'}</div>
    `;
    container.appendChild(card);
});

WS.on('debate_argument', (msg) => {
    clearAnalysisStream();
    const arg = msg.argument;
    if (!arg) return;

    setStep(3, 'done');
    setStep(4, 'active');
    document.getElementById('debate-section').classList.remove('hidden');

    const side = arg.side === 'bull' ? 'bull' : 'bear';
    updateAgentStatus(`${side.toUpperCase()} Agent — ${(arg.phase || '').toUpperCase()}`);

    const container = document.getElementById(`debate-${side}-args`);
    const div = document.createElement('div');
    div.className = 'debate-argument';
    div.innerHTML = `
        <span class="phase-label">${arg.phase || 'argument'}</span>
        ${arg.content || ''}
    `;
    container.appendChild(div);
});

WS.on('verdict', (msg) => {
    setStep(4, 'done');
    setStep(5, 'done');
    clearAnalysisStream();

    const v = msg.verdict;
    if (!v) return;

    state.currentVerdict = v;

    document.getElementById('verdict-section').classList.remove('hidden');
    document.getElementById('analysis-progress').classList.remove('hidden');

    const decision = v.final_decision || 'HOLD';
    const decEl = document.getElementById('verdict-decision');
    decEl.textContent = decision;
    decEl.className = `verdict-decision ${decision.toLowerCase()}`;

    document.getElementById('verdict-confidence').textContent =
        `Confidence: ${v.confidence_label || 'N/A'} (${((v.confidence_score || 0) * 100).toFixed(0)}%)`;
    document.getElementById('verdict-reasoning').textContent = v.reasoning || '';
    document.getElementById('verdict-bull-score').textContent = v.bull_score || '—';
    document.getElementById('verdict-bear-score').textContent = v.bear_score || '—';

    updateAgentStatus(`Analysis complete — Verdict: ${decision}`);
    showToast(`${msg.ticker}: ${decision} (${v.confidence_label})`, decision === 'BUY' ? 'success' : decision === 'SELL' ? 'error' : 'info');

    // Show trade action bar
    showTradeActionBar(decision, msg.ticker || state.currentAnalysisTicker, v);
});

WS.on('analysis_complete', (msg) => {
    _resetAnalysisButtons();
    clearAnalysisStream();

    const agentStatus = document.getElementById('agent-status');
    if (agentStatus) {
        agentStatus.innerHTML = `<span style="color:var(--accent-buy)">✓</span> <span id="agent-status-text">Analysis complete</span>`;
    }
});

WS.on('analysis_error', (msg) => {
    _resetAnalysisButtons();
    clearAnalysisStream();
    const isCancelled = msg.cancelled;
    if (isCancelled) {
        showToast('Analysis cancelled', 'info');
        updateAgentStatus('Analysis cancelled by user');
        const agentStatus = document.getElementById('agent-status');
        if (agentStatus) {
            agentStatus.innerHTML = `<span style="color:var(--accent-hold)">⏹</span> <span id="agent-status-text">Analysis cancelled</span>`;
        }
    } else {
        showToast('Analysis failed: ' + (msg.error || 'Unknown error'), 'error');
        updateAgentStatus('Analysis failed — ' + (msg.error || 'unknown error'));
    }
});

function _resetAnalysisButtons() {
    state.analysisRunning = false;
    state.currentAnalysisId = null;
    const btn = document.getElementById('btn-start-analysis');
    btn.disabled = false;
    btn.textContent = '🚀 Run Analysis';
    const cancelBtn = document.getElementById('btn-cancel-analysis');
    cancelBtn.classList.add('hidden');
    cancelBtn.disabled = false;
    cancelBtn.textContent = '⏹ Stop Analysis';
}

// ── Trade Action Bar (verdict → manual order) ────────────────────────

async function showTradeActionBar(decision, ticker, verdict) {
    const bar = document.getElementById('trade-action-bar');
    const label = document.getElementById('trade-action-label');
    const btn = document.getElementById('btn-execute-trade');
    const note = document.getElementById('trade-action-note');
    const qtyInput = document.getElementById('trade-qty');

    // Reset classes
    bar.className = 'trade-action-bar';

    if (decision === 'HOLD') {
        // Check if user owns the stock
        let ownsStock = false;
        try {
            const posData = await api('/api/positions');
            const positions = posData.positions || [];
            ownsStock = positions.some(p => p.symbol === ticker);
        } catch (e) { /* ignore */ }

        if (ownsStock) {
            bar.classList.add('hold-action');
            label.textContent = `🟡 Verdict: HOLD ${ticker} — keep your current position`;
            btn.style.display = 'none';
            qtyInput.parentElement.style.display = 'none';
            note.textContent = 'The agents recommend holding your position. No action needed.';
        } else {
            bar.classList.add('hold-action');
            label.textContent = `⏸ No Action — agents found no compelling reason to trade ${ticker}`;
            btn.style.display = 'none';
            qtyInput.parentElement.style.display = 'none';
            note.textContent = "You don't own this stock and the analysis didn't recommend buying. No trade to make.";
        }
        bar.classList.remove('hidden');
        return;
    }

    // BUY or SELL — show controls
    const side = decision === 'BUY' ? 'buy' : 'sell';
    bar.classList.add(`${side}-action`);

    // Calculate suggested quantity
    let suggestedQty = 1;
    try {
        const acctData = await api('/api/account');
        const equity = acctData.equity || 0;
        const tradeData = await api(`/api/orders`); // just to test connectivity
        // Use 5% of equity
        const maxVal = equity * 0.05;
        // Try to get current price from Alpaca
        try {
            const quoteResp = await fetch(`/api/market/quote/${ticker}`);
            if (quoteResp.ok) {
                const quoteData = await quoteResp.json();
                const price = quoteData.price || quoteData.last || 0;
                if (price > 0) suggestedQty = Math.max(1, Math.floor(maxVal / price));
            }
        } catch (e) { /* default to 1 */ }
    } catch (e) { /* default to 1 */ }

    qtyInput.parentElement.style.display = '';
    qtyInput.value = suggestedQty;
    btn.style.display = '';

    if (decision === 'BUY') {
        label.innerHTML = `📈 <strong>BUY ${ticker}</strong> — Confidence: ${((verdict.confidence_score || 0) * 100).toFixed(0)}%`;
        btn.textContent = '💰 Buy Now';
        btn.className = 'btn btn-buy btn-lg';
    } else {
        label.innerHTML = `📉 <strong>SELL ${ticker}</strong> — Confidence: ${((verdict.confidence_score || 0) * 100).toFixed(0)}%`;
        btn.textContent = '📉 Sell Now';
        btn.className = 'btn btn-sell btn-lg';
    }

    note.textContent = `This will place a market ${side} order on your Alpaca paper account. Adjust quantity as needed.`;
    bar.classList.remove('hidden');
}

async function executeFromVerdict() {
    const verdict = state.currentVerdict;
    const ticker = state.currentAnalysisTicker;
    if (!verdict || !ticker) {
        showToast('No verdict to execute', 'error');
        return;
    }

    const decision = verdict.final_decision || 'HOLD';
    if (decision === 'HOLD') return;

    const side = decision === 'BUY' ? 'buy' : 'sell';
    const qty = parseInt(document.getElementById('trade-qty').value) || 1;

    const btn = document.getElementById('btn-execute-trade');
    btn.disabled = true;
    btn.textContent = '⏳ Placing...';

    try {
        const result = await api('/api/orders', {
            method: 'POST',
            body: JSON.stringify({
                ticker: ticker,
                side: side,
                qty: qty,
                source: 'analysis',
            }),
        });
        showToast(`Order placed! ${side.toUpperCase()} ${qty} shares of ${ticker}`, 'success');
        btn.textContent = '✅ Order Placed';
        document.getElementById('trade-action-note').textContent =
            `Order ID: ${result.id || 'N/A'} — View in the Orders tab.`;
    } catch (e) {
        showToast('Failed to place order: ' + e.message, 'error');
        btn.disabled = false;
        btn.textContent = decision === 'BUY' ? '💰 Buy Now' : '📉 Sell Now';
    }
}

// ── Analysis History ─────────────────────────────────────────────────

async function showAnalysisHistory() {
    const section = document.getElementById('analysis-history-section');
    section.classList.remove('hidden');

    try {
        const data = await api('/api/analysis/history');
        const list = document.getElementById('analysis-history-list');

        if (!data.analyses || data.analyses.length === 0) {
            list.innerHTML = '<div class="empty-state"><p>No analyses yet.</p></div>';
            return;
        }

        list.innerHTML = data.analyses.map(a => `
            <div class="agent-card" style="margin-bottom:8px;cursor:pointer" onclick="loadAnalysis(${a.id})">
                <div class="agent-header">
                    <span class="agent-ticker">${a.ticker}</span>
                    <span class="badge badge-${a.decision === 'BUY' ? 'buy' : a.decision === 'SELL' ? 'sell' : 'hold'}">
                        ${a.decision || a.status}
                    </span>
                </div>
                <div class="agent-meta">
                    <span>Confidence: ${a.label || 'N/A'}</span>
                    <span>${a.timestamp ? new Date(a.timestamp).toLocaleString() : ''}</span>
                </div>
            </div>
        `).join('');
    } catch (e) {
        showToast('Failed to load history: ' + e.message, 'error');
    }
}

function hideAnalysisHistory() {
    document.getElementById('analysis-history-section').classList.add('hidden');
}

async function loadAnalysis(id) {
    try {
        const data = await api(`/api/analysis/${id}`);
        resetAnalysisUI();
        hideAnalysisHistory();

        state.currentAnalysisTicker = data.ticker;

        // Show factors
        if (data.factors && data.factors.length > 0) {
            const section = document.getElementById('factors-section');
            const list = document.getElementById('factors-list');
            section.classList.remove('hidden');
            data.factors.forEach((f, i) => {
                const chip = document.createElement('div');
                chip.className = 'factor-chip done';
                chip.innerHTML = `<span class="chip-icon">🔬</span> ${f.factor_name}`;
                list.appendChild(chip);
            });
        }

        // Show research
        if (data.research_reports && data.research_reports.length > 0) {
            document.getElementById('research-section').classList.remove('hidden');
            const container = document.getElementById('research-reports');
            data.research_reports.forEach(r => {
                const card = document.createElement('div');
                card.className = 'research-card';
                const impactClass = r.impact || 'neutral';
                const impactIcon = { bullish: '📈', bearish: '📉', neutral: '➡️' }[impactClass] || '❓';
                card.innerHTML = `
                    <div class="report-header">
                        <span class="report-factor">${r.factor_name}</span>
                        <span class="impact-indicator ${impactClass}">${impactIcon} ${(r.impact || 'neutral').toUpperCase()}</span>
                    </div>
                    <div class="report-findings">${r.findings || r.summary || ''}</div>
                `;
                container.appendChild(card);
            });
        }

        // Show debate
        if (data.debate_transcript && data.debate_transcript.length > 0) {
            document.getElementById('debate-section').classList.remove('hidden');
            data.debate_transcript.forEach(arg => {
                const side = arg.side === 'bull' ? 'bull' : 'bear';
                const container = document.getElementById(`debate-${side}-args`);
                const div = document.createElement('div');
                div.className = 'debate-argument';
                div.innerHTML = `<span class="phase-label">${arg.phase || ''}</span>${arg.content || ''}`;
                container.appendChild(div);
            });
        }

        // Show verdict
        if (data.verdict) {
            const v = data.verdict;
            state.currentVerdict = v;
            document.getElementById('verdict-section').classList.remove('hidden');
            const decision = v.final_decision || 'HOLD';
            const decEl = document.getElementById('verdict-decision');
            decEl.textContent = decision;
            decEl.className = `verdict-decision ${decision.toLowerCase()}`;
            document.getElementById('verdict-confidence').textContent =
                `Confidence: ${v.confidence_label || 'N/A'} (${((v.confidence_score || 0) * 100).toFixed(0)}%)`;
            document.getElementById('verdict-reasoning').textContent = v.reasoning || '';
            document.getElementById('verdict-bull-score').textContent = v.bull_score || '—';
            document.getElementById('verdict-bear-score').textContent = v.bear_score || '—';

            // Show trade action bar for historical analysis too
            showTradeActionBar(decision, data.ticker, v);
        }
    } catch (e) {
        showToast('Failed to load analysis: ' + e.message, 'error');
    }
}

// ── Orders Page ──────────────────────────────────────────────────────

async function loadAccount() {
    try {
        const data = await api('/api/account');
        document.getElementById('acct-equity').textContent = fmt$(data.equity);
        document.getElementById('acct-buying-power').textContent = fmt$(data.buying_power);
        document.getElementById('acct-cash').textContent = fmt$(data.cash);

        const statusEl = document.getElementById('acct-market-status');
        if (data.market_open) {
            statusEl.textContent = '🟢 Open';
            statusEl.className = 'stat-value positive';
        } else {
            statusEl.textContent = '🔴 Closed';
            statusEl.className = 'stat-value';
        }
    } catch (e) {
        console.warn('Failed to load account:', e);
    }
}

async function loadPositions() {
    try {
        const data = await api('/api/positions');
        const positions = data.positions || [];
        const container = document.getElementById('positions-list');

        if (positions.length === 0) {
            container.innerHTML = '<div class="empty-state" style="padding:20px"><p>No open positions</p></div>';
            return;
        }

        container.innerHTML = `<div class="positions-grid">${positions.map(p => {
            const pnl = parseFloat(p.unrealized_pl || 0);
            const pnlPct = parseFloat(p.unrealized_plpc || 0) * 100;
            const pnlClass = pnl >= 0 ? 'positive' : 'negative';
            const pnlSign = pnl >= 0 ? '+' : '';
            return `
                <div class="position-item">
                    <div class="pos-ticker">${p.symbol}</div>
                    <div class="pos-detail">
                        <span>${p.qty} shares</span>
                        <span class="pos-pnl ${pnlClass}">${pnlSign}${fmt$(pnl)} (${pnlSign}${pnlPct.toFixed(1)}%)</span>
                    </div>
                    <div class="pos-detail">
                        <span>Avg: ${fmt$(p.avg_entry_price)}</span>
                        <span>Cur: ${fmt$(p.current_price)}</span>
                    </div>
                </div>
            `;
        }).join('')}</div>`;
    } catch (e) {
        console.warn('Failed to load positions:', e);
    }
}

async function loadOrders() {
    try {
        const data = await api('/api/orders');
        state.allOrders = data.orders || [];
        renderOrders(state.allOrders);
    } catch (e) {
        showToast('Failed to load orders: ' + e.message, 'error');
        document.getElementById('orders-table-container').innerHTML =
            '<div class="empty-state"><p>Failed to load orders. Check your Alpaca connection.</p></div>';
    }
}

function filterOrders(source) {
    state.currentFilter = source;

    // Update filter button styles
    document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
    document.querySelector(`.filter-btn[data-source="${source}"]`)?.classList.add('active');

    if (source === 'all') {
        renderOrders(state.allOrders);
    } else {
        renderOrders(state.allOrders.filter(o => o.source === source));
    }
}

function renderOrders(orders) {
    const container = document.getElementById('orders-table-container');

    if (!orders || orders.length === 0) {
        const filterMsg = state.currentFilter !== 'all'
            ? ` with source "${state.currentFilter}"`
            : '';
        container.innerHTML = `<div class="empty-state"><p>No orders found${filterMsg}.</p></div>`;
        return;
    }

    const rows = orders.map(o => {
        const side = (o.side || '').toLowerCase();
        const sideClass = side === 'buy' ? 'side-buy' : 'side-sell';
        const sideLabel = side === 'buy' ? '📈 BUY' : '📉 SELL';
        const status = (o.status || 'unknown').toLowerCase();
        const source = (o.source || 'unknown').toLowerCase();
        const sourceIcon = { manual: '👤', analysis: '🔬', expert: '⚡', unknown: '❓' }[source] || '❓';
        const filledPrice = o.filled_avg_price ? fmt$(o.filled_avg_price) : '—';
        const cancelable = ['new', 'accepted', 'pending_new', 'partially_filled'].includes(status);

        return `
            <tr>
                <td class="ticker-cell">${o.ticker || ''}</td>
                <td class="${sideClass}">${sideLabel}</td>
                <td>${o.qty || 0}${o.filled_qty && o.filled_qty !== o.qty ? ` (${o.filled_qty} filled)` : ''}</td>
                <td>${filledPrice}</td>
                <td><span class="status-badge status-${status}">${status}</span></td>
                <td><span class="source-badge source-${source}">${sourceIcon} ${source}</span></td>
                <td>${fmtDate(o.submitted_at)}</td>
                <td>${cancelable
                    ? `<button class="btn btn-ghost btn-sm" style="color:var(--accent-sell);padding:4px 8px" onclick="cancelOrder('${o.id}')">✕</button>`
                    : ''
                }</td>
            </tr>
        `;
    }).join('');

    container.innerHTML = `
        <table class="orders-table">
            <thead>
                <tr>
                    <th>Ticker</th>
                    <th>Side</th>
                    <th>Qty</th>
                    <th>Fill Price</th>
                    <th>Status</th>
                    <th>Source</th>
                    <th>Date</th>
                    <th></th>
                </tr>
            </thead>
            <tbody>${rows}</tbody>
        </table>
    `;
}

async function cancelOrder(orderId) {
    if (!confirm('Cancel this order?')) return;
    try {
        await api(`/api/orders/${orderId}`, { method: 'DELETE' });
        showToast('Order cancelled', 'info');
        loadOrders();
    } catch (e) {
        showToast('Failed to cancel: ' + e.message, 'error');
    }
}

// ── Expert Mode ──────────────────────────────────────────────────────

async function loadExpertAgents() {
    try {
        const data = await api('/api/expert/agents');
        const list = document.getElementById('expert-agents-list');
        const empty = document.getElementById('expert-empty');

        if (!data.agents || data.agents.length === 0) {
            list.innerHTML = '';
            empty.classList.remove('hidden');
            return;
        }

        empty.classList.add('hidden');
        list.innerHTML = data.agents.map(a => {
            const config = a.llm_config || {};
            return `
                <div class="agent-card" style="margin-bottom:12px">
                    <div class="agent-header">
                        <div>
                            <span class="agent-ticker">${a.ticker}</span>
                            <span style="font-size:0.9rem;color:var(--text-secondary);margin-left:8px">${a.name}</span>
                        </div>
                        <div style="display:flex;gap:8px;align-items:center">
                            <span class="badge ${a.enabled ? 'badge-buy' : 'badge-hold'}">${a.enabled ? 'Active' : 'Paused'}</span>
                            ${a.auto_execute ? '<span class="badge badge-purple">Auto-Execute</span>' : ''}
                        </div>
                    </div>
                    <div class="agent-strategy">${a.strategy}</div>
                    <div class="agent-meta">
                        <span>📅 ${a.schedule || 'Manual only'}</span>
                        <span>🤖 ${config.provider || 'ollama'}/${config.model || 'default'}</span>
                        <span>🕐 Last: ${a.last_run ? new Date(a.last_run).toLocaleString() : 'Never'}</span>
                    </div>
                    <div style="margin-top:12px;display:flex;gap:8px">
                        <button class="btn btn-primary btn-sm" onclick="runExpertAgent(${a.id})">▶ Run Now</button>
                        <button class="btn btn-ghost btn-sm" onclick="showAgentLogs(${a.id}, '${a.name}')">📋 Logs</button>
                        <button class="btn btn-ghost btn-sm" onclick="toggleAgent(${a.id}, ${!a.enabled})">${a.enabled ? '⏸ Pause' : '▶ Enable'}</button>
                        <button class="btn btn-ghost btn-sm" style="color:var(--accent-sell)" onclick="deleteAgent(${a.id})">🗑 Delete</button>
                    </div>
                </div>
            `;
        }).join('');
    } catch (e) {
        showToast('Failed to load agents: ' + e.message, 'error');
    }
}

function showCreateAgentModal() {
    document.getElementById('create-agent-modal').classList.remove('hidden');
    updateModelSelect('agent');
}

function hideCreateAgentModal() {
    document.getElementById('create-agent-modal').classList.add('hidden');
}

async function createAgent(event) {
    event.preventDefault();

    const body = {
        name: document.getElementById('agent-name').value,
        ticker: document.getElementById('agent-ticker').value.toUpperCase(),
        strategy: document.getElementById('agent-strategy').value,
        schedule: document.getElementById('agent-schedule').value,
        auto_execute: document.getElementById('agent-auto-execute').checked,
        llm_provider: document.getElementById('agent-provider').value,
        llm_model: document.getElementById('agent-model').value,
        llm_think: document.getElementById('agent-think').checked,
    };

    try {
        await api('/api/expert/agents', { method: 'POST', body: JSON.stringify(body) });
        showToast(`Agent "${body.name}" created!`, 'success');
        hideCreateAgentModal();
        document.getElementById('create-agent-form').reset();
        loadExpertAgents();
    } catch (e) {
        showToast('Failed to create agent: ' + e.message, 'error');
    }
}

async function runExpertAgent(id) {
    showToast('Running agent...', 'info');
    try {
        const result = await api(`/api/expert/agents/${id}/run`, { method: 'POST' });
        showToast(
            `Agent decision: ${result.decision} (${result.reasoning?.substring(0, 80)}...)`,
            result.decision === 'BUY' ? 'success' : result.decision === 'SELL' ? 'error' : 'info'
        );
        loadExpertAgents();
    } catch (e) {
        showToast('Agent run failed: ' + e.message, 'error');
    }
}

async function toggleAgent(id, enabled) {
    try {
        await api(`/api/expert/agents/${id}`, {
            method: 'PUT',
            body: JSON.stringify({ enabled }),
        });
        loadExpertAgents();
    } catch (e) {
        showToast('Failed to update agent: ' + e.message, 'error');
    }
}

async function deleteAgent(id) {
    if (!confirm('Delete this agent? This cannot be undone.')) return;
    try {
        await api(`/api/expert/agents/${id}`, { method: 'DELETE' });
        showToast('Agent deleted', 'info');
        loadExpertAgents();
    } catch (e) {
        showToast('Failed to delete agent: ' + e.message, 'error');
    }
}

async function showAgentLogs(id, name) {
    document.getElementById('agent-logs-modal').classList.remove('hidden');
    document.getElementById('logs-modal-title').textContent = `Logs: ${name}`;

    try {
        const data = await api(`/api/expert/agents/${id}/logs`);
        const content = document.getElementById('agent-logs-content');

        if (!data.logs || data.logs.length === 0) {
            content.innerHTML = '<div class="empty-state"><p>No runs yet.</p></div>';
            return;
        }

        content.innerHTML = data.logs.map(l => `
            <div class="agent-card" style="margin-bottom:8px">
                <div class="agent-header">
                    <span class="badge badge-${l.decision === 'BUY' ? 'buy' : l.decision === 'SELL' ? 'sell' : 'hold'}">
                        ${l.decision || 'N/A'}
                    </span>
                    <span style="font-size:0.8rem;color:var(--text-muted)">
                        ${l.timestamp ? new Date(l.timestamp).toLocaleString() : ''}
                    </span>
                </div>
                <div style="font-size:0.85rem;color:var(--text-secondary);margin-top:8px">
                    ${l.reasoning || l.error || 'No details'}
                </div>
                ${l.executed ? '<span class="badge badge-buy" style="margin-top:8px">Executed</span>' : ''}
                ${l.error ? `<span class="badge badge-sell" style="margin-top:8px">Error</span>` : ''}
            </div>
        `).join('');
    } catch (e) {
        showToast('Failed to load logs: ' + e.message, 'error');
    }
}

function hideAgentLogsModal() {
    document.getElementById('agent-logs-modal').classList.add('hidden');
}

// ── WebSocket handler for trade fills ────────────────────────────────
WS.on('trade_fill', (msg) => {
    showToast(`Order filled: ${msg.side?.toUpperCase()} ${msg.qty} ${msg.ticker}`, 'success');
    // Refresh orders page if we're on it
    if (state.currentPage === 'orders') {
        loadOrders();
        loadAccount();
        loadPositions();
    }
});

// ── Strategy Assistant Chat ──────────────────────────────────────────

function toggleStrategyChat() {
    const panel = document.getElementById('strategy-chat-panel');
    const body = document.getElementById('strategy-chat-body');
    state.strategyChatOpen = !state.strategyChatOpen;

    if (state.strategyChatOpen) {
        body.classList.remove('hidden');
        panel.classList.add('chat-open', 'chat-active');
        document.getElementById('strategy-chat-input').focus();
        updateModelSelect('strategy');
        // Scroll to bottom
        const msgs = document.getElementById('strategy-chat-messages');
        msgs.scrollTop = msgs.scrollHeight;
    } else {
        body.classList.add('hidden');
        panel.classList.remove('chat-open', 'chat-active');
    }
}

async function sendStrategyMessage() {
    const input = document.getElementById('strategy-chat-input');
    const message = input.value.trim();
    if (!message || state.strategyChatBusy) return;

    // Clear welcome message on first send
    const welcome = document.querySelector('.chat-welcome');
    if (welcome) welcome.remove();

    // Add user bubble
    renderChatBubble('user', message);
    state.strategyChatHistory.push({ role: 'user', content: message });
    input.value = '';

    // Show typing indicator
    state.strategyChatBusy = true;
    const sendBtn = document.getElementById('btn-strategy-send');
    sendBtn.disabled = true;
    showTypingIndicator();

    // Create streaming assistant bubble (will be filled by WS tokens)
    createStreamingBubble();

    try {
        const provider = document.getElementById('strategy-provider')?.value || 'ollama';
        const model = document.getElementById('strategy-model')?.value || '';
        const think = document.getElementById('strategy-think')?.checked ?? true;

        // Fire-and-forget — tokens arrive via WebSocket
        const data = await api('/api/expert/strategy-chat', {
            method: 'POST',
            body: JSON.stringify({
                message,
                history: state.strategyChatHistory.slice(0, -1),
                llm_provider: provider,
                llm_model: model,
                llm_think: think,
            }),
        });

        // POST returns the full response — finalize
        const responseText = data.response || '';
        state.strategyChatHistory.push({ role: 'assistant', content: responseText });

        // If the streaming bubble is still empty (non-Ollama providers don't stream via token_callback),
        // fill it with the full response
        const streamBubble = document.getElementById('strategy-stream-bubble');
        if (streamBubble) {
            const streamContent = streamBubble.querySelector('.stream-content');
            if (streamContent && !streamContent.textContent.trim()) {
                // Clean and display the full response
                const displayText = responseText
                    .replace(/```agent_config\s*\n[\s\S]*?\n```/g, '')
                    .trim();
                streamContent.innerHTML = formatChatText(displayText);
            }
            // Remove streaming ID
            streamBubble.removeAttribute('id');
        }

        removeTypingIndicator();

        // Check for agent config
        if (data.agent_config) {
            renderStrategyConfigCard(data.agent_config);
        }

    } catch (e) {
        removeTypingIndicator();
        removeStreamingBubble();
        renderChatBubble('assistant', `⚠️ Error: ${e.message}`);
    } finally {
        state.strategyChatBusy = false;
        sendBtn.disabled = false;
    }
}

function createStreamingBubble() {
    const container = document.getElementById('strategy-chat-messages');
    const bubble = document.createElement('div');
    bubble.className = 'chat-bubble assistant';
    bubble.id = 'strategy-stream-bubble';
    bubble.innerHTML = `<span class="bubble-role">🧠 AI</span><span class="stream-content"></span><span class="stream-cursor">▍</span>`;
    container.appendChild(bubble);
    container.scrollTop = container.scrollHeight;
}

function removeStreamingBubble() {
    const el = document.getElementById('strategy-stream-bubble');
    if (el) el.remove();
}

// WebSocket handlers for streaming tokens
WS.on('strategy_chat_start', (msg) => {
    state._activeStreamId = msg.stream_id;
    // Remove typing indicator once tokens start flowing
});

WS.on('strategy_chat_token', (msg) => {
    removeTypingIndicator();
    const bubble = document.getElementById('strategy-stream-bubble');
    if (!bubble) return;
    const content = bubble.querySelector('.stream-content');
    if (!content) return;

    // Append token text
    content.textContent += msg.token;

    // Auto-scroll
    const container = document.getElementById('strategy-chat-messages');
    container.scrollTop = container.scrollHeight;
});

WS.on('strategy_chat_done', (msg) => {
    removeTypingIndicator();

    // Finalize the streaming bubble — apply formatting
    const bubble = document.getElementById('strategy-stream-bubble');
    if (bubble) {
        const content = bubble.querySelector('.stream-content');
        const cursor = bubble.querySelector('.stream-cursor');
        if (cursor) cursor.remove();

        if (content) {
            const rawText = content.textContent;
            // Clean and format
            const displayText = rawText
                .replace(/```agent_config\s*\n[\s\S]*?\n```/g, '')
                .trim();
            content.innerHTML = formatChatText(displayText);
        }
        bubble.removeAttribute('id');
    }

    // Render config card if present
    if (msg.agent_config) {
        renderStrategyConfigCard(msg.agent_config);
    }

    // Show error if present
    if (msg.error) {
        renderChatBubble('assistant', `⚠️ Error: ${msg.error}`);
    }
});

function formatChatText(text) {
    if (!text) return '';
    return text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.*?)\*/g, '<em>$1</em>')
        .replace(/^- /gm, '• ')
        .replace(/\n/g, '<br>');
}

function renderChatBubble(role, content) {
    const container = document.getElementById('strategy-chat-messages');
    const bubble = document.createElement('div');
    bubble.className = `chat-bubble ${role}`;

    const roleLabel = role === 'user' ? 'You' : '🧠 AI';
    const formatted = formatChatText(content);
    bubble.innerHTML = `<span class="bubble-role">${roleLabel}</span>${formatted}`;
    container.appendChild(bubble);
    container.scrollTop = container.scrollHeight;
}

function showTypingIndicator() {
    const container = document.getElementById('strategy-chat-messages');
    const typing = document.createElement('div');
    typing.className = 'chat-typing';
    typing.id = 'strategy-typing';
    typing.innerHTML = `
        <div class="typing-dots"><span></span><span></span><span></span></div>
        <span class="typing-label">Strategy Assistant is thinking...</span>
    `;
    container.appendChild(typing);
    container.scrollTop = container.scrollHeight;
}

function removeTypingIndicator() {
    const el = document.getElementById('strategy-typing');
    if (el) el.remove();
}

function renderStrategyConfigCard(config) {
    const container = document.getElementById('strategy-chat-messages');
    const card = document.createElement('div');
    card.className = 'strategy-config-card';

    const scheduleDisplay = config.schedule
        ? config.schedule
        : 'Manual only';

    card.innerHTML = `
        <div class="config-header">
            <span>✨</span>
            <span>Strategy Ready — Agent Configuration</span>
        </div>
        <div class="config-grid">
            <span class="config-label">Name</span>
            <span class="config-value">${config.name}</span>
            <span class="config-label">Ticker</span>
            <span class="config-value" style="font-family:'JetBrains Mono',monospace;font-weight:600;color:var(--accent-blue)">${config.ticker}</span>
            <span class="config-label">Schedule</span>
            <span class="config-value" style="font-family:'JetBrains Mono',monospace">${scheduleDisplay}</span>
            <span class="config-label">Auto-Execute</span>
            <span class="config-value">${config.auto_execute ? '✅ Yes' : '❌ No (manual approval)'}</span>
        </div>
        <div class="config-label" style="margin-bottom:6px">STRATEGY</div>
        <div class="config-strategy">${config.strategy}</div>
        <button class="btn-use-strategy" onclick='applyStrategyConfig(${JSON.stringify(config).replace(/'/g, "&#39;")})'>
            ✨ Use This Strategy — Create Agent
        </button>
    `;
    container.appendChild(card);
    container.scrollTop = container.scrollHeight;
}

function applyStrategyConfig(config) {
    // Open modal and fill fields
    showCreateAgentModal();

    // Small delay to ensure modal is rendered
    setTimeout(() => {
        document.getElementById('agent-name').value = config.name || '';
        document.getElementById('agent-ticker').value = config.ticker || '';
        document.getElementById('agent-strategy').value = config.strategy || '';
        document.getElementById('agent-schedule').value = config.schedule || '';
        document.getElementById('agent-auto-execute').checked = config.auto_execute || false;

        showToast('Strategy applied! Review and create your agent.', 'success');
    }, 150);
}

function clearStrategyChat() {
    state.strategyChatHistory = [];
    const container = document.getElementById('strategy-chat-messages');
    container.innerHTML = `
        <div class="chat-welcome">
            <div class="chat-welcome-icon">🤖</div>
            <div class="chat-welcome-title">Strategy Assistant</div>
            <div class="chat-welcome-text">
                Describe your trading idea and I'll help you build a complete agent strategy.
                <br>Try: <em>"I want to trade NVDA using momentum indicators"</em>
            </div>
        </div>
    `;
}

// ── Initialize ───────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    loadProviders();

    // Handle Enter key in ticker input
    const tickerInput = document.getElementById('analysis-ticker');
    if (tickerInput) {
        tickerInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') startAnalysis();
        });
    }
});
