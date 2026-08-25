"""
Cruza equipos y jugadores de Biwenger con SofaScore para tres cosas:
1. Si un jugador es titular previsto en su próximo partido (alineación probable).
2. Su rendimiento REAL reciente: la puntuación (0-10) y los minutos jugados que dio
   SofaScore en sus últimos partidos ya disputados.
3. Goles marcados/encajados REALES de cada equipo en sus últimos partidos — para el
   ajuste por rival del 11 ideal (ver `sync_team_goal_stats`).

El cruce de equipos es por nombre normalizado (sin acentos, en minúsculas, comprobando
si uno contiene al otro) con un pequeño diccionario de excepciones para los pocos casos
donde los nombres no coinciden lo suficiente (p.ej. "Atlético" vs "Atl. Madrid"). El
cruce de jugadores dentro de cada equipo es por dorsal (más fiable que por nombre, que
puede venir con acentos o apodos distintos en cada web).
"""

import unicodedata
from datetime import datetime, timezone

from sofascore_client.client import SofaScoreClient

MANUAL_TEAM_NAME_OVERRIDES = {
    "atlético": "atl. madrid",
}


def _normalize(name):
    stripped = "".join(c for c in unicodedata.normalize("NFKD", name.lower()) if not unicodedata.combining(c))
    return stripped.strip()


def _match_team(biwenger_name, sofascore_teams):
    key = _normalize(biwenger_name)
    key = MANUAL_TEAM_NAME_OVERRIDES.get(key, key)
    for team in sofascore_teams:
        candidates = [_normalize(team["name"]), _normalize(team["short_name"])]
        if any(key in c or c in key for c in candidates):
            return team["id"]
    return None


def _build_crosswalk(client, teams):
    """biwenger_team_id -> sofascore_team_id, y la temporada activa de SofaScore."""
    season_id = client.get_current_season_id()
    sofascore_teams = client.get_teams(season_id)
    crosswalk = {}
    for team in teams:
        matched = _match_team(team["name"], sofascore_teams)
        if matched:
            crosswalk[team["id"]] = matched
    return crosswalk, season_id


def _players_by_team_and_shirt(players):
    by_team = {}
    for p in players:
        if p.get("shirt_number") is not None:
            by_team.setdefault(p["team_id"], {})[p["shirt_number"]] = p["id"]
    return by_team


def sync_predicted_lineups(teams, players):
    """
    `teams`: [{id, name}] (salida de BiwengerClient.get_all_players). `players`: idem,
    debe incluir "id", "team_id" y "shirt_number".
    """
    players_by_team = _players_by_team_and_shirt(players)

    client = SofaScoreClient()
    team_crosswalk, season_id = _build_crosswalk(client, teams)
    upcoming_events = client.get_upcoming_events(season_id)

    def _next_event_for(sofascore_team_id):
        for event in upcoming_events:
            if sofascore_team_id in (event["home_team_id"], event["away_team_id"]):
                return event
        return None

    now = datetime.now(timezone.utc).isoformat()
    lineup_cache = {}  # event_id -> predicted lineup payload
    predictions = []

    for biwenger_team_id, sofascore_team_id in team_crosswalk.items():
        event = _next_event_for(sofascore_team_id)
        if not event:
            continue

        if event["id"] not in lineup_cache:
            lineup_cache[event["id"]] = client.get_predicted_lineup(event["id"])
        lineup = lineup_cache[event["id"]]

        side = lineup["home"] if event["home_team_id"] == sofascore_team_id else lineup["away"]
        if not side:
            continue  # SofaScore aún no tiene datos de este partido — no se puede afirmar nada

        # Las alineaciones no confirmadas solo listan a los 11 previstos (sin banquillo),
        # así que comparamos contra TODA la plantilla del equipo: quien no aparece en el
        # once previsto queda marcado explícitamente como no-titular, no como "sin dato".
        starting_shirt_numbers = {entry["shirt_number"] for entry in side if entry["starter"]}
        roster = players_by_team.get(biwenger_team_id, {})
        for shirt_number, player_id in roster.items():
            predictions.append(
                {
                    "player_id": player_id,
                    "predicted_starter": shirt_number in starting_shirt_numbers,
                    "confirmed": lineup["confirmed"],
                    "event_id": event["id"],
                    "updated_at": now,
                }
            )

    return predictions


