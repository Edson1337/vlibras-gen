from __future__ import annotations

import argparse
import hashlib
import json
import logging
import tempfile
import time
from pathlib import Path
from typing import Iterable, Dict, Any

import requests
from requests import Response

from config import AppConfig


# ===== Endpoints =====
TRANSLATE_PATH = "/translate"
SUBTITLE_PATH = "/subtitle"
REQUESTS_STATUS_PATH = "/requests/status/{uid}"
REQUESTS_DOWNLOAD_PATH = "/requests/download/{uid}"

# Status PT-BR retornados pela API
STATUS_SUCCESS = {"gerado", "mixado"}
STATUS_FAILURE = {"falhou", "expirado"}

# Avatares disponíveis
AVATAR_DEFAULT = "icaro"  # ou "hosana"


def setup_logging(level: str) -> None:
    numeric = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING if numeric >= logging.INFO else logging.DEBUG)


log = logging.getLogger("vlibras")


def _preview_body(resp: Response, limit: int = 240) -> str:
    try:
        txt = " ".join(resp.text.split())
        return (txt[:limit] + "…") if len(txt) > limit else txt
    except Exception:
        return "<unreadable body>"


def _fmt(path: str, **params: str) -> str:
    for k, v in params.items():
        path = path.replace("{" + k + "}", str(v))
    return path


def gloss_to_srt(gloss: str) -> str:
    """Converte uma glosa em arquivo SRT mínimo válido."""
    return (
        "1\n"
        "00:00:00,000 --> 00:00:10,000\n"
        f"{gloss}\n"
    )


class VLibrasClient:
    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        self.s = requests.Session()
        self.s.headers.update({"Accept": "*/*", "User-Agent": "vlibras-gen/2.0"})
        # Token estático vindo do .env — não há chamada a temp_login
        self._token: str = cfg.video_token or ""
        if not self._token:
            raise RuntimeError(
                "VLIBRAS_VIDEO_TOKEN não definido no .env.\n"
                "Gere um com:\n"
                "  docker exec vlibras_video_api node -e \"\n"
                "    const jwt = require('jsonwebtoken');\n"
                "    const s = '<JWT_SECRET>';\n"
                "    console.log(jwt.sign({ cpf: '00000000000' }, s, { expiresIn: '30d' }));\n"
                "  \""
            )

    def _url(self, base: str, path: str) -> str:
        return base.rstrip("/") + "/" + path.lstrip("/")

    def _auth_headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    def _req(self, method: str, url: str, **kwargs) -> Response:
        t0 = time.perf_counter()
        r = self.s.request(method, url, timeout=self.cfg.timeout_s, **kwargs)
        ms = (time.perf_counter() - t0) * 1000
        log.info("HTTP %s %s -> %s (%.1f ms) | body~=%s", method, url, r.status_code, ms, _preview_body(r))
        return r

    # -------- Tradução (texto -> glosa) --------
    def translate_to_gloss(self, text: str) -> str:
        url = self._url(self.cfg.translate_base_url, TRANSLATE_PATH)
        r = self._req(
            "POST",
            url,
            headers={"Content-Type": "application/json; charset=utf-8"},
            data=json.dumps({"text": text}, ensure_ascii=False),
        )
        r.raise_for_status()
        gloss = r.text.strip()
        if not gloss:
            raise RuntimeError("Glosa vazia retornada por /translate.")
        return gloss

    # -------- Submissão (glosa -> uid) --------
    def request_video(self, gloss: str, avatar: str = AVATAR_DEFAULT) -> str:
        """
        POST /subtitle com multipart/form-data:
          - subtitle: arquivo .srt com a glosa
          - avatar:   "icaro" ou "hosana"
        Retorna o uid do request.
        """
        url = self._url(self.cfg.video_base_url, SUBTITLE_PATH)
        srt_content = gloss_to_srt(gloss)

        # Escreve o .srt em arquivo temporário (a API valida a extensão)
        with tempfile.NamedTemporaryFile(suffix=".srt", mode="w",
                                        encoding="utf-8", delete=False) as tmp:
            tmp.write(srt_content)
            tmp_path = tmp.name

        try:
            with open(tmp_path, "rb") as srt_file:
                r = self._req(
                    "POST",
                    url,
                    headers=self._auth_headers(),
                    files={"subtitle": (Path(tmp_path).name, srt_file, "application/x-subrip")},
                    data={"avatar": avatar},
                )
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        r.raise_for_status()
        data = r.json()

        # Resposta: {"request": {"uid": "...", "status": "enfileirado"}}
        uid = (
            data.get("request", {}).get("uid")
            or data.get("uid")
            or data.get("requestUID")
        )
        if not uid:
            raise RuntimeError(f"Resposta inesperada de /subtitle: {data}")

        log.info("Request enfileirado | uid=%s", uid)
        return uid

    # -------- Polling (uid -> status final) --------
    def wait_video(self, uid: str) -> Dict[str, Any]:
        """
        GET /requests/status/:uid até status ∈ STATUS_SUCCESS ou STATUS_FAILURE.
        Status PT-BR: enfileirado, gerando, gerado, mixando, mixado, falhou, expirado.
        """
        url = self._url(self.cfg.video_base_url, _fmt(REQUESTS_STATUS_PATH, uid=uid))
        t0 = time.time()

        while time.time() - t0 < self.cfg.poll_timeout_s:
            r = self._req("GET", url, headers=self._auth_headers())
            r.raise_for_status()
            data = r.json()

            status = (data.get("status") or "").lower().strip()
            log.debug("uid=%s status=%s", uid, status)

            if status in STATUS_SUCCESS:
                return data
            if status in STATUS_FAILURE:
                raise RuntimeError(f"Falha no processamento do vídeo (status={status}): {data}")

            time.sleep(self.cfg.poll_interval_s)

        raise TimeoutError(f"Timeout aguardando vídeo (uid={uid}).")

    # -------- Download --------
    def download_video(self, uid: str, out_path: Path) -> None:
        url = self._url(self.cfg.video_base_url, _fmt(REQUESTS_DOWNLOAD_PATH, uid=uid))
        out_path.parent.mkdir(parents=True, exist_ok=True)

        log.info("Baixando vídeo → %s", out_path)
        with self.s.get(
            url,
            stream=True,
            timeout=self.cfg.timeout_s,
            headers=self._auth_headers(),
        ) as r:
            log.info("HTTP GET %s -> %s | content-type=%s",
                     url, r.status_code, r.headers.get("content-type", ""))
            r.raise_for_status()
            with open(out_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=256 * 1024):
                    if chunk:
                        f.write(chunk)

    # -------- Pipeline completo --------
    def text_to_video(self, text: str, out_path: Path,
                      avatar: str = AVATAR_DEFAULT) -> Dict[str, Any]:
        gloss = self.translate_to_gloss(text)
        log.info("Glosa: %s", gloss)

        uid = self.request_video(gloss, avatar=avatar)
        log.info("uid: %s", uid)

        meta = self.wait_video(uid)
        log.info("Status final: %s", meta)

        self.download_video(uid, out_path)

        return {
            "text": text,
            "gloss": gloss,
            "uid": uid,
            "meta": meta,
            "out": str(out_path),
        }


