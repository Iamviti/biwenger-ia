"""
Buscador de gangas libres: cruza el master de todos los jugadores de la competición
con las plantillas de la liga para encontrar jugadores libres (que nadie tiene) con
mejor relación rendimiento/precio.

Usa el mismo `Scorer` que el 11 ideal y las sustituciones de plantilla (puntos fantasy
+ calidad real de SofaScore + ajuste por rival), para que "ganga" signifique lo mismo
en toda la aplicación. Solo se consideran titulares reales (titularidad_value por
encima de GANGA_TITULARIDAD_THRESHOLD — ver `lineup_optimizer.py` para la jerarquía de
fiabilidad: minutos reales de SofaScore > minutos reales + próximo partido previsto >
proxy de partidos jugados en Biwenger cuando no hay ningún dato de SofaScore).
"""

from analysis.lineup_optimizer import GANGA_TITULARIDAD_THRESHOLD, Scorer, UNAVAILABLE_STATUSES


def find_bargains(conn, top_n=20, position=None, max_price=None, only_free_agents=True):
    """
    `only_free_agents=False` valora a TODOS los jugadores (estén libres o en alguna
    plantilla) — útil para juzgar si un jugador concreto del mercado (que puede ser de
    un rival puesto en venta) es una ganga en términos absolutos, no solo entre libres.
    """
    scorer = Scorer(conn)
    cur = conn.cursor()

    query = """
        SELECT p.id, p.name, p.position, p.status, p.team_id, t.name, p.price,
               p.points_avg_blended, p.games_played, p.rounds_available, p.points_last_season_blended
        FROM players p
        LEFT JOIN teams t ON t.id = p.team_id
        WHERE p.position != 'MI'
          AND p.price > 0
          AND p.team_id IS NOT NULL
    """
    if only_free_agents:
        query += """
          AND p.id NOT IN (
              SELECT player_id FROM squad_ownership
              WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM squad_ownership)
          )
        """
    params = []
    if position:
        query += " AND p.position = ?"
        params.append(position)
    if max_price:
        query += " AND p.price <= ?"
        params.append(max_price)

    rows = cur.execute(query, params).fetchall()

    bargains = []
    for player_id, name, pos, status, team_id, team_name, price, pab, games_played, rounds_available, pls in rows:
        if status in UNAVAILABLE_STATUSES:
            continue

        entry = scorer.score(player_id, name, pos, status, team_id, pab, games_played, rounds_available, pls)
        if entry["titularidad_value"] < GANGA_TITULARIDAD_THRESHOLD:
            continue

        entry["team"] = team_name
        entry["price"] = price
        entry["ratio"] = round(entry["score"] / price * 1_000_000, 3) if price else 0.0
        bargains.append(entry)

    bargains.sort(key=lambda b: b["score"], reverse=True)
    return bargains[:top_n]
