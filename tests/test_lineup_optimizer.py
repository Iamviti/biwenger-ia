"""
Tests del modelo de puntuación (analysis/lineup_optimizer.py). Cubren las funciones
puras que componen la puntuación (shrinkage, gating, bonus) y un extremo a extremo con
una base de datos SQLite en memoria para comprobar que Scorer no rompe con datos reales.
"""

import sqlite3
from pathlib import Path

import pytest

from analysis.lineup_optimizer import (
    DEFAULT_HOME_BONUS,
    DOUBT_TITULARIDAD_MULT,
    GANGA_TITULARIDAD_THRESHOLD,
    HOME_AWAY_BOUNDS,
    MINUTES_FOR_FULL_REGULARITY,
    QUALITY_BOUNDS,
    TITULARIDAD_FLOOR,
    Scorer,
    _appearance_value,
    _fixture_multiplier,
    _minutes_regularity,
    _player_home_away_multiplier,
    _quality_multiplier,
    _titularidad,
    base_score,
    competition_multiplier,
    market_average_ratio,
    recommended_max_bid,
    weakest_score_by_position,
)

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "db" / "schema.sql"


# ---------------------------------------------------------------------------
# _minutes_regularity / _appearance_value
# ---------------------------------------------------------------------------

def test_minutes_regularity_none_without_data():
    assert _minutes_regularity(None) is None


def test_minutes_regularity_full_at_threshold():
    assert _minutes_regularity(MINUTES_FOR_FULL_REGULARITY) == 1.0


def test_minutes_regularity_capped_at_one():
    assert _minutes_regularity(MINUTES_FOR_FULL_REGULARITY * 2) == 1.0


def test_appearance_value_none_without_rounds():
    assert _appearance_value(5, 0) is None


def test_appearance_value_full_when_plays_every_round():
    assert _appearance_value(10, 10) == 1.0


def test_appearance_value_below_threshold_has_floor():
    value = _appearance_value(1, 10)  # 10% appearance rate, muy por debajo del 50%
    assert 0.2 <= value < 1.0


# ---------------------------------------------------------------------------
# _titularidad
# ---------------------------------------------------------------------------

def test_titularidad_falls_back_to_appearance_proxy_without_sofascore_data():
    multiplier, value, note = _titularidad(
        player_id=1, sofascore_starters={}, avg_minutes=None, matches_rated=0,
        games_played=10, rounds_available=10, status="ok",
    )
    assert value == 1.0
    assert multiplier == 1.0  # jugador que participa siempre, sin penalización
    assert note is None


def test_titularidad_doubt_status_penalizes_regardless_of_minutes():
    _, value_ok, _ = _titularidad(
        player_id=1, sofascore_starters={}, avg_minutes=90, matches_rated=3,
        games_played=3, rounds_available=3, status="ok",
    )
    _, value_doubt, note_doubt = _titularidad(
        player_id=1, sofascore_starters={}, avg_minutes=90, matches_rated=3,
        games_played=3, rounds_available=3, status="doubt",
    )
    assert value_doubt == pytest.approx(value_ok * DOUBT_TITULARIDAD_MULT)
    assert "duda" in note_doubt.lower()


def test_titularidad_low_sample_shrinks_toward_appearance_proxy():
    # 1 solo partido puntuado por SofaScore, jugando 90 min -> minutes_val_raw = 1.0,
    # pero con solo 1 partido de muestra se mezcla con una tasa de aparición baja.
    _, value_1_match, _ = _titularidad(
        player_id=1, sofascore_starters={}, avg_minutes=90, matches_rated=1,
        games_played=1, rounds_available=10, status="ok",  # aparece en solo 1 de 10 jornadas
    )
    _, value_many_matches, _ = _titularidad(
        player_id=1, sofascore_starters={}, avg_minutes=90, matches_rated=10,
        games_played=1, rounds_available=10, status="ok",
    )
    # con más partidos puntuados, se confía más en los minutos reales (más alto) que con 1 solo
    assert value_many_matches > value_1_match


