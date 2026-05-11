import sqlite3
import os

db_path = r'c:\Users\samue\OneDrive\Área de Trabalho\blueocean\deteccao_relampagos\lightning_tracker\webapp\backend\db\service_takers.sqlite'

if not os.path.exists(db_path):
    print(f"Database not found at {db_path}")
    exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Find the TestTaker
cursor.execute("SELECT id, nome_plataforma, latitude, longitude FROM tomadores_servico WHERE nome_plataforma LIKE '%Test%' OR nome_plataforma LIKE '%Acre%'")
rows = cursor.fetchall()

if not rows:
    print("TestTaker not found by name. Listing all to find it manually...")
    cursor.execute("SELECT id, nome_plataforma, latitude, longitude FROM tomadores_servico")
    rows = cursor.fetchall()
    for row in rows:
        print(row)
else:
    for row in rows:
        print(f"Found: {row}")
        # Update coordinates
        new_lat = -23.79541633604562
        new_lon = -55.25367632383309
        cursor.execute("UPDATE tomadores_servico SET latitude = ?, longitude = ? WHERE id = ?", (new_lat, new_lon, row[0]))
        print(f"Updated ID {row[0]} to {new_lat}, {new_lon}")

conn.commit()
conn.close()
