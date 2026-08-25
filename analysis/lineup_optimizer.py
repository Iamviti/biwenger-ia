"""
Optimizador del 11 ideal a partir de la plantilla actual (programación lineal con PuLP).

La puntuación de cada jugador combina estas fuentes:
1. Rendimiento fantasy esta temporada según "Media AS y SofaScore" de Biwenger
   (points_avg_blended), con más peso conforme lleva más partidos jugados, amortiguado
   al principio de temporada con su rendimiento de la pasada (points_last_season_blended).
2. Calidad real de juego: la puntuación media (0-10) que da SofaScore en sus últimos
   partidos jugados, comparada con la media de la liga — sube o baja el rendimiento
   fantasy esperado hasta un ±20% si viene rindiendo mejor o peor que el resto. Con
   pocos partidos puntuados (SofaScore da como mucho los 3 últimos) se mezcla (shrinkage
   bayesiano) con la media de la liga, para no dejar que 1-2 partidos sueltos disparen el
   ajuste — con más partidos puntuados, más se confía en su propio dato.
3. Titularidad, con jerarquía de fiabilidad — se usa el mejor dato disponible:
   a) Minutos REALES jugados en sus últimos partidos (SofaScore) — el hecho más fiable,
      aunque con pocos partidos puntuados también se mezcla con la tasa de aparición de
      Biwenger de toda la temporada (mismo shrinkage que en la calidad de juego).
   b) Si además hay alineación prevista de SofaScore para el próximo partido, se combina
      con los minutos reales (65%/35%) para no ignorar una baja o sanción de última hora
      que el histórico no puede prever.
   c) Si no hay ningún dato de SofaScore, se cae al proxy de Biwenger (jornadas jugadas
      esta temporada respecto a las disputadas por su equipo).
   d) Si Biwenger marca al jugador como "duda" para el próximo partido (con su propio
      texto, p.ej. "Molestias en el sóleo") se aplica una penalización adicional — es una
      señal directa de Biwenger sobre el PRÓXIMO partido que el resto de fuentes (medias
      históricas) no puede capturar.
   Con esto se calcula un "valor de titularidad" de 0 a 1: por debajo de un umbral, el
   buscador de gangas, las sustituciones sugeridas y los posibles fichajes del 11 ideal
   descartan directamente al jugador (no se recomienda fichar a quien no es titular
   real). Sobre tu propia plantilla actual esto NO excluye a nadie, solo penaliza la
   puntuación — se asume que revisas tú mismo la titularidad antes de alinear.
4. Dificultad del próximo rival, SEPARADA POR POSICIÓN (no una única "fuerza" genérica):
   a un centrocampista/delantero le beneficia que el rival tenga la DEFENSA floja (más
   fácil marcar/asistir); a un portero/defensa le beneficia que el rival tenga el ATAQUE
   flojo (más fácil portería a cero). La base es la puntuación fantasy media de cada
   bloque de jugadores (DF+PT vs. MC+DL) de cada equipo, pero en cuanto hay goles REALES
   marcados/encajados de SofaScore para ese equipo, se mezclan con esa base (más peso
   cuantos más partidos reales hay) — los goles de verdad son más fieles que un proxy de
   puntos fantasy, pero con pocos partidos disputados son ruidosos, así que no sustituyen
   al proxy de golpe.
5. Casa/fuera, con el reparto REAL de puntos en casa y fuera de CADA jugador (que da
   Biwenger) en vez de un +5%/-5% genérico para todos — con pocos partidos propios en esa
   condición se mezcla (shrinkage) con el +5%/-5% por defecto.

6. Bonus de consistencia: un centrocampista o delantero con titularidad casi asegurada
   (valor de titularidad ≥ 0.9, ~90% de los minutos posibles) recibe un extra en la
   puntuación. Un titular fijo en esas posiciones acumula muchas más ocasiones de anotar
   o asistir (lo que más puntúa en Biwenger para MC/DL) que uno rotativo aunque tenga
   una puntuación media similar — así no se pasan por alto jugadores fiables solo porque
   su ratio puntos/precio puntual no destaque. No aplica a PT/DF, donde la titularidad ya
   pesa lo suficiente por sí sola (su puntuación depende menos de participar en jugadas
   ofensivas).

Se excluyen del 11 real: jugadores lesionados/sancionados/descartados, entrenadores
(no juegan), y jugadores que ya tienes puestos en venta (podrías perderlos antes del
partido). Para estos últimos, se resuelve también un 11 hipotético incluyéndolos: si
alguno habría sido titular, se avisa de que quizá no convenga venderlo.

Solo se consideran dos formaciones (las únicas que se van a usar en toda la temporada):
3-4-3 y 3-5-2. Cada jornada se resuelve la alineación óptima para AMBAS formaciones con
los datos disponibles (rival, titularidad, forma) y se recomienda la que dé mayor
puntuación total — no siempre es la misma según quién juegue cada semana.

Además, usando la misma puntuación se compara tu 11 contra los jugadores que hay HOY en
el mercado (mismo criterio que "Gangas libres" y "Mercado"): si alguno mejoraría a tu
titular más débil de su posición, es titular real y su precio cabe en tu puja máxima
permitida, se avisa como posible fichaje. Y si ninguna de las dos formaciones es viable
con tu plantilla actual, se buscan los mejores candidatos titulares del mercado en las
posiciones que te faltan.

Con el mismo resultado se calcula también una puja máxima RECOMENDADA por jugador del
mercado (ver `recommended_max_bid`): no es solo cuánto puedes permitirte pagar (tu saldo
real), sino cuánto tiene sentido pagar dado su rendimiento, si tu equipo lo necesita en
esa posición ahora mismo, y si ya es una ganga reconocida.
"""

