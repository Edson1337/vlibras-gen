#!/usr/bin/env python3
"""
bridge.py — Conecta vlibras-video-api:3.2.1 ao video_container (worker antigo).

Usa multiprocessing para isolar os consumers de cada fila, evitando
problemas de thread-safety do pika e consumers duplicados.

Processos:
  - file_server : HTTP server servindo uploads para o extractor.py baixar .srt
  - consumer_core   : core → requests  (novo → antigo)
  - consumer_libras : libras → PostgreSQL (resultado do renderer)
"""

import json
import logging
import multiprocessing
import os
import shutil
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

import pika
import psycopg2

# ── Logging ──────────────────────────────────────────────────────────────────

def setup_logging(name: str):
    logging.basicConfig(
        level=logging.INFO,
        format=f"%(asctime)s | %(levelname)s | {name} | %(message)s",
    )
    return logging.getLogger(name)

# ── Config ───────────────────────────────────────────────────────────────────

AMQP_HOST      = os.getenv("AMQP_HOST",      "rabbit")
AMQP_PORT      = int(os.getenv("AMQP_PORT",  "5672"))
AMQP_USER      = os.getenv("AMQP_USER",      "vlibras")
AMQP_PASS      = os.getenv("AMQP_PASS",      "vlibras")

CORE_QUEUE     = os.getenv("CORE_QUEUE",     "core")
REQUESTS_QUEUE = os.getenv("REQUESTS_QUEUE", "requests")

PG_HOST = os.getenv("POSTGRES_HOST",     "postgres")
PG_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
PG_DB   = os.getenv("POSTGRES_DB",       "vlibras")
PG_USER = os.getenv("POSTGRES_USER",     "vlibrasuser")
PG_PASS = os.getenv("POSTGRES_PASSWORD", "vlibraspass")

PATH_UPLOAD  = os.getenv("PATH_UPLOAD",  "/app/uploads")
PATH_STORAGE = os.getenv("PATH_STORAGE", "/storage/libras")

BRIDGE_HOST  = os.getenv("BRIDGE_HOST",  "bridge")
BRIDGE_PORT  = int(os.getenv("BRIDGE_PORT", "8000"))

# ── DB helpers ────────────────────────────────────────────────────────────────

def pg_conn():
    return psycopg2.connect(
        host=PG_HOST, port=PG_PORT,
        dbname=PG_DB, user=PG_USER, password=PG_PASS,
    )

