import sqlite3
from typing import Optional, Tuple

DB_NAME = "data.db"

def get_connection():
    return sqlite3.connect(DB_NAME, check_same_thread=False)

def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    # Table membre
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS membre (
        username TEXT PRIMARY KEY,
        points INTEGER DEFAULT 0,
        rank INTEGER DEFAULT 1,
        rank_name TEXT,
        notes TEXT
    )
    """)

    # Table robux
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS robux (
        username TEXT PRIMARY KEY,
        éligible INTEGER DEFAULT 0,
        attente INTEGER DEFAULT 0,
        last TEXT DEFAULT 'Jamais',
        total INTEGER DEFAULT 0
    )
    """)

    # Table stats
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS stats (
        username TEXT PRIMARY KEY,
        nb_message INTEGER DEFAULT 0,
        nb_cmd INTEGER DEFAULT 0,
        last_cmd_n INTEGER DEFAULT 0,
        last_cmd_t TEXT DEFAULT 'Jamais'
    )
    """)
    
    # NOUVEAU : Table pour les déploiements actifs (Lock system)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS active_deployments (
        username TEXT PRIMARY KEY,
        log_id INTEGER
    )
    """)

    # Config
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS config (
        key TEXT PRIMARY KEY,
        value INTEGER
    )
    """)
    cursor.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('log_count', 0)")

    # Table pour l'historique des salaires (éviter double paiement)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS salary_log (
        month_key TEXT PRIMARY KEY,
        paid_at TEXT
    )
    """)

    conn.commit()
    conn.close()

def get_rank_name(rank_num: int) -> str:
    ranks = {
        8: "T-8 Commandant",
        7: "T-7 Capitaine",
        6: "T-6 Lieutenant",
        5: "T-5 Sous-lieutenant",
        4: "T-4 Sergent",
        3: "T-3 Caporal",
        2: "T-2 Soldat",
        1: "T-1 Recrue"
    }
    return ranks.get(rank_num, "T-1 Recrue")

def get_rank_from_points(points: int) -> int:
    if points >= 60: return 8
    if points >= 30: return 7
    if points >= 15: return 6
    if points >= 10: return 5
    if points >= 5: return 4
    if points >= 3: return 3
    if points >= 1: return 2
    return 1

def get_next_rank_points(points: int) -> int:
    if points < 1: return 1
    if points < 3: return 3
    if points < 5: return 5
    if points < 10: return 10
    if points < 15: return 15
    if points < 30: return 30
    if points < 60: return 60
    return 0 

def add_points(username: str, amount: int):
    conn = get_connection()
    cursor = conn.cursor()

    # 1. Ajouter les points
    cursor.execute("UPDATE membre SET points = points + ? WHERE username = ?", (amount, username))
    
    # 2. Récupérer les nouvelles stats
    cursor.execute("SELECT points, rank FROM membre WHERE username = ?", (username,))
    result = cursor.fetchone()
    
    if not result:
        conn.close()
        return 0, 1, "T-1 Recrue"

    new_points, current_rank = result

    # 3. Calculer le grade théorique basé sur les points
    theoretical_rank = get_rank_from_points(new_points)
    
    # --- LOGIQUE MODIFIÉE ---
    # Si le grade théorique est T-7 (ou plus) MAIS que le membre est encore T-6 (ou moins),
    # on BLOQUE le passage automatique à T-7.
    if theoretical_rank >= 7 and current_rank < 7:
        # On le laisse monter jusqu'à T-6 s'il n'y est pas encore
        # Mais s'il est déjà T-6 (Lieutenant), il reste T-6 même avec 30+ points
        new_rank = 6 if current_rank < 6 else current_rank
    else:
        # Sinon comportement normal (T-1 à T-6, ou déjà T-7+)
        new_rank = theoretical_rank

    new_rank_name = get_rank_name(new_rank)

    # 4. Sauvegarder le grade (potentiellement bloqué)
    cursor.execute("UPDATE membre SET rank = ?, rank_name = ? WHERE username = ?", 
                   (new_rank, new_rank_name, username))

    conn.commit()
    conn.close()

    return new_points, new_rank, new_rank_name