import pulp

SEASON_ROUNDS = 38
SHRINKAGE_GAMES = 5  # nº de partidos "virtuales" que aporta la temporada pasada al inicio de curso
UNAVAILABLE_STATUSES = {"injured", "sanctioned", "discarded"}
CANDIDATE_FORMATIONS = {"3-4-3": {"DF": 3, "MC": 4, "DL": 3}, "3-5-2": {"DF": 3, "MC": 5, "DL": 2}}
VALID_POSITIONS = {"PT", "DF", "MC", "DL"}
TOTAL_STARTERS = 11

OPPONENT_STRENGTH_ALPHA = 0.25  # cuánto pesa la fuerza del rival en el ajuste (± en torno a la media de la liga)
MULTIPLIER_BOUNDS = (0.7, 1.3)  # límites para no disparar el ajuste con datos escasos
REAL_GOALS_SHRINKAGE_MATCHES = 4  # "peso" en partidos del proxy de puntos fantasy frente a los goles reales

# Casa/fuera: reparto real de puntos de CADA jugador (Biwenger), no un +/-5% genérico para
# todos. Con pocos partidos propios en esa condición se mezcla con el valor por defecto.
DEFAULT_HOME_BONUS = 0.05  # +5%/-5% de referencia si no hay histórico propio suficiente
HOME_AWAY_SHRINKAGE_GAMES = 6
HOME_AWAY_BOUNDS = (0.85, 1.15)

# Calidad real de juego (rating medio de SofaScore en sus últimos partidos vs. la liga)
QUALITY_ALPHA = 0.15
QUALITY_BOUNDS = (0.85, 1.20)
QUALITY_SHRINKAGE_MATCHES = 3  # "peso" en partidos de la media de la liga frente a la propia del jugador

# Titularidad: minutos reales (SofaScore) > minutos reales + próximo partido previsto > proxy de Biwenger
MINUTES_FOR_FULL_REGULARITY = 75  # min. medios reales a partir de los cuales se considera titular indiscutible
TITULARIDAD_SHRINKAGE_MATCHES = 2  # con 1-2 partidos SofaScore reales, se mezcla con el proxy de Biwenger
REAL_MINUTES_WEIGHT = 0.65
PREDICTION_WEIGHT = 0.35
FORWARD_NON_STARTER_VALUE = 0.35  # valor de titularidad (0-1) si SofaScore predice que NO sale de inicio
LOW_APPEARANCE_THRESHOLD = 0.5  # proxy de Biwenger, solo si no hay ni minutos reales ni predicción
APPEARANCE_FLOOR_VALUE = 0.2
DOUBT_TITULARIDAD_MULT = 0.7  # penalización si Biwenger marca "duda" para el próximo partido

TITULARIDAD_FLOOR = 0.4  # multiplicador mínimo sobre la puntuación (nunca se anula del todo)
GANGA_TITULARIDAD_THRESHOLD = 0.55  # por debajo de esto no se considera titular real para gangas/fichajes/sustituciones

# Bonus de consistencia: titulares casi fijos (≥90% de titularidad) en posiciones ofensivas
# generan más ocasiones de puntuar (goles/asistencias) cuanto más juegan — se premia aparte
# de la propia puntuación media, para no infravalorar a un fijo frente a un rotativo con racha.
CONSISTENCY_TITULARIDAD_THRESHOLD = 0.9
CONSISTENCY_BONUS = {"MC": 0.12, "DL": 0.12}  # % extra de puntuación; DF/PT no reciben bonus


def _minutes_regularity(avg_minutes):
    if avg_minutes is None:
        return None
    return max(0.0, min(1.0, avg_minutes / MINUTES_FOR_FULL_REGULARITY))


def _appearance_value(games_played, rounds_available):
    """Proxy de Biwenger — último recurso, sin dato real de minutos ni predicción de SofaScore."""
    if not rounds_available:
        return None
    rate = games_played / rounds_available
    if rate >= LOW_APPEARANCE_THRESHOLD:
        return 1.0
    return APPEARANCE_FLOOR_VALUE + (1 - APPEARANCE_FLOOR_VALUE) * (rate / LOW_APPEARANCE_THRESHOLD)


