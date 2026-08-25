import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from biwenger_client.client import BiwengerClient
from config import BIWENGER_LEAGUE_ID, BIWENGER_TOKEN, BIWENGER_USER_ID
from db.database import (
    init_db,
    get_connection,
    insert_balance_snapshot,
    insert_market_snapshot,
    insert_price_snapshot,
    insert_squad_snapshot,
    replace_balance_ledger,
    replace_sofascore_lineups,
    replace_sofascore_ratings,
    replace_sofascore_team_stats,
    upsert_current_round,
    upsert_league_users,
    upsert_player_purchases,
    upsert_players,
    upsert_team_fixtures,
    upsert_teams,
)
from sofascore_client.sync import sync_player_ratings, sync_predicted_lineups, sync_team_goal_stats

BLENDED_SCORE_ID = 5  # "Media AS y SofaScore" en Biwenger


def main(log=print):
    """
    `log` recibe un mensaje de texto por cada paso — por defecto los imprime en la
    terminal, pero el botón "Actualizar datos" del dashboard le pasa una función que
    los va mostrando en pantalla (ver `app/views/home.py`).
    """
    if not (BIWENGER_TOKEN and BIWENGER_LEAGUE_ID and BIWENGER_USER_ID):
        raise SystemExit(
            "Faltan credenciales. Rellena BIWENGER_TOKEN, BIWENGER_LEAGUE_ID y BIWENGER_USER_ID en .env"
        )

    init_db()

    client = BiwengerClient(BIWENGER_TOKEN, BIWENGER_LEAGUE_ID, BIWENGER_USER_ID)
    today = date.today().isoformat()

    log("Descargando master de jugadores...")
    teams, players, current_round, fixtures = client.get_all_players()

    log("Descargando puntuación combinada AS + SofaScore...")
    _, blended_players, _, _ = client.get_all_players(score=BLENDED_SCORE_ID)
    blended_by_id = {p["id"]: p for p in blended_players}
    for player in players:
        blended = blended_by_id.get(player["id"])
        if blended:
            player["points_total_blended"] = blended["points_total"]
            player["points_avg_blended"] = blended["points_avg"]
            player["points_last_season_blended"] = blended["points_last_season"]
            player["points_home_blended"] = blended["points_home"]
            player["points_away_blended"] = blended["points_away"]

    log("Descargando mercado...")
    market_listings, market_status = client.get_market()

    log("Descargando plantillas de la liga...")
    league_users, ownerships = client.get_league_squads()

    log("Descargando saldos...")
    balances = client.get_balances(own_maximum_bid=market_status["maximum_bid"])

    log("Descargando historial de fichajes (precio de compra + saldos)...")
    board_entries = client.get_board_entries()
    purchases = client.get_purchase_history(board_entries)
    ledger_movements = client.get_transaction_ledger(board_entries)
    net_movements_by_user = {}
    for m in ledger_movements:
        net_movements_by_user[m["league_user_id"]] = net_movements_by_user.get(m["league_user_id"], 0) + m["delta"]

    log("Descargando alineaciones previstas de SofaScore...")
    try:
        sofascore_predictions = sync_predicted_lineups(teams, players)
    except Exception as e:
        log(f"Aviso: no se pudo sincronizar con SofaScore ({e}). Se sigue sin ese dato.")
        sofascore_predictions = []

    log("Descargando puntuaciones y minutos reales de SofaScore (puede tardar un poco)...")
    try:
        sofascore_ratings = sync_player_ratings(teams, players)
    except Exception as e:
        log(f"Aviso: no se pudieron sincronizar las puntuaciones de SofaScore ({e}). Se sigue sin ese dato.")
        sofascore_ratings = []

    log("Descargando goles reales marcados/encajados de SofaScore...")
    try:
        sofascore_team_stats = sync_team_goal_stats(teams)
    except Exception as e:
        log(f"Aviso: no se pudieron sincronizar los goles reales de SofaScore ({e}). Se sigue sin ese dato.")
        sofascore_team_stats = []

    with get_connection() as conn:
        upsert_teams(conn, teams)
        upsert_players(conn, players)
        insert_price_snapshot(conn, today, players)
        upsert_current_round(conn, current_round)
        upsert_team_fixtures(conn, fixtures)
        upsert_league_users(conn, league_users)
        insert_squad_snapshot(conn, today, ownerships)
        insert_market_snapshot(conn, today, market_listings)
        insert_balance_snapshot(conn, today, balances)
        upsert_player_purchases(conn, purchases)
        replace_balance_ledger(conn, net_movements_by_user, datetime.now(timezone.utc).isoformat())
        replace_sofascore_lineups(conn, sofascore_predictions)
        replace_sofascore_ratings(conn, sofascore_ratings)
        replace_sofascore_team_stats(conn, sofascore_team_stats)

    log(
        f"OK — {len(players)} jugadores, {len(market_listings)} en mercado, "
        f"{len(league_users)} managers, {len(sofascore_predictions)} alineaciones SofaScore, "
        f"{len(sofascore_ratings)} puntuaciones SofaScore, {len(sofascore_team_stats)} equipos con goles "
        f"reales, snapshot {today}"
    )


if __name__ == "__main__":
    main()
