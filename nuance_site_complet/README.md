# Nüance — site de rencontre par personnalité

Prototype full-stack : invitations par code, création de compte, questionnaire sans critère physique, profil modifiable, calcul global des paires, publication du match et espace administrateur.

## Lancer sur ton Mac

1. Installe Python 3.11+ si nécessaire.
2. Ouvre Terminal dans ce dossier.
3. Exécute :

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export SECRET_KEY="une-cle-longue-et-secrete"
export ADMIN_PASSWORD="ton-mot-de-passe-admin"
flask --app app init-db
flask --app app run
```

4. Ouvre `http://127.0.0.1:5000`.
5. Admin : `http://127.0.0.1:5000/admin`.

La commande `init-db` crée 5 premiers codes d'invitation et les affiche dans le terminal.

## Prise en main

- **Créer des invitations** : connecte-toi à `/admin`, choisis un nombre de codes et clique sur Générer. Envoie un code unique à chaque participant par mail ou message avec le lien `/register`.
- **Participant** : il crée son compte avec le code, remplit le questionnaire, puis retrouve ses réponses dans **Profil**. Il peut les modifier avant le matching.
- **Calculer les matchs** : dans l’admin, clique sur **Recalculer tous les matchs**. Le moteur cherche la combinaison globale de paires qui maximise la compatibilité de l’ensemble du groupe.
- **Publier** : vérifie que le groupe est prêt puis clique sur **Publier les matchs**. Chaque participant verra alors son partenaire dans l’onglet **Match**.
- **Nouveau tour** : si des réponses changent ou si de nouveaux participants arrivent, recalcule puis republie.

## Logique de compatibilité

Le questionnaire couvre : personnalité inspirée du modèle Big Five, valeurs, communication, gestion des désaccords, mode de vie et attentes relationnelles. Les préférences de chaque personne déterminent aussi le poids relatif de ces catégories. Le moteur privilégie surtout la similarité/compatibilité plutôt que l’idée simpliste que « les opposés s’attirent ». Le score sert à classer les paires du groupe ; ce n’est pas une prédiction scientifique de la réussite d’une relation.

## Mise en ligne

Le site peut être déployé tel quel sur Render, Railway ou un VPS. Pour un vrai lancement public :

- utilise PostgreSQL plutôt que SQLite via `DATABASE_URL` ;
- définis `SECRET_KEY` et `ADMIN_PASSWORD` dans les variables d’environnement de l’hébergeur ;
- active HTTPS ;
- ajoute ton nom de domaine ;
- complète la page Confidentialité avec ton identité juridique, contact RGPD, durée de conservation et hébergeur ;
- ajoute un système de récupération de mot de passe et, si tu veux des invitations automatiques, un prestataire e-mail transactionnel ;
- fais relire les mentions légales et la politique de confidentialité avant lancement commercial.

## Accès “IA / ChatGPT”

ChatGPT n’a pas accès automatiquement aux données de ce site. Le prototype fait donc le matching directement dans le serveur, de façon reproductible. Si tu veux ensuite une couche IA pour expliquer les matchs ou enrichir le calcul, branche une API côté serveur uniquement, avec consentement explicite et en minimisant les données envoyées. Ne mets jamais une clé API dans le navigateur.

## Important pour ton concept

Cette version n’utilise **aucune photo, taille, poids, couleur de cheveux, attractivité ou autre critère physique**. Elle ne demande pas non plus d’origine, religion ou opinion politique. Le groupe d’utilisateurs invité doit déjà être constitué de personnes éligibles à se rencontrer entre elles ; cela évite d’utiliser des catégories sensibles pour filtrer les personnes.
