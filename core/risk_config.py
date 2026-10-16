# core/risk_config.py
# 리스크 설정 기본값 — 각 프로젝트에서 오버라이드 가능

from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class RiskConfig:
    max_daily_loss: float = 500.0
    max_position_size: int = 1000
    max_total_position: float = 50_000.0
    max_daily_trades: int = 100
