# ═══════════════════════════════════════════════════════════════════
# BIKES PROMPTS
# ═══════════════════════════════════════════════════════════════════

TEXT_ONLY_PROMPT = """Tu es un expert du marché du vélo d'occasion en Île-de-France, spécialisé dans l'achat-revente. On te présente une annonce leboncoin. Détermine si c'est une bonne affaire pour un revendeur.

Lis attentivement l'intégralité de l'annonce ci-dessous — titre, prix, description — pour comprendre exactement ce qui est vendu, dans quel état, et à quel prix réel.

---
Titre: {title}
Prix affiché: {price}€
Localisation: {location}

Description du vendeur:
{description}
---

Réponds UNIQUEMENT en JSON valide:

{{
  "item_name": "identification complète (marque + modèle + année si possible)",
  "brand": "marque identifiée ou 'inconnu'",
  "model": "modèle identifié ou 'inconnu'",
  "condition": "comme_neuf | bon_état | état_correct | mauvais_état",
  "confidence": 0.0-1.0,
  "estimated_resale_min": prix revente minimum réaliste EUR,
  "estimated_resale_max": prix revente maximum réaliste EUR,
  "reasoning": "2-3 phrases: ce que tu achètes exactement pour le prix affiché, pourquoi c'est (ou pas) une bonne affaire, sur quoi tu bases ton estimation de revente"
}}

Contexte marché: Île-de-France, printemps/été 2026. Le revendeur nettoiera le vélo et fera de belles photos. Base tes estimations sur les prix réels leboncoin et troc-velo. Abréviations courantes: TBE = très bon état, BE = bon état, RAS = rien à signaler."""


VISION_PROMPT = """Tu es un expert du marché du vélo d'occasion en Île-de-France, spécialisé dans l'achat-revente. On te présente une annonce leboncoin avec ses photos. Détermine si c'est une bonne affaire pour un revendeur.

Lis attentivement l'intégralité de l'annonce et analyse les photos pour comprendre exactement ce qui est vendu, dans quel état, et à quel prix réel.

---
Titre: {title}
Prix affiché: {price}€
Localisation: {location}

Description du vendeur:
{description}
---

Les photos sont jointes. Utilise-les pour identifier marque, modèle, matériaux, état réel, et tout ce que le vendeur a pu manquer (logos, composants premium, défauts cachés).

Réponds UNIQUEMENT en JSON valide:

{{
  "item_name": "identification complète",
  "brand": "marque identifiée ou 'inconnu'",
  "model": "modèle identifié ou 'inconnu'",
  "condition": "comme_neuf | bon_état | état_correct | mauvais_état",
  "condition_details": "observations concrètes depuis les photos",
  "red_flags": [],
  "hidden_value": [],
  "confidence": 0.0-1.0,
  "estimated_resale_min": prix revente minimum réaliste EUR,
  "estimated_resale_max": prix revente maximum réaliste EUR,
  "reasoning": "2-3 phrases: ce que tu achètes exactement pour le prix affiché, pourquoi c'est (ou pas) une bonne affaire, sur quoi tu bases ton estimation de revente"
}}

Contexte marché: Île-de-France, printemps/été 2026. Le revendeur nettoiera le vélo et fera de belles photos. Base tes estimations sur les prix réels leboncoin et troc-velo."""


# ═══════════════════════════════════════════════════════════════════
# FURNITURE PROMPTS
# ═══════════════════════════════════════════════════════════════════

FURNITURE_TEXT_ONLY_PROMPT = """Tu es un expert du marché du mobilier design et vintage en France, spécialisé dans l'achat-revente. On te présente une annonce leboncoin. Détermine si c'est une bonne affaire pour un revendeur.

Lis attentivement l'intégralité de l'annonce ci-dessous — titre, prix, description — pour comprendre exactement ce qui est vendu, dans quel état, et à quel prix réel.

---
Titre: {title}
Prix affiché: {price}€
Localisation: {location}

Description du vendeur:
{description}
---

Réponds UNIQUEMENT en JSON valide:

{{
  "item_name": "identification complète (designer/marque + modèle + type)",
  "brand": "marque ou maison de design, ou 'inconnu'",
  "model": "modèle ou 'inconnu'",
  "designer": "designer ou 'inconnu'",
  "era": "période estimée ou 'inconnu'",
  "condition": "comme_neuf | bon_état | état_correct | mauvais_état",
  "confidence": 0.0-1.0,
  "estimated_resale_min": prix revente minimum réaliste EUR,
  "estimated_resale_max": prix revente maximum réaliste EUR,
  "reasoning": "2-3 phrases: ce que tu achètes exactement pour le prix affiché, pourquoi c'est (ou pas) une bonne affaire, sur quoi tu bases ton estimation de revente"
}}

Contexte marché: Île-de-France 2026. Le revendeur nettoiera l'objet et fera de belles photos. Base tes estimations sur les prix réels Selency, Design Market, Kolectiv Design, eBay.fr et leboncoin. La patine est un plus pour le vintage. Abréviations courantes: TBE = très bon état, BE = bon état."""


FURNITURE_VISION_PROMPT = """Tu es un expert du marché du mobilier design et vintage en France, spécialisé dans l'achat-revente. On te présente une annonce leboncoin avec ses photos. Détermine si c'est une bonne affaire pour un revendeur.

Lis attentivement l'intégralité de l'annonce et analyse les photos pour comprendre exactement ce qui est vendu, dans quel état, et à quel prix réel.

---
Titre: {title}
Prix affiché: {price}€
Localisation: {location}

Description du vendeur:
{description}
---

Les photos sont jointes. Utilise-les pour identifier designer, marque, matériaux, époque, état réel, et tout ce que le vendeur a pu manquer (étiquettes sous la chaise, formes iconiques, matériaux nobles).

Réponds UNIQUEMENT en JSON valide:

{{
  "item_name": "identification complète",
  "brand": "marque/maison de design ou 'inconnu'",
  "model": "modèle ou 'inconnu'",
  "designer": "designer ou 'inconnu'",
  "era": "période estimée ou 'inconnu'",
  "condition": "comme_neuf | bon_état | état_correct | mauvais_état",
  "condition_details": "observations concrètes depuis les photos",
  "red_flags": [],
  "hidden_value": [],
  "confidence": 0.0-1.0,
  "estimated_resale_min": prix revente minimum réaliste EUR,
  "estimated_resale_max": prix revente maximum réaliste EUR,
  "reasoning": "2-3 phrases: ce que tu achètes exactement pour le prix affiché, pourquoi c'est (ou pas) une bonne affaire, sur quoi tu bases ton estimation de revente"
}}

Contexte marché: Île-de-France 2026. Le revendeur nettoiera l'objet et fera de belles photos. Base tes estimations sur les prix réels Selency, Design Market, Kolectiv Design, eBay.fr et leboncoin. La patine est un plus pour le vintage."""


# ═══════════════════════════════════════════════════════════════════
# PROMPT REGISTRY — maps category → (text_prompt, vision_prompt)
# ═══════════════════════════════════════════════════════════════════

PROMPTS = {
    "bikes": (TEXT_ONLY_PROMPT, VISION_PROMPT),
    "furniture": (FURNITURE_TEXT_ONLY_PROMPT, FURNITURE_VISION_PROMPT),
}
