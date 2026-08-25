"""
Cliente para la API pública (no oficial) de SofaScore — se usa solo para leer la
alineación probable de cada equipo antes de la próxima jornada. SofaScore bloquea las
peticiones que no tengan la huella TLS de un navegador real (devuelve 403 con
`requests` normal), así que aquí se usa curl_cffi, que la imita.

La alineación que da SofaScore cuando `confirmed` es False es una predicción editorial
suya (no oficial, actualizada según convocatorias/rotaciones recientes) — es lo más
parecido a "titular indiscutible" que se puede obtener con días de antelación; el once
se confirma oficialmente ~1h antes del partido, y el orden de entrada de los suplentes
no se publica hasta entonces, así que "primer cambio" no es un dato que se pueda leer
con antelación desde ninguna fuente.
"""

from curl_cffi import requests

BASE_URL = "https://api.sofascore.com/api/v1"
LALIGA_TOURNAMENT_ID = 8


class SofaScoreClient:
    def __init__(self):
        self.session = requests.Session(impersonate="chrome124")

    def _get(self, path, params=None):
        response = self.session.get(f"{BASE_URL}/{path.lstrip('/')}", params=params)
        response.raise_for_status()
        return response.json()

    def get_current_season_id(self):
        data = self._get(f"unique-tournament/{LALIGA_TOURNAMENT_ID}/seasons")
        return data["seasons"][0]["id"]  # la más reciente va primero

    def get_teams(self, season_id):
        """[{id, name, short_name}] de los equipos de la temporada, vía la tabla clasificatoria."""
        data = self._get(f"unique-tournament/{LALIGA_TOURNAMENT_ID}/season/{season_id}/standings/total")
        teams = []
        for row in data["standings"][0]["rows"]:
            t = row["team"]
            teams.append({"id": t["id"], "name": t["name"], "short_name": t.get("shortName", t["name"])})
        return teams

    def get_upcoming_events(self, season_id):
        """Próximos partidos: [{id, home_team_id, away_team_id, kickoff}]."""
        data = self._get(f"unique-tournament/{LALIGA_TOURNAMENT_ID}/season/{season_id}/events/next/0")
        return [
            {
                "id": e["id"],
                "home_team_id": e["homeTeam"]["id"],
                "away_team_id": e["awayTeam"]["id"],
                "kickoff": e.get("startTimestamp"),
            }
            for e in data.get("events", [])
        ]

    def get_predicted_lineup(self, event_id):
        """
        {"confirmed": bool, "home": [...], "away": [...]}, cada jugador como
        {"name", "shirt_number", "starter"}. Si SofaScore no tiene datos para este
        partido todavía, ambas listas vienen vacías.
        """
        try:
            data = self._get(f"event/{event_id}/lineups")
        except Exception:
            return {"confirmed": False, "home": [], "away": []}

        def _side(payload):
            return [
                {
                    "name": p["player"]["name"],
                    "shirt_number": p.get("shirtNumber"),
                    "starter": not p.get("substitute", False),
                }
                for p in (payload or {}).get("players", [])
            ]

        return {
            "confirmed": bool(data.get("confirmed", False)),
            "home": _side(data.get("home")),
            "away": _side(data.get("away")),
        }

    def get_recent_team_events(self, team_id, limit=5):
        """
        Últimos partidos ya jugados de un equipo (cualquier competición/temporada,
        orden del más reciente al más antiguo) — para leer la puntuación real que dio
        SofaScore y los minutos jugados de cada jugador, y el resultado final (goles),
        que ya viene en esta misma respuesta sin necesidad de otra llamada.
        """
        try:
            data = self._get(f"team/{team_id}/events/last/0")
        except Exception:
            return []
        events = [e for e in data.get("events", []) if e.get("status", {}).get("type") == "finished"]
        return [
            {
                "id": e["id"],
                "home_team_id": e["homeTeam"]["id"],
                "away_team_id": e["awayTeam"]["id"],
                "home_score": (e.get("homeScore") or {}).get("current"),
                "away_score": (e.get("awayScore") or {}).get("current"),
                "kickoff": e.get("startTimestamp"),
            }
            for e in events[:limit]
        ]

    def get_match_stats(self, event_id):
        """
        Rendimiento real por jugador de un partido ya finalizado: {"home": [...], "away": [...]}
        con {"shirt_number", "rating", "minutes_played"} — solo para quienes llegaron a jugar
        (los que se quedaron en el banquillo sin salir no tienen "statistics").
        """
        try:
            data = self._get(f"event/{event_id}/lineups")
        except Exception:
            return {"home": [], "away": []}

        def _side(payload):
            out = []
            for p in (payload or {}).get("players", []):
                stats = p.get("statistics")
                if not stats or not stats.get("minutesPlayed"):
                    continue
                out.append(
                    {
                        "shirt_number": p.get("shirtNumber"),
                        "rating": stats.get("rating"),
                        "minutes_played": stats.get("minutesPlayed"),
                    }
                )
            return out

        return {"home": _side(data.get("home")), "away": _side(data.get("away"))}