def _titularidad(player_id, sofascore_starters, avg_minutes, matches_rated, games_played, rounds_available, status):
    """Devuelve (multiplicador_sobre_puntuación, valor_titularidad_0_a_1, nota_textual)."""
    appearance = _appearance_value(games_played, rounds_available)

    minutes_val_raw = _minutes_regularity(avg_minutes) if matches_rated else None
    if minutes_val_raw is not None:
        # con pocos partidos puntuados por SofaScore, se mezcla con el proxy de Biwenger
        # (tasa de aparición de toda la temporada) en vez de fiarse solo de 1-2 partidos.
        weight = matches_rated / (matches_rated + TITULARIDAD_SHRINKAGE_MATCHES)
        blend_base = appearance if appearance is not None else minutes_val_raw
        minutes_val = weight * minutes_val_raw + (1 - weight) * blend_base
    else:
        minutes_val = None

    prediction = sofascore_starters.get(player_id)
    prediction_val = None if prediction is None else (1.0 if prediction else FORWARD_NON_STARTER_VALUE)

    if minutes_val is not None and prediction_val is not None:
        value = REAL_MINUTES_WEIGHT * minutes_val + PREDICTION_WEIGHT * prediction_val
        note = f"{avg_minutes:.0f} min/partido reales (últimos {matches_rated})" + (
            "" if prediction else " · SofaScore no lo da titular el próximo"
        )
    elif minutes_val is not None:
        value = minutes_val
        note = f"{avg_minutes:.0f} min/partido reales (últimos {matches_rated})"
    elif prediction_val is not None:
        value = prediction_val
        note = "titular previsto (SofaScore)" if prediction else "no titular previsto (SofaScore)"
    else:
        value = appearance if appearance is not None else 1.0
        note = None if appearance is None or appearance >= 1.0 else "irregular esta temporada (sin dato SofaScore)"

    if status == "doubt":
        value *= DOUBT_TITULARIDAD_MULT
        note = (note + " · " if note else "") + "duda para el próximo partido (Biwenger)"

    multiplier = TITULARIDAD_FLOOR + (1 - TITULARIDAD_FLOOR) * value
    return multiplier, value, note


def _quality_multiplier(avg_rating, matches_rated, league_avg_rating):
    """
    Ajusta la puntuación según si el jugador rinde mejor o peor de lo habitual (rating real
    de SofaScore). Con pocos partidos puntuados se mezcla (shrinkage bayesiano) con la media
    de la liga, para que 1-2 partidos sueltos no disparen el ajuste.
    """
    if not matches_rated or avg_rating is None or not league_avg_rating:
        return 1.0
    shrunk_rating = (
        matches_rated * avg_rating + QUALITY_SHRINKAGE_MATCHES * league_avg_rating
    ) / (matches_rated + QUALITY_SHRINKAGE_MATCHES)
    multiplier = 1 + QUALITY_ALPHA * (shrunk_rating - league_avg_rating) / league_avg_rating
    return max(QUALITY_BOUNDS[0], min(QUALITY_BOUNDS[1], multiplier))


def _player_home_away_multiplier(is_home, played_home, played_away, points_home, points_away):
    """
    Ajuste casa/fuera propio de CADA jugador (no un +/-5% genérico para todos): compara su
    propio promedio de puntos en casa vs. fuera. Con pocos partidos en esa condición se
    mezcla (shrinkage) con el +/-5% por defecto hasta tener histórico propio suficiente.
    """
    default_ratio = 1 + (DEFAULT_HOME_BONUS if is_home else -DEFAULT_HOME_BONUS)
    played_home = played_home or 0
    played_away = played_away or 0
    total = played_home + played_away
    if total == 0:
        return default_ratio

    overall_avg = ((points_home or 0) + (points_away or 0)) / total
    if overall_avg <= 0:
        return default_ratio

    own_games = played_home if is_home else played_away
    own_points = points_home if is_home else points_away
    own_avg = (own_points / own_games) if own_games else None
    raw_ratio = (own_avg / overall_avg) if own_avg is not None else default_ratio

    # cuanta más experiencia propia en esa condición, más se confía en el ratio propio
    weight = total / (total + HOME_AWAY_SHRINKAGE_GAMES)
    multiplier = weight * raw_ratio + (1 - weight) * default_ratio
    return max(HOME_AWAY_BOUNDS[0], min(HOME_AWAY_BOUNDS[1], multiplier))


def base_score(points_avg_blended, games_played, points_last_season_blended):
    prior_avg = (points_last_season_blended or 0) / SEASON_ROUNDS
    current_avg = points_avg_blended if points_avg_blended is not None else 0
    return (games_played * current_avg + SHRINKAGE_GAMES * prior_avg) / (games_played + SHRINKAGE_GAMES)


