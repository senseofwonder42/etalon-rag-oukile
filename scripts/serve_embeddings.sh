#!/usr/bin/env bash
# Serveur d'embeddings local : llama-server expose les poids Jina v5
# téléchargés par download_embeddings.py, en API compatible OpenAI
# (`/v1/embeddings`, `/v1/models`). C'est lui qu'appelle monitor_run.py.
#
# Usage : scripts/serve_embeddings.sh start|stop|restart|status
#
# Variables facultatives : MODELS_DIR (models), EMBEDDINGS_HOST
# (127.0.0.1), EMBEDDINGS_PORT (8080, à accorder avec JINA_BASE_URL),
# EMBEDDING_MODEL (alias exposé, à accorder avec le .env).
#
# Aucun droit sudo. Le serveur ne survit pas à un redémarrage : ajouter
# `@reboot cd /chemin/du/projet && scripts/serve_embeddings.sh start` à la
# crontab si elle est permise.
set -euo pipefail

cd "$(dirname "$0")/.."
# shellcheck source=scripts/_rotation.sh
source scripts/_rotation.sh

MODELS_DIR="${MODELS_DIR:-models}"
HOST="${EMBEDDINGS_HOST:-127.0.0.1}"
PORT="${EMBEDDINGS_PORT:-8080}"
ALIAS="${EMBEDDING_MODEL:-jina-embeddings-v5-text-small-text-matching}"
LOG_FILE="logs/embeddings.log"
PID_FILE="logs/embeddings.pid"

running() {
    [[ -f $PID_FILE ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null
}

healthy() {
    curl -fsS "http://$HOST:$PORT/health" > /dev/null 2>&1
}

start() {
    if running; then
        echo "Déjà lancé (PID $(cat "$PID_FILE"))."
        return 0
    fi
    local server model
    server=$(find "$MODELS_DIR/llama.cpp" -type f -name llama-server \
        2>/dev/null | head -n 1 || true)
    model=$(find "$MODELS_DIR" -maxdepth 1 -name '*.gguf' 2>/dev/null \
        | head -n 1 || true)
    if [[ -z $server || -z $model ]]; then
        echo "llama-server ou poids GGUF introuvables dans $MODELS_DIR :"
        echo "lancer d'abord scripts/download_embeddings.py."
        exit 1
    fi
    mkdir -p logs
    rotate_log "$LOG_FILE"
    # -c, -b et -ub : un texte doit tenir dans un seul lot pour être
    # encodé ; 8 192 jetons couvrent largement une question.
    nohup "$server" --model "$model" --alias "$ALIAS" \
        --embedding --pooling last \
        --host "$HOST" --port "$PORT" \
        --ctx-size 8192 --batch-size 8192 --ubatch-size 8192 \
        >> "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    for _ in $(seq 120); do
        if healthy; then
            echo "Prêt : http://$HOST:$PORT/v1 — modèle « $ALIAS »."
            return 0
        fi
        if ! running; then
            break
        fi
        sleep 1
    done
    echo "Le serveur n'a pas démarré. Fin de $LOG_FILE :"
    tail -n 20 "$LOG_FILE"
    stop > /dev/null
    exit 1
}

stop() {
    if running; then
        kill "$(cat "$PID_FILE")"
        echo "Arrêté."
    else
        echo "Pas lancé."
    fi
    rm -f "$PID_FILE"
}

status() {
    if running && healthy; then
        echo "En marche (PID $(cat "$PID_FILE")) : http://$HOST:$PORT/v1"
    elif running; then
        echo "Processus présent (PID $(cat "$PID_FILE")) mais /health ne répond pas."
        exit 1
    else
        echo "Arrêté."
        exit 1
    fi
}

case "${1:-}" in
    start) start ;;
    stop) stop ;;
    restart) stop; start ;;
    status) status ;;
    *) echo "Usage : $0 start|stop|restart|status"; exit 2 ;;
esac
