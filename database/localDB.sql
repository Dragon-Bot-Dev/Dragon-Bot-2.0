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