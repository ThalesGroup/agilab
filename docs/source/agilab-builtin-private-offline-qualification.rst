Qualification hors ligne des applications AGILAB
================================================

Le harnais ``tools/testing/agilab_offline_app_qualification.py`` exécute des
contrôles explicitement choisis avec des environnements déjà provisionnés. Il
n'installe aucune dépendance. Les manifestes, les données et les reçus privés
restent dans un répertoire de qualification extérieur au dépôt public.

Manifeste et commande
--------------------

Le schéma est ``agilab.offline_app_qualification_manifest.v1``. Chaque source
déclare un ``root`` absolu, sa révision Git exacte de 40 caractères et des
``paths`` relatifs. Chaque contrôle fournit ``id``, ``app``, ``layer``, ``scope``,
``argv`` et ``cwd``. Les couches sont ``science``, ``web`` et ``notebook``.

Utiliser un Python absolu propre à l'environnement isolé dans ``argv`` et
``control_python``. ``env`` complète son environnement ; ``timeout`` vaut entre
1 et 1800 secondes. ``network`` choisit ``deny_all`` ou ``loopback``.
``{output}`` est remplacé dans les arguments par le répertoire de preuves.
Un ``junit`` désigne un XML de tests exécutés ; ``json_evidence`` désigne un JSON
dont ``status`` doit valoir ``passed``. ``artifacts`` déclare les autres fichiers
à conserver et à vérifier. Ces chemins de preuves sont relatifs à la sortie.

Exemple de commande, après création d'un manifeste contenant de vrais contrôles
scientifiques et des chemins absolus résolus :

.. code-block:: console

   tokki run -- uv run --no-sync python tools/testing/agilab_offline_app_qualification.py \
     --manifest "$QUALIFICATION_ROOT/agilab_offline_science_manifest.json" \
     --output-dir "$QUALIFICATION_ROOT/agilab_offline_science_evidence"

La sortie doit être nouvelle. Une session agent gérée emploie le préfixe
authentifié fourni par son hook pour cette commande. Un nom de test, un import
réussi ou une sortie zéro ne suffit pas à établir une fonction scientifique.

Sources et reçus
----------------

Le harnais vérifie la révision, l'absence de modifications suivies et les hashes
des sources avant et après exécution. Il refuse les entrées non suivies dans les
périmètres déclarés, y compris le code masqué par des règles Git d'exclusion.
Les caches Python canoniques sont liés à une source suivie et leurs octets sont
hashés, même pour un périmètre limité à un fichier. Les caches de test et de
typage non exécutables, les métadonnées de construction reconnues et ``uv.lock``
restent des sous-produits exclus. Le bytecode sans source et le code ajouté dans
un répertoire portant un nom de cache sont refusés.

Le hash du manifeste correspond aux octets lus avant le calcul. Une modification
du manifeste, du harnais ou des entrées liées invalide la qualification. Les
preuves JSON imbriquées gardent leur chemin relatif complet. Vérifier aussi les
modules effectivement chargés, leur ``__file__`` et le bundle des vues : une
révision déclarée ne choisit pas automatiquement les imports de l'environnement.

Chaque reçu conserve les contrôles réseau, la portée annoncée, les sorties et
leurs hashes. Les tests entièrement ignorés restent bloqués. Les couches non
exécutées restent non qualifiées. Une reprise crée de nouveaux reçus ; les
échecs et les contrôles ignorés précédents restent intacts.

Réseau et processus
------------------

Le backend actuel nécessite macOS et ``sandbox-exec``. ``deny_all`` refuse le
réseau, y compris la boucle locale. ``loopback`` autorise la boucle locale et les
sockets Unix nécessaires au navigateur et au noyau Jupyter ; les connexions IP
externes restent refusées. Les sondes vérifient le refus externe dans le
processus et un enfant avant les contrôles. Cela décrit une exécution contrainte
par le système, sans établir un isolement physique du poste.

Le nettoyage lie les descendants observés à leur PID et à leur instant de
création. Un enfant détaché observé est arrêté et vérifié ; une erreur concernant
un processus vivant reste un échec. Ce mécanisme ne garantit pas le confinement
d'un descendant très rapidement daemonisé avant son observation.

Provisionnement et portée vérifiée le 8 octobre 2026
--------------------------------------------------

Provisionner les fermetures de dépendances des gestionnaires, travailleurs et
contrôles choisis dans des environnements et caches dédiés hors dépôt. Les
téléchargements appartiennent à cette phase préalable. En exécution, le réseau
externe reste bloqué et aucune installation n'est effectuée. Conserver les logs,
les versions, les contrôles de cohérence et les hashes ; préserver les
environnements de l'utilisateur et les données absentes.

Les preuves existantes couvrent 14 projets intégrés et 9 projets privés par des
périmètres scientifiques réels explicitement nommés. Au total, les périmètres
réussis contiennent 212 cas JUnit exécutés sans cas ignoré, dont 96 contrôles de
planification et de contrôle du CLI privé. Des travailleurs réels et un dispatch
multi-application produisent également des artefacts vérifiés hors JUnit.

Ces résultats ne qualifient pas toutes les fonctions de chaque application.
Le dataplane réel du CLI reste bloqué sur macOS : il exige un noyau Linux, les
outils réseau et les privilèges nécessaires au contrôle réel. Les contrôles de
planification ne remplacent pas cette exécution.

La vue native spécialisée et l'export spécialisé commun exécuté dans un noyau
frais disposent de preuves séparées. Les anciens notebooks de test avec des
données externes absentes ne constituent pas des workflows exposés qualifiés.
Le bundle d'un nouveau candidat doit recevoir sa propre vérification de parité
web et notebook avant de reprendre les résultats d'une version précédente.
