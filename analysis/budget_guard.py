"""
Aviso de riesgo de saldo negativo: compara mis pujas activas contra mi saldo,
teniendo en cuenta el saldo futuro que entraría si se vendieran los jugadores
que ya tengo listados en el mercado. Si aun así queda un déficit, propone a
quién más vender de la plantilla (peor relación rendimiento/precio primero,
con la misma puntuación que el resto de la app) antes de que termine la
jornada activa.
"""

from analysis.lineup_optimizer import Scorer


def evaluate_budget_risk(conn, user_id):
    cur = conn.cursor()

    balance_row = cur.execute(
        "SELECT balance, maximum_bid FROM balances WHERE league_user_id = ? "
        "ORDER BY snapshot_date DESC LIMIT 1",
        (user_id,),
    ).fetchone()
    if balance_row is None:
        return None
    balance, maximum_bid = balance_row

    latest_market_date = cur.execute("SELECT MAX(snapshot_date) FROM market_listings").fetchone()[0]

    committed_bids = cur.execute(
        "SELECT COALESCE(SUM(my_bid_amount), 0) FROM market_listings "
        "WHERE snapshot_date = ? AND my_bid_amount IS NOT NULL",
        (latest_market_date,),
    ).fetchone()[0]

    own_listings = cur.execute(
        "SELECT player_id, price FROM market_listings WHERE snapshot_date = ? AND seller_user_id = ?",
        (latest_market_date, user_id),
    ).fetchall()
    pending_own_sales_total = sum(price for _, price in own_listings)
    already_listed_player_ids = {player_id for player_id, _ in own_listings}

    round_row = cur.execute("SELECT name, ends_at FROM current_round WHERE id = 1").fetchone()
    round_name, round_ends_at = round_row if round_row else (None, None)

    projected_balance = balance + pending_own_sales_total
    deficit_now = committed_bids - balance
    deficit_after_listed_sales = committed_bids - projected_balance

    result = {
        "balance": balance,
        "maximum_bid": maximum_bid,
        "committed_bids": committed_bids,
        "pending_own_sales_total": pending_own_sales_total,
        "projected_balance": projected_balance,
        "deficit_now": max(0, deficit_now),
        "deficit_after_listed_sales": max(0, deficit_after_listed_sales),
        "round_name": round_name,
        "round_ends_at": round_ends_at,
        "sale_suggestions": [],
    }

    # Si mis ventas ya listadas cubren el déficit, no hace falta vender nada más.
    if deficit_after_listed_sales <= 0:
        return result

    scorer = Scorer(conn)
    latest_squad_date = cur.execute("SELECT MAX(snapshot_date) FROM squad_ownership").fetchone()[0]
    squad = cur.execute(
        """
        SELECT p.id, p.name, p.position, p.status, p.team_id, p.price,
               p.points_avg_blended, p.games_played, p.rounds_available, p.points_last_season_blended
        FROM squad_ownership s
        JOIN players p ON p.id = s.player_id
        WHERE s.snapshot_date = ? AND s.league_user_id = ? AND p.team_id IS NOT NULL
        """,
        (latest_squad_date, user_id),
    ).fetchall()

    candidates = []
    for player_id, name, position, status, team_id, price, pab, gp, ra, pls in squad:
        if player_id in already_listed_player_ids:
            continue  # ya está en venta, su importe ya cuenta en pending_own_sales_total
        entry = scorer.score(player_id, name, position, status, team_id, pab, gp, ra, pls)
        price = price or 0
        ratio = (entry["score"] / price) if price > 0 else 0
        candidates.append(
            {
                "player_id": player_id,
                "name": name,
                "price": price,
                "score": entry["score"],
                "ratio": ratio,
            }
        )
    candidates.sort(key=lambda c: c["ratio"])

    running_total = 0
    for candidate in candidates:
        if running_total >= deficit_after_listed_sales:
            break
        running_total += candidate["price"]
        result["sale_suggestions"].append({**candidate, "cumulative_total": running_total})

    return result
