import os
import requests
import io
import json
from flask import (Flask, render_template, request, redirect,session, url_for, flash,jsonify)
from datetime import datetime
from flask_login import login_required
from flask_wtf.csrf import CSRFProtect, generate_csrf, CSRFError
from xhtml2pdf import pisa
from functools import wraps
import logging
from google.api_core.exceptions import GoogleAPIError
import firebase_admin
from firebase_admin import credentials, firestore, auth

FIREBASE_WEB_API_KEY = os.environ.get('FIREBASE_WEB_API_KEY')
from firebase_admin.firestore import SERVER_TIMESTAMP
from google.cloud.firestore_v1.base_query import FieldFilter
import openai

try:
    from openai.error import OpenAIError
except ImportError:
    OpenAIError = Exception

from prompts_py import (
    generate_history_questions_prompt,
    generate_diagnosis_prompt,
    generate_subjective_field_prompt,
    generate_subjective_diagnosis_prompt,
    generate_perspectives_field_prompt,
    generate_perspectives_diagnosis_prompt,
    generate_initial_plan_prompt,
    generate_initial_plan_summary_prompt,
    generate_patho_possible_source_prompt,
    generate_chronic_factors_prompt,
    generate_clinical_flags_prompt,
    generate_objective_assessment_prompt,
    generate_objective_field_prompt,
    generate_provisional_diagnosis_prompt,
    generate_smart_goals_prompt,
    generate_treatment_plan_prompt,
    generate_treatment_summary_prompt,
    generate_followup_prompt
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

openai.api_key = os.environ['OPENAI_API_KEY']

# ─── FIREBASE INIT ───────────────────────────
# Load the service-account JSON from a Render Secret File
# ─── DEBUG: Inspect secret-file mount ─────────────────────────
SECRETS_DIR = "/etc/secrets"
print("DEBUG: /etc/secrets exists?", os.path.isdir(SECRETS_DIR))
if os.path.isdir(SECRETS_DIR):
    print("DEBUG: /etc/secrets contents:", os.listdir(SECRETS_DIR))

# ─── FETCH ENV-VAR & SHOW PATH ─────────────────────────────────
cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
print(f"DEBUG: GOOGLE_APPLICATION_CREDENTIALS = {cred_path!r}")
if not cred_path:
    raise RuntimeError("Missing GOOGLE_APPLICATION_CREDENTIALS")

# ─── TRY LOADING & INITIALIZING ───────────────────────────────
try:
    # 1) Read & parse the JSON
    with open(cred_path, "r") as f:
        sa = json.load(f)
    print("DEBUG: Loaded service-account JSON, project_id =", sa.get("project_id"))

    # 2) Initialize Firebase
    cred = credentials.Certificate(cred_path)
    firebase_admin.initialize_app(cred, {"projectId": sa.get("project_id")})
    print("DEBUG: Firebase Admin SDK initialized successfully")

    # 3) Test Firestore access
    db = firestore.client()
    col_ids = [c.id for c in db.collections()]
    print("DEBUG: Firestore collections:", col_ids)

except Exception:
    print("DEBUG: Exception during Firebase init:")
    traceback.print_exc()
    # re-raise so Render still fails if it’s truly broken
    raise

# Initialize the Admin SDK straight from the file

# Then get your Firestore client as usual
db = firestore.client()

def get_ai_suggestion(prompt: str) -> str:
    resp = openai.chat.completions.create(
        model="gpt-4-turbo",
        messages=[{
            "role": "system",
            "content": "You are a helpful clinical reasoning assistant."
        }, {
            "role": "user",
            "content": prompt
        }],
        temperature=0.7,
        max_tokens=200)
    return resp.choices[0].message.content

def log_action(user_id, action, details=None):
    entry = {
        'user_id': user_id,
        'action': action,
        'details': details,
        'timestamp': SERVER_TIMESTAMP
    }
    db.collection('audit_logs').add(entry)

def fetch_patient(patient_id):
    try:
        doc = db.collection('patients').document(patient_id).get()
        if not doc.exists:
            return None
        data = doc.to_dict()
        data['patient_id'] = doc.id
        return data
    except GoogleAPIError as e:
        logger.error(f"Firestore error fetching patient {patient_id}: {e}", exc_info=True)
        return None

app = Flask(__name__)
app.secret_key =os.environ.get('SECRET_KEY', 'dev_default_key')
app.config['WTF_CSRF_ENABLED'] = True

@app.template_filter('datetimeformat')
def datetimeformat(value, format='%d-%m-%Y'):
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value.strftime(format)

csrf = CSRFProtect(app)

@app.errorhandler(CSRFError)
def handle_csrf_error(error):
    flash("The form you submitted is invalid or has expired. Please try again.", "error")
    return redirect(request.referrer or url_for('index')), 400

@app.after_request
def set_csrf_cookie(response):
    response.set_cookie('csrf_token', generate_csrf())
    return response

@app.context_processor
def inject_csrf_token():
    return dict(csrf_token=generate_csrf)

def login_required(approved_only=True):
    def wrapper(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                return redirect('/login')
            if approved_only and session.get('is_admin') != 1 and session.get('approved') == 0:
                return "Access denied. Awaiting approval by admin."
            return f(*args, **kwargs)
        return decorated_function
    return wrapper

@app.route('/')
def index():
    return render_template('index.html')



@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']

        try:
            # 1. Create user in Firebase Auth
            user_record = auth.create_user(email=email, password=password, display_name=name)

            # 2. Store metadata in Firestore
            db.collection('users').document(email).set({
                'name': name,
                'email': email,
                'is_admin': 0,
                'approved': 1,
                'active': 1,
                'created_at': firestore.SERVER_TIMESTAMP
            })

            flash('Registration successful. You can now log in.', 'success')
            return redirect('/login')

        except Exception as e:
            print("Registration error:", e)
            flash('Registration failed. ' + str(e), 'danger')
            return redirect('/register')

    return render_template('register.html')




@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        password = request.form['password']

        try:
            # Firebase login
            payload = {
                'email': email,
                'password': password,
                'returnSecureToken': True
            }
            r = requests.post(
                f'https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={FIREBASE_WEB_API_KEY}',
                json=payload
            )
            result = r.json()
            if 'error' in result:
                flash('Invalid credentials', 'danger')
                return redirect('/login')

            # Firestore user check
            user_doc = db.collection('users').document(email).get()
            if not user_doc.exists:
                flash('User not found in Firestore.', 'danger')
                return redirect('/login')
            user_data = user_doc.to_dict()

            # No approval required now
            if user_data.get('active') != 1:
                flash('Account is inactive.', 'danger')
                return redirect('/login')

            session['user_email'] = email
            session['user_name'] = user_data['name']
            session['user_id'] = email
            session['is_admin'] = 0
            session['role'] = 'individual'
            return redirect('/dashboard')

        except Exception as e:
            print("Login error (individual):", e)
            flash("Login failed due to a system error.", "danger")
            return redirect('/login')

    return render_template('login.html')





@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')


@app.route('/dashboard')
@login_required()
def dashboard():
    return render_template('dashboard.html', name=session.get('user_name'))


@app.route('/admin_dashboard')
@login_required()
def admin_dashboard():
    # only institute‑admins allowed
    if session.get('is_admin') != 1:
        return redirect(url_for('login_institute'))

    # build a query for non‑admin physios in this institute, pending approval
    users_ref = db.collection('users')
    docs = (
        users_ref
        .where(filter=FieldFilter('is_admin',   '==', 0))
        .where(filter=FieldFilter('approved',   '==', 0))
        .where(filter=FieldFilter('institute',  '==', session.get('institute')))
        .stream()
    )

    # pull the documents into a list of dicts
    pending_physios = [doc.to_dict() for doc in docs]

    # render
    return render_template(
        'admin_dashboard.html',
        pending_physios=pending_physios,
        name=session.get('user_name'),
        institute=session.get('institute')
    )


 

@app.route('/view_patients')
@login_required()
def view_patients():
        name_f = request.args.get('name')
        id_f   = request.args.get('patient_id')

        try:
            # 1) Base collection
            coll = db.collection('patients')
            q = coll

            # 2) Apply filters
            if name_f:
                # Note: Firestore requires an order_by on the same field when using >=
                q = q.where('name', '>=', name_f).order_by('name')
            if id_f:
                q = q.where('patient_id', '==', id_f)

            # 3) Restrict by institute or physio
            if session.get('is_admin') == 1:
                q = q.where('institute', '==', session.get('institute'))
            else:
                q = q.where('physio_id', '==', session.get('user_id'))

            # 4) Execute and materialize
            docs = q.stream()
            patients = [doc.to_dict() for doc in docs]

        except GoogleAPIError as e:
            logger.error(f"Firestore error in view_patients: {e}", exc_info=True)
            flash("Could not load your patients list. Please try again later.", "error")
            return redirect(url_for('dashboard'))

        # 5) Render on success
        return render_template('view_patients.html', patients=patients)



@app.route('/register_institute', methods=['GET', 'POST'])
def register_institute():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']
        institute_name = request.form['institute_name']

        try:
            # Create Firebase Auth user
            auth.create_user(email=email, password=password, display_name=name)

            # Save to Firestore
            db.collection('users').document(email).set({
                'name': name,
                'email': email,
                'institute_name': institute_name,
                'is_admin': 1,
                'approved': 1,
                'active': 1,
                'created_at': firestore.SERVER_TIMESTAMP
            })

            flash("Institute admin registered successfully. You can log in.", "success")
            return redirect('/login_institute')

        except Exception as e:
            print("Registration error (institute):", e)
            flash('Registration failed. ' + str(e), 'danger')
            return redirect('/register_institute')

    return render_template('register_institute.html')




@app.route('/login_institute', methods=['GET', 'POST'])
def login_institute():
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        password = request.form['password']

        try:
            payload = {
                'email': email,
                'password': password,
                'returnSecureToken': True
            }
            r = requests.post(
                f'https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={FIREBASE_WEB_API_KEY}',
                json=payload
            )
            result = r.json()
            if 'error' in result:
                flash("Invalid credentials.", "danger")
                return redirect('/login_institute')

            user_doc = db.collection('users').document(email).get()
            if not user_doc.exists:
                flash('User not found in Firestore.', 'danger')
                return redirect('/login_institute')

            user_data = user_doc.to_dict()

            # Skip approval logic for now
            if user_data.get('active') != 1:
                flash('Account is inactive.', 'danger')
                return redirect('/login_institute')

            session['user_email'] = email
            session['user_name'] = user_data.get('name')
            session['user_id'] = email
            session['is_admin'] = user_data.get('is_admin', 0)

            if session['is_admin'] == 1:
                session['role'] = 'institute_admin'
                session['institute'] = user_data.get('institute_name') or email
                return redirect('/admin_dashboard')
            else:
                session['role'] = 'institute_physio'
                session['institute'] = user_data.get('institute_email')
                return redirect('/dashboard')

        except Exception as e:
            print("Login error (institute):", e)
            flash("Login failed due to a system error.", "danger")
            return redirect('/login_institute')

    return render_template('login_institute.html')



@app.route('/register_with_institute', methods=['GET', 'POST'])
def register_with_institute():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email'].strip().lower()
        password = request.form['password']
        institute_name_input = request.form['institute_email'].strip()  # This is actually the name

        try:
            # Step 2: Look up the email of the selected institute admin
            institute_admin = db.collection('users')\
                .where('is_admin', '==', 1)\
                .where('institute_name', '==', institute_name_input)\
                .limit(1).get()

            if not institute_admin:
                flash("No matching institute found. Please select a valid institute.", "danger")
                return redirect('/register_with_institute')

            institute_email = institute_admin[0].to_dict()['email']

            # Create Firebase user
            auth.create_user(email=email, password=password, display_name=name)

            # Save to Firestore
            db.collection('users').document(email).set({
                'name': name,
                'email': email,
                'institute_email': institute_email,
                'institute': institute_name_input,  # Add this line
                'is_admin': 0,
                'approved': 0,
                'active': 1,
                'created_at': firestore.SERVER_TIMESTAMP
            })

            flash("Registered with institute. Awaiting admin approval.", "info")
            return redirect('/login_institute')

        except Exception as e:
            print("Registration error (with institute):", e)
            flash('Registration failed. ' + str(e), 'danger')
            return redirect('/register_with_institute')

    return render_template('register_with_institute.html')
    

@app.route('/approve_physios')
@login_required()
def approve_physios():
    if session.get('is_admin') != 1:
        return redirect('/login_institute')

    docs = (db.collection('users')
              .where('is_admin','==',0)
              .where('approved','==',0)
              .where('institute','==', session.get('institute'))
              .stream())

    pending = []
    for d in docs:
        data = d.to_dict()
        # Firestore doc ID is the physio’s email
        data['email'] = d.id
        pending.append(data)

    return render_template('approve_physios.html', physios=pending)

@app.route('/reject_user/<user_email>', methods=['POST'])
@login_required()
def reject_user(user_email):
    try:
        # Deactivate and unapprove the user
        db.collection('users').document(user_email).update({
            'active': 0,
            'approved': 0
        })
        flash(f"{user_email} has been rejected and deactivated.", "info")
    except Exception as e:
        print("Error rejecting user:", e)
        flash("Failed to reject user.", "danger")
    return redirect(url_for('approve_physios'))



@app.route('/approve_user/<user_email>', methods=['POST'])
@login_required()
def approve_user(user_email):
        if session.get('is_admin') != 1:
            return redirect('/login_institute')
        db.collection('users').document(user_email).update({'approved': 1})
        log_action(session.get('user_id'), 'Approve User',
                   f"Approved user {user_email}")
        return redirect('/approve_physios')



@app.route('/audit_logs')
@login_required()
def audit_logs():
    logs = []

    if session.get('is_admin') == 1:
        # Admin: fetch logs for all users in their institute
        users = db.collection('users') \
                  .where('institute', '==', session['institute']) \
                  .stream()
        user_map = {u.id: u.to_dict() for u in users}
        user_ids = list(user_map.keys())

        for uid in user_ids:
            entries = db.collection('audit_logs').where('user_id', '==', uid).stream()
            for e in entries:
                data = e.to_dict()
                data['name'] = user_map[uid]['name']
                logs.append(data)

    elif session.get('is_admin') == 0:
        # Individual physio: only their logs
        entries = db.collection('audit_logs').where('user_id', '==', session['user_id']).stream()
        for e in entries:
            data = e.to_dict()
            data['name'] = session['user_name']
            logs.append(data)

    # Sort by timestamp descending
    logs.sort(key=lambda x: x.get('timestamp', 0), reverse=True)

    return render_template('audit_logs.html', logs=logs)

@app.route('/export_audit_logs')
@login_required()
def export_audit_logs():
    if session.get('is_admin') != 1:
        return redirect('/login_institute')

    users = db.collection('users') \
              .where('institute', '==', session['institute']) \
              .stream()
    user_map = {u.id: u.to_dict() for u in users}
    user_ids = list(user_map.keys())

    logs = []
    for uid in user_ids:
        entries = db.collection('audit_logs').where('user_id', '==', uid).stream()
        for e in entries:
            log = e.to_dict()
            logs.append([
                user_map[uid]['name'],
                log.get('action', ''),
                log.get('details', ''),
                log.get('timestamp', '')
            ])

    # Prepare CSV
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['User', 'Action', 'Details', 'Timestamp'])
    writer.writerows(logs)

    response = make_response(output.getvalue())
    response.headers['Content-Disposition'] = 'attachment; filename=audit_logs.csv'
    response.headers['Content-Type'] = 'text/csv'
    return response


@app.route('/add_patient', methods=['GET', 'POST'])
@login_required()
def add_patient():
    if request.method == 'POST':
        # 1) collect form values
        data = {
            'physio_id':       session.get('user_id'),
            'name':            request.form['name'],
            'age_sex':         request.form['age_sex'],
            'contact':         request.form['contact'],
            'present_history': request.form['present_history'],
            'past_history':    request.form.get('past_history', '').strip(),
            'institute':       session.get('institute'),
            'created_at':      SERVER_TIMESTAMP
        }

        # 2) build a per‑month counter key, e.g. "2025/07"
        now       = datetime.utcnow()
        month_key = now.strftime('%Y%m')

        counter_ref = db.collection('patient_counters').document(month_key)

        # 3) bump the counter transactionally
        @firestore.transactional
        def bump(txn):
            snap = counter_ref.get(transaction=txn)
            data_snap = snap.to_dict() or {}
            if not snap.exists:
                txn.set(counter_ref, {'count': 1})
                return 1
            else:
                new_count = data_snap.get('count', 0) + 1
                txn.update(counter_ref, {'count': new_count})
                return new_count

        seq = bump(db.transaction())

        # 4) assemble your pretty patient ID "YYYY/MM/NN"
        pid = f"{now.year:04d}/{now.month:02d}/{seq:02d}"

        # 5) write the patient doc under that ID
        db.collection('patients').document(pid).set({
            **data,
            'patient_id': pid
        })

        log_action(session.get('user_id'),
                   'Add Patient',
                   f"Added {data['name']} (ID: {pid})")

        # 6) redirect to the next screen
        return redirect(url_for('subjective', patient_id=pid))

    # GET → render the blank form
    return render_template('add_patient.html')





@app.route('/subjective/<path:patient_id>', methods=['GET', 'POST'])
@login_required()
def subjective(patient_id):
    doc = db.collection('patients').document(
        patient_id).get()  # type: ignore[attr-defined]
    if not doc.exists:
        return "Patient not found."
    patient = doc.to_dict()
    if session.get('is_admin') == 0 and patient.get(
            'physio_id') != session.get('user_id'):
        return "Access denied."
    if request.method == 'POST':
        fields = [
            'body_structure', 'body_function', 'activity_performance',
            'activity_capacity', 'contextual_environmental',
            'contextual_personal'
        ]
        entry = {f: request.form[f] for f in fields}
        entry['patient_id'] = patient_id
        entry['timestamp'] = SERVER_TIMESTAMP
        db.collection('subjective_examination').add(entry)
        return redirect(f'/perspectives/{patient_id}')
    return render_template('subjective.html', patient_id=patient_id, patient=patient)



@app.route('/perspectives/<path:patient_id>', methods=['GET','POST'])
@login_required()
def perspectives(patient_id):
    doc = db.collection('patients').document(patient_id).get()
    if not doc.exists:
        return "Patient not found."
    patient = doc.to_dict()
    if session.get('is_admin') == 0 and patient.get('physio_id') != session.get('user_id'):
        return "Access denied."

    if request.method == 'POST':
        # ← UPDATED TO MATCH YOUR HTML FIELD NAMES
        keys = [
            'knowledge',
            'attribution',
            'expectation',               # was 'illness_duration'
            'consequences_awareness',
            'locus_of_control',
            'affective_aspect'
        ]

        # collect form values safely
        entry = {
            k: request.form.get(k, '')  # use .get() to avoid KeyError
            for k in keys
        }
        entry.update({
            'patient_id': patient_id,
            'timestamp': SERVER_TIMESTAMP
        })

        # save to your collection
        db.collection('patient_perspectives').add(entry)

        # redirect to the next screen
        return redirect(url_for('initial_plan', patient_id=patient_id))

    # GET: render the form
    return render_template('perspectives.html', patient_id=patient_id)


@app.route('/initial_plan/<path:patient_id>', methods=['GET','POST'])
@login_required()
def initial_plan(patient_id):
    doc = db.collection('patients').document(patient_id).get()  # type: ignore[attr-defined]
    if not doc.exists:
        return "Patient not found."
    patient = doc.to_dict()
    if session.get('is_admin') == 0 and patient.get('physio_id') != session.get('user_id'):
        return "Access denied."
    if request.method == 'POST':
        sections = ['active_movements','passive_movements','passive_over_pressure',
                    'resisted_movements','combined_movements','special_tests','neuro_dynamic_examination']
        entry = {'patient_id': patient_id, 'timestamp': SERVER_TIMESTAMP}
        for s in sections:
            entry[s] = request.form.get(s)
            entry[f"{s}_details"] = request.form.get(f"{s}_details", '')
        db.collection('initial_plan').add(entry)
        return redirect(f'/patho_mechanism/{patient_id}')
    return render_template('initial_plan.html', patient_id=patient_id)



@app.route('/patho_mechanism/<path:patient_id>', methods=['GET', 'POST'])
@login_required()
def patho_mechanism(patient_id):
    doc = db.collection('patients').document(
        patient_id).get()  # type: ignore[attr-defined]
    if not doc.exists:
        return "Patient not found."
    patient = doc.to_dict()
    if session.get('is_admin') == 0 and patient.get(
            'physio_id') != session.get('user_id'):
        return "Access denied."
    if request.method == 'POST':
        keys = [
            'area_involved', 'presenting_symptom', 'pain_type', 'pain_nature',
            'pain_severity', 'pain_irritability', 'possible_source',
            'stage_healing'
        ]
        entry = {k: request.form[k] for k in keys}
        entry['patient_id'] = patient_id
        entry['timestamp'] = SERVER_TIMESTAMP
        db.collection('patho_mechanism').add(entry)
        return redirect(f'/chronic_disease/{patient_id}')
    return render_template('patho_mechanism.html', patient_id=patient_id)


@app.route('/chronic_disease/<path:patient_id>', methods=['GET','POST'])
@login_required()
def chronic_disease(patient_id):
    if request.method == 'POST':
        # Pull back *all* selected options as a Python list:
        causes = request.form.getlist('maintenance_causes')
        entry = {
            'patient_id': patient_id,
            'causes': causes,                            # <- store the list
            'specific_factors': request.form.get('specific_factors', ''),
            'timestamp': SERVER_TIMESTAMP
        }
        db.collection('chronic_diseases').add(entry)
        return redirect(f'/clinical_flags/{patient_id}')
    return render_template('chronic_disease.html', patient_id=patient_id)


@app.route('/clinical_flags/<path:patient_id>', methods=['GET', 'POST'])
@login_required()
def clinical_flags(patient_id):
    # fetch patient record just like your other screens
    doc = db.collection('patients').document(patient_id).get()
    if not doc.exists:
        return "Patient not found."
    patient = doc.to_dict()
    if session.get('is_admin') == 0 and patient.get('physio_id') != session.get('user_id'):
        return "Access denied."

    if request.method == 'POST':
        entry = {
            'patient_id': patient_id,
            'red_flags':     request.form.get('red_flags', ''),
            'yellow_flags':  request.form.get('yellow_flags', ''),
            'black_flags':   request.form.get('black_flags', ''),
            'blue_flags':    request.form.get('blue_flags', ''),
            'timestamp':     SERVER_TIMESTAMP
        }
        db.collection('clinical_flags').add(entry) 
        return redirect(url_for('objective_assessment', patient_id=patient_id))


    return render_template('clinical_flags.html', patient_id=patient_id)


@app.route('/objective_assessment/<path:patient_id>', methods=['GET','POST'])
@csrf.exempt
@login_required()
def objective_assessment(patient_id):
    # (fetch patient, check access—same as your other screens)
    doc = db.collection('patients').document(patient_id).get()
    if not doc.exists:
        return "Patient not found."
    patient = doc.to_dict()
    if session.get('is_admin') == 0 and patient.get('physio_id') != session.get('user_id'):
        return "Access denied."

    if request.method == 'POST':
        entry = {
            'patient_id': patient_id,
            'plan':          request.form['plan'],
            'plan_details':  request.form.get('plan_details',''),
            'timestamp':     SERVER_TIMESTAMP
        }
        db.collection('objective_assessments').add(entry)
        return redirect(f'/provisional_diagnosis/{patient_id}')

    return render_template('objective_assessment.html', patient_id=patient_id)



@app.route('/provisional_diagnosis/<path:patient_id>', methods=['GET', 'POST'])
@login_required()
def provisional_diagnosis(patient_id):
    doc = db.collection('patients').document(
        patient_id).get()  # type: ignore[attr-defined]
    if not doc.exists:
        return "Patient not found."
    patient = doc.to_dict()
    if session.get('is_admin') == 0 and patient.get(
            'physio_id') != session.get('user_id'):
        return "Access denied."
    if request.method == 'POST':
        keys = [
            'likelihood', 'structure_fault', 'symptom', 'findings_support',
            'findings_reject', 'hypothesis_supported'
        ]
        entry = {k: request.form[k] for k in keys}
        entry['patient_id'] = patient_id
        entry['timestamp'] = SERVER_TIMESTAMP
        db.collection('provisional_diagnosis').add(entry)
        return redirect(f'/smart_goals/{patient_id}')
    return render_template('provisional_diagnosis.html', patient_id=patient_id)


@app.route('/smart_goals/<path:patient_id>', methods=['GET', 'POST'])
@login_required()
def smart_goals(patient_id):
    doc = db.collection('patients').document(
        patient_id).get()  # type: ignore[attr-defined]
    if not doc.exists:
        return "Patient not found."
    patient = doc.to_dict()
    if session.get('is_admin') == 0 and patient.get(
            'physio_id') != session.get('user_id'):
        return "Access denied."
    if request.method == 'POST':
        keys = [
            'patient_goal', 'baseline_status', 'measurable_outcome',
            'time_duration'
        ]
        entry = {k: request.form[k] for k in keys}
        entry['patient_id'] = patient_id
        entry['timestamp'] = SERVER_TIMESTAMP
        db.collection('smart_goals').add(entry)
        return redirect(f'/treatment_plan/{patient_id}')
    return render_template('smart_goals.html', patient_id=patient_id)


@app.route('/treatment_plan/<path:patient_id>', methods=['GET', 'POST'])
@login_required()
def treatment_plan(patient_id):
    doc = db.collection('patients').document(
        patient_id).get()  # type: ignore[attr-defined]
    if not doc.exists:
        return "Patient not found."
    patient = doc.to_dict()
    if session.get('is_admin') == 0 and patient.get(
            'physio_id') != session.get('user_id'):
        return "Access denied."
    if request.method == 'POST':
        keys = ['treatment_plan', 'goal_targeted', 'reasoning', 'reference']
        entry = {k: request.form[k] for k in keys}
        entry['patient_id'] = patient_id
        entry['timestamp'] = SERVER_TIMESTAMP
        db.collection('treatment_plan').add(entry)
        return redirect('/dashboard')
    return render_template('treatment_plan.html', patient_id=patient_id)

@app.route('/follow_ups/<path:patient_id>', methods=['GET', 'POST'])
@login_required()
def follow_ups(patient_id):
    # 1) fetch patient and permission check
    patient_doc = db.collection('patients').document(patient_id).get()
    if not patient_doc.exists:
        return "Patient not found", 404
    patient = patient_doc.to_dict()
    if session.get('is_admin') == 0 and patient.get('physio_id') != session.get('user_id'):
        return "Access denied", 403

    # 2) handle new entry
    if request.method == 'POST':
        entry = {
            'patient_id':      patient_id,
            'session_number':  int(request.form['session_number']),
            'session_date':    request.form['session_date'],
            'grade':           request.form['grade'],
            'perception':      request.form['belief_treatment'],
            'feedback':        request.form['belief_feedback'],
            'treatment_plan':  request.form['treatment_plan'],
            'timestamp':       SERVER_TIMESTAMP
        }
        db.collection('follow_ups').add(entry)
        log_action(session['user_id'], 'Add Follow-Up',
                   f"Follow-up #{entry['session_number']} for {patient_id}")
        return redirect(f'/follow_ups/{patient_id}')

    # 3) on GET, pull all existing
    docs = (db.collection('follow_ups')
              .where('patient_id', '==', patient_id)
              .order_by('session_number')
              .stream())
    followups = [d.to_dict() for d in docs]

    return render_template('follow_ups.html',                       patient=patient, patient_id=patient_id,
                           followups=followups)

# ─── VIEW FOLLOW-UPS ROUTE ─────────────────────────────────────────────
@app.route('/view_follow_ups/<path:patient_id>')
@login_required()
def view_follow_ups(patient_id):
    doc = db.collection('patients').document(patient_id).get()
    if not doc.exists:
        return "Patient not found."
    patient = doc.to_dict()

    # Access control
    if session.get('is_admin') == 0 and patient.get('physio_id') != session.get('user_id'):
        return "Access denied."

    docs = (db.collection('follow_ups')
              .where('patient_id', '==', patient_id)
              .order_by('session_date', direction=firestore.Query.DESCENDING)
              .stream())
    followups = [d.to_dict() for d in docs]

    return render_template('view_follow_ups.html', patient=patient, followups=followups)


@app.route('/edit_patient/<path:patient_id>', methods=['GET', 'POST'])
@login_required()
def edit_patient(patient_id):
    doc_ref = db.collection('patients').document(patient_id)
    doc = doc_ref.get()
    if not doc.exists:
        return "Patient not found", 404

    patient = doc.to_dict()

    if session.get('is_admin') == 0 and patient.get('physio_id') != session.get('user_id'):
        return "Access denied", 403

    if request.method == 'POST':
        updated_data = {
            'name': request.form['name'],
            'age_sex': request.form['age_sex'],
            'contact': request.form['contact']
        }
        doc_ref.update(updated_data)
        log_action(session['user_id'], 'Edit Patient', f"Edited patient {patient_id}")
        return redirect(url_for('view_patients'))

    return render_template('edit_patient.html', patient=patient, patient_id=patient_id)


@app.route('/patient_report/<path:patient_id>')
@login_required()
def patient_report(patient_id):
    doc = db.collection('patients').document(
        patient_id).get()  # type: ignore[attr-defined]
    if not doc.exists:
        return "Patient not found."
    patient = doc.to_dict()
    if session.get('is_admin') == 0 and patient.get(
            'physio_id') != session.get('user_id'):
        return "Access denied."
    # fetch each section
    def fetch_one(coll):
        d = db.collection(coll).where('patient_id', '==',
                                      patient_id).limit(1).get()
        return d[0].to_dict() if d else {}

    subjective = fetch_one('subjective_examination')
    perspectives = fetch_one('patient_perspectives')
    diagnosis = fetch_one('provisional_diagnosis')
    treatment = fetch_one('treatment_plan')
    goals = fetch_one('smart_goals')
    return render_template('patient_report.html',
                           patient=patient,
                           subjective=subjective,
                           perspectives=perspectives,
                           diagnosis=diagnosis,
                           goals=goals,
                           treatment=treatment)


@app.route('/download_report/<path:patient_id>')
@login_required()
def download_report(patient_id):
    # 1) Fetch patient record and check permissions
    doc = db.collection('patients').document(patient_id).get()
    if not doc.exists:
        return "Patient not found.", 404
    patient = doc.to_dict()
    if session.get('is_admin') == 0 and patient.get('physio_id') != session.get('user_id'):
        return "Access denied.", 403

    # 2) Fetch each section for the report
    def fetch_one(coll):
        result = db.collection(coll) \
                     .where('patient_id', '==', patient_id) \
                     .limit(1).get()
        return result[0].to_dict() if result else {}

    subjective   = fetch_one('subjective_examination')
    perspectives = fetch_one('patient_perspectives')
    diagnosis    = fetch_one('provisional_diagnosis')
    goals        = fetch_one('smart_goals')
    treatment    = fetch_one('treatment_plan')

    # 3) Render the HTML template
    rendered = render_template(
        'patient_report.html',
        patient=patient,
        subjective=subjective,
        perspectives=perspectives,
        diagnosis=diagnosis,
        goals=goals,
        treatment=treatment
    )

    # 4) Generate PDF
    pdf = io.BytesIO()
    pisa_status = pisa.CreatePDF(io.StringIO(rendered), dest=pdf)
    if pisa_status.err:
        return "Error generating PDF", 500

    # 5) Return the PDF
    response = make_response(pdf.getvalue())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = (
        f'attachment; filename={patient_id}_report.pdf'
    )
    log_action(
        session.get('user_id'),
        'Download Report',
        f"Downloaded PDF report for patient {patient_id}"
    )
    return response


@app.route('/manage_users')
@login_required()
def manage_users():
    if session.get('is_admin') != 1:
        return "Access Denied: Admins only."
    docs = db.collection('users')\
             .where('is_admin','==',0)\
             .where('approved','==',1)\
             .where('institute','==',session.get('institute'))\
             .stream()
    users = [d.to_dict() for d in docs]
    return render_template('manage_users.html', users=users)


@app.route('/deactivate_user/<user_email>')
@login_required()
def deactivate_user(user_email):
    if session.get('is_admin') != 1:
        return "Access Denied"
    db.collection('users').document(user_email).update({'active': 0})
    log_action(session.get('user_id'), 'Deactivate User',
               f"User {user_email} was deactivated")
    return redirect('/manage_users')


@app.route('/reactivate_user/<user_email>')
@login_required()
def reactivate_user(user_email):
    if session.get('is_admin') != 1:
        return "Access Denied"
    db.collection('users').document(user_email).update({'active': 1})
    log_action(session.get('user_id'), 'Reactivate User',
               f"User {user_email} was reactivated")
    return redirect('/manage_users')



@app.route('/ai_suggestion/past_questions', methods=['POST'])
@csrf.exempt
@login_required()
def ai_past_questions():
    data = request.get_json() or {}
    age_sex = data.get('age_sex', '').strip()
    present_hist = data.get('present_history', '').strip()
    prompt = generate_history_questions_prompt(age_sex, present_hist)
    try:
        suggestion = get_ai_suggestion(prompt)
        return jsonify({'suggestion': suggestion})
    except OpenAIError:
        return jsonify({'error': 'AI service unavailable. Please try again later.'}), 503
    except Exception:
        return jsonify({'error': 'An unexpected error occurred.'}), 500

@app.route('/ai_suggestion/provisional_diagnosis', methods=['POST'])
@csrf.exempt
@login_required()
def ai_provisional_diagnosis():
    data = request.get_json() or {}
    age_sex = data.get('age_sex', '').strip()
    present_hist = data.get('present_history', '').strip()
    past_hist = data.get('past_history', '').strip()
    prompt = generate_diagnosis_prompt(age_sex, present_hist, past_hist)
    try:
        suggestion = get_ai_suggestion(prompt)
        return jsonify({'suggestion': suggestion})
    except OpenAIError:
        return jsonify({'error': 'AI service unavailable. Please try again later.'}), 503
    except Exception:
        return jsonify({'error': 'An unexpected error occurred.'}), 500

@app.route('/ai_suggestion/subjective/<field>', methods=['POST'])
@csrf.exempt
@login_required()
def ai_subjective_field(field):
    data = request.get_json() or {}
    age_sex = data.get('age_sex', '').strip()
    present_hist = data.get('present_history', '').strip()
    past_hist = data.get('past_history', '').strip()
    inputs = data.get('inputs', {})
    prompt = generate_subjective_field_prompt(age_sex, present_hist, past_hist, inputs, field)
    try:
        suggestion = get_ai_suggestion(prompt)
        return jsonify({'suggestion': suggestion})
    except OpenAIError:
        return jsonify({'error': 'AI service unavailable.'}), 503
    except Exception:
        return jsonify({'error': 'Unexpected error.'}), 500

@app.route('/ai_suggestion/subjective_diagnosis', methods=['POST'])
@csrf.exempt
@login_required()
def ai_subjective_diagnosis():
    data = request.get_json() or {}
    age_sex = data.get('age_sex', '').strip()
    present_hist = data.get('present_history', '').strip()
    past_hist = data.get('past_history', '').strip()
    inputs = data.get('inputs', {})
    prompt = generate_subjective_diagnosis_prompt(age_sex, present_hist, past_hist, inputs)
    try:
        suggestion = get_ai_suggestion(prompt)
        return jsonify({'suggestion': suggestion})
    except OpenAIError:
        return jsonify({'error': 'AI service unavailable.'}), 503
    except Exception:
        return jsonify({'error': 'Unexpected error.'}), 500

@app.route('/ai_suggestion/perspectives/<field>', methods=['POST'])
@csrf.exempt
@login_required()
def ai_perspectives_field(field):
    data = request.get_json() or {}
    previous = data.get('previous', {})
    inputs = data.get('inputs', {})
    prompt = generate_perspectives_field_prompt(previous, inputs, field)
    try:
        suggestion = get_ai_suggestion(prompt)
        return jsonify({'suggestion': suggestion})
    except OpenAIError:
        return jsonify({'error': 'AI service unavailable.'}), 503
    except Exception:
        return jsonify({'error': 'Unexpected error.'}), 500

@app.route('/ai_suggestion/perspectives_diagnosis', methods=['POST'])
@csrf.exempt
@login_required()
def ai_perspectives_diagnosis():
    data = request.get_json() or {}
    previous = data.get('previous', {})
    inputs = data.get('inputs', {})
    prompt = generate_perspectives_diagnosis_prompt(previous, inputs)
    try:
        suggestion = get_ai_suggestion(prompt)
        return jsonify({'suggestion': suggestion})
    except OpenAIError:
        return jsonify({'error': 'AI service unavailable.'}), 503
    except Exception:
        return jsonify({'error': 'Unexpected error.'}), 500

@app.route('/ai_suggestion/initial_plan/<field>', methods=['POST'])
@csrf.exempt
@login_required()
def ai_initial_plan_field(field):
    data = request.get_json() or {}
    prev = data.get('previous', {})
    selection = data.get('selection', '').strip()
    try:
        prompt = generate_initial_plan_prompt(prev, field, selection)
        suggestion = get_ai_suggestion(prompt)
        return jsonify({'suggestion': suggestion})
    except OpenAIError:
        return jsonify({'error': 'AI service unavailable.'}), 503
    except Exception:
        return jsonify({'error': 'Unexpected error.'}), 500

@app.route('/ai_suggestion/initial_plan_summary', methods=['POST'])
@csrf.exempt
@login_required()
def ai_initial_plan_summary():
    data = request.get_json() or {}
    prev = data.get('previous', {})
    assessments = data.get('assessments', {})
    try:
        prompt = generate_initial_plan_summary_prompt(prev, assessments)
        summary = get_ai_suggestion(prompt)
        return jsonify({'summary': summary})
    except OpenAIError:
        return jsonify({'error': 'AI service unavailable.'}), 503
    except Exception:
        return jsonify({'error': 'Unexpected error.'}), 500

@app.route('/ai_suggestion/patho/possible_source', methods=['POST'])
@csrf.exempt
@login_required()
def ai_patho_source():
    data = request.get_json() or {}
    prev = data.get('previous', {})
    selection = data.get('selection', '').strip()
    try:
        prompt = generate_patho_possible_source_prompt(prev, selection)
        suggestion = get_ai_suggestion(prompt)
        return jsonify({'suggestion': suggestion})
    except OpenAIError:
        return jsonify({'error': 'AI service unavailable.'}), 503
    except Exception:
        return jsonify({'error': 'Unexpected error.'}), 500

@app.route('/ai_suggestion/chronic/specific_factors', methods=['POST'])
@csrf.exempt
@login_required()
def ai_chronic_factors():
    data = request.get_json() or {}
    prev = data.get('previous', {})
    text_input = data.get('input', '').strip()
    causes_selected = data.get('causes', [])
    try:
        prompt = generate_chronic_factors_prompt(prev, text_input, causes_selected)
        suggestion = get_ai_suggestion(prompt)
        return jsonify({'suggestion': suggestion})
    except OpenAIError:
        return jsonify({'error': 'AI service unavailable.'}), 503
    except Exception:
        return jsonify({'error': 'Unexpected error.'}), 500

# FIXED: Removed double slash and missing parentheses
@app.route('/ai_suggestion/clinical_flags/<patient_id>/suggest', methods=['POST'])
@csrf.exempt
@login_required()
def clinical_flags_suggest(patient_id):
    data = request.get_json() or {}
    prev = data.get('previous', {})
    field = data.get('field', '')
    text = data.get('text', '').strip()
    try:
        prompt = generate_clinical_flags_prompt(prev, field, text)
        suggestion = get_ai_suggestion(prompt)
        return jsonify({'suggestions': suggestion})
    except OpenAIError:
        return jsonify({'error': 'AI service unavailable.'}), 503
    except Exception:
        return jsonify({'error': 'Unexpected error.'}), 500

# FIXED: Removed double slash and missing parentheses
@app.route('/objective_assessment/<patient_id>/suggest', methods=['POST'])
@csrf.exempt
@login_required()
def objective_assessment_suggest(patient_id):
    data = request.get_json() or {}
    logger.info(f"📘 [server] ObjectiveAssessment payload for patient {patient_id}: {data}")
    field = data.get('field')
    choice = data.get('value')
    prompt = generate_objective_assessment_prompt(patient_id, field, choice)
    try:
        suggestion = get_ai_suggestion(prompt).strip()
        logger.info(f"📘 [server] ObjectiveAssessment suggestion: {suggestion}")
        return jsonify({'suggestion': suggestion})
    except OpenAIError as e:
        logger.error(f"OpenAI API error in objective_assessment_suggest: {e}", exc_info=True)
        return jsonify({'error': 'AI service unavailable. Please try again later.'}), 503
    except Exception as e:
        logger.error(f"Unexpected error in objective_assessment_suggest: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred.'}), 500

@app.route('/ai_suggestion/objective_assessment/<field>', methods=['POST'])
@csrf.exempt
@login_required()
def objective_assessment_field_suggest(field):
    data = request.get_json() or {}
    logger.info(f"🧠 [server] ObjectiveAssessment payload for patient {data.get('patient_id')}: {data}")
    choice = data.get('value', '')
    prompt = generate_objective_field_prompt(data.get('patient_id'), field, choice)
    try:
        suggestion = get_ai_suggestion(prompt).strip()
        logger.info(f"🧠 [server] ObjectiveAssessment suggestion for '{field}': {suggestion}")
        return jsonify({'suggestion': suggestion})
    except OpenAIError as e:
        logger.error(f"OpenAI API error in objective_assessment_field_suggest: {e}", exc_info=True)
        return jsonify({'error': 'AI service unavailable. Please try again later.'}), 503
    except Exception as e:
        logger.error(f"Unexpected error in objective_assessment_field_suggest: {e}", exc_info=True)
        return jsonify({'error': 'An unexpected error occurred.'}), 500

@app.route('/provisional_diagnosis_suggest/<patient_id>')
@csrf.exempt
@login_required()
def provisional_diagnosis_suggest(patient_id):
    field = request.args.get('field', '')
    logger.info(f"🧠 [server] provisional_diagnosis_suggest for patient {patient_id}, field {field}")
    doc = db.collection('patients').document(patient_id).get()
    if not doc.exists:
        return jsonify({'suggestion': ''}), 404
    patient = doc.to_dict()
    try:
        prompt = generate_provisional_diagnosis_prompt(patient_id, field, patient)
        suggestion = get_ai_suggestion(prompt).strip()
        logger.info(f"💡 [server] provisional_diagnosis_suggest → {suggestion}")
        return jsonify({'suggestion': suggestion})
    except OpenAIError as e:
        logger.error(f"OpenAI API error in provisional_diagnosis_suggest: {e}", exc_info=True)
        return jsonify({'suggestion': 'AI service unavailable. Please try again later.'}), 503
    except Exception as e:
        logger.error(f"Unexpected error in provisional_diagnosis_suggest: {e}", exc_info=True)
        return jsonify({'suggestion': ''}), 500

@app.route('/ai_suggestion/smart_goals/<field>', methods=['POST'])
@csrf.exempt
@login_required()
def ai_smart_goals(field):
    data = request.get_json() or {}
    prev = {
        **data.get('previous', {}),
        **data.get('previous_subjective', {}),
        **data.get('previous_perspectives', {}),
        **data.get('previous_assessments', {})
    }
    text = data.get('input', '').strip()
    try:
        prompt = generate_smart_goals_prompt(field, prev, text)
        suggestion = get_ai_suggestion(prompt).strip()
        return jsonify({'suggestion': suggestion})
    except OpenAIError:
        return jsonify({'error': 'AI service unavailable'}), 503
    except Exception:
        return jsonify({'error': 'Unexpected error'}), 500

@app.route('/ai_suggestion/treatment_plan/<field>', methods=['POST'])
@csrf.exempt
@login_required()
def treatment_plan_suggest(field):
    data = request.get_json() or {}
    text_input = data.get('input', '').strip()
    prompt = generate_treatment_plan_prompt(field, text_input)
    try:
        suggestion = get_ai_suggestion(prompt).strip()
        return jsonify({'field': field, 'suggestion': suggestion})
    except OpenAIError:
        return jsonify({'error': 'AI service unavailable. Please try again later.'}), 503
    except Exception:
        return jsonify({'error': 'An unexpected error occurred.'}), 500

@app.route('/ai_suggestion/treatment_plan_summary/<patient_id>')
@csrf.exempt
@login_required()
def treatment_plan_summary(patient_id):
    pat_doc = db.collection('patients').document(patient_id).get()
    patient_info = pat_doc.to_dict() if pat_doc.exists else {}

    def fetch_latest(collection_name):
        coll = db.collection(collection_name) \
            .where('patient_id', '==', patient_id) \
            .order_by('timestamp', direction=firestore.Query.DESCENDING) \
            .limit(1).get()
        return coll[0].to_dict() if coll else {}

    subj = fetch_latest('subjective_examination')
    persp = fetch_latest('subjective_perspectives')
    assess = fetch_latest('subjective_assessments')
    patho = fetch_latest('pathophysiological_mechanism')
    chronic = fetch_latest('chronic_disease_factors')
    flags = fetch_latest('clinical_flags')
    objective= fetch_latest('objective_assessment')
    prov_dx = fetch_latest('provisional_diagnosis')
    goals = fetch_latest('smart_goals')
    tx_plan = fetch_latest('treatment_plan')

    prompt = generate_treatment_summary_prompt(patient_info, subj, persp, assess, patho, chronic, flags, objective, prov_dx, goals, tx_plan)
    try:
        summary = get_ai_suggestion(prompt).strip()
        return jsonify({'summary': summary})
    except OpenAIError:
        return jsonify({'error': 'AI service unavailable. Please try again later.'}), 503
    except Exception:
        return jsonify({'error': 'An unexpected error occurred.'}), 500

@app.route('/ai/followup_suggestion/<patient_id>', methods=['POST'])
@csrf.exempt
@login_required()
def ai_followup_suggestion(patient_id):
    doc = db.collection('patients').document(patient_id).get()
    if not doc.exists:
        return jsonify({'error': 'Patient not found'}), 404
    patient = doc.to_dict()
    
    data = request.get_json() or {}
    session_no = data.get('session_number')
    session_date = data.get('session_date')
    grade = data.get('grade')
    perception = data.get('perception')
    feedback = data.get('feedback')
    
    prompt = generate_followup_prompt(patient, session_no, session_date, grade, perception, feedback, patient_id)
    try:
        suggestion = get_ai_suggestion(prompt).strip()
        return jsonify({'suggestion': suggestion})
    except OpenAIError:
        return jsonify({'error': 'AI service unavailable. Please try again later.'}), 503
    except Exception:
        return jsonify({'error': 'Unexpected error occurred.'}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