def test_titularidad_blends_real_minutes_with_prediction():
    # SofaScore predice que NO sale de inicio el próximo partido, pese a buenos minutos reales
    _, value, note = _titularidad(
        player_id=1, sofascore_starters={1: False}, avg_minutes=90, matches_rated=5,
        games_played=5, rounds_available=5, status="ok",
    )
    _, value_no_prediction, _ = _titularidad(
        player_id=1, sofascore_starters={}, avg_minutes=90, matches_rated=5,
        games_played=5, rounds_available=5, status="ok",
    )
    assert value < value_no_prediction  # la predicción negativa baja el valor
    assert "no lo da titular" in note.lower() or "sofascore" in note.lower()


def test_titularidad_multiplier_respects_floor():
    multiplier, _, _ = _titularidad(
        player_id=1, sofascore_starters={1: False}, avg_minutes=0, matches_rated=5,
        games_played=0, rounds_available=10, status="doubt",
    )
    assert multiplier >= TITULARIDAD_FLOOR


def test_ganga_threshold_gates_low_titularidad_players():
    _, value, _ = _titularidad(
        player_id=1, sofascore_starters={1: False}, avg_minutes=5, matches_rated=3,
        games_played=1, rounds_available=10, status="doubt",
    )
    assert value < GANGA_TITULARIDAD_THRESHOLD


# ---------------------------------------------------------------------------
# _quality_multiplier
# ---------------------------------------------------------------------------

def test_quality_multiplier_neutral_without_data():
    assert _quality_multiplier(None, 0, 7.0) == 1.0


def test_quality_multiplier_small_sample_shrinks_toward_league_average():
    # Un rating altísimo en un solo partido no debe disparar el multiplicador al máximo
    mult_1_match = _quality_multiplier(9.5, 1, 7.0)
    mult_many_matches = _quality_multiplier(9.5, 10, 7.0)
    assert mult_1_match < mult_many_matches
    assert QUALITY_BOUNDS[0] <= mult_1_match <= QUALITY_BOUNDS[1]
    assert QUALITY_BOUNDS[0] <= mult_many_matches <= QUALITY_BOUNDS[1]


def test_quality_multiplier_bounded():
    # con muchísimos partidos (shrinkage despreciable) y un rating muy por encima de la
    # liga, el ratio bruto supera el límite superior y debe quedar recortado a él
    assert _quality_multiplier(20.0, 1000, 5.0) == QUALITY_BOUNDS[1]
    # un rating muy bajo se acerca al límite inferior sin llegar nunca a superarlo por abajo
    low = _quality_multiplier(0.0, 1000, 20.0)
    assert QUALITY_BOUNDS[0] <= low < 1.0


# ---------------------------------------------------------------------------
# _player_home_away_multiplier
# ---------------------------------------------------------------------------

def test_home_away_multiplier_defaults_without_history():
    mult_home = _player_home_away_multiplier(True, 0, 0, 0, 0)
    mult_away = _player_home_away_multiplier(False, 0, 0, 0, 0)
    assert mult_home == pytest.approx(1 + DEFAULT_HOME_BONUS)
    assert mult_away == pytest.approx(1 - DEFAULT_HOME_BONUS)


def test_home_away_multiplier_uses_own_split_with_enough_games():
    # Juega mucho mejor en casa (10 pts/partido) que fuera (2 pts/partido), con bastante historial
    mult_home = _player_home_away_multiplier(True, played_home=20, played_away=20, points_home=200, points_away=40)
    assert mult_home > 1 + DEFAULT_HOME_BONUS  # su propio sesgo es mayor que el +5% genérico
    assert mult_home <= HOME_AWAY_BOUNDS[1]


def test_home_away_multiplier_bounded():
    mult = _player_home_away_multiplier(True, played_home=50, played_away=1, points_home=500, points_away=0)
    assert HOME_AWAY_BOUNDS[0] <= mult <= HOME_AWAY_BOUNDS[1]


# ---------------------------------------------------------------------------
# base_score
# ---------------------------------------------------------------------------