def get_user_stats(username: str) -> Optional[Tuple]:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT m.username, m.points, m.rank, m.notes, r.total, r.éligible, s.nb_message, s.nb_cmd, r.attente
        FROM membre m 
        LEFT JOIN robux r ON m.username = r.username
        LEFT JOIN stats s ON m.username = s.username
        WHERE m.username = ?
    """, (username,))
    
    result = cursor.fetchone()
    conn.close()
    return result

def add_user(username: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO membre (username, points, rank) VALUES (?, 0, 1)", (username,))
    cursor.execute("INSERT OR IGNORE INTO robux (username) VALUES (?)", (username,))
    cursor.execute("INSERT OR IGNORE INTO stats (username) VALUES (?)", (username,))
    conn.commit()
    conn.close()

def increment_log_count() -> int:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE config SET value = value + 1 WHERE key = 'log_count'")
    cursor.execute("SELECT value FROM config WHERE key = 'log_count'")
    count = cursor.fetchone()[0]
    conn.commit()
    conn.close()
    return count

def claim_robux(username: str):
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT attente FROM robux WHERE username = ?", (username,))
    result = cursor.fetchone()
    if not result:
        conn.close()
        return False, 0
    
    attente = result[0]
    if attente <= 0:
        conn.close()
        return False, 0
        
    cursor.execute("UPDATE robux SET total = total + ? WHERE username = ?", (attente, username))
    cursor.execute("UPDATE robux SET attente = 0 WHERE username = ?", (username,))
    cursor.execute("UPDATE robux SET last = datetime('now') WHERE username = ?", (username,))
    
    conn.commit()
    conn.close()
    return True, attente

# --- NOUVELLES FONCTIONS POUR LE LOCK SYSTÈME ---

def get_active_deployment(username: str) -> Optional[int]:
    """Retourne l'ID du log si un déploiement est actif, sinon None"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT log_id FROM active_deployments WHERE username = ?", (username,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def start_deployment(username: str, log_id: int):
    """Enregistre un déploiement actif pour l'utilisateur"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO active_deployments (username, log_id) VALUES (?, ?)", (username, log_id))
    conn.commit()
    conn.close()

def end_deployment(username: str):
    """Supprime le déploiement actif"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM active_deployments WHERE username = ?", (username,))
    conn.commit()
    conn.close()

# --- NOUVELLES FONCTIONS POUR LE SALAIRE ---

def get_all_members_with_ranks() -> list[Tuple[str, int]]:
    """Retourne la liste de tous les membres éligibles (username, rank)"""
    conn = get_connection()
    cursor = conn.cursor()
    # On ne prend que ceux qui ont aussi une entrée dans la table robux pour éviter les erreurs
    cursor.execute("SELECT m.username, m.rank FROM membre m JOIN robux r ON m.username = r.username")
    rows = cursor.fetchall()
    conn.close()
    return rows

def add_pending_robux(username: str, amount: int) -> int:
    """Ajoute des robux en attente et retourne le nouveau total d'attente"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE robux SET attente = attente + ? WHERE username = ?", (amount, username))
    cursor.execute("SELECT attente FROM robux WHERE username = ?", (username,))
    
    row = cursor.fetchone()
    new_attente = row[0] if row else 0
    
    conn.commit()
    conn.close()
    return new_attente

def is_month_paid(month_key: str) -> bool:
    """Vérifie si le salaire du mois (format 'MM-YYYY') a déjà été payé"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM salary_log WHERE month_key = ?", (month_key,))
    result = cursor.fetchone()
    conn.close()
    return result is not None

def mark_month_paid(month_key: str):
    """Marque le mois comme payé"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO salary_log (month_key, paid_at) VALUES (?, datetime('now'))", (month_key,))
    conn.commit()
    conn.close()

def force_rank_update(username: str, specific_rank: int):
    conn = get_connection()
    cursor = conn.cursor()
    
    new_rank_name = get_rank_name(specific_rank)
    
    cursor.execute("UPDATE membre SET rank = ?, rank_name = ? WHERE username = ?", 
                   (specific_rank, new_rank_name, username))
                   
    conn.commit()
    conn.close()
    return new_rank_name