def get_subtitle_path(uid: str):
    with pg_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT m.path FROM media m
            JOIN requests r ON r."subtitleId" = m.id
            WHERE r.uid = %s LIMIT 1
            """,
            (uid,),
        )
        row = cur.fetchone()
    return row[0] if row else None

def insert_media_and_update_request(uid: str, video_path: str, log):
    with pg_conn() as conn, conn.cursor() as cur:
        filename = Path(video_path).name
        cur.execute(
            """
            INSERT INTO media (name, path, mimetype, kind, "createdAt", "updatedAt")
            VALUES (%s, %s, %s, %s, NOW(), NOW()) RETURNING id
            """,
            (filename, video_path, "video/mp4", "accessibleVideo"),
        )
        media_id = cur.fetchone()[0]
        cur.execute(
            """
            UPDATE requests SET status='generated', "accessibleVideoId"=%s, "updatedAt"=NOW()
            WHERE uid=%s
            """,
            (media_id, uid),
        )
        conn.commit()
    log.info("PostgreSQL atualizado | uid=%s | media_id=%s", uid, media_id)

# ── RabbitMQ helpers ──────────────────────────────────────────────────────────

def amqp_params():
    return pika.ConnectionParameters(
        host=AMQP_HOST, port=AMQP_PORT,
        credentials=pika.PlainCredentials(AMQP_USER, AMQP_PASS),
    )

# ── HTTP file server ──────────────────────────────────────────────────────────

def run_file_server():
    log = setup_logging("file_server")

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=PATH_UPLOAD, **kw)
        def log_message(self, fmt, *args):
            log.debug("HTTP " + fmt, *args)

    server = HTTPServer(("0.0.0.0", BRIDGE_PORT), Handler)
    log.info("HTTP server em 0.0.0.0:%d servindo %s", BRIDGE_PORT, PATH_UPLOAD)
    server.serve_forever()

# ── Consumer: core → requests ─────────────────────────────────────────────────

def run_consumer_core():
    log = setup_logging("core")

    def callback(ch, method, properties, body):
        try:
            msg = json.loads(body)
        except Exception:
            log.error("JSON inválido: %r", body)
            return

        uid = msg.get("uid")
        if not uid:
            log.warning("Mensagem sem uid: %s", msg)
            return

        log.info("[core→requests] uid=%s", uid)

        sub_path = get_subtitle_path(uid)
        if not sub_path:
            log.error("Subtitle não encontrado para uid=%s", uid)
            return

        rel = sub_path.replace(PATH_UPLOAD.rstrip("/") + "/", "", 1)
        subtitle_url = f"http://{BRIDGE_HOST}:{BRIDGE_PORT}/{rel}"
        log.info("Subtitle URL: %s", subtitle_url)

        payload = {
            "subtitle": subtitle_url,
            "uid": uid,
            "mix": msg.get("mix", False),
            "playerOptions": msg.get("playerOptions", {}),
        }

        pub = pika.BlockingConnection(amqp_params())
        pch = pub.channel()
        pch.queue_declare(queue=REQUESTS_QUEUE, durable=False)
        pch.basic_publish(
            exchange="", routing_key=REQUESTS_QUEUE,
            body=json.dumps(payload),
            properties=pika.BasicProperties(correlation_id=uid),
        )
        pub.close()
        log.info("Republicado em '%s' | uid=%s", REQUESTS_QUEUE, uid)

    while True:
        try:
            conn = pika.BlockingConnection(amqp_params())
            ch = conn.channel()
            ch.queue_declare(queue=CORE_QUEUE, durable=False)
            ch.basic_qos(prefetch_count=1)
            ch.basic_consume(queue=CORE_QUEUE, on_message_callback=callback, auto_ack=True)
            log.info("Aguardando mensagens em '%s'...", CORE_QUEUE)
            ch.start_consuming()
        except Exception as e:
            log.error("Erro, reconectando em 5s: %s", e)
            time.sleep(5)

# ── Consumer: libras → PostgreSQL ─────────────────────────────────────────────

def run_consumer_libras():
    log = setup_logging("libras")

    def callback(ch, method, properties, body):
        try:
            msg = json.loads(body)
        except Exception:
            log.error("JSON inválido: %r", body)
            return

        uid = (properties.correlation_id or "").strip() or msg.get("uid", "")
        worker_path = msg.get("libras-video", "")
        log.info("[libras] uid=%s | worker_path=%s", uid, worker_path)

        if not uid:
            log.error("uid vazio, ignorando mensagem")
            return

        if not worker_path or not os.path.exists(worker_path):
            log.error("Arquivo não encontrado: %s", worker_path)
            return

        dest_dir = Path(PATH_UPLOAD) / uid
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / f"{uid}.mp4"

        shutil.copy2(worker_path, dest_path)
        log.info("Vídeo copiado para %s", dest_path)

        try:
            insert_media_and_update_request(uid, str(dest_path), log)
        except Exception as e:
            log.error("Erro ao atualizar PostgreSQL: %s", e, exc_info=True)

    while True:
        try:
            conn = pika.BlockingConnection(amqp_params())
            ch = conn.channel()
            ch.queue_declare(queue="libras-bridge", durable=False)
            ch.basic_qos(prefetch_count=1)
            ch.basic_consume(queue="libras-bridge", on_message_callback=callback, auto_ack=True)
            log.info("Aguardando mensagens em 'libras-bridge'...")
            ch.start_consuming()
        except Exception as e:
            log.error("Erro, reconectando em 5s: %s", e)
            time.sleep(5)

# ── Entrypoint ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    processes = [
        multiprocessing.Process(target=run_file_server,    name="file_server",    daemon=True),
        multiprocessing.Process(target=run_consumer_core,  name="consumer_core",  daemon=False),
        multiprocessing.Process(target=run_consumer_libras,name="consumer_libras",daemon=False),
    ]

    for p in processes:
        p.start()

    # Monitorar processos e reiniciar se morrer
    while True:
        for p in processes:
            if not p.is_alive() and not p.daemon:
                print(f"[monitor] Processo '{p.name}' morreu, reiniciando...")
                new_p = multiprocessing.Process(
                    target=p._target, name=p.name, daemon=p.daemon
                )
                processes[processes.index(p)] = new_p
                new_p.start()
        time.sleep(5)
        