def test_base_score_blends_with_last_season_early_in_the_year():
    # Sin partidos esta temporada todavía: debe caer por completo en la temporada pasada
    score = base_score(points_avg_blended=None, games_played=0, points_last_season_blended=190)
    assert score == pytest.approx(190 / 38)


def test_base_score_trusts_current_season_more_with_more_games():
    score_early = base_score(points_avg_blended=8.0, games_played=1, points_last_season_blended=0)
    score_established = base_score(points_avg_blended=8.0, games_played=30, points_last_season_blended=0)
    # menos "arrastre" hacia 0 (temporada pasada) cuantos más partidos lleva jugados esta temporada
    assert score_established > score_early
    assert score_early < 4.0  # con 1 solo partido, el arrastre de SHRINKAGE_GAMES pesa mucho todavía
    assert score_established > 6.0  # con 30 partidos, ya pesa poco frente a su media real (8.0)


# ---------------------------------------------------------------------------
# _fixture_multiplier (posición-aware)
# ---------------------------------------------------------------------------

def _fixtures_and_strengths(goals_by_team=None, league_goals_scored=None, league_goals_conceded=None):
    fixtures_by_team = {1: {"opponent_team_id": 2, "is_home": True, "kickoff_at": 123}}
    # equipo 2: defensa floja (fácil marcarle), ataque flojo (fácil no encajar)
    attack_strengths = {2: 2.0}
    defense_strengths = {2: 2.0}
    league_attack = 5.0
    league_defense = 5.0
    return (
        fixtures_by_team, attack_strengths, defense_strengths, league_attack, league_defense,
        goals_by_team or {}, league_goals_scored, league_goals_conceded,
    )


def test_fixture_multiplier_attacker_uses_opponent_defense():
    args = _fixtures_and_strengths()
    multiplier, fixture = _fixture_multiplier(1, "DL", *args)
    assert multiplier > 1.0  # rival con defensa floja (2.0 vs media 5.0) favorece al delantero
    assert fixture is not None


def test_fixture_multiplier_defender_uses_opponent_attack():
    args = _fixtures_and_strengths()
    multiplier, _ = _fixture_multiplier(1, "DF", *args)
    assert multiplier > 1.0  # rival con ataque flojo favorece al defensa/portero


def test_fixture_multiplier_no_fixture_is_neutral():
    multiplier, fixture = _fixture_multiplier(999, "DL", {}, {}, {}, None, None, {}, None, None)
    assert multiplier == 1.0
    assert fixture is None


def test_fixture_multiplier_real_goals_override_proxy_with_enough_matches():
    # el proxy de puntos fantasy dice que el equipo 2 tiene defensa floja (favorece al DL),
    # pero los goles reales dicen justo lo contrario (encaja MENOS que la media) y con
    # muchos partidos de por medio, así que el resultado neto debe acabar por debajo de 1.
    goals_by_team = {2: {"scored": 1.0, "conceded": 0.2, "matches": 20}}
    args = _fixtures_and_strengths(goals_by_team, league_goals_scored=1.5, league_goals_conceded=1.5)
    multiplier, _ = _fixture_multiplier(1, "DL", *args)
    assert multiplier < 1.0


def test_fixture_multiplier_real_goals_barely_move_proxy_with_few_matches():
    # mismo caso, pero con solo 1 partido real de por medio -> apenas debe apartarse del
    # multiplicador que daría el proxy solo (>1.0, ver test de arriba con solo proxy)
    goals_by_team = {2: {"scored": 1.0, "conceded": 0.2, "matches": 1}}
    args = _fixtures_and_strengths(goals_by_team, league_goals_scored=1.5, league_goals_conceded=1.5)
    multiplier, _ = _fixture_multiplier(1, "DL", *args)
    assert multiplier > 1.0


# ---------------------------------------------------------------------------
# competition_multiplier / recommended_max_bid
# ---------------------------------------------------------------------------

def test_competition_multiplier_neutral_without_data():
    assert competition_multiplier(None) == 1.0


