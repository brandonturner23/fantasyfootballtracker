"""Shared data structures."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

TEAM_ALIASES = {
    "WSH": "WAS", "JAC": "JAX", "LA": "LAR", "STL": "LAR", "OAK": "LV",
    "SD": "LAC", "ARZ": "ARI", "GNB": "GB", "KAN": "KC", "NWE": "NE",
    "NOR": "NO", "SFO": "SF", "TAM": "TB", "HST": "HOU", "BLT": "BAL",
    "CLV": "CLE",
}

# Injury designations and how much of a player's projection we expect to see.
INJURY_MULTIPLIER = {
    "": 1.0, "P": 1.0, "Q": 0.85, "GTD": 0.85, "D": 0.3,
    "O": 0.0, "IR": 0.0, "IR-R": 0.0, "PUP": 0.0, "PUP-R": 0.0, "PUP-P": 0.0,
    "NFI": 0.0, "NFI-R": 0.0, "SUSP": 0.0, "NA": 0.0, "DNR": 0.0, "COVID-19": 0.0,
}

FANTASY_POSITIONS = ("QB", "RB", "WR", "TE", "K", "DEF")


def norm_team(abbr: str | None) -> str:
    if not abbr:
        return ""
    a = abbr.strip().upper()
    return TEAM_ALIASES.get(a, a)


def norm_status(status: str | None) -> str:
    s = (status or "").strip().upper()
    mapping = {"QUESTIONABLE": "Q", "DOUBTFUL": "D", "OUT": "O", "INJURED RESERVE": "IR",
               "SUSPENDED": "SUSP", "ACTIVE": "", "HEALTHY": "", "NONE": ""}
    return mapping.get(s, s)


@dataclass
class Player:
    key: str                       # league-source player key (Yahoo player_key in live mode)
    name: str
    position: str                  # primary position (QB/RB/WR/TE/K/DEF)
    eligible: list[str]
    nfl_team: str
    status: str = ""
    injury_note: str = ""
    bye_week: int | None = None
    selected_position: str | None = None  # slot in the fantasy lineup (BN, IR, QB, W/R/T, ...)
    nfl_id: str | None = None      # id in the NFL data source (Sleeper player id)
    fantasy_team_key: str | None = None
    # enrichment (filled by the companion)
    projection: float = 0.0
    history: dict[int, float] = field(default_factory=dict)
    opponent: str | None = None
    home: bool | None = None
    kickoff: str | None = None     # ISO timestamp
    game_state: str = "pre"        # pre / in / post / bye
    on_bye: bool = False
    matchup_rank: int | None = None  # 1 = easiest matchup for this position, 32 = hardest
    trending: int = 0

    @property
    def injury_multiplier(self) -> float:
        return INJURY_MULTIPLIER.get(norm_status(self.status), 1.0)

    @property
    def locked(self) -> bool:
        return self.game_state in ("in", "post")

    def to_dict(self) -> dict:
        d = asdict(self)
        d["history"] = {str(k): v for k, v in sorted(self.history.items())}
        return d
