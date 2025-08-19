from pydantic import BaseModel
from typing import Literal
import yaml, os

class Settings(BaseModel):
    class Risk(BaseModel):
        day_abs_loss_stop: float = 50
        week_loss_pct_stop: float = 0.10
        max_open_risk_pct: float = 0.06
        vix_ceiling: float = 28
        trade_cooldown_min: int = 20
        max_trades_per_day: int = 3
        direction_cap_ratio: float = 2.0

    symbol: str = "QQQM"
    mode: Literal["paper","live"] = "paper"
    broker: Literal["paper","alpaca","tradier","schwab"] = "paper"
    profile: Literal["conservative","balanced","enhanced"] = "balanced"
    weekly_dca: float = 100
    cash_buffer_pct: float = 0.12
    max_drawdown: float = 0.15
    vix_max: float = 28  # legacy; superseded by risk.vix_ceiling
    put_pct_otm: float = 0.05
    call_pct_otm: float = 0.05
    dte_preference: int = 7
    spreads_max_allocation_pct: float = 0.05
    condors_max_concurrent: int = 2
    condor_allocation_pct: float = 0.02
    deploy_full_cash_on_start: bool = True
    options_symbol: str = "QQQ"
    class Exits(BaseModel):
        spread_take_profit_pct: float = 0.5
        spread_stop_loss_pct: float = 0.5
        condor_take_profit_pct: float = 0.4
        condor_stop_loss_pct: float = 0.6
    exits: Exits = Exits()
    class VolSizing(BaseModel):
        vix_floor: float = 15
        vix_target: float = 20
        vix_ceiling: float = 28
        min_factor: float = 0.4
        max_factor: float = 1.0
    vol_sizing: VolSizing = VolSizing()
    class Perf(BaseModel):
        enable_weekly_report: bool = True
    performance: Perf = Perf()
    margin_policy: str = 'cash_only'
    class Limits(BaseModel):
        # Sensible defaults (approx): Schwab ~120/min data; 2-4 trades/sec; Alpaca ~200/min; Tradier ~120/min
        data_capacity_per_min: int = 110
        trade_capacity_per_sec: int = 2
    limits: Limits = Limits()
    class DTE(BaseModel):
        min: int = 21
        max: int = 35
    dte_window: DTE = DTE()
    daily_reports: bool = True
    report_time_hhmm: str = "17:30"
    db_url: str = "sqlite:///data/trades.db"
    risk: Risk = Risk()

def load_config() -> Settings:
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "config.yaml")
    with open(path, "r") as f:
        data = yaml.safe_load(f) or {}
    return Settings(**data)


    @property
    def symbols(self):
        sym_list = self.raw.get('symbols')
        if sym_list:
            return sym_list
        return [{
            "ticker": self.raw.get("symbol","QQQM"),
            "options_ticker": self.raw.get("options_symbol", self.raw.get("symbol","QQQM")),
            "weight": 1.0,
            "strategies": ["dca","wheel","credit_spreads","iron_condor"],
            "max_alloc_pct": 1.0
        }]

    @property
    def weekly_dca_total(self):
        return self.raw.get("weekly_dca_total", self.raw.get("weekly_dca", 100))
