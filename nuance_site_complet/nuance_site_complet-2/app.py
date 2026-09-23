import os
import json
import re
import secrets
import string
from datetime import datetime
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, session, flash
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

SITE_NAME = 'Nüance'

db = SQLAlchemy(app)
csrf = CSRFProtect(app)


class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    slug = db.Column(db.String(140), unique=True, nullable=False, index=True)
    description = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class InviteCode(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(32), unique=True, nullable=False, index=True)
    used = db.Column(db.Boolean, default=False, nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    display_name = db.Column(db.String(80), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    answers_json = db.Column(db.Text, nullable=True)
    profile_complete = db.Column(db.Boolean, default=False, nullable=False)
    consent = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def answers(self):
        try:
            return json.loads(self.answers_json or '{}')
        except Exception:
            return {}


class Match(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)
    user_a_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    user_b_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    score = db.Column(db.Float, nullable=False)
    explanation_json = db.Column(db.Text, nullable=False)
    published = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


QUESTIONS = [
    {'id': 'age', 'section': 'Infos de base', 'text': 'Quel âge as-tu ?', 'kind': 'number', 'min': 18, 'max': 80},
    {'id': 'gender', 'section': 'Infos de base', 'text': 'Comment te définis-tu ?', 'kind': 'single', 'options': [('woman','Femme'),('man','Homme'),('nonbinary','Non-binaire / autre')]},
    {'id': 'seeking_genders', 'section': 'Infos de base', 'text': 'Qui souhaites-tu rencontrer ?', 'kind': 'multi', 'options': [('woman','Femmes'),('man','Hommes'),('nonbinary','Personnes non-binaires / autres')]},
    {'id': 'age_min', 'section': 'Infos de base', 'text': 'Âge minimum recherché', 'kind': 'number', 'min': 18, 'max': 80},
    {'id': 'age_max', 'section': 'Infos de base', 'text': 'Âge maximum recherché', 'kind': 'number', 'min': 18, 'max': 80},
    {'id': 'q01', 'section': 'Personnalité', 'text': 'Je me sens énergisé(e) par les interactions sociales.', 'dim': 'extraversion', 'kind': 'scale'},
    {'id': 'q02', 'section': 'Personnalité', 'text': 'J’aime régulièrement avoir du temps seul(e) pour me ressourcer.', 'dim': 'extraversion', 'kind': 'scale', 'reverse': True},
    {'id': 'q03', 'section': 'Personnalité', 'text': 'J’aime découvrir des idées, cultures ou activités nouvelles.', 'dim': 'openness', 'kind': 'scale'},
    {'id': 'q04', 'section': 'Personnalité', 'text': 'Je préfère les habitudes familières aux expériences nouvelles.', 'dim': 'openness', 'kind': 'scale', 'reverse': True},
    {'id': 'q05', 'section': 'Personnalité', 'text': 'Je planifie généralement les choses à l’avance.', 'dim': 'conscientiousness', 'kind': 'scale'},
    {'id': 'q06', 'section': 'Personnalité', 'text': 'Je suis à l’aise avec beaucoup d’improvisation dans mon quotidien.', 'dim': 'conscientiousness', 'kind': 'scale', 'reverse': True},
    {'id': 'q07', 'section': 'Personnalité', 'text': 'Dans un désaccord, j’essaie spontanément de comprendre le point de vue de l’autre.', 'dim': 'agreeableness', 'kind': 'scale'},
    {'id': 'q08', 'section': 'Personnalité', 'text': 'Je peux être très direct(e), même si cela crée de la tension.', 'dim': 'agreeableness', 'kind': 'scale', 'reverse': True},
    {'id': 'q09', 'section': 'Personnalité', 'text': 'Je reste généralement calme quand les choses ne se passent pas comme prévu.', 'dim': 'emotional_stability', 'kind': 'scale'},
    {'id': 'q10', 'section': 'Personnalité', 'text': 'Les incertitudes relationnelles ont tendance à beaucoup m’occuper l’esprit.', 'dim': 'emotional_stability', 'kind': 'scale', 'reverse': True},

    {'id': 'q11', 'section': 'Valeurs', 'text': 'La famille et les liens proches doivent occuper une place centrale dans ma vie.', 'dim': 'family', 'kind': 'scale'},
    {'id': 'q12', 'section': 'Valeurs', 'text': 'La réussite professionnelle est une priorité importante pour moi.', 'dim': 'ambition', 'kind': 'scale'},
    {'id': 'q13', 'section': 'Valeurs', 'text': 'J’accorde une grande importance à un mode de vie sobre et attentif à son impact environnemental.', 'dim': 'sustainability', 'kind': 'scale'},
    {'id': 'q14', 'section': 'Valeurs', 'text': 'J’ai besoin de préserver une forte autonomie dans une relation.', 'dim': 'autonomy', 'kind': 'scale'},
    {'id': 'q15', 'section': 'Valeurs', 'text': 'La curiosité intellectuelle et les discussions de fond sont importantes pour moi.', 'dim': 'intellectual', 'kind': 'scale'},
    {'id': 'q16', 'section': 'Valeurs', 'text': 'Je recherche une vie très stable et prévisible.', 'dim': 'stability', 'kind': 'scale'},

    {'id': 'q17', 'section': 'Communication', 'text': 'Quand quelque chose me dérange, je préfère en parler rapidement.', 'dim': 'direct_communication', 'kind': 'scale'},
    {'id': 'q18', 'section': 'Communication', 'text': 'Après une dispute, j’ai besoin d’un temps seul(e) avant de reparler.', 'dim': 'cooldown', 'kind': 'scale'},
    {'id': 'q19', 'section': 'Communication', 'text': 'J’aime exprimer souvent mon affection verbalement.', 'dim': 'verbal_affection', 'kind': 'scale'},
    {'id': 'q20', 'section': 'Communication', 'text': 'Pour moi, les gestes et services comptent davantage que les mots.', 'dim': 'acts_affection', 'kind': 'scale'},
    {'id': 'q21', 'section': 'Communication', 'text': 'Je préfère régler un désaccord de manière très factuelle et structurée.', 'dim': 'structured_conflict', 'kind': 'scale'},
    {'id': 'q22', 'section': 'Communication', 'text': 'Je suis à l’aise pour parler de mes émotions en détail.', 'dim': 'emotional_openness', 'kind': 'scale'},

    {'id': 'q23', 'section': 'Mode de vie', 'text': 'J’aime sortir souvent et avoir un agenda social chargé.', 'dim': 'social_rhythm', 'kind': 'scale'},
    {'id': 'q24', 'section': 'Mode de vie', 'text': 'J’apprécie surtout les soirées calmes à la maison.', 'dim': 'home_rhythm', 'kind': 'scale'},
    {'id': 'q25', 'section': 'Mode de vie', 'text': 'Le sport ou l’activité physique fait partie de mon équilibre de vie.', 'dim': 'activity', 'kind': 'scale'},
    {'id': 'q26', 'section': 'Mode de vie', 'text': 'Voyager et changer régulièrement d’environnement est important pour moi.', 'dim': 'travel', 'kind': 'scale'},
    {'id': 'q27', 'section': 'Relation', 'text': 'Je cherche une relation qui puisse devenir sérieuse si la compatibilité est là.', 'dim': 'commitment', 'kind': 'scale'},
    {'id': 'q28', 'section': 'Relation', 'text': 'Je préfère que la relation se construise lentement, sans projection rapide.', 'dim': 'relationship_pace', 'kind': 'scale'},
    {'id': 'q29', 'section': 'Relation', 'text': 'J’aime partager beaucoup d’activités avec la personne que je fréquente.', 'dim': 'togetherness', 'kind': 'scale'},
    {'id': 'q30', 'section': 'Relation', 'text': 'Même en couple, je tiens à garder beaucoup d’activités séparées.', 'dim': 'independence', 'kind': 'scale'},
    {'id': 'q31', 'section': 'Relation', 'text': 'Je suis à l’aise avec les démonstrations d’affection fréquentes.', 'dim': 'affection_frequency', 'kind': 'scale'},
    {'id': 'q32', 'section': 'Relation', 'text': 'La ponctualité et la fiabilité sont très importantes pour moi.', 'dim': 'reliability', 'kind': 'scale'},

    {'id': 'p_values', 'section': 'Ce que je recherche', 'text': 'Importance d’avoir des valeurs proches des miennes.', 'dim': 'pref_values', 'kind': 'scale'},
    {'id': 'p_communication', 'section': 'Ce que je recherche', 'text': 'Importance d’avoir une manière de communiquer proche de la mienne.', 'dim': 'pref_communication', 'kind': 'scale'},
    {'id': 'p_lifestyle', 'section': 'Ce que je recherche', 'text': 'Importance d’avoir un rythme de vie compatible avec le mien.', 'dim': 'pref_lifestyle', 'kind': 'scale'},
    {'id': 'p_personality', 'section': 'Ce que je recherche', 'text': 'Importance d’avoir un tempérament proche du mien.', 'dim': 'pref_personality', 'kind': 'scale'},

    {'id': 't_energy', 'section': 'Questions ouvertes', 'text': 'Qu’est-ce qui te donne le plus d’énergie dans une rencontre ou une relation ?', 'kind': 'text', 'placeholder': 'Ex. les discussions profondes, l’humour, les moments simples, les projets à deux…'},
    {'id': 't_weekend', 'section': 'Questions ouvertes', 'text': 'À quoi ressemble un week-end idéal pour toi ?', 'kind': 'text', 'placeholder': 'Ex. brunch, sport, expo, dîner entre amis, balade, lecture…'},
    {'id': 't_greenflags', 'section': 'Questions ouvertes', 'text': 'Quelles sont les qualités ou green flags qui te touchent le plus chez quelqu’un ?', 'kind': 'text', 'placeholder': 'Ex. écoute, curiosité, fiabilité, humour, douceur…'},
    {'id': 't_growth', 'section': 'Questions ouvertes', 'text': 'Qu’aimerais-tu construire ou partager avec la bonne personne ?', 'kind': 'text', 'placeholder': 'Ex. une relation stable, une complicité, des aventures, une routine douce…'},
    {'id': 't_note', 'section': 'Questions ouvertes', 'text': 'Y a-t-il quelque chose que tu aimerais que ton match sache de toi dès le début ? (sans critère physique)', 'kind': 'text', 'placeholder': 'Ex. ce que tu apprécies chez les autres, ton style de vie, ce que tu cherches…'},
]

PERSONALITY_DIMS = {'extraversion', 'openness', 'conscientiousness', 'agreeableness', 'emotional_stability'}
VALUES_DIMS = {'family', 'ambition', 'sustainability', 'autonomy', 'intellectual', 'stability'}
COMM_DIMS = {'direct_communication', 'cooldown', 'verbal_affection', 'acts_affection', 'structured_conflict', 'emotional_openness'}
LIFESTYLE_DIMS = {'social_rhythm', 'home_rhythm', 'activity', 'travel', 'commitment', 'relationship_pace', 'togetherness', 'independence', 'affection_frequency', 'reliability'}
GENDER_LABELS = {
    'woman': 'Femme',
    'man': 'Homme',
    'nonbinary': 'Non-binaire / autre',
}

CATEGORY_LABELS = {
    'personality': 'tempérament',
    'values': 'valeurs',
    'communication': 'communication',
    'lifestyle': 'mode de vie',
}


def current_user():
    uid = session.get('user_id')
    return db.session.get(User, uid) if uid else None


@app.context_processor
def inject_globals():
    return {'current_user': current_user(), 'site_name': SITE_NAME}


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


def slugify(value):
    value = re.sub(r'[^a-zA-Z0-9]+', '-', value.lower()).strip('-')
    return value or f'event-{secrets.token_hex(3)}'


def ensure_default_event():
    if not Event.query.first():
        db.session.add(Event(name='Soirée pilote', slug='soiree-pilote', description='Événement de démonstration pour tester le service.'))
        db.session.commit()


def generate_code(length=10):
    alphabet = string.ascii_uppercase + string.digits
    while True:
        code = ''.join(secrets.choice(alphabet) for _ in range(length))
        if not InviteCode.query.filter_by(code=code).first():
            return code


def has_match_preferences(user):
    ans = user.answers()
    try:
        age = int(ans.get('age'))
        age_min = int(ans.get('age_min'))
        age_max = int(ans.get('age_max'))
    except (TypeError, ValueError):
        return False
    gender = ans.get('gender')
    seeking = ans.get('seeking_genders')
    return (
        18 <= age <= 80
        and gender in GENDER_LABELS
        and isinstance(seeking, list) and len(seeking) > 0
        and all(g in GENDER_LABELS for g in seeking)
        and 18 <= age_min <= age_max <= 80
    )


def mutually_eligible(u1, u2):
    if not has_match_preferences(u1) or not has_match_preferences(u2):
        return False
    a1, a2 = u1.answers(), u2.answers()
    age1, age2 = int(a1['age']), int(a2['age'])
    return (
        a2['gender'] in a1['seeking_genders']
        and a1['gender'] in a2['seeking_genders']
        and int(a1['age_min']) <= age2 <= int(a1['age_max'])
        and int(a2['age_min']) <= age1 <= int(a2['age_max'])
    )


def profile_vector(user):
    ans = user.answers()
    vector = {}
    for q in QUESTIONS:
        if q.get('kind') != 'scale' or q.get('dim', '').startswith('pref_'):
            continue
        raw = float(ans.get(q['id'], 3))
        vector[q['dim']] = (6 - raw) if q.get('reverse') else raw
    return vector


def category_similarity(v1, v2, dims):
    vals = []
    for d in dims:
        a, b = v1.get(d, 3), v2.get(d, 3)
        vals.append(1 - abs(a - b) / 4)
    return sum(vals) / len(vals) if vals else 0


def summarize_text(text, size=120):
    text = ' '.join((text or '').split())
    if len(text) <= size:
        return text
    return text[:size - 1].rstrip() + '…'


def match_score(u1, u2):
    a1, a2 = u1.answers(), u2.answers()
    v1, v2 = profile_vector(u1), profile_vector(u2)

    sims = {
        'personality': category_similarity(v1, v2, PERSONALITY_DIMS),
        'values': category_similarity(v1, v2, VALUES_DIMS),
        'communication': category_similarity(v1, v2, COMM_DIMS),
        'lifestyle': category_similarity(v1, v2, LIFESTYLE_DIMS),
    }

    raw_weights = {
        'personality': (float(a1.get('p_personality', 3)) + float(a2.get('p_personality', 3))) / 2,
        'values': (float(a1.get('p_values', 3)) + float(a2.get('p_values', 3))) / 2,
        'communication': (float(a1.get('p_communication', 3)) + float(a2.get('p_communication', 3))) / 2,
        'lifestyle': (float(a1.get('p_lifestyle', 3)) + float(a2.get('p_lifestyle', 3))) / 2,
    }
    total_weight = sum(raw_weights.values()) or 1
    score = 100 * sum(sims[k] * raw_weights[k] for k in sims) / total_weight

    if abs(v1.get('commitment', 3) - v2.get('commitment', 3)) >= 3:
        score -= 4
    if abs(v1.get('direct_communication', 3) - v2.get('direct_communication', 3)) >= 3 and raw_weights['communication'] >= 4:
        score -= 2.5
    score = max(0, min(100, score))

    ranked = sorted(sims.items(), key=lambda x: x[1], reverse=True)
    top_labels = [CATEGORY_LABELS[k] for k, _ in ranked[:3]]
    soft_label = CATEGORY_LABELS[ranked[-1][0]]

    explanation = {
        'categories': {k: round(v * 100) for k, v in sims.items()},
        'highlights': [f"Bonne compatibilité sur {CATEGORY_LABELS[k]}" for k, _ in ranked[:3]],
        'narrative': f"Vous semblez particulièrement alignés sur {top_labels[0]}, {top_labels[1]} et {top_labels[2]}.",
        'nuance': f"Le décalage le plus marqué concerne plutôt {soft_label} : ce n’est pas forcément un problème, mais c’est un sujet à apprivoiser.",
        'notes': [
            f"{u1.display_name} : {summarize_text(a1.get('t_note', ''))}" if a1.get('t_note') else '',
            f"{u2.display_name} : {summarize_text(a2.get('t_note', ''))}" if a2.get('t_note') else '',
        ],
    }
    explanation['notes'] = [n for n in explanation['notes'] if n]
    return round(score, 1), explanation


def build_pair_preview(users):
    items = []
    users = list(users)
    for i, u1 in enumerate(users):
        for u2 in users[i + 1:]:
            if not mutually_eligible(u1, u2):
                continue
            score, explanation = match_score(u1, u2)
            items.append({'user_a': u1, 'user_b': u2, 'score': score, 'explanation': explanation})
    return sorted(items, key=lambda x: x['score'], reverse=True)


def rebuild_matches(event_id):
    users = User.query.filter_by(event_id=event_id, profile_complete=True, consent=True).all()
    Match.query.filter_by(event_id=event_id).delete()
    db.session.commit()
    if len(users) < 2:
        return {'count': 0, 'unmatched': None}

    g = nx.Graph()
    for user in users:
        g.add_node(user.id)

    for i, u1 in enumerate(users):
        for u2 in users[i + 1:]:
            if not mutually_eligible(u1, u2):
                continue
            score, explanation = match_score(u1, u2)
            g.add_edge(u1.id, u2.id, weight=score, explanation=explanation)

    pairs = nx.algorithms.matching.max_weight_matching(g, maxcardinality=True, weight='weight')
    paired_ids = set()
    for a, b in pairs:
        data = g.get_edge_data(a, b)
        db.session.add(Match(event_id=event_id, user_a_id=a, user_b_id=b, score=data['weight'], explanation_json=json.dumps(data['explanation'], ensure_ascii=False), published=False))
        paired_ids.update([a, b])

    db.session.commit()
    unmatched = None
    if len(paired_ids) < len(users):
        remaining = [u for u in users if u.id not in paired_ids]
        if remaining:
            unmatched = remaining[0].display_name
    return {'count': len(pairs), 'unmatched': unmatched}


def selected_event_from_request():
    ensure_default_event()
    events = Event.query.order_by(Event.created_at.desc()).all()
    event_id = request.args.get('event_id', type=int) or request.form.get('event_id', type=int)
    selected = db.session.get(Event, event_id) if event_id else None
    if selected is None and events:
        selected = events[0]
    return selected, events


@app.route('/')
def home():
    if current_user():
        return redirect(url_for('profile'))
    return render_template('home.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        code = request.form.get('code', '').strip().upper()
        email = request.form.get('email', '').strip().lower()
        name = request.form.get('display_name', '').strip()
        password = request.form.get('password', '')
        adult = request.form.get('adult') == 'on'
        consent = request.form.get('consent') == 'on'
        invite = InviteCode.query.filter_by(code=code, used=False).first()

        if not invite:
            flash('Code invalide ou déjà utilisé.', 'error')
        elif User.query.filter_by(email=email).first():
            flash('Cette adresse e-mail est déjà utilisée.', 'error')
        elif len(password) < 8:
            flash('Le mot de passe doit contenir au moins 8 caractères.', 'error')
        elif not adult or not consent:
            flash('Tu dois avoir 18 ans ou plus et accepter le traitement des réponses.', 'error')
        else:
            user = User(event_id=invite.event_id, email=email, display_name=name or email.split('@')[0], password_hash=generate_password_hash(password), consent=True)
            db.session.add(user)
            invite.used = True
            db.session.commit()
            session['user_id'] = user.id
            return redirect(url_for('questionnaire'))
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
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


@app.route('/questionnaire', methods=['GET', 'POST'])
@login_required
def questionnaire():
    user = current_user()
    existing = user.answers()
    if request.method == 'POST':
        answers = {}
        for q in QUESTIONS:
            if q['kind'] == 'scale':
                value = request.form.get(q['id'])
                if value not in {'1', '2', '3', '4', '5'}:
                    flash('Merci de répondre à toutes les questions.', 'error')
                    return render_template('questionnaire.html', questions=QUESTIONS, existing=request.form)
                answers[q['id']] = int(value)
            elif q['kind'] == 'text':
                value = ' '.join(request.form.get(q['id'], '').split())
                if len(value) < 6:
                    flash('Merci de compléter les questions ouvertes avec quelques mots.', 'error')
                    return render_template('questionnaire.html', questions=QUESTIONS, existing=request.form)
                answers[q['id']] = value
            elif q['kind'] == 'number':
                try:
                    value = int(request.form.get(q['id'], ''))
                except ValueError:
                    value = None
                if value is None or value < q['min'] or value > q['max']:
                    flash('Merci de renseigner des âges valides.', 'error')
                    return render_template('questionnaire.html', questions=QUESTIONS, existing=request.form)
                answers[q['id']] = value
            elif q['kind'] == 'single':
                value = request.form.get(q['id'])
                allowed = {key for key, _ in q['options']}
                if value not in allowed:
                    flash('Merci de renseigner ton genre.', 'error')
                    return render_template('questionnaire.html', questions=QUESTIONS, existing=request.form)
                answers[q['id']] = value
            elif q['kind'] == 'multi':
                values = request.form.getlist(q['id'])
                allowed = {key for key, _ in q['options']}
                values = [v for v in values if v in allowed]
                if not values:
                    flash('Merci d’indiquer qui tu souhaites rencontrer.', 'error')
                    return render_template('questionnaire.html', questions=QUESTIONS, existing=request.form)
                answers[q['id']] = values
        if answers['age_min'] > answers['age_max']:
            flash('L’âge minimum recherché doit être inférieur ou égal à l’âge maximum.', 'error')
            return render_template('questionnaire.html', questions=QUESTIONS, existing=request.form)
        user.answers_json = json.dumps(answers, ensure_ascii=False)
        user.profile_complete = True
        # Any change to preferences can make existing pairings invalid.
        Match.query.filter_by(event_id=user.event_id).delete(synchronize_session=False)
        db.session.commit()
        flash('Ton profil a bien été enregistré.', 'success')
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
    event = db.session.get(Event, user.event_id)
    return render_template('profile.html', user=user, sections=sections, event=event, gender_labels=GENDER_LABELS)


@app.route('/match')
@login_required
def my_match():
    user = current_user()
    match = Match.query.filter(Match.published.is_(True), Match.event_id == user.event_id, ((Match.user_a_id == user.id) | (Match.user_b_id == user.id))).order_by(Match.created_at.desc()).first()
    partner = None
    explanation = None
    if match:
        partner_id = match.user_b_id if match.user_a_id == user.id else match.user_a_id
        partner = db.session.get(User, partner_id)
        explanation = json.loads(match.explanation_json)
    event = db.session.get(Event, user.event_id)
    return render_template('match.html', match=match, partner=partner, explanation=explanation, event=event)


@app.route('/delete-account', methods=['POST'])
@login_required
def delete_account():
    user = current_user()
    Match.query.filter(((Match.user_a_id == user.id) | (Match.user_b_id == user.id))).delete(synchronize_session=False)
    db.session.delete(user)
    db.session.commit()
    session.clear()
    flash('Compte supprimé.', 'success')
    return redirect(url_for('home'))


@app.route('/privacy')
def privacy():
    return render_template('privacy.html')


@app.route('/admin', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        if secrets.compare_digest(request.form.get('password', ''), os.getenv('ADMIN_PASSWORD', 'change-me')):
            session['admin'] = True
            return redirect(url_for('admin_dashboard'))
        flash('Mot de passe administrateur incorrect.', 'error')
    return render_template('admin_login.html')


@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    selected_event, events = selected_event_from_request()
    users, invites, matches, preview_pairs, stats = [], [], [], [], {}
    if selected_event:
        users = User.query.filter_by(event_id=selected_event.id).order_by(User.created_at.desc()).all()
        invites = InviteCode.query.filter_by(event_id=selected_event.id).order_by(InviteCode.created_at.desc()).limit(60).all()
        matches = Match.query.filter_by(event_id=selected_event.id).order_by(Match.score.desc()).all()
        ready_users = [u for u in users if u.profile_complete and u.consent and has_match_preferences(u)]
        preview_pairs = build_pair_preview(ready_users)[:16]
        stats = {
            'participants': len(users),
            'completed': len([u for u in users if u.profile_complete]),
            'ready': len(ready_users),
            'codes_available': InviteCode.query.filter_by(event_id=selected_event.id, used=False).count(),
            'codes_used': InviteCode.query.filter_by(event_id=selected_event.id, used=True).count(),
            'published_pairs': Match.query.filter_by(event_id=selected_event.id, published=True).count(),
            'draft_pairs': Match.query.filter_by(event_id=selected_event.id, published=False).count(),
        }
    name_map = {u.id: u.display_name for u in users}
    readiness_map = {u.id: (u.profile_complete and u.consent and has_match_preferences(u)) for u in users}
    invite_message = ''
    if selected_event:
        invite_message = (
            f"Bonjour ✨\nVoici ton invitation {SITE_NAME} pour « {selected_event.name} ».\n"
            f"Lien : [ton-url]/register\n"
            f"Code personnel : [CODE]\n\n"
            f"Le matching repose uniquement sur la personnalité, les valeurs et la compatibilité."
        )
    return render_template('admin_dashboard.html', events=events, selected_event=selected_event, users=users, invites=invites, matches=matches, preview_pairs=preview_pairs, name_map=name_map, readiness_map=readiness_map, stats=stats, invite_message=invite_message)


@app.route('/admin/events', methods=['POST'])
@admin_required
def admin_create_event():
    name = ' '.join(request.form.get('name', '').split())
    description = ' '.join(request.form.get('description', '').split())
    if len(name) < 3:
        flash('Donne un nom plus explicite à l’événement.', 'error')
        return redirect(url_for('admin_dashboard'))
    base_slug = slugify(name)
    slug = base_slug
    i = 2
    while Event.query.filter_by(slug=slug).first():
        slug = f"{base_slug}-{i}"
        i += 1
    event = Event(name=name, slug=slug, description=description)
    db.session.add(event)
    db.session.commit()
    flash('Événement créé.', 'success')
    return redirect(url_for('admin_dashboard', event_id=event.id))


@app.route('/admin/invites', methods=['POST'])
@admin_required
def admin_invites():
    event_id = request.form.get('event_id', type=int)
    event = db.session.get(Event, event_id)
    if not event:
        flash('Événement introuvable.', 'error')
        return redirect(url_for('admin_dashboard'))
    count = min(max(int(request.form.get('count', 1)), 1), 200)
    for _ in range(count):
        db.session.add(InviteCode(code=generate_code(), event_id=event.id))
    db.session.commit()
    flash(f'{count} code(s) créé(s) pour « {event.name} ».', 'success')
    return redirect(url_for('admin_dashboard', event_id=event.id))


@app.route('/admin/matches/rebuild', methods=['POST'])
@admin_required
def admin_rebuild_matches():
    event_id = request.form.get('event_id', type=int)
    event = db.session.get(Event, event_id)
    if not event:
        flash('Événement introuvable.', 'error')
        return redirect(url_for('admin_dashboard'))
    result = rebuild_matches(event.id)
    msg = f"{result['count']} paire(s) calculée(s) pour « {event.name} »."
    if result['unmatched']:
        msg += f" {result['unmatched']} reste sans match pour l’instant."
    flash(msg, 'success')
    return redirect(url_for('admin_dashboard', event_id=event.id))


@app.route('/admin/matches/publish', methods=['POST'])
@admin_required
def admin_publish_matches():
    event_id = request.form.get('event_id', type=int)
    event = db.session.get(Event, event_id)
    if not event:
        flash('Événement introuvable.', 'error')
        return redirect(url_for('admin_dashboard'))
    Match.query.filter_by(event_id=event.id).update({'published': True})
    db.session.commit()
    flash(f'Les matchs de « {event.name} » ont été publiés.', 'success')
    return redirect(url_for('admin_dashboard', event_id=event.id))


@app.route('/admin/matches/unpublish', methods=['POST'])
@admin_required
def admin_unpublish_matches():
    event_id = request.form.get('event_id', type=int)
    event = db.session.get(Event, event_id)
    if not event:
        flash('Événement introuvable.', 'error')
        return redirect(url_for('admin_dashboard'))
    Match.query.filter_by(event_id=event.id).update({'published': False})
    db.session.commit()
    flash(f'Les matchs de « {event.name} » sont repassés en brouillon.', 'success')
    return redirect(url_for('admin_dashboard', event_id=event.id))


@app.route('/admin/logout')
def admin_logout():
    session.pop('admin', None)
    return redirect(url_for('admin_login'))


@app.cli.command('init-db')
def init_db():
    db.drop_all()
    db.create_all()
    ensure_default_event()
    event = Event.query.order_by(Event.created_at.asc()).first()
    codes = []
    for _ in range(5):
        code = generate_code()
        db.session.add(InviteCode(code=code, event_id=event.id))
        codes.append(code)
    db.session.commit()
    print('Database ready.')
    print('Initial invite codes:', ', '.join(codes))


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        ensure_default_event()
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)), debug=os.getenv('FLASK_DEBUG') == '1')
