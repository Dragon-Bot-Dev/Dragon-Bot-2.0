-- Drop tables in order of dependencies
DROP TABLE IF EXISTS coc_sessions;
DROP TABLE IF EXISTS players;
DROP TABLE IF EXISTS servers;

-- Create the players table
CREATE TABLE IF NOT EXISTS players (
    discord_id VARCHAR(255) PRIMARY KEY,
    discord_username VARCHAR(255) NOT NULL,
    player_tag VARCHAR(50) NOT NULL,
    is_premium TINYINT(1) DEFAULT 0,
    autoclaim_enabled TINYINT(1) DEFAULT 0
);

-- Create the coc_sessions table
CREATE TABLE IF NOT EXISTS coc_sessions (
    discord_id VARCHAR(255) PRIMARY KEY,
    cookies_json TEXT,
    FOREIGN KEY (discord_id) REFERENCES players(discord_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS servers (
    guild_id BIGINT PRIMARY KEY,
    guild_name VARCHAR(255) NOT NULL,
    clan_tag VARCHAR(15),
    war_channel_id BIGINT DEFAULT NULL,
    raid_channel_id BIGINT DEFAULT NULL,
    last_war_reminder DATETIME DEFAULT NULL,
    last_raid_reminder DATETIME DEFAULT NULL,
    war_reminder_1 TINYINT(1) DEFAULT 0,
    war_reminder_2 TINYINT(1) DEFAULT 0,
);

-- Records each roster member's result for every war that ends, for a rolling
-- short-term (7-day, enforced at read time) view of who's been showing up and
-- finishing their attacks. Keyed by clan_tag (not guild_id) since war activity
-- belongs to the clan, not any one Discord server.
CREATE TABLE IF NOT EXISTS war_participation (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    clan_tag VARCHAR(15) NOT NULL,
    player_tag VARCHAR(50) NOT NULL,
    player_name VARCHAR(255) NOT NULL,
    war_end_time DATETIME NOT NULL,
    is_cwl TINYINT(1) DEFAULT 0,
    stars TINYINT DEFAULT 0,
    destruction DECIMAL(5,2) DEFAULT 0,
    attacks_used TINYINT DEFAULT 0,
    max_attacks TINYINT DEFAULT 2,
    opponent_name VARCHAR(255),
    recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uniq_war_player (clan_tag, player_tag, war_end_time)
);