def _team_strengths(conn):
    """
    Fuerza de ataque y de defensa de cada equipo, por separado — no una única "fuerza"
    genérica. Ataque = media de points_avg_blended de sus MC+DL (a más puntúan, más
    amenaza ofensiva). Defensa = media de sus PT+DF (a más puntúan, más porterías a cero
    y menos goles encajados, ya que Biwenger premia eso en esas posiciones). Es el proxy
    de base — `_fixture_multiplier` lo mezcla con goles reales de SofaScore cuando hay
    suficientes partidos disputados (ver `_team_goal_stats`).
    """
    rows = conn.execute(
        "SELECT team_id, position, AVG(points_avg_blended) FROM players "
        "WHERE position != 'MI' AND games_played > 0 AND points_avg_blended IS NOT NULL "
        "GROUP BY team_id, position"
    ).fetchall()

    attack_samples, defense_samples = {}, {}
    for team_id, position, avg in rows:
        if avg is None:
            continue
        bucket = attack_samples if position in ("MC", "DL") else defense_samples
        bucket.setdefault(team_id, []).append(avg)

    attack = {tid: sum(vals) / len(vals) for tid, vals in attack_samples.items()}
    defense = {tid: sum(vals) / len(vals) for tid, vals in defense_samples.items()}
    league_attack = sum(attack.values()) / len(attack) if attack else None
    league_defense = sum(defense.values()) / len(defense) if defense else None
    return attack, defense, league_attack, league_defense


def _team_goal_stats(conn):
    """Goles reales marcados/encajados de media por equipo (SofaScore) y la media de la liga."""
    rows = conn.execute(
        "SELECT team_id, goals_scored_avg, goals_conceded_avg, matches_counted FROM sofascore_team_stats"
    ).fetchall()
    goals_by_team = {
        team_id: {"scored": scored, "conceded": conceded, "matches": matches}
        for team_id, scored, conceded, matches in rows
    }
    scored_vals = [g["scored"] for g in goals_by_team.values()]
    conceded_vals = [g["conceded"] for g in goals_by_team.values()]
    league_goals_scored = sum(scored_vals) / len(scored_vals) if scored_vals else None
    league_goals_conceded = sum(conceded_vals) / len(conceded_vals) if conceded_vals else None
    return goals_by_team, league_goals_scored, league_goals_conceded


def _blend_with_shrinkage(proxy_term, real_term, matches):
    """Mezcla el término del proxy de puntos fantasy con el de goles reales, con más peso
    para los goles reales cuantos más partidos hay detrás (shrinkage)."""
    if real_term is None:
        return proxy_term
    if proxy_term is None:
        return real_term
    weight = matches / (matches + REAL_GOALS_SHRINKAGE_MATCHES)
    return weight * real_term + (1 - weight) * proxy_term


def _fixture_multiplier(
    team_id, position, fixtures_by_team, attack_strengths, defense_strengths, league_attack, league_defense,
    goals_by_team, league_goals_scored, league_goals_conceded,
):
    fixture = fixtures_by_team.get(team_id)
    if not fixture:
        return 1.0, None

    opponent_id = fixture["opponent_team_id"]
    opponent_goals = goals_by_team.get(opponent_id)

    if position in ("MC", "DL"):
        # cuanto más floja la DEFENSA rival, más fácil marcar/asistir
        proxy_term = None
        opponent_defense = defense_strengths.get(opponent_id)
        if opponent_defense is not None and league_defense:
            proxy_term = (league_defense - opponent_defense) / league_defense

        real_term = None
        if opponent_goals is not None and league_goals_conceded:
            # el rival encaja MÁS que la media -> defensa floja -> bueno para el atacante
            real_term = (opponent_goals["conceded"] - league_goals_conceded) / league_goals_conceded
    else:
        # PT/DF: cuanto más flojo el ATAQUE rival, más fácil portería a cero
        proxy_term = None
        opponent_attack = attack_strengths.get(opponent_id)
        if opponent_attack is not None and league_attack:
            proxy_term = (league_attack - opponent_attack) / league_attack

        real_term = None
        if opponent_goals is not None and league_goals_scored:
            # el rival marca MENOS que la media -> ataque flojo -> bueno para el defensa/portero
            real_term = (league_goals_scored - opponent_goals["scored"]) / league_goals_scored

    term = _blend_with_shrinkage(proxy_term, real_term, opponent_goals["matches"] if opponent_goals else 0)
    multiplier = 1.0 + (OPPONENT_STRENGTH_ALPHA * term if term is not None else 0.0)
    multiplier = max(MULTIPLIER_BOUNDS[0], min(MULTIPLIER_BOUNDS[1], multiplier))
    return multiplier, fixture


