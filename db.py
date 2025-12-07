import sqlite3

DB_NAME = "game_store.db"


def get_connection():
    """Return a connection to the SQLite database."""
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create tables if they do not exist."""
    conn = get_connection()
    cur = conn.cursor()

    # Users table
    # user_type: 'buyer' or 'seller'
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            user_type TEXT NOT NULL CHECK (user_type IN ('buyer', 'seller')),
            is_admin INTEGER NOT NULL DEFAULT 0
        )
    """)

    # Games table
    # seller_id: which seller listed the game
    cur.execute("""
        CREATE TABLE IF NOT EXISTS games (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            price REAL NOT NULL,
            image_url TEXT,
            seller_id INTEGER,
            FOREIGN KEY (seller_id) REFERENCES users(id)
        )
    """)

    # Orders table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            total_amount REAL NOT NULL,
            created_at TEXT NOT NULL,
            status TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    # Order items table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            game_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            price_each REAL NOT NULL,
            FOREIGN KEY (order_id) REFERENCES orders(id),
            FOREIGN KEY (game_id) REFERENCES games(id)
        )
    """)

    conn.commit()
    conn.close()


def seed_sample_games():
    """
    No-op seeding function.

    Kept so existing imports and calls in app.py still work,
    but it does not insert any sample games.
    """
    print("seed_sample_games() called: no sample games are inserted.")


if __name__ == "__main__":
    print("Initializing database...")
    init_db()
    seed_sample_games()
    print("Database setup complete.")
