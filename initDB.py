import sqlite3

def initialize_database():
    conn = sqlite3.connect('points.db')
    cursor = conn.cursor()
    
    # Create users table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id TEXT PRIMARY KEY,
        points INTEGER DEFAULT 0
    )
    ''')

    # Create matches table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS matches (
        match_id INTEGER PRIMARY KEY AUTOINCREMENT,
        match_name TEXT NOT NULL,
        team1 TEXT NOT NULL,
        team2 TEXT NOT NULL,
        date TIMESTAMP NOT NULL,
        result TEXT,
        team1_dividend REAL DEFAULT 1.0,
        team2_dividend REAL DEFAULT 1.0,
        closed INTEGER DEFAULT 0,
        team1_total_bet INTEGER DEFAULT 0,
        team2_total_bet INTEGER DEFAULT 0
    )
    ''')

    # Create bets table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS bets (
        bet_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        match_id INTEGER NOT NULL,
        team TEXT NOT NULL,
        amount INTEGER NOT NULL,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (match_id) REFERENCES matches(match_id)
    )
    ''')

    # Create teams table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS teams (
        match_name TEXT,
        team INTEGER,
        user_id TEXT,
        PRIMARY KEY (match_name, user_id)
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS records (
        user_id TEXT PRIMARY KEY,
        wins INTEGER DEFAULT 0,
        losses INTEGER DEFAULT 0,
        mmr INTEGER DEFAULT 1600,
        streak INTEGER DEFAULT 0
    )
    ''')

    conn.commit()
    conn.close()

if __name__ == '__main__':
    initialize_database()