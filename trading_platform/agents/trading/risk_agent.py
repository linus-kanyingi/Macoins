"""agents/trading/risk_agent.py — Risk management gate for all trade execution."""
from dataclasses import dataclass
from typing import Optional
from core.config import settings
from core.database import SessionLocal
from core.models import RiskLog


@dataclass
class RiskDecision:
    approved: bool
    reason: str
    adjusted_qty: Optional[int] = None


class RiskAgent:
    def check_position_size(self, ticker, qty, price, account_equity) -> RiskDecision:
        if account_equity <= 0:
            return RiskDecision(False, "Cannot determine account equity")
        position_value = qty * price
        max_allowed    = account_equity * settings.MAX_POSITION_PCT
        if position_value > max_allowed:
            adjusted = int(max_allowed / price)
            if adjusted < 1:
                return RiskDecision(False,
                    f"Position size ${position_value:.0f} exceeds {settings.MAX_POSITION_PCT*100:.0f}% "
                    f"limit (${max_allowed:.0f}). Min qty not met.")
            return RiskDecision(True,
                f"Qty adjusted {qty}→{adjusted} to respect position size limit",
                adjusted_qty=adjusted)
        return RiskDecision(True, f"Position size OK: ${position_value:.0f} ≤ ${max_allowed:.0f}")

    def check_max_positions(self, current_count) -> RiskDecision:
        if current_count >= settings.MAX_OPEN_POSITIONS:
            return RiskDecision(False, f"Max open positions ({settings.MAX_OPEN_POSITIONS}) reached")
        return RiskDecision(True, f"Open positions: {current_count}/{settings.MAX_OPEN_POSITIONS}")

    def approve_trade(self, ticker, side, qty, price, account_equity,
                      open_position_count) -> RiskDecision:
        checks = []
        if side.upper() == "BUY":
            size_check = self.check_position_size(ticker, qty, price, account_equity)
            if not size_check.approved:
                self._log(ticker, "position_size_rejected", size_check.reason)
                return size_check
            if size_check.adjusted_qty:
                qty = size_check.adjusted_qty
            checks.append(size_check)

            pos_check = self.check_max_positions(open_position_count)
            if not pos_check.approved:
                self._log(ticker, "max_positions_rejected", pos_check.reason)
                return pos_check
            checks.append(pos_check)

        reason   = " | ".join(c.reason for c in checks) if checks else "Sell order approved"
        decision = RiskDecision(True, reason, adjusted_qty=qty)
        self._log(ticker, "approved", reason)
        return decision

    def _log(self, ticker, event_type, message):
        try:
            db = SessionLocal()
            try:
                log = RiskLog(ticker=ticker, event_type=event_type, message=message)
                db.add(log)
                db.commit()
            finally:
                db.close()
        except Exception:
            pass


risk_agent = RiskAgent()
