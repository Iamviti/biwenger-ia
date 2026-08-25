from datetime import datetime, timezone

import requests

BASE_URL = "https://biwenger.as.com/api/v2"

# Códigos de posición confirmados contra la API real
# (1=Portero, 2=Defensa, 3=Centrocampista, 4=Delantero, 5=Entrenador — no juega, no cuenta para el 11)
POSITION_MAP = {1: "PT", 2: "DF", 3: "MC", 4: "DL", 5: "MI"}


class BiwengerClient:
    """
    Wrapper sobre la API (no oficial) de Biwenger.

    Todas las respuestas llegan envueltas como {"status": ..., "data": ...} —
    `get_raw` desenvuelve y devuelve directamente el contenido de "data".
    """

    def __init__(self, token, league_id, user_id, competition="la-liga", lang="es"):
        self.league_id = league_id
        self.user_id = user_id
        self.competition = competition
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "X-League": str(league_id),
                "X-User": str(user_id),
                "X-Lang": lang,
            }
        )

    def get_raw(self, path, params=None):
        """
        Fetch a path under BASE_URL and return the unwrapped `data` field, for exploración/debug.

        La mayoría de endpoints envuelven la respuesta como {"status": 200, "data": ...},
        pero no todos (p.ej. /market devuelve {"status": {...}, "sales": [...], "offers": [...]}
        directamente) — si no hay clave "data", se devuelve el payload completo tal cual.
        """
        response = self.session.get(f"{BASE_URL}/{path.lstrip('/')}", params=params)
        response.raise_for_status()
        payload = response.json()
        return payload.get("data", payload)

    def get_account(self):
        """Perfil propio y ligas a las que pertenezco (incluye mi saldo dentro de cada liga)."""
        return self.get_raw("account")

    def get_all_players(self, score=1):
        """
        Master list de todos los jugadores de la competición (precio, puntos, estado),
        la jornada activa (nombre + timestamp en que termina) según `activeEvents`, y el
        próximo partido de cada equipo (rival y local/visitante) según `nextGames`.

        `score` selecciona el sistema de puntuación de Biwenger con el que se calculan
        `points`/`fitness`/`pointsLastSeason`/`pointsHome`/`pointsAway` — 1 = Diario AS
        (el que rige esta liga, usarlo para precios/puntos "oficiales"), 5 = Media AS y
        SofaScore (más completo, para puntuar candidatos en el optimizador de alineación).

        También trae `statusInfo` (texto de lesión/duda de Biwenger, p.ej. "Lesión
        muscular. Retorno estimado: Principios de Septiembre") y el reparto casa/fuera de
        partidos jugados y puntos (`playedHome`/`playedAway`/`pointsHome`/`pointsAway`) —
        antes se descartaban, ahora se usan para el ajuste de casa/fuera por jugador.
        """
        data = self.get_raw(f"competitions/{self.competition}/data", params={"score": score, "lang": "es"})
        now = datetime.now(timezone.utc).isoformat()

        teams = [{"id": int(team_id), "name": team["name"]} for team_id, team in data.get("teams", {}).items()]

        fixtures = []
        for team_id, team in data.get("teams", {}).items():
            next_games = team.get("nextGames") or []
            if not next_games:
                continue
            game = next_games[0]
            home_id = (game.get("home") or {}).get("id")
            away_id = (game.get("away") or {}).get("id")
            is_home = home_id == int(team_id)
            fixtures.append(
                {
                    "team_id": int(team_id),
                    "opponent_team_id": away_id if is_home else home_id,
                    "is_home": is_home,
                    "kickoff_at": game.get("date"),
                    "round_id": (game.get("round") or {}).get("id"),
                }
            )

        players = []
        for player_id, player in data.get("players", {}).items():
            raw_fitness = player.get("fitness") or []
            fitness = [f for f in raw_fitness if isinstance(f, (int, float))]
            points_avg = (sum(fitness) / len(fitness)) if fitness else None
            players.append(
                {
                    "id": int(player_id),
                    "name": player.get("name"),
                    "team_id": player.get("teamID"),
                    "shirt_number": player.get("number"),
                    "position": POSITION_MAP.get(player.get("position"), str(player.get("position"))),
                    "status": player.get("status"),
                    "status_info": player.get("statusInfo"),
                    "points_total": player.get("points"),
                    "points_avg": points_avg,
                    "games_played": len(fitness),
                    # nº de jornadas que su equipo lleva jugadas (incluye las que no jugó por lesión/sanción/etc.)
                    "rounds_available": len(raw_fitness),
                    "points_last_season": player.get("pointsLastSeason"),
                    "played_home": player.get("playedHome"),
                    "played_away": player.get("playedAway"),
                    "points_home": player.get("pointsHome"),
                    "points_away": player.get("pointsAway"),
                    "price": player.get("price"),
                    "price_increment_day": player.get("priceIncrement"),
                    "updated_at": now,
                }
            )

        current_round = None
        for event in data.get("activeEvents", []):
            if event.get("type") == "round" and event.get("status") == "active":
                current_round = {"round_id": event.get("id"), "name": event.get("name"), "ends_at": event.get("end")}
                break

        return teams, players, current_round, fixtures

    def get_market(self):
        """
        Jugadores actualmente en venta en la liga, con mi puja activa (si la hay) en cada uno.

        Biwenger solo expone las pujas del propio usuario mientras la subasta sigue abierta —
        las de los demás managers permanecen ocultas hasta que se resuelve la puja.
        Devuelve (listings, status) donde status trae mi saldo y mi puja máxima permitida
        (`maximumBid`, que puede superar el saldo por el sistema de crédito de Biwenger).
        """
        data = self.get_raw("market")

        my_bids = {}
        for offer in data.get("offers", []):
            if offer.get("type") == "purchase" and offer.get("status") == "waiting":
                for player_id in offer.get("requestedPlayers", []):
                    my_bids[player_id] = offer.get("amount")

        listings = []
        for sale in data.get("sales", []):
            player_id = (sale.get("player") or {}).get("id")
            listings.append(
                {
                    "player_id": player_id,
                    "price": sale.get("price"),
                    "expires_at": sale.get("until"),
                    "my_bid_amount": my_bids.get(player_id),
                    "seller_user_id": (sale.get("user") or {}).get("id"),
                }
            )

        status = data.get("status") or {}
        return listings, {"balance": status.get("balance"), "maximum_bid": status.get("maximumBid")}

    def get_league_squads(self):
        """
        Todos los managers de la liga y los jugadores que posee cada uno.

        Biwenger no expone el precio de compra en este endpoint (ni en ningún otro
        probado) — precio_compra queda a None por ahora. Se calculará más adelante
        a partir del histórico de fichajes leído del board de la liga.
        """
        data = self.get_raw(f"league/{self.league_id}", params={"fields": "standings"})
        users = [{"id": s["id"], "name": s["name"]} for s in data.get("standings", [])]

        ownerships = []
        for user in users:
            owned = self.get_raw(f"user/{user['id']}", params={"fields": "players"})
            for player in owned.get("players", []):
                ownerships.append(
                    {
                        "league_user_id": user["id"],
                        "player_id": player["id"],
                        "purchase_price": None,
                    }
                )
        return users, ownerships

    def get_board_entries(self):
        """Todo el histórico del "board" de actividad de la liga (paginado hasta agotarlo)."""
        entries = []
        limit = 100
        offset = 0
        while True:
            page = self.get_raw(f"league/{self.league_id}/board", params={"limit": limit, "offset": offset})
            if not page:
                break
            entries.extend(page)
            if len(page) < limit:
                break
            offset += limit
        return entries

    def get_purchase_history(self, board_entries=None):
        """
        Historial de fichajes de la liga (ganadores de puja en el mercado + traspasos
        directos entre managers). Es la única forma de recuperar el precio de compra de
        un jugador — Biwenger no lo expone en ningún endpoint de plantilla. No cubre el
        reparto inicial de plantillas al crear la liga (no genera entradas en el board),
        así que jugadores que llevan en tu equipo desde el principio quedarán sin precio
        de compra conocido.
        """
        board_entries = board_entries if board_entries is not None else self.get_board_entries()
        purchases = {}  # player_id -> registro más reciente
        for entry in board_entries:
            if entry.get("type") not in ("market", "transfer"):
                continue
            for item in entry.get("content", []):
                to = item.get("to")
                if not to:
                    continue
                player_id = item.get("player")
                date = entry.get("date")
                existing = purchases.get(player_id)
                if not existing or date > existing["purchased_at"]:
                    purchases[player_id] = {
                        "player_id": player_id,
                        "league_user_id": to["id"],
                        "amount": item.get("amount"),
                        "purchased_at": date,
                    }
        return list(purchases.values())

    def get_transaction_ledger(self, board_entries=None):
        """
        Cada movimiento de saldo de cada manager (compras en negativo, ventas en
        positivo) leído del board — base para estimar el saldo de los rivales, ya que
        Biwenger no lo expone directamente salvo el propio.
        """
        board_entries = board_entries if board_entries is not None else self.get_board_entries()
        movements = []
        for entry in board_entries:
            if entry.get("type") not in ("market", "transfer"):
                continue
            date = entry.get("date")
            for item in entry.get("content", []):
                amount = item.get("amount")
                if amount is None:
                    continue
                to = item.get("to")
                from_ = item.get("from")
                if to:
                    movements.append({"league_user_id": to["id"], "delta": -amount, "date": date})
                if from_:
                    movements.append({"league_user_id": from_["id"], "delta": amount, "date": date})
        return movements

    def get_balances(self, own_maximum_bid=None):
        """
        Saldo de los managers de la liga.

        Biwenger solo expone el saldo del propio usuario autenticado — el de los
        rivales está oculto por configuración de la liga. Se estimará en una fase
        posterior (módulo de inteligencia de mercado) en vez de leerse directamente.
        `own_maximum_bid` permite adjuntar el límite de puja real (de `get_market`)
        a la fila del propio usuario.
        """
        account = self.get_account()
        own_balance = None
        for league in account.get("leagues", []):
            if str(league.get("id")) == str(self.league_id):
                own_balance = league.get("user", {}).get("balance")
                break
        return [
            {
                "league_user_id": int(self.user_id),
                "balance": own_balance,
                "maximum_bid": own_maximum_bid,
            }
        ]
