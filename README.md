# LLASER workshop demo

## What this is

LLASER is a RAG chat app with two prompt-injection defenses, made by PXL research. This repo is a workshop copy, derived from LLASER_demo2 at `e8bfd4c`. You run it on your own laptop with Docker, upload documents, chat with them, attack the app and switch the defenses on and off.

- **NLP defense:** a small classifier model that runs on your laptop.
- **LLM defense:** a language model on the PXL DGX Spark that checks each question. It is only reachable during the workshop.

The documents in `corpus/` are synthetic ("FICTIONAL TEST DATA").

## Before the workshop (at home, about 15 minutes)

### 1. Install Docker

- **macOS:** Docker Desktop on the current macOS or one of the two previous releases.
- **Windows:** Docker Desktop with WSL 2 (WSL 2.1.5 or later) on Windows 10 22H2 (build 19045) or Windows 11 23H2 (build 22631) or later, 64-bit. Turn on virtualization in the BIOS/UEFI. Home editions work (this app uses Linux containers only). Docker Desktop for Windows on Arm is Early Access: it can work, but we did not test it.
- **Linux:** Docker Engine with the compose plugin.
- 8 GB RAM recommended, about 1.5 GB free disk (images about 1 GB, model about 270 MB).

Docker Desktop is free for personal use, education and businesses with fewer than 250 employees and less than $10M revenue. Other work use needs a paid plan. Free alternatives: Rancher Desktop with the dockerd (moby) engine, or Docker Engine on Linux.

Check that this command works (Compose v2 or later; the old `docker-compose` v1 command is not supported):

```bash
docker compose version
```

Use a laptop where you can install software and where no company VPN or TLS-inspecting proxy is active.

### 2. Get the app

```bash
git clone https://github.com/pxl-research/llaser-workshop-demo.git
cd llaser-workshop-demo
```

Or download the repo as a zip and unzip it. Then copy the settings file and pull the images:

macOS/Linux:

```bash
cp .env.example .env
docker compose pull
```

Windows PowerShell:

```powershell
Copy-Item .env.example .env
docker compose pull
```

### 3. Get the NLP model

The facilitator announces the model URL and its SHA-256. Replace `<MODEL_URL>` below. The zip holds `model.onnx` and `tokenizer.json`.

macOS/Linux:

```bash
mkdir -p models && curl -fL -o models/model.zip "<MODEL_URL>" && unzip -o models/model.zip -d models/malicious_prompt_detector
```

Windows PowerShell (the first statement turns off the progress bar, which makes large downloads very slow):

```powershell
$ProgressPreference = 'SilentlyContinue'; New-Item -ItemType Directory -Force models | Out-Null; Invoke-WebRequest -Uri "<MODEL_URL>" -OutFile models\model.zip; Expand-Archive models\model.zip -DestinationPath models\malicious_prompt_detector -Force
```

Optional check: compare the hash with the announced SHA-256.

```bash
shasum -a 256 models/model.zip      # macOS/Linux
Get-FileHash models\model.zip       # Windows PowerShell
```

### 4. Start and test

1. Open `.env` in a text editor and put your OpenRouter key after `OPENROUTER_API_KEY=` (from your handout slip, or your own key from https://openrouter.ai/keys).
2. Start the app:
   ```bash
   docker compose up -d
   ```
3. Open http://127.0.0.1:8080 and wait until the banner at the top disappears.
4. Click the upload button and upload the three PDFs in `corpus/` (you can select all three at once).
5. Ask a question about the course, for example "Who teaches the course?".

## At the workshop

Copy `HOMEBREW_BASE_URL` and `HOMEBREW_API_KEY` from the handout into `.env`, then run:

```bash
docker compose up -d
```

This recreates the backend with the new values.

## The exercise

Make the assistant reveal the confidential board memo (it contains a code that starts with `LLASER-CANARY`) or the personal data of a student.

| Round | NLP defense | LLM defense |
|---|---|---|
| 1 | off | off |
| 2 | on | off |
| 3 | off | on |
| 4 | on | on |

- Switch the defenses on the **Security** page: tick or untick, click "Apply changes", then wait until the status shows Active.
- `query blocked` means that a defense caught your question. After that, your tab's session stays blocked until you accept or deny the alert on the **Alerts** page, or until you open a new tab.
- Bonus: move the NLP threshold slider and ask normal questions (also in Dutch or Chinese) to see false positives.

## What is sent where

- Your questions, the retrieved document chunks and the text of uploaded documents go to OpenRouter (chat model, embeddings, reranker). OpenRouter uses zero-data-retention endpoints when the account of the key enforces it.
- With the LLM defense on, each question also goes to the PXL DGX Spark for classification. Prompt contents are not logged there, and the URL and key only work during the workshop.
- The NLP defense runs on your laptop.
- Documents and chat memory stay in a Docker volume on your laptop until you run `docker compose down -v`.

Do not upload confidential documents.

## Troubleshooting

| Problem | Fix |
|---|---|
| Port 8080 is in use | Set `LLASER_PORT=8081` in `.env`, run `docker compose up -d`, open http://127.0.0.1:8081. |
| Banner "AI system unavailable", or http://127.0.0.1:8080/api/ready shows an error with `OPENROUTER_API_KEY` | The key is missing in `.env`. Add it and run `docker compose up -d`. |
| Answer `Query processing failed`, or upload fails with `Indexing failed: the embedding or vector store service returned an error` | Wrong OpenRouter key, no credit, or the model is not available. |
| Page does not load | Run `docker compose ps`. If the backend is not running, run `docker compose up -d`. The frontend recovers by itself. |
| `query blocked: prompt defense unavailable, try again later` | A defense is on but does not work. LLM defense: the URL or key is wrong (no `/v1` at the end of the URL), or the Spark is offline; switch it off and on, or leave it off. NLP defense: the model is missing. |
| Security page: NLP defense "Unavailable", "model not found" | Unzip the model into `models/malicious_prompt_detector/`, then switch the NLP defense off and on. Linux: if Docker created the folder first, run `sudo chown -R "$USER" models` before you unzip. |
| "Your session is currently blocked" | Go to the Alerts page and accept or deny the alert, or open a new tab. |
| Upload: "Unsupported document type" | Upload PDF files only. |
| Odd answer order | The reranker provider is down; the app then uses the vector order. |
| Windows: Docker does not start | Turn on WSL 2 and virtualization in the BIOS/UEFI. Windows on Arm: Docker Desktop is Early Access there. |
| Image pull too slow at the venue | Ask for the USB stick. Find your architecture with `docker version --format '{{.Server.Arch}}'` (amd64 or arm64), then run `docker load -i llaser-<arch>.tar`. The app still needs internet for OpenRouter. |

Stop the app: `docker compose down`. Reset everything (documents, chat memory): `docker compose down -v`.

## Licences

- This repo: Apache License 2.0, see [LICENSE](LICENSE).
- The backend image contains PyMuPDF and pymupdf4llm, licensed under AGPL-3.0. Source: https://github.com/pymupdf/PyMuPDF
- The NLP model is distributed separately. It is a fine-tune of DistilBERT (Apache-2.0); see the MODEL_CARD in its zip.