class Scorer:
    """Puntúa a cualquier jugador (de tu plantilla o del mercado) con el mismo criterio."""

    def __init__(self, conn):
        self.attack_strengths, self.defense_strengths, self.league_attack, self.league_defense = _team_strengths(conn)
        self.goals_by_team, self.league_goals_scored, self.league_goals_conceded = _team_goal_stats(conn)
        self.fixtures_by_team = {
            row[0]: {"opponent_team_id": row[1], "is_home": bool(row[2]), "kickoff_at": row[3]}
            for row in conn.execute(
                "SELECT team_id, opponent_team_id, is_home, kickoff_at FROM team_fixtures"
            ).fetchall()
        }
        self.team_names = {row[0]: row[1] for row in conn.execute("SELECT id, name FROM teams").fetchall()}
        self.sofascore_starters = dict(
            conn.execute("SELECT player_id, predicted_starter FROM sofascore_lineups").fetchall()
        )
        self.sofascore_ratings = {
            row[0]: {"avg_rating": row[1], "avg_minutes": row[2], "matches_rated": row[3]}
            for row in conn.execute(
                "SELECT player_id, avg_rating, avg_minutes, matches_rated FROM sofascore_ratings"
            ).fetchall()
        }
        rated = [r["avg_rating"] for r in self.sofascore_ratings.values() if r["avg_rating"] is not None]
        self.league_avg_rating = sum(rated) / len(rated) if rated else None
        self.home_away = {
            row[0]: {"played_home": row[1], "played_away": row[2], "points_home": row[3], "points_away": row[4]}
            for row in conn.execute(
                "SELECT id, played_home, played_away, points_home_blended, points_away_blended FROM players"
            ).fetchall()
        }

    def score(self, player_id, name, position, status, team_id, points_avg_blended, games_played, rounds_available, points_last_season_blended):
        games_played = games_played or 0
        fixture_mult, fixture = _fixture_multiplier(
            team_id, position, self.fixtures_by_team,
            self.attack_strengths, self.defense_strengths, self.league_attack, self.league_defense,
            self.goals_by_team, self.league_goals_scored, self.league_goals_conceded,
        )

        rating_info = self.sofascore_ratings.get(player_id, {})
        avg_rating = rating_info.get("avg_rating")
        avg_minutes = rating_info.get("avg_minutes")
        matches_rated = rating_info.get("matches_rated") or 0

        titularidad_mult, titularidad_value, titularidad_note = _titularidad(
            player_id, self.sofascore_starters, avg_minutes, matches_rated, games_played, rounds_available or 0, status
        )
        quality_mult = _quality_multiplier(avg_rating, matches_rated, self.league_avg_rating)

        ha = self.home_away.get(player_id, {})
        home_away_mult = (
            _player_home_away_multiplier(
                fixture["is_home"], ha.get("played_home"), ha.get("played_away"), ha.get("points_home"), ha.get("points_away")
            )
            if fixture else 1.0
        )

        consistente = titularidad_value >= CONSISTENCY_TITULARIDAD_THRESHOLD
        consistency_mult = 1 + CONSISTENCY_BONUS.get(position, 0.0) if consistente else 1.0

        rival_name = self.team_names.get(fixture["opponent_team_id"], "?") if fixture else None
        raw_score = base_score(points_avg_blended, games_played, points_last_season_blended)
        return {
            "player_id": player_id,
            "name": name,
            "position": position,
            "status": status,
            "rival": (("vs " if fixture and fixture["is_home"] else "@ ") + rival_name) if rival_name else "sin próximo partido",
            "kickoff_at": fixture["kickoff_at"] if fixture else None,
            "games_played": games_played,
            "rounds_available": rounds_available or 0,
            "avg_rating": avg_rating,
            "avg_minutes": avg_minutes,
            "matches_rated": matches_rated,
            "titularidad_value": round(titularidad_value, 2),
            "low_appearance": titularidad_value < GANGA_TITULARIDAD_THRESHOLD,
            "titularidad_note": titularidad_note,
            "consistente": consistente,
            "score": round(raw_score * fixture_mult * home_away_mult * quality_mult * titularidad_mult * consistency_mult, 2),
        }


def _solve_formation(eligible, formation_name, formation_counts):
    """Resuelve el LP para UNA formación exacta (recuento fijo de DF/MC/DL, PT=1)."""
    if len(eligible) < TOTAL_STARTERS:
        return {
            "feasible": False,
            "formation": formation_name,
            "reason": f"Solo hay {len(eligible)} jugadores disponibles (se necesitan {TOTAL_STARTERS}).",
        }

    prob = pulp.LpProblem("lineup", pulp.LpMaximize)
    x = {p["player_id"]: pulp.LpVariable(f"x_{p['player_id']}", cat="Binary") for p in eligible}
    prob += pulp.lpSum(p["score"] * x[p["player_id"]] for p in eligible)
    prob += pulp.lpSum(x.values()) == TOTAL_STARTERS

    pos_vars = {"PT": [x[p["player_id"]] for p in eligible if p["position"] == "PT"]}
    prob += pulp.lpSum(pos_vars["PT"]) == 1
    for pos, count in formation_counts.items():
        pos_vars[pos] = [x[p["player_id"]] for p in eligible if p["position"] == pos]
        prob += pulp.lpSum(pos_vars[pos]) == count

    prob.solve(pulp.PULP_CBC_CMD(msg=0))

    if pulp.LpStatus[prob.status] != "Optimal":
        return {
            "feasible": False,
            "formation": formation_name,
            "reason": f"No tienes jugadores suficientes en las posiciones necesarias para jugar {formation_name}.",
        }

    starters = [p for p in eligible if x[p["player_id"]].value() == 1]
    bench = [p for p in eligible if x[p["player_id"]].value() != 1]

    order = {"PT": 0, "DF": 1, "MC": 2, "DL": 3}
    starters.sort(key=lambda p: order[p["position"]])
    bench.sort(key=lambda p: (order[p["position"]], -p["score"]))

    return {
        "feasible": True,
        "formation": formation_name,
        "starters": starters,
        "bench": bench,
        "total_score": round(sum(p["score"] for p in starters), 2),
    }


