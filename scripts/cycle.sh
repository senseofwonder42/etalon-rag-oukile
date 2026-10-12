#!/usr/bin/env bash
# Un cycle complet : promotion des arbitrages, puis rédaction des
# brouillons pour les cas passés en A_REGENERER.
#
# Variables attendues : ID_A et ID_B (projets Kili), DOCUMENTS_DIR (PDF
# sources). Facultatives : UV (chemin de uv, utile sous cron),
# OPTIONS_REGENERATION (par exemple « --hors-ligne »).
#
# Deux cycles ne se chevauchent jamais : `flock` sort sans rien faire si
# un cycle tourne encore. Ni l'un ni l'autre ne demande de droits sudo.
set -euo pipefail

cd "$(dirname "$0")/.."
: "${ID_A:?ID_A non renseigné}"
: "${ID_B:?ID_B non renseigné}"
: "${DOCUMENTS_DIR:?DOCUMENTS_DIR non renseigné}"
UV="${UV:-uv}"

exec 9>"${TMPDIR:-/tmp}/rag-referentiel-cycle.lock"
flock -n 9 || { echo "Un cycle tourne déjà : rien à faire."; exit 0; }

"$UV" run python scripts/promote.py \
    --projet-referentiel "$ID_A" --projet-revue "$ID_B" \
    --documents "$DOCUMENTS_DIR"
# shellcheck disable=SC2086 # options volontairement découpées
"$UV" run python scripts/regenerate.py \
    --projet-referentiel "$ID_A" --projet-revue "$ID_B" \
    --documents "$DOCUMENTS_DIR" ${OPTIONS_REGENERATION:-}
