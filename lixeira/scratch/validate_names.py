import sqlite3
import json
import os
import unicodedata

def normalize_str(s):
    # Remove accents and spaces for comparison
    return "".join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn').lower().strip()

db_path = r'c:\Users\samue\OneDrive\Área de Trabalho\blueocean\deteccao_relampagos\lightning_tracker\webapp\backend\db\service_takers.sqlite'
json_path = r'c:\Users\samue\OneDrive\Área de Trabalho\blueocean\deteccao_relampagos\lightning_tracker\webapp\backend\db\alert_contacts.json'

conn = sqlite3.connect(db_path)
cursor = conn.cursor()
cursor.execute("SELECT nome_plataforma FROM tomadores_servico")
db_names = [row[0] for row in cursor.fetchall()]
conn.close()

with open(json_path, 'r', encoding='utf-8') as f:
    contacts = json.load(f)

print("--- ANALISANDO DIVERGÊNCIAS ---")
for contact in contacts:
    target = contact['unitName']
    match = None
    for db_name in db_names:
        if db_name == target:
            match = db_name
            break
    
    if match:
        print(f"OK: '{target}' encontrado exatamente.")
    else:
        # Try soft match
        for db_name in db_names:
            if normalize_str(db_name) == normalize_str(target):
                match = db_name
                break
        
        if match:
            print(f"CORRIGINDO: '{target}' -> '{match}'")
            contact['unitName'] = match
        else:
            print(f"ERRO: '{target}' NÃO ENCONTRADO NO BANCO!")

# Save back if corrected
with open(json_path, 'w', encoding='utf-8') as f:
    json.dump(contacts, f, indent=2, ensure_ascii=False)

print("\nValidação concluída e arquivo atualizado se necessário.")
