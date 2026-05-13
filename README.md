# RedditVideoMakerBot — Fork Web UI + Auto-Downloader 🎬

Fork di [RedditVideoMakerBot](https://github.com/elebumm/RedditVideoMakerBot) con **Web UI**, **downloader automatico** di background (video + audio) e **nessuna API Reddit necessaria**.

## Cosa c'è di diverso in questo fork

- ✅ **Web UI** — genera video dal browser invece che da terminale interattivo
- ✅ **Nessuna API Reddit** — usa scraping pubblico (PullPush + JSON) senza client_id/secret
- ✅ **Auto-downloader** — se manca un background, cerca e scarica automaticamente da YouTube
- ✅ **Pexels fallback** — opzionale, per download ancora più stabili (API key gratuita)
- ✅ **Generazione audio procedurale** — se manca la musica, genera lofi/ambient con ffmpeg
- ✅ **Temi personalizzati** — aggiungi nuovi background (video/audio) direttamente dalla UI
- ✅ **Headless server** — funziona su VPS/server senza monitor (xvfb)
- ✅ **GPU encoding non necessaria** — usa libx264 CPU

---

## Requisiti

| Componente | Installazione |
|---|---|
| Python 3.11+ | `python3 --version` |
| ffmpeg | `sudo apt install ffmpeg` (Debian/Ubuntu) |
| xvfb | `sudo apt install xvfb` (solo per server headless) |
| Git | `sudo apt install git` |

---

## Installazione

### 1. Clona il repo

```bash
git clone https://github.com/edoargo1996/RedditVideoMakerBot.git
cd RedditVideoMakerBot
```

### 2. Ambiente virtuale e dipendenze

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -m spacy download en_core_web_sm
```

### 3. Playwright (browser per screenshot Reddit)

```bash
python -m playwright install chromium
```

---

## Avvio

### Desktop / PC con monitor

```bash
source venv/bin/activate
python web_ui/app.py
```

Apri nel browser: **http://localhost:5000**

### Server headless / VPS / WSL

```bash
source venv/bin/activate
xvfb-run -a python web_ui/app.py
```

Oppure usa lo script incluso:

```bash
chmod +x run_web.sh
xvfb-run -a ./run_web.sh
```

> **Nota:** se stai avviando su un server remoto, usa l'**IP della macchina** al posto di `localhost` (es. `http://192.168.1.50:5000`).

---

## Configurazione

La configurazione viene gestita automaticamente dalla Web UI, ma puoi anche editare il file `config.toml` manualmente.

### API Key Pexels (opzionale, consigliata)

Se vuoi download di background video **più stabili e veloci** rispetto a YouTube:

1. Registrati gratis su [pexels.com/api](https://www.pexels.com/api/)
2. Copia la tua API key
3. Inseriscila nella Web UI (sezione *Settings*) oppure in `config.toml`:

```toml
[settings]
pexels_api_key = "la-tua-api-key"
```

---

## Web UI — Guida

### Generare un video

1. Apri `http://localhost:5000`
2. Scegli la modalità:
   - **Search Reddit** — cerca per argomento (es. "3D printing", "gaming news")
   - **Subreddit only** — usa un subreddit specifico (es. `AskReddit`)
3. Scegli il **tema video** e **tema audio**
4. Clicca **🚀 Generate Video**
5. Attendi (il primo download di un background può richiedere qualche minuto)
6. Scarica il video dalla sezione *Generated videos*

### Aggiungere un tema personalizzato

Se non trovi il gioco/tema che vuoi:

1. Scendi fino alla sezione **🎨 Custom backgrounds**
2. Scegli il tipo (Video o Audio)
3. Scrivi un nome tema (es. `elden-ring`)
4. Scrivi una query di ricerca (es. `elden ring gameplay no copyright`)
5. Clicca **➕ Add & Download** — il sistema cercherà e scaricherà automaticamente da YouTube
6. Oppure clicca **🔍 Preview search** per vedere i risultati prima di scaricare

### Inserire la API Key Pexels dalla UI

Vai nella sezione **⚙️ Settings** in fondo alla pagina, incolla la tua Pexels API key e clicca **Save**. La key verrà salvata in `config.toml` automaticamente.

---

## Temi disponibili

### Video
`minecraft`, `minecraft-2`, `rocket-league`, `motor-gta`, `gta`, `csgo-surf`, `cluster-truck`, `multiversus`, `fall-guys`, `steep`, `trackmania`, `racing-cars`, `3d-printing`, `parkour`, `subnautica`, `satisfactory`, `zelda`, `elden-ring`, `forza`, `cod`

### Audio
`lofi`, `lofi-2`, `chill-summer`, `cinematic`, `upbeat`, `ambient`, `rain-lofi`, `jazz-lofi`, `synthwave`

---

## Troubleshooting

| Problema | Soluzione |
|---|---|
| `Can't find model 'en_core_web_sm'` | `python -m spacy download en_core_web_sm` |
| `Display is not set` / browser crash | Usa `xvfb-run -a python web_ui/app.py` |
| Porta 5000 occupata | `lsof -ti:5000 \| xargs kill -9` poi riavvia |
| Download YouTube lento/fallito | Aggiungi una Pexels API key per fallback |
| Background nero con scritte | È il fallback locale (Game of Life). Il download precedente è fallito — prova un altro tema o aggiungi la Pexels key |

---

## Architettura

```
Web UI (Flask)  →  config.toml  →  bot main.py  →  Reddit scraper (PullPush)
                                            ↓
                              Background downloader (YouTube → Pexels → Fallback)
                                            ↓
                              Video finale (libx264 + TTS)
```

---

## Crediti

- Originale: [elebumm/RedditVideoMakerBot](https://github.com/elebumm/RedditVideoMakerBot) by Lewis Menelaws & TMRRW
- Fork Web UI + no-API scraper + auto-downloader: [edoargo1996](https://github.com/edoargo1996)

## Licenza
Vedi [LICENSE](LICENSE) originale del progetto.
