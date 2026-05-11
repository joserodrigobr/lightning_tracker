import sqlite3
import os

db_path = r'c:\Users\samue\OneDrive\Área de Trabalho\blueocean\deteccao_relampagos\lightning_tracker\webapp\backend\db\service_takers.sqlite'

if not os.path.exists(db_path):
    print(f"Database not found at {db_path}")
    exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

cursor.execute("SELECT id, nome_plataforma FROM tomadores_servico ORDER BY nome_plataforma")
rows = cursor.fetchall()

print("--- LISTA DE TOMADORES NO BANCO ---")
for row in rows:
    print(f"ID {row[0]}: '{row[1]}'")

conn.close()
