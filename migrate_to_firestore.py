import sqlite3
import os
import json
import firebase_admin
from firebase_admin import credentials, firestore

# --- 0. Debug: list env vars and current directory ---
print("PWD:", os.getcwd())
print("Available env vars:", list(os.environ.keys()))
print("GOOGLE_APPLICATION_CREDENTIALS_JSON starts with:",
      os.environ.get('GOOGLE_APPLICATION_CREDENTIALS_JSON', '')[:30], "…")

# --- 1. Write service account to file for Certificate(path) support ---
sa_json = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS_JSON')
if not sa_json:
    raise RuntimeError(
        "Environment variable GOOGLE_APPLICATION_CREDENTIALS_JSON not found!")
with open('serviceAccount.json', 'w') as f:
    f.write(sa_json)
print("Wrote serviceAccount.json (size:",
      os.path.getsize('serviceAccount.json'), "bytes)")

# --- 2. Initialize Firebase Admin ---
cred = credentials.Certificate('serviceAccount.json')
firebase_admin.initialize_app(cred)
fs = firestore.client()
print("✅ Firestore client initialized")

# --- 3. Connect to SQLite and list tables ---
db_path = 'physio.db'
if not os.path.exists(db_path):
    raise RuntimeError(f"SQLite file not found at {db_path}")
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
tables = [row[0] for row in cursor.fetchall()]
print("Found SQLite tables:", tables)


# --- 4. Migrate each table, with row counts ---
def migrate_table(table_name):
    cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
    count = cursor.fetchone()[0]
    print(f"\n-- Migrating {table_name}: {count} rows --")
    if count == 0:
        print("  (no rows, skipping)")
        return

    cursor.execute(f"PRAGMA table_info({table_name})")
    cols = [info[1] for info in cursor.fetchall()]

    cursor.execute(f"SELECT * FROM {table_name}")
    for row in cursor.fetchall():
        doc = dict(zip(cols, row))
        # pick a document ID: if there’s an "id" or first column
        doc_id = str(doc.get('id', row[0]))
        fs.collection(table_name).document(doc_id).set(doc)
    print(f"  → Done migrating {count} docs")


for tbl in tables:
    # skip sqlite_sequence and any internal tables
    if tbl == 'sqlite_sequence': continue
    migrate_table(tbl)

conn.close()
print("\n🎉 Migration script complete. Check Firestore Console.")
# ——— after your migration loop ———

# 1. List the project your Admin SDK is using:
import firebase_admin
app = firebase_admin.get_app()
print("Using Firebase project:", app.project_id)

# 2. List any root collections that exist now:
root_cols = list(firestore.client().collections())
print("Root collections in Firestore:", [col.id for col in root_cols])

# 3. Write a test document:
test_ref = firestore.client().collection('__migration_test').document('ping')
test_ref.set({'timestamp': firestore.SERVER_TIMESTAMP})
print("✅ Wrote test document to __migration_test/ping")
docs = firestore.client().collection('__migration_test').stream()
print("Docs in __migration_test:")
for doc in docs:
    print("  ", doc.id, doc.to_dict())
