# Sentinel-1 backscatter trends on Bodmin Moor

Interview task: map the 2023–2024 trend in Sentinel-1 radar backscatter over peatland on Bodmin Moor, Cornwall.

## Layout

| Path | Contents |
| --- | --- |
| `code/` | Python scripts (`download_s1.py` fetches Sentinel-1 GRD scenes from Earth Engine) |
| `code/data/` | Downloaded data (git-ignored) |
| `write_up/` | LaTeX write-up (`main.tex`, figures in `write_up/figures/`) |
| `notes/` | Working notes |

## Setup

### Python environment

Python 3.14 with a standard `venv` and `pip`:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r code/requirements.txt
```

### Earth Engine authentication

Authenticate once per machine:

```bash
earthengine authenticate --auth_mode=localhost
```

This opens a browser for Google sign-in and saves a token locally.

> **Note:** plain `earthengine authenticate` uses `gcloud` by default. The installed Google Cloud SDK (v416) fails on Python ≥ 3.12 with `ModuleNotFoundError: No module named 'imp'`. `--auth_mode=localhost` skips `gcloud`. If browser redirection fails, use `--auth_mode=notebook`, which gives a code to paste into the terminal.

### Earth Engine project

Scripts also need a Google Cloud project registered for Earth Engine ([register here](https://code.earthengine.google.com/register): Unpaid usage → Academic & Research). Put its ID in a `.env` file at the repository root:

```bash
cp .env.example .env
# then edit .env:
EE_PROJECT=your-project-id
```

`download_s1.py` loads `.env` automatically, and `--project` overrides it. `.env` is git-ignored, and `.env.example` is the committed template.

## Usage

```bash
# list matching scenes and per-orbit counts without downloading
python code/download_s1.py --dry-run

# download all scenes to code/data/s1_VV
python code/download_s1.py
```

## Write-up

```bash
cd write_up && latexmk -pdf main.tex
```
