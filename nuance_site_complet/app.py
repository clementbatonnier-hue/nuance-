import os, json, secrets, string, math
from datetime import datetime
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, session, flash, abort
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import generate_password_hash, check_password_hash
import networkx as nx

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-change-me')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///personality_match.db')
if app.config['SQLALCHEMY_DATABASE_URI'].startswith('postgres://'):
    app.config['SQLALCHEMY_DATABASE_URI'] = app.config['SQLALCHEMY_DATABASE_URI'].replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['WTF_CSRF_TIME_LIMIT'] = None

db = SQLAlchemy(app)
csrf = CSRFProtect(app)

class InviteCode(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(32), unique=True, nullable=False, index=True)
    used = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    display_name = db.Column(db.String(80), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    answers_json = db.Column(db.Text, nullable=True)
    profile_complete = db.Column(db.Boolean, default=False, nullable=False)
    consent = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def answers(self):
        try:
            return json.loads(self.answers_json or '{}')
        except Exception:
            return {}

class Match(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_a_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    user_b_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    score = db.Column(db.Float, nullable=False)
    explanation_json = db.Column(db.Text, nullable=False)
    published = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

QUESTIONS = [
    # Big Five-inspired, original wording
    {'id':'q01','section':'Personnalité','text':'Je me sens énergisé(e) par les interactions sociales.','dim':'extraversion','kind':'scale'},
    {'id':'q02','section':'Personnalité','text':'J’aime régulièrement avoir du temps seul(e) pour me ressourcer.','dim':'extraversion','kind':'scale','reverse':True},
    {'id':'q03','section':'Personnalité','text':'J’aime découvrir des idées, cultures ou activités nouvelles.','dim':'openness','kind':'scale'},
    {'id':'q04','section':'Personnalité','text':'Je préfère les habitudes familières aux expériences nouvelles.','dim':'openness','kind':'scale','reverse':True},
    {'id':'q05','section':'Personnalité','text':'Je planifie généralement les choses à l’avance.','dim':'conscientiousness','kind':'scale'},
    {'id':'q06','section':'Personnalité','text':'Je suis à l’aise avec beaucoup d’improvisation dans mon quotidien.','dim':'conscientiousness','kind':'scale','reverse':True},
    {'id':'q07','section':'Personnalité','text':'Dans un désaccord, j’essaie spontanément de comprendre le point de vue de l’autre.','dim':'agreeableness','kind':'scale'},
    {'id':'q08','section':'Personnalité','text':'Je peux être très direct(e), même si cela crée de la tension.','dim':'agreeableness','kind':'scale','reverse':True},
    {'id':'q09','section':'Personnalité','text':'Je reste généralement calme quand les choses ne se passent pas comme prévu.','dim':'emotional_stability','kind':'scale'},
    {'id':'q10','section':'Personnalité','text':'Les incertitudes relationnelles ont tendance à beaucoup m’occuper l’esprit.','dim':'emotional_stability','kind':'scale','reverse':True},

    # Values
    {'id':'q11','section':'Valeurs','text':'La famille et les liens proches doivent occuper une place centrale dans ma vie.','dim':'family','kind':'scale'},
    {'id':'q12','section':'Valeurs','text':'La réussite professionnelle est une priorité importante pour moi.','dim':'ambition','kind':'scale'},
    {'id':'q13','section':'Valeurs','text':'J’accorde une grande importance à un mode de vie sobre et attentif à son impact environnemental.','dim':'sustainability','kind':'scale'},
    {'id':'q14','section':'Valeurs','text':'J’ai besoin de préserver une forte autonomie dans une relation.','dim':'autonomy','kind':'scale'},
    {'id':'q15','section':'Valeurs','text':'La curiosité intellectuelle et les discussions de fond sont importantes pour moi.','dim':'intellectual','kind':'scale'},
    {'id':'q16','section':'Valeurs','text':'Je recherche une vie très stable et prévisible.','dim':'stability','kind':'scale'},

    # Communication / conflict
    {'id':'q17','section':'Communication','text':'Quand quelque chose me dérange, je préfère en parler rapidement.','dim':'direct_communication','kind':'scale'},
    {'id':'q18','section':'Communication','text':'Après une dispute, j’ai besoin d’un temps seul(e) avant de reparler.','dim':'cooldown','kind':'scale'},
    {'id':'q19','section':'Communication','text':'J’aime exprimer souvent mon affection verbalement.','dim':'verbal_affection','kind':'scale'},
    {'id':'q20','section':'Communication','text':'Pour moi, les gestes et services comptent davantage que les mots.','dim':'acts_affection','kind':'scale'},
    {'id':'q21','section':'Communication','text':'Je préfère régler un désaccord de manière très factuelle et structurée.','dim':'structured_conflict','kind':'scale'},
    {'id':'q22','section':'Communication','text':'Je suis à l’aise pour parler de mes émotions en détail.','dim':'emotional_openness','kind':'scale'},

    # Lifestyle / relationship expectations
    {'id':'q23','section':'Mode de vie','text':'J’aime sortir souvent et avoir un agenda social chargé.','dim':'social_rhythm','kind':'scale'},
    {'id':'q24','section':'Mode de vie','text':'J’apprécie surtout les soirées calmes à la maison.','dim':'home_rhythm','kind':'scale'},
    {'id':'q25','section':'Mode de vie','text':'Le sport ou l’activité physique fait partie de mon équilibre de vie.','dim':'activity','kind':'scale'},
    {'id':'q26','section':'Mode de vie','text':'Voyager et changer régulièrement d’environnement est important pour moi.','dim':'travel','kind':'scale'},
    {'id':'q27','section':'Relation','text':'Je cherche une relation qui puisse devenir sérieuse si la compatibilité est là.','dim':'commitment','kind':'scale'},
    {'id':'q28','section':'Relation','text':'Je préfère que la relation se construise lentement, sans projection rapide.','dim':'relationship_pace','kind':'scale'},
    {'id':'q29','section':'Relation','text':'J’aime partager beaucoup d’activités avec la personne que je fréquente.','dim':'togetherness','kind':'scale'},
    {'id':'q30','section':'Relation','text':'Même en couple, je tiens à garder beaucoup d’activités séparées.','dim':'independence','kind':'scale'},
    {'id':'q31','section':'Relation','text':'Je suis à l’aise avec les démonstrations d’affection fréquentes.','dim':'affection_frequency','kind':'scale'},
    {'id':'q32','section':'Relation','text':'La ponctualité et la fiabilité sont très importantes pour moi.','dim':'reliability','kind':'scale'},

    # Preference importance sliders: how important in a match
    {'id':'p_values','section':'Ce que je recherche','text':'Importance d’avoir des valeurs proches des miennes.','dim':'pref_values','kind':'scale'},
    {'id':'p_communication','section':'Ce que je recherche','text':'Importance d’avoir une manière de communiquer proche de la mienne.','dim':'pref_communication','kind':'scale'},
    {'id':'p_lifestyle','section':'Ce que je recherche','text':'Importance d’avoir un rythme de vie compatible avec le mien.','dim':'pref_lifestyle','kind':'scale'},
    {'id':'p_personality','section':'Ce que je recherche','text':'Importance d’avoir un tempérament proche du mien.','dim':'pref_personality','kind':'scale'},
]

PERSONALITY_DIMS = {'extraversion','openness','conscientiousness','agreeableness','emotional_stability'}
VALUES_DIMS = {'family','ambition','sustainability','autonomy','intellectual','stability'}
COMM_DIMS = {'direct_communication','cooldown','verbal_affection','acts_affection','structured_conflict','emotional_openness'}
LIFESTYLE_DIMS = {'social_rhythm','home_rhythm','activity','travel','commitment','relationship_pace','togetherness','independence','affection_frequency','reliability'}


def current_user():
    uid = session.get('user_id')
    return db.session.get(User, uid) if uid else None


def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not current_user():
            return redirect(url_for('login'))
        return fn(*args, **kwargs)
    return wrapped


def admin_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get('admin'):
            return redirect(url_for('admin_login'))
        return fn(*args, **kwargs)
    return wrapped


def generate_code(length=10):
    alphabet = string.ascii_uppercase + string.digits
    while True:
        code = ''.join(secrets.choice(alphabet) for _ in range(length))
        if not InviteCode.query.filter_by(code=code).first():
            return code


def profile_vector(user):
    ans = user.answers()
    v = {}
    for q in QUESTIONS:
        if q['dim'].startswith('pref_'):
            continue
        raw = float(ans.get(q['id'], 3))
        val = 6 - raw if q.get('reverse') else raw
        v[q['dim']] = val
    return v


def category_similarity(v1, v2, dims):
    vals = []
    for d in dims:
        a, b = v1.get(d, 3), v2.get(d, 3)
        vals.append(1 - abs(a-b)/4)
    return sum(vals)/len(vals) if vals else 0


def match_score(u1, u2):
    a1, a2 = u1.answers(), u2.answers()
    v1, v2 = profile_vector(u1), profile_vector(u2)

    sims = {
        'personality': category_similarity(v1,v2,PERSONALITY_DIMS),
        'values': category_similarity(v1,v2,VALUES_DIMS),
        'communication': category_similarity(v1,v2,COMM_DIMS),
        'lifestyle': category_similarity(v1,v2,LIFESTYLE_DIMS),
    }

    # Average both people's stated importance weights, with nonzero baseline.
    raw_weights = {
        'personality': (float(a1.get('p_personality',3)) + float(a2.get('p_personality',3))) / 2,
        'values': (float(a1.get('p_values',3)) + float(a2.get('p_values',3))) / 2,
        'communication': (float(a1.get('p_communication',3)) + float(a2.get('p_communication',3))) / 2,
        'lifestyle': (float(a1.get('p_lifestyle',3)) + float(a2.get('p_lifestyle',3))) / 2,
    }
    total_w = sum(raw_weights.values()) or 1
    score = 100 * sum(sims[k] * raw_weights[k] for k in sims) / total_w

    labels = {
        'values':'valeurs', 'communication':'communication', 'lifestyle':'mode de vie', 'personality':'tempérament'
    }
    best = sorted(sims.items(), key=lambda x:x[1], reverse=True)[:3]
    explanation = [f"Bonne compatibilité sur {labels[k]}" for k,_ in best]
    return round(score,1), {'categories': {k: round(v*100) for k,v in sims.items()}, 'highlights': explanation}


def rebuild_matches():
    users = User.query.filter_by(profile_complete=True, consent=True).all()
    Match.query.delete()
    db.session.commit()
    if len(users) < 2:
        return 0
    g = nx.Graph()
    for u in users:
        g.add_node(u.id)
    for i,u1 in enumerate(users):
        for u2 in users[i+1:]:
            score, explanation = match_score(u1,u2)
            g.add_edge(u1.id,u2.id,weight=score,explanation=explanation)
    pairs = nx.algorithms.matching.max_weight_matching(g, maxcardinality=True, weight='weight')
    for a,b in pairs:
        data = g.get_edge_data(a,b)
        db.session.add(Match(user_a_id=a,user_b_id=b,score=data['weight'],explanation_json=json.dumps(data['explanation']),published=False))
    db.session.commit()
    return len(pairs)

@app.context_processor
def inject_user():
    return {'current_user': current_user()}

@app.route('/')
def home():
    if current_user():
        return redirect(url_for('profile'))
    return render_template('home.html')

@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        code = request.form.get('code','').strip().upper()
        email = request.form.get('email','').strip().lower()
        name = request.form.get('display_name','').strip()
        password = request.form.get('password','')
        adult = request.form.get('adult') == 'on'
        consent = request.form.get('consent') == 'on'
        inv = InviteCode.query.filter_by(code=code, used=False).first()
        if not inv:
            flash('Code invalide ou déjà utilisé.', 'error')
        elif User.query.filter_by(email=email).first():
            flash('Cette adresse e-mail est déjà utilisée.', 'error')
        elif len(password) < 8:
            flash('Le mot de passe doit contenir au moins 8 caractères.', 'error')
        elif not adult or not consent:
            flash('Tu dois avoir 18 ans ou plus et accepter le traitement des réponses.', 'error')
        else:
            user = User(email=email, display_name=name or email.split('@')[0], password_hash=generate_password_hash(password), consent=True)
            db.session.add(user)
            inv.used = True
            db.session.commit()
            session['user_id'] = user.id
            return redirect(url_for('questionnaire'))
    return render_template('register.html')

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email','').strip().lower()
        password = request.form.get('password','')
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password_hash, password):
            session['user_id'] = user.id
            return redirect(url_for('profile'))
        flash('Identifiants incorrects.', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

@app.route('/questionnaire', methods=['GET','POST'])
@login_required
def questionnaire():
    user = current_user()
    existing = user.answers()
    if request.method == 'POST':
        answers = {}
        for q in QUESTIONS:
            value = request.form.get(q['id'])
            if value not in {'1','2','3','4','5'}:
                flash('Merci de répondre à toutes les questions.', 'error')
                return render_template('questionnaire.html', questions=QUESTIONS, existing=request.form)
            answers[q['id']] = int(value)
        user.answers_json = json.dumps(answers)
        user.profile_complete = True
        db.session.commit()
        flash('Ton profil a été enregistré.', 'success')
        return redirect(url_for('profile'))
    return render_template('questionnaire.html', questions=QUESTIONS, existing=existing)

@app.route('/profile')
@login_required
def profile():
    user = current_user()
    answers = user.answers()
    sections = {}
    for q in QUESTIONS:
        sections.setdefault(q['section'], []).append((q, answers.get(q['id'])))
    return render_template('profile.html', user=user, sections=sections)

@app.route('/match')
@login_required
def my_match():
    user = current_user()
    match = Match.query.filter(
        Match.published.is_(True),
        ((Match.user_a_id == user.id) | (Match.user_b_id == user.id))
    ).order_by(Match.created_at.desc()).first()
    partner = None
    explanation = None
    if match:
        partner_id = match.user_b_id if match.user_a_id == user.id else match.user_a_id
        partner = db.session.get(User, partner_id)
        explanation = json.loads(match.explanation_json)
    return render_template('match.html', match=match, partner=partner, explanation=explanation)

@app.route('/delete-account', methods=['POST'])
@login_required
def delete_account():
    user = current_user()
    Match.query.filter((Match.user_a_id==user.id)|(Match.user_b_id==user.id)).delete(synchronize_session=False)
    db.session.delete(user)
    db.session.commit()
    session.clear()
    flash('Compte supprimé.', 'success')
    return redirect(url_for('home'))

@app.route('/privacy')
def privacy():
    return render_template('privacy.html')

@app.route('/admin', methods=['GET','POST'])
def admin_login():
    if request.method == 'POST':
        if secrets.compare_digest(request.form.get('password',''), os.getenv('ADMIN_PASSWORD','change-me')):
            session['admin'] = True
            return redirect(url_for('admin_dashboard'))
        flash('Mot de passe administrateur incorrect.', 'error')
    return render_template('admin_login.html')

@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    users = User.query.order_by(User.created_at.desc()).all()
    invites = InviteCode.query.order_by(InviteCode.created_at.desc()).limit(30).all()
    matches = Match.query.order_by(Match.score.desc()).all()
    name_map = {u.id: u.display_name for u in users}
    return render_template('admin_dashboard.html', users=users, invites=invites, matches=matches, name_map=name_map)

@app.route('/admin/invites', methods=['POST'])
@admin_required
def admin_invites():
    count = min(max(int(request.form.get('count',1)),1),100)
    codes=[]
    for _ in range(count):
        code=generate_code()
        codes.append(code)
        db.session.add(InviteCode(code=code))
    db.session.commit()
    flash(f'{count} code(s) créé(s) : ' + ', '.join(codes), 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/matches/rebuild', methods=['POST'])
@admin_required
def admin_rebuild_matches():
    count = rebuild_matches()
    flash(f'{count} paire(s) calculée(s). Vérifie puis publie.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/matches/publish', methods=['POST'])
@admin_required
def admin_publish_matches():
    Match.query.update({'published': True})
    db.session.commit()
    flash('Tous les matchs actuels ont été publiés.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin',None)
    return redirect(url_for('admin_login'))

@app.cli.command('init-db')
def init_db():
    db.create_all()
    if not InviteCode.query.first():
        codes=[]
        for _ in range(5):
            c=generate_code(); codes.append(c); db.session.add(InviteCode(code=c))
        db.session.commit()
        print('Initial invite codes:', ', '.join(codes))
    print('Database ready.')

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=int(os.getenv('PORT',5000)), debug=os.getenv('FLASK_DEBUG')=='1')