# ===== Helpers CLI =====

def iter_phrases(inputs: list) -> Iterable[str]:
    for arg in inputs:
        p = Path(arg)
        if p.exists() and p.suffix == ".txt":
            for line in p.read_text(encoding="utf-8").splitlines():
                s = line.strip()
                if not s or s.startswith("#"):
                    continue
                yield s
        else:
            s = arg.strip()
            if s:
                yield s


def slug_name(text: str, max_len: int = 60) -> str:
    t = "".join(ch if ch.isalnum() else "_" for ch in text.lower())
    t = "_".join(filter(None, t.split("_")))[:max_len].strip("_")
    return t or "frase"


def stable_key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


# ===== Entrypoint =====

def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Gera vídeos em LIBRAS via VLibras local.\n"
            "Passe uma frase ou um caminho .txt (1 frase por linha)."
        )
    )
    parser.add_argument(
        "input",
        nargs="+",
        help="Uma ou mais frases em PT-BR e/ou arquivos .txt (1 frase por linha)",
    )
    parser.add_argument(
        "--avatar",
        default=AVATAR_DEFAULT,
        choices=["icaro", "hosana"],
        help="Avatar a ser usado (padrão: icaro)",
    )
    args = parser.parse_args()

    cfg = AppConfig.load()
    setup_logging(cfg.log_level)

    client = VLibrasClient(cfg)

    out_dir = Path(cfg.out_dir)
    manifest = out_dir / "manifest.jsonl"
    out_dir.mkdir(parents=True, exist_ok=True)

    for i, phrase in enumerate(iter_phrases(args.input), start=1):
        phrase = phrase.strip()
        if not phrase:
            continue

        filename = f"{i:04d}_{slug_name(phrase)}_{stable_key(phrase)}.mp4"
        out_path = out_dir / filename

        log.info("── Frase %d: %s", i, phrase)

        try:
            record = client.text_to_video(phrase, out_path, avatar=args.avatar)
            with open(manifest, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            log.info("✓ Vídeo salvo: %s", out_path)
        except Exception as e:
            log.exception("✗ Erro gerando vídeo para: %s", phrase)
            with open(manifest, "a", encoding="utf-8") as f:
                f.write(json.dumps({"text": phrase, "error": str(e)}, ensure_ascii=False) + "\n")

    log.info("Finalizado. Manifest: %s", manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())