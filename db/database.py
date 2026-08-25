import sqlite3
from contextlib import contextmanager

from config import DB_PATH, SCHEMA_PATH


@contextmanager
def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _ensure_columns(conn, table, columns):
    """Migra bases de datos ya existentes: añade columnas nuevas sin tocar sus datos."""
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    for name, coltype in columns:
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {coltype}")


def init_db():
    with get_connection() as conn:
        conn.executescript(SCHEMA_PATH.read_text())
        _ensure_columns(
            conn, "players",
            [
                ("status_info", "TEXT"),
                ("played_home", "INTEGER"),
                ("played_away", "INTEGER"),
                ("points_home_blended", "INTEGER"),
                ("points_away_blended", "INTEGER"),
            ],
        )


def upsert_teams(conn, teams):
    conn.executemany(
        "INSERT INTO teams (id, name) VALUES (?, ?) "
        "ON CONFLICT(id) DO UPDATE SET name = excluded.name",
        [(t["id"], t["name"]) for t in teams],
    )


def upsert_players(conn, players):
    conn.executemany(
        """
        INSERT INTO players
            (id, name, team_id, shirt_number, position, status, status_info, points_total, points_avg,
             points_total_blended, points_avg_blended, games_played, rounds_available,
             points_last_season, points_last_season_blended, played_home, played_away,
             points_home_blended, points_away_blended, price, price_increment_day, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            name = excluded.name,
            team_id = excluded.team_id,
            shirt_number = excluded.shirt_number,
            position = excluded.position,
            status = excluded.status,
            status_info = excluded.status_info,
            points_total = excluded.points_total,
            points_avg = excluded.points_avg,
            points_total_blended = excluded.points_total_blended,
            points_avg_blended = excluded.points_avg_blended,
            games_played = excluded.games_played,
            rounds_available = excluded.rounds_available,
            points_last_season = excluded.points_last_season,
            points_last_season_blended = excluded.points_last_season_blended,
            played_home = excluded.played_home,
            played_away = excluded.played_away,
            points_home_blended = excluded.points_home_blended,
            points_away_blended = excluded.points_away_blended,
            price = excluded.price,
            price_increment_day = excluded.price_increment_day,
            updated_at = excluded.updated_at
        """,
        [
            (
                p["id"], p["name"], p["team_id"], p.get("shirt_number"), p["position"], p["status"],
                p.get("status_info"), p["points_total"], p["points_avg"], p.get("points_total_blended"),
                p.get("points_avg_blended"), p["games_played"], p["rounds_available"], p["points_last_season"],
                p.get("points_last_season_blended"), p.get("played_home"), p.get("played_away"),
                p.get("points_home_blended"), p.get("points_away_blended"),
                p["price"], p["price_increment_day"], p["updated_at"],
            )
            for p in players
        ],
    )


def upsert_team_fixtures(conn, fixtures):
    conn.executemany(
        "INSERT INTO team_fixtures (team_id, opponent_team_id, is_home, kickoff_at, round_id) "
        "VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(team_id) DO UPDATE SET "
        "opponent_team_id = excluded.opponent_team_id, is_home = excluded.is_home, "
        "kickoff_at = excluded.kickoff_at, round_id = excluded.round_id",
        [(f["team_id"], f["opponent_team_id"], int(f["is_home"]), f["kickoff_at"], f["round_id"]) for f in fixtures],
    )


def upsert_player_purchases(conn, purchases):
    conn.executemany(
        "INSERT INTO player_purchases (player_id, league_user_id, amount, purchased_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(player_id) DO UPDATE SET "
        "league_user_id = excluded.league_user_id, amount = excluded.amount, purchased_at = excluded.purchased_at "
        "WHERE excluded.purchased_at > player_purchases.purchased_at",
        [(p["player_id"], p["league_user_id"], p["amount"], p["purchased_at"]) for p in purchases],
    )