def _solve(eligible):
    """
    Prueba las dos formaciones candidatas. Devuelve la de mayor puntuación total como
    resultado principal, pero guarda AMBAS completas (starters/bench incluidos) en
    "all_formations" para poder alternar entre ellas en el dashboard sin recalcular.
    """
    attempts = {name: _solve_formation(eligible, name, counts) for name, counts in CANDIDATE_FORMATIONS.items()}
    feasible_attempts = {name: a for name, a in attempts.items() if a["feasible"]}
    if not feasible_attempts:
        return {
            "feasible": False,
            "reason": " / ".join(f"{a['formation']}: {a['reason']}" for a in attempts.values()),
            "all_formations": attempts,
        }

    best_name = max(feasible_attempts, key=lambda name: feasible_attempts[name]["total_score"])
    best = feasible_attempts[best_name]
    best["all_formations"] = attempts
    best["formation_comparison"] = [
        {"formation": a["formation"], "feasible": a["feasible"], "total_score": a.get("total_score")}
        for a in attempts.values()
    ]
    return best


def _position_shortfall_for(available_pool, formation_counts):
    """Cuánto falta en cada posición para completar ESTA formación en concreto."""
    counts = {"PT": 0, "DF": 0, "MC": 0, "DL": 0}
    for p in available_pool:
        counts[p["position"]] += 1

    full_requirement = {"PT": 1, **formation_counts}
    return {
        pos: needed - counts[pos]
        for pos, needed in full_requirement.items()
        if needed - counts[pos] > 0
    }


def _best_effort_lineup(available_pool, formation_name, formation_counts):
    """
    Cuando ninguna formación es viable: rellena los huecos que sí se pueden cubrir con
    tus mejores disponibles y deja el resto como hueco vacío, para poder dibujar el
    esquema igualmente y ver de un vistazo qué posiciones faltan por cubrir.
    """
    full_requirement = {"PT": 1, **formation_counts}
    by_position = {"PT": [], "DF": [], "MC": [], "DL": []}
    for p in available_pool:
        by_position[p["position"]].append(p)
    for pos in by_position:
        by_position[pos].sort(key=lambda p: -p["score"])

    order = {"PT": 0, "DF": 1, "MC": 2, "DL": 3}
    starters, bench, empty_count = [], [], 0
    for pos in ("PT", "DF", "MC", "DL"):
        need = full_requirement.get(pos, 0)
        group = by_position[pos]
        starters.extend(group[:need])
        bench.extend(group[need:])
        missing = need - len(group[:need])
        starters.extend({"position": pos, "empty": True} for _ in range(missing))
        empty_count += missing

    starters.sort(key=lambda p: order[p["position"]])
    bench.sort(key=lambda p: (order[p["position"]], -p["score"]))
    return {
        "formation": formation_name,
        "starters": starters,
        "bench": bench,
        "empty_count": empty_count,
        "total_score": round(sum(p["score"] for p in starters if not p.get("empty")), 2),
    }


def market_candidates(conn, scorer, user_id, positions=None):
    """Jugadores comprables HOY (en el mercado) que no son ya tuyos, puntuados igual que tu plantilla."""
    latest_market_date = conn.execute("SELECT MAX(snapshot_date) FROM market_listings").fetchone()[0]
    query = """
        SELECT p.id, p.name, p.position, p.status, p.team_id,
               p.points_avg_blended, p.games_played, p.rounds_available, p.points_last_season_blended, m.price
        FROM market_listings m
        JOIN players p ON p.id = m.player_id
        WHERE m.snapshot_date = ?
          AND p.position != 'MI'
          AND p.team_id IS NOT NULL
          AND m.player_id NOT IN (
              SELECT player_id FROM squad_ownership
              WHERE league_user_id = ? AND snapshot_date = (SELECT MAX(snapshot_date) FROM squad_ownership)
          )
    """
    params = [latest_market_date, user_id]
    if positions:
        query += f" AND p.position IN ({','.join('?' * len(positions))})"
        params.extend(positions)

    candidates = []
    for player_id, name, position, status, team_id, pab, gp, ra, pls, price in conn.execute(query, params).fetchall():
        if status in UNAVAILABLE_STATUSES:
            continue
        entry = scorer.score(player_id, name, position, status, team_id, pab, gp, ra, pls)
        entry["price"] = price
        candidates.append(entry)
    return candidates


