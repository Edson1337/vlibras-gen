# VLibras Local Video Generator

A Docker-based automation to generate LIBRAS (Brazilian Sign Language) videos from text using the VLibras stack locally, with no dependency on external servers.

## Prerequisites

### Docker + Docker Compose

- [Docker Engine](https://docs.docker.com/engine/install/) 24+
- Docker Compose v2 (already included in Docker Desktop and modern Docker Engine)

Verify installation:
```bash
docker --version
docker compose version
```

### uv (Python package manager)

Official documentation: https://docs.astral.sh/uv/

**Linux / macOS:**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Windows (PowerShell):**
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Verify installation:
```bash
uv --version
```

> `uv` automatically manages the virtual environment and dependencies when running `uv run vlibras_gen.py`. No need to manually create a virtualenv or install packages.

## Architecture

```
main.py
  └── POST /subtitle (video_api:3.2.1)
        └── publishes to queue "core"
              └── bridge (consumer_core)
                    └── publishes to queue "requests"
                          └── video_worker (extractor → translator → renderer)
                                └── publishes to queue "libras-bridge"
                                      └── bridge (consumer_libras)
                                            └── copies .mp4 + updates PostgreSQL
                                                  └── GET /requests/status/:uid → "generated"
                                                        └── GET /requests/download/:uid → .mp4
```

## Required Files in Repository

| File | Description |
|---|---|
| `compose.yaml` | Container orchestration |
| `Dockerfile.bridge` | Bridge service build |
| `bridge.py` | Bridge between video_api and video_worker |
| `rabbitmq.conf` | RabbitMQ configuration (allows remote guest user) |
| `rabbitmq-definitions.json` | RabbitMQ users and permissions |
| `renderer.py` | Worker's renderer.py with corrected queue (`libras-bridge`) |

## Configuration

Copy `.env.example` to `.env` and fill in the values:

```bash
cp .env.example .env
```

Required variables:

```env
VLIBRAS_API_BASE_URL=http://localhost:8080
VLIBRAS_VIDEO_TOKEN=<JWT token generated below>
VLIBRAS_TRANSLATE_URL=https://vlibras.gov.br/api/translate
```

## Starting the Services

```bash
docker compose up -d --build
```

The `db_init` container automatically waits for `video_api` migrations to complete and creates the dev user in PostgreSQL. No manual steps required.

## Generating the JWT Token

After the containers are up:

```bash
docker exec vlibras_video_api node -e "
const jwt = require('jsonwebtoken');
const token = jwt.sign({ cpf: '00000000000' }, '6BrmHrRvuss7RzXrvbFkO2MfpXzJB4dYa1XPU4GYLGMiiarRbGSRf615zN6YET9d', { expiresIn: '10y' });
console.log(token);
"
```

Paste the token into `.env` as `VLIBRAS_VIDEO_TOKEN`.

## Usage

```bash
# Single phrase
uv run vlibras_gen.py "Hello, how are you?"

# Multiple phrases at once
uv run vlibras_gen.py "Hello" "Good morning" "I want to check my bill"

# From a .txt file (one phrase per line)
uv run vlibras_gen.py phrases.txt

# Mix of phrases and files
uv run vlibras_gen.py "Hello" phrases.txt "Goodbye"

# Choose avatar (icaro or hosana)
uv run vlibras_gen.py "Good morning" --avatar hosana
```

The `phrases.txt` format:
```
# comments are ignored
Hello, how are you?
Good morning

I want to check my bill
# blank lines are also ignored
```

Videos are saved to `videos/` and the manifest to `videos/manifest.jsonl`.

## Monitoring

- RabbitMQ Management: http://localhost:15672 (vlibras/vlibras)
- API: http://localhost:8080

```bash
# Check queues
curl -s -u vlibras:vlibras http://localhost:15672/api/queues | \
  python3 -c "
import sys,json
for q in json.load(sys.stdin):
    print(f\"{q['name']:20} consumers={q.get('consumers',0)} messages={q.get('messages',0)}\")
"

# Bridge logs
docker logs vlibras_bridge -f

# Worker logs
docker logs vlibras_video_worker -f
```

## Troubleshooting

**Video generation timeout**
```bash
# Check if consumers are active
curl -s -u vlibras:vlibras http://localhost:15672/api/queues | \
  python3 -c "
import sys,json
for q in json.load(sys.stdin):
    if q['name'] in ('core','libras-bridge','requests'):
        print(q['name'], 'consumers:', q.get('consumers',0))
"
# Expected: core=1, libras-bridge=1, requests=1
```

**Worker not connecting to RabbitMQ**
```bash
# guest user must have full permissions
docker exec vlibras_rabbit rabbitmqctl list_permissions -p /
# Expected: guest .* .* .*

# If not:
docker exec vlibras_rabbit rabbitmqctl set_permissions -p / guest ".*" ".*" ".*"
docker restart vlibras_video_worker
```

## Acknowledgements

This project is built on top of [VLibras](https://vlibras.gov.br), a free and open suite developed by [LAVID/UFPB](http://lavid.ufpb.br) in partnership with the Brazilian government to promote digital accessibility for the deaf community in Brazil.

- VLibras portal: https://vlibras.gov.br
- Source code: https://github.com/spbgovbr-vlibras
- License: [LGPLv3](https://www.gnu.org/licenses/lgpl-3.0.html)

### License compliance

`renderer.py` is a modified version of the original VLibras renderer, covered by LGPLv3. The only modification made is changing the output queue from `libras` to `libras-bridge` to prevent unintended round-robin message delivery. This modification is distributed under the same LGPLv3 terms, in compliance with the license requirements.