def replace_balance_ledger(conn, net_movements_by_user, updated_at):
    """`net_movements_by_user`: {league_user_id: net_movement}."""
    conn.execute("DELETE FROM balance_ledger")
    conn.executemany(
        "INSERT INTO balance_ledger (league_user_id, net_movement, updated_at) VALUES (?, ?, ?)",
        [(user_id, net, updated_at) for user_id, net in net_movements_by_user.items()],
    )


def replace_sofascore_ratings(conn, ratings):
    """`ratings`: [{player_id, avg_rating, avg_minutes, matches_rated, updated_at}]."""
    conn.execute("DELETE FROM sofascore_ratings")
    conn.executemany(
        "INSERT INTO sofascore_ratings (player_id, avg_rating, avg_minutes, matches_rated, updated_at) "
        "VALUES (?, ?, ?, ?, ?)",
        [(r["player_id"], r["avg_rating"], r["avg_minutes"], r["matches_rated"], r["updated_at"]) for r in ratings],
    )


def replace_sofascore_team_stats(conn, stats):
    """`stats`: [{team_id, goals_scored_avg, goals_conceded_avg, matches_counted, updated_at}]."""
    conn.execute("DELETE FROM sofascore_team_stats")
    conn.executemany(
        "INSERT INTO sofascore_team_stats (team_id, goals_scored_avg, goals_conceded_avg, matches_counted, updated_at) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            (s["team_id"], s["goals_scored_avg"], s["goals_conceded_avg"], s["matches_counted"], s["updated_at"])
            for s in stats
        ],
    )


def replace_sofascore_lineups(conn, predictions):
    """`predictions`: [{player_id, predicted_starter, confirmed, event_id, updated_at}]."""
    conn.execute("DELETE FROM sofascore_lineups")
    conn.executemany(
        "INSERT INTO sofascore_lineups (player_id, predicted_starter, confirmed, event_id, updated_at) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            (p["player_id"], int(p["predicted_starter"]), int(p["confirmed"]), p["event_id"], p["updated_at"])
            for p in predictions
        ],
    )


def insert_price_snapshot(conn, snapshot_date, players):
    conn.executemany(
        "INSERT OR REPLACE INTO price_history (player_id, snapshot_date, price) VALUES (?, ?, ?)",
        [(p["id"], snapshot_date, p["price"]) for p in players],
    )


def upsert_current_round(conn, current_round):
    if not current_round:
        return
    conn.execute(
        "INSERT INTO current_round (id, round_id, name, ends_at) VALUES (1, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET round_id = excluded.round_id, name = excluded.name, "
        "ends_at = excluded.ends_at",
        (current_round["round_id"], current_round["name"], current_round["ends_at"]),
    )


def upsert_league_users(conn, users):
    conn.executemany(
        "INSERT INTO league_users (id, name) VALUES (?, ?) "
        "ON CONFLICT(id) DO UPDATE SET name = excluded.name",
        [(u["id"], u["name"]) for u in users],
    )


def insert_squad_snapshot(conn, snapshot_date, ownerships):
    conn.executemany(
        "INSERT OR REPLACE INTO squad_ownership (league_user_id, player_id, purchase_price, snapshot_date) "
        "VALUES (?, ?, ?, ?)",
        [(o["league_user_id"], o["player_id"], o["purchase_price"], snapshot_date) for o in ownerships],
    )


def insert_market_snapshot(conn, snapshot_date, listings):
    conn.executemany(
        "INSERT OR REPLACE INTO market_listings "
        "(player_id, snapshot_date, price, expires_at, my_bid_amount, seller_user_id) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [
            (
                m["player_id"], snapshot_date, m["price"], m["expires_at"],
                m.get("my_bid_amount"), m.get("seller_user_id"),
            )
            for m in listings
        ],
    )


def insert_balance_snapshot(conn, snapshot_date, balances):
    conn.executemany(
        "INSERT OR REPLACE INTO balances (league_user_id, snapshot_date, balance, maximum_bid) VALUES (?, ?, ?, ?)",
        [(b["league_user_id"], snapshot_date, b["balance"], b.get("maximum_bid")) for b in balances],
    )