# Puja máxima recomendada: cuánto tendría sentido ofrecer por un jugador del mercado,
# no solo lo que puedas permitirte. Combina cuatro factores:
#   1. Valor justo: su puntuación convertida a precio usando el rendimiento medio por
#      millón que se está pagando ahora mismo en el mercado (si un jugador rinde el
#      doble que la media al mismo precio, vale más que lo que pide).
#   2. Necesidad de tu equipo: si la posición tiene un hueco real en tu 11, o el
#      candidato mejoraría a tu titular más débil de esa posición, sube lo que
#      deberías estar dispuesto a pagar; si ya tienes algo claramente mejor, baja.
#   3. Si ya es una ganga reconocida (buena relación puntos/precio), un pequeño extra
#      para no dejarla escapar por regatear de más.
#   4. Presión de puja de la liga: si de media los demás managers tienen más saldo
#      disponible que al empezar la temporada, pueden permitirse pujarte fuerte por los
#      buenos jugadores, así que los márgenes de arriba (necesidad/ganga) se estiran un
#      poco; si están escasos de saldo hay menos competencia real y se pueden ajustar.
# La oferta nunca baja del precio de mercado (es el mínimo real para pujar), y nunca
# sube por encima de tu puja máxima permitida (tu saldo real) salvo que ya no puedas
# permitirte ni el propio precio de mercado.
BID_NEED_GAP = 1.30  # no tienes titular real en esa posición ahora mismo
BID_NEED_UPGRADE = 1.15  # mejoraría a tu titular más débil de esa posición
BID_NEED_DEPTH = 1.0  # rendimiento similar al que ya tienes
BID_NEED_LOW = 0.85  # ya tienes a alguien claramente mejor en esa posición
BID_GANGA_BONUS = 1.1
COMPETITION_BOUNDS = (0.9, 1.15)  # cuánto puede estirar/ajustar la presión de puja los márgenes de arriba


def market_average_ratio(scored_entries):
    """Puntos por millón medios del mercado actual — referencia de "precio justo"."""
    ratios = [e["score"] / e["price"] * 1_000_000 for e in scored_entries if e.get("price") and e["score"] > 0]
    return sum(ratios) / len(ratios) if ratios else None


def weakest_score_by_position(lineup_result):
    """
    A partir del resultado de optimize_lineup(): puntuación de tu titular más débil de
    cada posición, y qué posiciones tienen un hueco real (sin titular) ahora mismo.
    """
    if not lineup_result:
        return {}, set()
    starters = lineup_result["starters"] if lineup_result.get("feasible") else lineup_result["best_effort"]["starters"]

    weakest, gaps = {}, set()
    for p in starters:
        if p.get("empty"):
            gaps.add(p["position"])
            continue
        pos = p["position"]
        if pos not in weakest or p["score"] < weakest[pos]:
            weakest[pos] = p["score"]
    return weakest, gaps


def competition_multiplier(rival_balance_info):
    """
    Cuánto saldo disponible tienen de media los rivales respecto a como empezaron la
    temporada: por encima de 1 significa que están en condiciones de pujar fuerte
    (conviene ser algo más agresivo), por debajo que hay menos competencia real.
    """
    if not rival_balance_info:
        return 1.0
    baseline = rival_balance_info.get("estimated_starting_balance")
    rivals = [m["estimated_balance"] for m in rival_balance_info.get("managers", []) if not m["is_self"]]
    if not baseline or not rivals:
        return 1.0
    ratio = (sum(rivals) / len(rivals)) / baseline
    return max(COMPETITION_BOUNDS[0], min(COMPETITION_BOUNDS[1], ratio))


def recommended_max_bid(
    score, position, price, weakest_by_position, gap_positions, is_ganga, avg_market_ratio, maximum_bid,
    competition_mult=1.0,
):
    fair_value = (score / avg_market_ratio * 1_000_000) if avg_market_ratio else price

    if position in gap_positions or position not in weakest_by_position:
        need_mult = BID_NEED_GAP * competition_mult
    else:
        weakest = weakest_by_position[position]
        if score > weakest:
            need_mult = BID_NEED_UPGRADE * competition_mult
        elif score > weakest * 0.9:
            need_mult = BID_NEED_DEPTH
        else:
            need_mult = BID_NEED_LOW

    ganga_mult = (BID_GANGA_BONUS * competition_mult) if is_ganga else 1.0
    recommended = max(fair_value * need_mult * ganga_mult, price)  # nunca por debajo del precio de mercado
    if maximum_bid:
        recommended = min(recommended, max(maximum_bid, price))
    return round(recommended)


