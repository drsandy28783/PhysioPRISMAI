import firebase_admin
from firebase_admin import credentials, firestore, auth
from google.api_core.exceptions import AlreadyExists

# Load your service account
cred = credentials.Certificate("serviceAccount.json")
firebase_admin.initialize_app(cred)

# Connect to Firestore
db = firestore.client()

# Default password for users that will be created
TEMP_PASSWORD = "TempPass@123"

# Stream all documents from users collection
users_ref = db.collection('users')
docs = users_ref.stream()

for doc in docs:
    user = doc.to_dict()
    email = user.get('email')
    name = user.get('name', 'User')

    if not email:
        print("❌ Skipping: Missing email")
        continue

    try:
        auth.get_user_by_email(email)
        print(f"🔁 Already exists in Firebase Auth: {email}")
    except auth.UserNotFoundError:
        try:
            auth.create_user(
                email=email,
                password=TEMP_PASSWORD,
                display_name=name
            )
            print(f"✅ Created: {email}")
        except Exception as e:
            print(f"❌ Error creating {email}: {e}")
