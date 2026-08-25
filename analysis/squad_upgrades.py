"""
Posibles sustituciones para TODA tu plantilla (no solo los titulares del 11 ideal):
para cada jugador que tienes, busca candidatos comprables hoy en el mercado que sean
mejores en dos cosas a la vez — rendimiento (misma puntuación que el resto de la app,
que ya combina puntos fantasy, calidad real de juego y titularidad real de SofaScore)
Y relación rendimiento/precio — para no sugerir a alguien simplemente más caro que
puntúa un poco más. Solo se proponen candidatos con titularidad real por encima de
GANGA_TITULARIDAD_THRESHOLD: no tiene sentido fichar a alguien que no va a jugar.

No se consideran los jugadores que ya tienes puestos en venta: si te vas a
desprender de ellos de todas formas, sugerir "véndelo y ficha a X" no aporta nada.
"""

from analysis.lineup_optimizer import GANGA_TITULARIDAD_THRESHOLD, Scorer, market_candidates


def _ratio(score, price):
    return round(score / price * 1_000_000, 3) if price else 0.0


def find_squad_upgrades(conn, user_id):
    scorer = Scorer(conn)

    maximum_bid_row = conn.execute(
        "SELECT maximum_bid FROM balances WHERE league_user_id = ? ORDER BY snapshot_date DESC LIMIT 1", (user_id,)
    ).fetchone()
    maximum_bid = maximum_bid_row[0] if maximum_bid_row else 0

    latest_market_date = conn.execute("SELECT MAX(snapshot_date) FROM market_listings").fetchone()[0]
    listed_for_sale = {
        row[0]
        for row in conn.execute(
            "SELECT player_id FROM market_listings WHERE snapshot_date = ? AND seller_user_id = ?",
            (latest_market_date, user_id),
        ).fetchall()
    }

    squad_rows = conn.execute(
        """
        SELECT p.id, p.name, p.position, p.status, p.team_id, p.price,
               p.points_avg_blended, p.games_played, p.rounds_available, p.points_last_season_blended
        FROM squad_ownership s
        JOIN players p ON p.id = s.player_id
        WHERE s.league_user_id = ? AND s.snapshot_date = (SELECT MAX(snapshot_date) FROM squad_ownership)
          AND p.team_id IS NOT NULL
        """,
        (user_id,),
    ).fetchall()

    squad_entries = []
    for player_id, name, position, status, team_id, price, pab, gp, ra, pls in squad_rows:
        if position not in ("PT", "DF", "MC", "DL") or player_id in listed_for_sale:
            continue
        entry = scorer.score(player_id, name, position, status, team_id, pab, gp, ra, pls)
        entry["price"] = price
        entry["ratio"] = _ratio(entry["score"], price)
        squad_entries.append(entry)

    if not squad_entries:
        return []

    # Solo se compara al portero titular (mejor puntuado): el suplente no cuenta como
    # "jugador con bajo rendimiento" a sustituir, es un rol distinto en la plantilla.
    goalkeepers = [e for e in squad_entries if e["position"] == "PT"]
    if len(goalkeepers) > 1:
        backups = sorted(goalkeepers, key=lambda e: -e["score"])[1:]
        backup_ids = {e["player_id"] for e in backups}
        squad_entries = [e for e in squad_entries if e["player_id"] not in backup_ids]

    positions = list({e["position"] for e in squad_entries})
    pool = market_candidates(conn, scorer, user_id, positions=positions)
    for c in pool:
        c["ratio"] = _ratio(c["score"], c["price"])

    suggestions = []
    for squad_player in squad_entries:
        candidates = [
            c for c in pool
            if c["position"] == squad_player["position"]
            and c["price"] <= maximum_bid
            and c["score"] > squad_player["score"]
            and c["ratio"] > squad_player["ratio"]
            and c["titularidad_value"] >= GANGA_TITULARIDAD_THRESHOLD
        ]
        if not candidates:
            continue
        best = max(candidates, key=lambda c: c["score"])
        mejora_puntos_pct = (
            round((best["score"] - squad_player["score"]) / squad_player["score"] * 100)
            if squad_player["score"] > 0 else None
        )
        mejora_ratio_pct = (
            round((best["ratio"] - squad_player["ratio"]) / squad_player["ratio"] * 100)
            if squad_player["ratio"] > 0 else None
        )
        suggestions.append(
            {
                "position": squad_player["position"],
                "out": squad_player["name"],
                "out_score": squad_player["score"],
                "out_ratio": squad_player["ratio"],
                "in": best["name"],
                "in_score": best["score"],
                "in_ratio": best["ratio"],
                "price": best["price"],
                "mejora_puntos": round(best["score"] - squad_player["score"], 2),
                "mejora_puntos_pct": mejora_puntos_pct,
                "mejora_ratio": round(best["ratio"] - squad_player["ratio"], 2),
                "mejora_ratio_pct": mejora_ratio_pct,
            }
        )

    suggestions.sort(key=lambda s: -s["mejora_puntos"])
    return suggestions