def optimize_lineup(conn, user_id):
    cur = conn.cursor()

    latest_market_date = cur.execute("SELECT MAX(snapshot_date) FROM market_listings").fetchone()[0]
    listed_for_sale = {
        row[0]
        for row in cur.execute(
            "SELECT player_id FROM market_listings WHERE snapshot_date = ? AND seller_user_id = ?",
            (latest_market_date, user_id),
        ).fetchall()
    }
    maximum_bid_row = cur.execute(
        "SELECT maximum_bid FROM balances WHERE league_user_id = ? ORDER BY snapshot_date DESC LIMIT 1", (user_id,)
    ).fetchone()
    maximum_bid = maximum_bid_row[0] if maximum_bid_row else 0

    scorer = Scorer(conn)

    squad = cur.execute(
        """
        SELECT p.id, p.name, p.position, p.status, p.team_id,
               p.points_avg_blended, p.games_played, p.rounds_available, p.points_last_season_blended
        FROM squad_ownership s
        JOIN players p ON p.id = s.player_id
        WHERE s.league_user_id = ? AND s.snapshot_date = (SELECT MAX(snapshot_date) FROM squad_ownership)
          AND p.team_id IS NOT NULL
        """,
        (user_id,),
    ).fetchall()

    available = []  # posición y estado válidos (jugables), estén o no en venta
    excluded = []  # lesionados/sancionados/descartados/entrenadores: nunca jugables
    for player_id, name, position, status, team_id, points_avg_blended, games_played, rounds_available, points_last_season_blended in squad:
        entry = scorer.score(
            player_id, name, position, status, team_id,
            points_avg_blended, games_played, rounds_available, points_last_season_blended,
        )
        entry["listed_for_sale"] = player_id in listed_for_sale

        if position not in VALID_POSITIONS or status in UNAVAILABLE_STATUSES:
            entry["reason"] = "no disponible"
            excluded.append(entry)
        else:
            available.append(entry)

    real_eligible = [p for p in available if not p["listed_for_sale"]]
    result = _solve(real_eligible)
    listed_entries = [p for p in available if p["listed_for_sale"]]
    for p in listed_entries:
        p["reason"] = "en venta"
    result["excluded"] = excluded + listed_entries

    if not result["feasible"]:
        result["market_fill_suggestions_by_formation"] = {}
        for name, counts in CANDIDATE_FORMATIONS.items():
            shortfall = _position_shortfall_for(real_eligible, counts)
            suggestions = {}
            for pos, gap in shortfall.items():
                candidates = [
                    c for c in market_candidates(conn, scorer, user_id, positions=[pos])
                    if c["price"] <= maximum_bid and c["titularidad_value"] >= GANGA_TITULARIDAD_THRESHOLD
                ]
                candidates.sort(key=lambda c: c["score"], reverse=True)
                suggestions[pos] = {"faltan": gap, "candidatos": candidates[:5]}
            result["market_fill_suggestions_by_formation"][name] = suggestions

        result["best_effort_options"] = {
            name: _best_effort_lineup(real_eligible, name, counts) for name, counts in CANDIDATE_FORMATIONS.items()
        }
        result["best_effort"] = min(result["best_effort_options"].values(), key=lambda a: a["empty_count"])
        return result

    result["sale_warnings"] = []
    if any(p["listed_for_sale"] for p in available):
        hypothetical = _solve(available)  # incluye también a los que están en venta
        if hypothetical["feasible"]:
            would_start_ids = {p["player_id"] for p in hypothetical["starters"]}
            result["sale_warnings"] = [
                p for p in available if p["listed_for_sale"] and p["player_id"] in would_start_ids
            ]

    # Posibles fichajes: alguien del mercado de hoy que mejore a tu titular más débil de su
    # posición y cuyo precio quepa en tu puja máxima permitida.
    result["market_upgrades"] = []
    positions_in_lineup = {p["position"] for p in result["starters"]}
    market_pool = market_candidates(conn, scorer, user_id, positions=list(positions_in_lineup))
    for pos in positions_in_lineup:
        starters_in_pos = [p for p in result["starters"] if p["position"] == pos]
        weakest = min(starters_in_pos, key=lambda p: p["score"])
        pos_candidates = [
            c for c in market_pool
            if c["position"] == pos and c["price"] <= maximum_bid and c["titularidad_value"] >= GANGA_TITULARIDAD_THRESHOLD
        ]
        better = [c for c in pos_candidates if c["score"] > weakest["score"]]
        if not better:
            continue
        best = max(better, key=lambda c: c["score"])
        result["market_upgrades"].append(
            {
                "position": pos,
                "out": weakest["name"],
                "out_score": weakest["score"],
                "in": best["name"],
                "in_score": best["score"],
                "price": best["price"],
                "mejora": round(best["score"] - weakest["score"], 2),
            }
        )
    result["market_upgrades"].sort(key=lambda u: -u["mejora"])

    return result
