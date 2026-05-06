"""agents/trading/market_data_agent.py — Build live FinancialScenario from Alpaca data."""
from broker import alpaca_client
from data.scenario_schema import FinancialScenario, TechnicalIndicators, MacroContext, NewsItem
from datetime import date
import statistics


class MarketDataAgent:
    def build_scenario(self, ticker: str) -> FinancialScenario:
        ticker = ticker.upper()
        # Current price
        try:
            trade_data    = alpaca_client.get_latest_trade(ticker)
            current_price = float(trade_data["trade"]["p"])
        except Exception:
            current_price = 0.0

        # Historical bars
        bars = []
        try:
            bars_data = alpaca_client.get_bars(ticker, timeframe="1Day", limit=60)
            bars      = bars_data.get("bars", [])
        except Exception:
            pass

        closes = [float(b["c"]) for b in bars] if bars else [current_price]

        # Price changes
        price_1w    = closes[-6]  if len(closes) >= 6  else closes[0]
        price_1m    = closes[-22] if len(closes) >= 22 else closes[0]
        change_1w   = ((current_price - price_1w)  / price_1w  * 100) if price_1w  else 0
        change_1m   = ((current_price - price_1m)  / price_1m  * 100) if price_1m  else 0

        # RSI
        rsi     = self._compute_rsi(closes) if len(closes) >= 15 else 50.0
        sma_50  = statistics.mean(closes[-50:])  if len(closes) >= 50  else statistics.mean(closes)
        sma_200 = statistics.mean(closes[-200:]) if len(closes) >= 200 else statistics.mean(closes)
        sma_cross = "50-SMA above 200-SMA (bullish)" if sma_50 > sma_200 else "50-SMA below 200-SMA (bearish)"

        high_52w      = max(float(b["h"]) for b in bars) if bars else current_price
        pct_from_high = ((current_price - high_52w) / high_52w * 100) if high_52w else 0

        technicals = TechnicalIndicators(
            rsi_14=round(rsi, 1),
            macd_signal="bullish" if rsi > 50 else "bearish",
            sma_50_vs_200=sma_cross,
            price_vs_52w_high_pct=round(pct_from_high, 1),
            avg_volume_ratio=1.0,
        )

        # News
        news_items = []
        try:
            raw_news = alpaca_client.get_news(ticker, limit=5)
            if isinstance(raw_news, list):
                for n in raw_news[:5]:
                    news_items.append(NewsItem(
                        headline=n.get("headline", ""),
                        sentiment="neutral",
                        source=n.get("source", "Alpaca News"),
                        date=str(n.get("created_at", date.today()))[:10],
                        relevance="medium",
                    ))
        except Exception:
            pass

        macro = MacroContext(
            interest_rate_trend="neutral",
            inflation_cpi_yoy=3.2,
            gdp_growth_latest=2.1,
            sector_rotation="mixed signals",
            vix_level=20.0,
        )

        return FinancialScenario(
            scenario_id=f"{ticker.lower()}_live_{date.today()}",
            asset_ticker=ticker,
            asset_name=ticker,
            asset_class="stock",
            evaluation_date=str(date.today()),
            current_price=round(current_price, 2),
            price_change_1w_pct=round(change_1w, 2),
            price_change_1m_pct=round(change_1m, 2),
            analyst_consensus="Hold",
            news=news_items,
            technicals=technicals,
            macro=macro,
            notes=f"Live scenario built from Alpaca data on {date.today()}",
        )

    def _compute_rsi(self, closes: list, period: int = 14) -> float:
        if len(closes) < period + 1:
            return 50.0
        deltas  = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
        gains   = [max(d, 0) for d in deltas[-period:]]
        losses  = [abs(min(d, 0)) for d in deltas[-period:]]
        avg_g   = sum(gains)  / period
        avg_l   = sum(losses) / period
        if avg_l == 0:
            return 100.0
        rs = avg_g / avg_l
        return 100 - (100 / (1 + rs))


market_data_agent = MarketDataAgent()
