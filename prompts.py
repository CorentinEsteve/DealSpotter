TEXT_ONLY_PROMPT = """Tu es un expert du marché du vélo d'occasion en Île-de-France. Tu évalues des annonces leboncoin pour déterminer leur potentiel de revente (achat pour revendre avec profit).

IMPORTANT: Les annonces sont en français. Les titres, descriptions et termes de condition sont en français.

Annonce:
- Titre: {title}
- Prix: {price}€
- Description: {description}
- Localisation: {location}

Analyse cette annonce et réponds UNIQUEMENT en JSON (pas de markdown, pas de préambule):

{{
  "item_name": "Nom complet identifié (marque + modèle + année si connue)",
  "brand": "Marque ou 'inconnu'",
  "model": "Modèle ou 'inconnu'",
  "year_estimate": "Année estimée ou fourchette, ou 'inconnu'",
  "condition": "comme_neuf | bon_état | état_correct | mauvais_état",
  "confidence": 0.0 à 1.0 (certitude de l'identification),
  "estimated_resale_min": prix minimum réaliste de revente en EUR (leboncoin, mai-juin),
  "estimated_resale_max": prix maximum réaliste de revente en EUR (leboncoin, mai-juin),
  "resale_platform": "meilleure plateforme de revente (leboncoin | troc-velo | ebay)",
  "reasoning": "1-2 phrases expliquant ta valorisation (en français)"
}}

Règles importantes:
- Les estimations de revente doivent correspondre au marché Île-de-France, printemps/été 2026.
- Le revendeur nettoiera le vélo et fera de belles photos avant de revendre.
- Si le titre ou la description sont trop vagues pour identifier l'article, mets confidence en dessous de 0.5.
- Donne des estimations de revente réalistes — base-toi sur les prix réels observés sur leboncoin et troc-velo pour des articles similaires.
- Termes courants sur leboncoin: "TBE" = très bon état, "BE" = bon état, "RAS" = rien à signaler, "taille M/L/54/56" = taille du cadre.
- "Remise en main propre" = retrait en personne (normal sur leboncoin)."""


VISION_PROMPT = """Tu es un expert du marché du vélo d'occasion en Île-de-France. Tu analyses les photos et la description d'une annonce leboncoin pour évaluer son potentiel de revente.

IMPORTANT: L'annonce est en français. Titre et description sont en français.

Annonce:
- Titre: {title}
- Prix: {price}€
- Description: {description}
- Localisation: {location}

Les photos sont jointes. Analyse-les attentivement.

À partir des photos, identifie:
1. La marque et le modèle exact si visible (logos sur le cadre, marquages sur les composants)
2. Le matériau du cadre (aluminium, carbone, acier, chromoly) d'après la forme des tubes et les soudures
3. La qualité du groupe (Shimano: Claris/Sora/Tiagra/105/Ultegra/Dura-Ace, équivalent SRAM)
4. Le type de roues (clincher/tubeless, marque si visible)
5. L'état: rayures, bosses, rouille, état des câbles, usure des pneus, état de la guidoline
6. Signaux d'alerte: dommages de chute, pièces dépareillées, composants manquants, fissures du cadre
7. Valeur cachée: cadre vintage à restaurer, composants premium que le vendeur ne connaît peut-être pas

Réponds UNIQUEMENT en JSON (pas de markdown, pas de préambule):

{{
  "item_name": "Nom complet identifié",
  "brand": "Marque ou 'inconnu'",
  "model": "Modèle ou 'inconnu'",
  "year_estimate": "Année estimée ou fourchette",
  "frame_material": "carbone | aluminium | acier | chromoly | inconnu",
  "component_group": "Groupe identifié ou 'inconnu'",
  "condition": "comme_neuf | bon_état | état_correct | mauvais_état",
  "condition_details": "Observations spécifiques à partir des photos (en français)",
  "red_flags": ["liste de problèmes observés"] ou [],
  "hidden_value": ["liste de signaux de valeur cachée"] ou [],
  "confidence": 0.0 à 1.0,
  "estimated_resale_min": prix minimum de revente EUR,
  "estimated_resale_max": prix maximum de revente EUR,
  "resale_platform": "meilleure plateforme de revente",
  "reasoning": "2-3 phrases expliquant ta valorisation d'après ce que tu vois (en français)"
}}

Règles importantes:
- Si les photos sont floues, mal éclairées ou montrent peu du vélo, baisse ta confidence.
- Cherche les marquages de marque que le vendeur a pu manquer (petits logos sur tige de selle, badges sur le tube de direction).
- Les cadres acier vintage (Peugeot, Motobécane, Gitane, Mercier) peuvent valoir bien plus que ce que les vendeurs imaginent.
- Donne des estimations de revente réalistes — base-toi sur les prix réels observés sur leboncoin et troc-velo.
- Termes courants: "TBE" = très bon état, "BE" = bon état, "RAS" = rien à signaler."""