def sync_player_ratings(teams, players, matches_per_team=3):
    """
    Puntuación media (0-10) y minutos medios de cada jugador en sus últimos partidos
    ya disputados, según SofaScore — puede incluir partidos de la temporada anterior si
    esta apenas lleva jornadas jugadas. Solo cuenta a quien realmente saltó al campo
    (SofaScore no da estadísticas a quien se quedó en el banquillo sin jugar).
    """
    players_by_team = _players_by_team_and_shirt(players)

    client = SofaScoreClient()
    team_crosswalk, _season_id = _build_crosswalk(client, teams)

    now = datetime.now(timezone.utc).isoformat()
    stats_cache = {}  # event_id -> {"home": [...], "away": [...]}
    samples_by_player = {}  # player_id -> [(rating, minutes_played), ...]

    for biwenger_team_id, sofascore_team_id in team_crosswalk.items():
        recent_events = client.get_recent_team_events(sofascore_team_id, limit=matches_per_team)
        roster = players_by_team.get(biwenger_team_id, {})

        for event in recent_events:
            if event["id"] not in stats_cache:
                stats_cache[event["id"]] = client.get_match_stats(event["id"])
            stats = stats_cache[event["id"]]

            side = stats["home"] if event["home_team_id"] == sofascore_team_id else stats["away"]
            for entry in side:
                player_id = roster.get(entry["shirt_number"])
                if player_id is None or entry["rating"] is None:
                    continue
                samples_by_player.setdefault(player_id, []).append((entry["rating"], entry["minutes_played"]))

    results = []
    for player_id, samples in samples_by_player.items():
        ratings = [r for r, _ in samples]
        minutes = [m for _, m in samples]
        results.append(
            {
                "player_id": player_id,
                "avg_rating": round(sum(ratings) / len(ratings), 2),
                "avg_minutes": round(sum(minutes) / len(minutes), 1),
                "matches_rated": len(samples),
                "updated_at": now,
            }
        )
    return results


def sync_team_goal_stats(teams, matches_per_team=5):
    """
    Goles marcados y encajados de media por cada equipo en sus últimos partidos ya
    disputados, según SofaScore — el resultado real ya viene incluido en la misma
    respuesta que usa `sync_player_ratings` para las alineaciones (sin llamadas extra).
    Sustituye gradualmente (con más peso cuantos más partidos reales hay) al proxy de
    "fuerza de equipo" basado en puntos fantasy que usa el ajuste por rival del 11 ideal.
    """
    client = SofaScoreClient()
    team_crosswalk, _season_id = _build_crosswalk(client, teams)

    now = datetime.now(timezone.utc).isoformat()
    results = []
    for biwenger_team_id, sofascore_team_id in team_crosswalk.items():
        recent_events = client.get_recent_team_events(sofascore_team_id, limit=matches_per_team)
        scored, conceded = [], []
        for event in recent_events:
            if event["home_score"] is None or event["away_score"] is None:
                continue
            is_home = event["home_team_id"] == sofascore_team_id
            scored.append(event["home_score"] if is_home else event["away_score"])
            conceded.append(event["away_score"] if is_home else event["home_score"])

        if not scored:
            continue
        results.append(
            {
                "team_id": biwenger_team_id,
                "goals_scored_avg": round(sum(scored) / len(scored), 2),
                "goals_conceded_avg": round(sum(conceded) / len(conceded), 2),
                "matches_counted": len(scored),
                "updated_at": now,
            }
        )
    return results
