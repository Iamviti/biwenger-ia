CREATE TABLE IF NOT EXISTS teams (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS players (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    team_id INTEGER REFERENCES teams(id),
    shirt_number INTEGER,
    position TEXT,
    status TEXT,
    status_info TEXT,
    points_total INTEGER,
    points_avg REAL,
    points_total_blended INTEGER,
    points_avg_blended REAL,
    games_played INTEGER,
    rounds_available INTEGER,
    points_last_season INTEGER,
    points_last_season_blended INTEGER,
    played_home INTEGER,
    played_away INTEGER,
    points_home_blended INTEGER,
    points_away_blended INTEGER,
    price INTEGER,
    price_increment_day INTEGER,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS price_history (
    player_id INTEGER REFERENCES players(id),
    snapshot_date TEXT NOT NULL,
    price INTEGER,
    PRIMARY KEY (player_id, snapshot_date)
);

CREATE TABLE IF NOT EXISTS league_users (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS squad_ownership (
    league_user_id INTEGER REFERENCES league_users(id),
    player_id INTEGER REFERENCES players(id),
    purchase_price INTEGER,
    snapshot_date TEXT NOT NULL,
    PRIMARY KEY (league_user_id, player_id, snapshot_date)
);

CREATE TABLE IF NOT EXISTS market_listings (
    player_id INTEGER REFERENCES players(id),
    snapshot_date TEXT NOT NULL,
    price INTEGER,
    expires_at TEXT,
    my_bid_amount INTEGER,
    seller_user_id INTEGER,
    PRIMARY KEY (player_id, snapshot_date)
);

CREATE TABLE IF NOT EXISTS team_fixtures (
    team_id INTEGER PRIMARY KEY REFERENCES teams(id),
    opponent_team_id INTEGER REFERENCES teams(id),
    is_home INTEGER,
    kickoff_at INTEGER,
    round_id INTEGER
);

CREATE TABLE IF NOT EXISTS current_round (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    round_id INTEGER,
    name TEXT,
    ends_at INTEGER
);

CREATE TABLE IF NOT EXISTS sofascore_lineups (
    player_id INTEGER PRIMARY KEY REFERENCES players(id),
    predicted_starter INTEGER NOT NULL,
    confirmed INTEGER NOT NULL,
    event_id INTEGER,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sofascore_ratings (
    player_id INTEGER PRIMARY KEY REFERENCES players(id),
    avg_rating REAL,
    avg_minutes REAL,
    matches_rated INTEGER,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sofascore_team_stats (
    team_id INTEGER PRIMARY KEY REFERENCES teams(id),
    goals_scored_avg REAL,
    goals_conceded_avg REAL,
    matches_counted INTEGER,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS balance_ledger (
    league_user_id INTEGER PRIMARY KEY REFERENCES league_users(id),
    net_movement INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS player_purchases (
    player_id INTEGER PRIMARY KEY REFERENCES players(id),
    league_user_id INTEGER REFERENCES league_users(id),
    amount INTEGER,
    purchased_at INTEGER
);

CREATE TABLE IF NOT EXISTS balances (
    league_user_id INTEGER REFERENCES league_users(id),
    snapshot_date TEXT NOT NULL,
    balance INTEGER,
    maximum_bid INTEGER,
    PRIMARY KEY (league_user_id, snapshot_date)
);
