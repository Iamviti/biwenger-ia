"""
Inteligencia de mercado: especulación por tendencia de precio, y estimación del saldo
de los rivales (Biwenger solo expone el saldo del propio usuario).
"""


def price_trends(conn, top_n=15):
    """
    Candidatos a fichaje especulativo: jugadores comprables (libres o en el mercado)
    cuyo precio está subiendo. Usa el histórico diario de precios cuando ya hay más de
    un día acumulado; con un solo día disponible (recién empezado a usar la app) cae al
    incremento diario que ya calcula el propio Biwenger.
    """
    cur = conn.cursor()

    history_rows = cur.execute(
        "SELECT player_id, snapshot_date, price FROM price_history ORDER BY player_id, snapshot_date"
    ).fetchall()
    history_by_player = {}
    for player_id, snapshot_date, price in history_rows:
        history_by_player.setdefault(player_id, []).append((snapshot_date, price))

    latest_squad_date = cur.execute("SELECT MAX(snapshot_date) FROM squad_ownership").fetchone()[0]
    owned_by_others = {
        row[0]
        for row in cur.execute(
            "SELECT player_id FROM squad_ownership WHERE snapshot_date = ?", (latest_squad_date,)
        ).fetchall()
    }
    latest_market_date = cur.execute("SELECT MAX(snapshot_date) FROM market_listings").fetchone()[0]
    listed_ids = {
        row[0]
        for row in cur.execute(
            "SELECT player_id FROM market_listings WHERE snapshot_date = ?", (latest_market_date,)
        ).fetchall()
    }

    players = cur.execute(
        "SELECT id, name, position, price, price_increment_day, status FROM players "
        "WHERE position != 'MI' AND price > 0 AND team_id IS NOT NULL"
    ).fetchall()

    candidates = []
    for player_id, name, position, price, price_increment_day, status in players:
        if status in ("injured", "sanctioned", "discarded"):
            continue
        buyable = player_id not in owned_by_others or player_id in listed_ids
        if not buyable:
            continue

        history = history_by_player.get(player_id, [])
        if len(history) >= 2:
            first_price = history[0][1]
            trend_pct = ((price - first_price) / first_price * 100) if first_price else 0
            days_tracked = len(history)
        else:
            trend_pct = (price_increment_day / price * 100) if price else 0
            days_tracked = 1

        candidates.append(
            {
                "player_id": player_id,
                "name": name,
                "position": position,
                "price": price,
                "price_increment_day": price_increment_day,
                "trend_pct": round(trend_pct, 2),
                "days_tracked": days_tracked,
            }
        )

    candidates.sort(key=lambda c: c["trend_pct"], reverse=True)
    return candidates[:top_n]


def estimate_rival_balances(conn, own_user_id):
    """
    Estima el saldo de cada manager de la liga a partir del histórico de movimientos
    (compras/ventas leídas del board) calibrado contra tu propio saldo real, asumiendo
    que todos empezaron con el mismo presupuesto inicial (configuración habitual de
    Biwenger salvo que la liga diga lo contrario). Es una estimación, no un dato exacto:
    no cubre bonificaciones puntuales ni ajustes manuales que no dejen rastro en el board.
    """
    cur = conn.cursor()
    own_user_id = int(own_user_id)

    own_balance_row = cur.execute(
        "SELECT balance FROM balances WHERE league_user_id = ? ORDER BY snapshot_date DESC LIMIT 1",
        (own_user_id,),
    ).fetchone()
    if not own_balance_row or own_balance_row[0] is None:
        return None
    own_balance = own_balance_row[0]

    net_movements = dict(cur.execute("SELECT league_user_id, net_movement FROM balance_ledger").fetchall())
    own_net_movement = net_movements.get(own_user_id, 0)
    estimated_starting_balance = own_balance - own_net_movement

    latest_squad_date = cur.execute("SELECT MAX(snapshot_date) FROM squad_ownership").fetchone()[0]
    squad_values = dict(
        cur.execute(
            """
            SELECT s.league_user_id, SUM(p.price)
            FROM squad_ownership s JOIN players p ON p.id = s.player_id
            WHERE s.snapshot_date = ?
            GROUP BY s.league_user_id
            """,
            (latest_squad_date,),
        ).fetchall()
    )

    users = cur.execute("SELECT id, name FROM league_users").fetchall()
    results = []
    for user_id, name in users:
        net = net_movements.get(user_id, 0)
        results.append(
            {
                "league_user_id": user_id,
                "name": name,
                "estimated_balance": estimated_starting_balance + net,
                "squad_value": squad_values.get(user_id, 0),
                "is_self": user_id == own_user_id,
            }
        )

    results.sort(key=lambda r: r["estimated_balance"], reverse=True)
    return {"estimated_starting_balance": estimated_starting_balance, "managers": results}
