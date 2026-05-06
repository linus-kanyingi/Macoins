"""
data/scenario_schema.py — Dataclass + loader for financial scenarios.
Adapted from findebate — no changes to logic, only file location.
"""
from __future__ import annotations
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional


@dataclass
class TechnicalIndicators:
    rsi_14: Optional[float] = None
    macd_signal: Optional[str] = None
    sma_50_vs_200: Optional[str] = None
    price_vs_52w_high_pct: Optional[float] = None
    avg_volume_ratio: Optional[float] = None


@dataclass
class MacroContext:
    interest_rate_trend: Optional[str] = None
    inflation_cpi_yoy: Optional[float] = None
    gdp_growth_latest: Optional[float] = None
    sector_rotation: Optional[str] = None
    vix_level: Optional[float] = None


@dataclass
class NewsItem:
    headline: str
    sentiment: str
    source: str
    date: str
    relevance: str = "high"


@dataclass
class WeatherSignal:
    region: str
    condition: str
    economic_impact: str


@dataclass
class FinancialScenario:
    scenario_id: str
    asset_ticker: str
    asset_name: str
    asset_class: str
    evaluation_date: str
    current_price: float
    price_change_1w_pct: float
    price_change_1m_pct: float
    market_cap_bn: Optional[float] = None
    market_summary: str = ""
    analyst_consensus: str = "Hold"
    analyst_target_price: Optional[float] = None
    pe_ratio: Optional[float] = None
    forward_pe: Optional[float] = None
    earnings_surprise_pct: Optional[float] = None
    news: List[NewsItem] = field(default_factory=list)
    technicals: TechnicalIndicators = field(default_factory=TechnicalIndicators)
    macro: MacroContext = field(default_factory=MacroContext)
    weather: Optional[WeatherSignal] = None
    sentiment_score: Optional[float] = None
    notes: str = ""

    def to_debate_topic(self) -> str:
        return (
            f"Should an investor BUY {self.asset_ticker} ({self.asset_name}) "
            f"as of {self.evaluation_date}?"
        )

    def evidence_packet(self) -> str:
        lines = [
            f"=== FINANCIAL EVIDENCE PACKET: {self.asset_ticker} ({self.evaluation_date}) ===",
            f"Asset       : {self.asset_name} [{self.asset_class.upper()}]",
            f"Price       : ${self.current_price:.2f}  |  1W: {self.price_change_1w_pct:+.1f}%  |  1M: {self.price_change_1m_pct:+.1f}%",
        ]
        if self.market_cap_bn:
            lines.append(f"Market Cap  : ${self.market_cap_bn:.1f}B")
        if self.pe_ratio:
            lines.append(f"P/E (fwd)   : {self.pe_ratio} ({self.forward_pe} fwd)")
        if self.earnings_surprise_pct is not None:
            lines.append(f"Last EPS    : {self.earnings_surprise_pct:+.1f}% vs estimate")
        if self.analyst_target_price:
            lines.append(f"Analysts    : {self.analyst_consensus}  |  Target ${self.analyst_target_price:.2f}")
        t = self.technicals
        if any(v is not None for v in [t.rsi_14, t.macd_signal, t.sma_50_vs_200]):
            lines.append("--- Technicals ---")
            if t.rsi_14 is not None:
                lines.append(f"  RSI(14)         : {t.rsi_14:.1f}")
            if t.macd_signal:
                lines.append(f"  MACD signal     : {t.macd_signal}")
            if t.sma_50_vs_200:
                lines.append(f"  50/200 SMA      : {t.sma_50_vs_200}")
            if t.price_vs_52w_high_pct is not None:
                lines.append(f"  vs 52w high     : {t.price_vs_52w_high_pct:+.1f}%")
        m = self.macro
        if any(v is not None for v in [m.interest_rate_trend, m.inflation_cpi_yoy, m.vix_level]):
            lines.append("--- Macro ---")
            if m.interest_rate_trend:
                lines.append(f"  Rates           : {m.interest_rate_trend}")
            if m.inflation_cpi_yoy is not None:
                lines.append(f"  CPI YoY         : {m.inflation_cpi_yoy:.1f}%")
            if m.gdp_growth_latest is not None:
                lines.append(f"  GDP growth      : {m.gdp_growth_latest:.1f}%")
            if m.sector_rotation:
                lines.append(f"  Sector rotation : {m.sector_rotation}")
            if m.vix_level is not None:
                lines.append(f"  VIX             : {m.vix_level:.1f}")
        if self.news:
            lines.append("--- Recent News ---")
            for n in self.news[:5]:
                lines.append(f"  [{n.sentiment.upper():<8}] {n.headline}  ({n.source}, {n.date})")
        if self.weather:
            lines.append("--- Weather Signal ---")
            lines.append(f"  Region: {self.weather.region}")
            lines.append(f"  Condition: {self.weather.condition}")
            lines.append(f"  Economic impact: {self.weather.economic_impact}")
        if self.market_summary:
            lines.append("--- Summary ---")
            lines.append(f"  {self.market_summary}")
        lines.append("=" * 60)
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return asdict(self)


def load_scenario(path: str | Path) -> FinancialScenario:
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    raw["news"] = [NewsItem(**n) for n in raw.get("news", [])]
    raw["technicals"] = TechnicalIndicators(**raw.get("technicals", {}))
    raw["macro"] = MacroContext(**raw.get("macro", {}))
    w = raw.get("weather")
    raw["weather"] = WeatherSignal(**w) if w else None
    return FinancialScenario(**raw)
