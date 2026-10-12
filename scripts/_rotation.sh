# Rotation des journaux, partagée par cycle.sh et serve_embeddings.sh.
#
# rotate_log FICHIER : au-delà de LOG_MAX_OCTETS (10 Mio par défaut),
# FICHIER devient FICHIER.1, FICHIER.1 devient FICHIER.2, et ainsi de
# suite jusqu'à LOG_ARCHIVES (5 par défaut) ; la plus ancienne disparaît.
# À appeler avant d'ouvrir le fichier, jamais pendant qu'un processus y
# écrit encore.
rotate_log() {
    local file=$1
    local max=${LOG_MAX_OCTETS:-10485760}
    local keep=${LOG_ARCHIVES:-5}
    local index
    [[ -f $file ]] || return 0
    (( $(wc -c < "$file") > max )) || return 0
    rm -f "$file.$keep"
    for (( index = keep - 1; index >= 1; index-- )); do
        if [[ -f $file.$index ]]; then
            mv "$file.$index" "$file.$(( index + 1 ))"
        fi
    done
    mv "$file" "$file.1"
}