def test_competition_multiplier_rises_with_rival_balance():
    rich_rivals = {
        "estimated_starting_balance": 100,
        "managers": [{"is_self": True, "estimated_balance": 100}, {"is_self": False, "estimated_balance": 150}],
    }
    assert competition_multiplier(rich_rivals) > 1.0


def test_recommended_max_bid_never_below_market_price():
    bid = recommended_max_bid(
        score=0.1, position="PT", price=5_000_000, weakest_by_position={"PT": 10.0}, gap_positions=set(),
        is_ganga=False, avg_market_ratio=1.0, maximum_bid=20_000_000,
    )
    assert bid >= 5_000_000


def test_recommended_max_bid_capped_by_maximum_bid():
    bid = recommended_max_bid(
        score=10.0, position="DL", price=1_000_000, weakest_by_position={}, gap_positions={"DL"},
        is_ganga=True, avg_market_ratio=0.5, maximum_bid=2_000_000,
    )
    assert bid <= 2_000_000


def test_market_average_ratio_empty_is_none():
    assert market_average_ratio([]) is None


def test_weakest_score_by_position_tracks_gaps():
    lineup_result = {
        "feasible": False,
        "best_effort": {
            "starters": [
                {"position": "PT", "score": 5.0},
                {"position": "DF", "empty": True},
            ]
        },
    }
    weakest, gaps = weakest_score_by_position(lineup_result)
    assert weakest == {"PT": 5.0}
    assert gaps == {"DF"}


# ---------------------------------------------------------------------------
# Scorer end-to-end sobre una base de datos SQLite en memoria
# ---------------------------------------------------------------------------

def _seed_db(conn):
    conn.executescript(SCHEMA_PATH.read_text())
    conn.execute("INSERT INTO teams (id, name) VALUES (1, 'Equipo A'), (2, 'Equipo B')")
    conn.execute(
        "INSERT INTO team_fixtures (team_id, opponent_team_id, is_home, kickoff_at, round_id) "
        "VALUES (1, 2, 1, 1700000000, 1)"
    )
    conn.execute(
        """
        INSERT INTO players
            (id, name, team_id, shirt_number, position, status, status_info, points_total, points_avg,
             points_total_blended, points_avg_blended, games_played, rounds_available,
             points_last_season, points_last_season_blended, played_home, played_away,
             points_home_blended, points_away_blended, price, price_increment_day, updated_at)
        VALUES
            (1, 'Jugador Titular', 1, 9, 'DL', 'ok', NULL, 20, 6.5, 20, 6.5, 3, 3, 100, 100,
             2, 1, 15, 5, 5000000, 10000, '2026-01-01'),
            (2, 'Jugador Duda', 1, 10, 'MC', 'doubt', 'Molestias', 10, 4.0, 10, 4.0, 3, 3, 60, 60,
             1, 2, 4, 6, 2000000, 0, '2026-01-01')
        """
    )


def test_scorer_end_to_end_applies_doubt_penalty():
    conn = sqlite3.connect(":memory:")
    try:
        _seed_db(conn)
        scorer = Scorer(conn)

        titular = scorer.score(1, "Jugador Titular", "DL", "ok", 1, 6.5, 3, 3, 100)
        duda = scorer.score(2, "Jugador Duda", "MC", "doubt", 1, 4.0, 3, 3, 60)

        assert titular["score"] > 0
        assert duda["titularidad_note"] is not None and "duda" in duda["titularidad_note"].lower()
        assert duda["titularidad_value"] < 1.0
    finally:
        conn.close()


def test_scorer_uses_position_aware_fixture_and_home_away():
    conn = sqlite3.connect(":memory:")
    try:
        _seed_db(conn)
        scorer = Scorer(conn)
        entry = scorer.score(1, "Jugador Titular", "DL", "ok", 1, 6.5, 3, 3, 100)
        # no debe lanzar excepciones y debe traer un rival calculado (equipo 2, en casa)
        assert entry["rival"].startswith("vs ")
    finally:
        conn.close()
