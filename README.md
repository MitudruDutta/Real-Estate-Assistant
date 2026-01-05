# 🏠 Real Estate Sentiment Tracker

AI-powered sentiment analysis for US real estate markets. Automatically ingests news from multiple sources, extracts market-specific sentiment using LLMs, and provides a RAG-based Q&A interface.

![Python](https://img.shields.io/badge/Python-3.12+-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.109+-green)
![Streamlit](https://img.shields.io/badge/Streamlit-1.30+-red)

## ✨ Features

- **📰 Auto-Ingestion** - Fetches news from 5 RSS feeds + NewsAPI hourly
- **🇺🇸 US Market Focus** - Tracks 40+ validated US cities only
- **📊 Sentiment Analysis** - LLM-powered extraction with confidence scores
- **🤖 RAG Q&A** - Ask questions about market conditions
- **⚠️ Anomaly Detection** - Alerts when sentiment shifts significantly
- **🗺️ Regional Analysis** - Markets grouped by US region

## 🚀 Quick Start

### Prerequisites
- Python 3.12+
- [Groq API Key](https://console.groq.com/) (free tier available)

### Installation

```bash
# Clone the repository
git clone https://github.com/MitudruDutta/real-estate-sentiment.git

cd real-estate-sentiment

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env and add your GROQ_API_KEY
```

### Database Initialization

The application auto-initializes the SQLite database and ChromaDB vector store on first startup. No manual migration is required.

Both databases are created automatically when the API server starts:
- **SQLite** (`data/sentiment.db`) - Created via SQLAlchemy's `create_all()`
- **ChromaDB** (`data/chroma/`) - Created via ChromaDB's `PersistentClient`

The `data/` directory and subdirectories are created automatically if they don't exist.

### Running

The application requires two services running concurrently in separate terminals:

```bash
# Terminal 1: Start the API server
uvicorn src.api.main:app --port 8000

# Terminal 2: Start the dashboard
streamlit run dashboard.py
```

**Note:** Both services must be running simultaneously. The dashboard communicates with the API server, so start Terminal 1 first.

**Docker Alternative:** If you prefer a single command, use Docker Compose:
```bash
docker-compose up
```

Open http://localhost:8501 for the dashboard.

## 🔧 Configuration

Create a `.env` file with the following variables:

```env
# Required - Groq API key for LLM sentiment extraction
# Obtain from: https://console.groq.com/keys
# Format: gsk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx (56 characters)
GROQ_API_KEY=your_groq_api_key_here

# Optional - NewsAPI key for additional news sources
# If omitted, the app falls back to RSS feeds only
# Obtain from: https://newsapi.org/
NEWSAPI_KEY=optional_newsapi_key_here

# Optional - API URL for dashboard (defaults to localhost)
API_URL=http://localhost:8000/api
```

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GROQ_API_KEY` | **Yes** | API key for Groq LLM service. Required for sentiment extraction and RAG Q&A. |
| `NEWSAPI_KEY` | No | API key for NewsAPI. Optional — used by NewsAPI hourly feature; if omitted the app falls back to RSS feeds only. |
| `API_URL` | No | Base URL for the API server. Defaults to `http://localhost:8000/api`. |

### Validation Errors

| Error | Cause | Fix |
|-------|-------|-----|
| `ValidationError: groq_api_key field required` | Missing `GROQ_API_KEY` in `.env` | Add your Groq API key to `.env` |
| `AuthenticationError` from Groq | Invalid or expired `GROQ_API_KEY` | Verify key at https://console.groq.com/keys |
| `401 Unauthorized` from NewsAPI | Invalid `NEWSAPI_KEY` | Check key at https://newsapi.org/account |
| `429 Rate Limited` from NewsAPI | NewsAPI rate limit exceeded | Wait or upgrade NewsAPI plan; RSS feeds still work |

## 📡 API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Health check |
| `/api/stats` | GET | System statistics |
| `/api/markets` | GET | All markets with sentiment trends |
| `/api/markets/{name}/trend` | GET | Single market trend |
| `/api/markets/{name}/history` | GET | Historical sentiment data |
| `/api/articles` | GET | List ingested articles |
| `/api/alerts` | GET | Active anomaly alerts |
| `/api/alerts/{id}/acknowledge` | POST | Dismiss an alert |
| `/api/ingest` | POST | Manually ingest URLs |
| `/api/ingest/auto` | POST | Trigger auto-ingestion |
| `/api/query` | POST | RAG Q&A |

### Example API Usage

```bash
# Get system stats
curl http://localhost:8000/api/stats

# Get all market sentiments
curl http://localhost:8000/api/markets

# Ask a question
curl -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"question": "Which markets are most bullish?"}'

# Trigger news ingestion
curl -X POST http://localhost:8000/api/ingest/auto
```

## 🏗️ Architecture

```
├── dashboard.py              # Streamlit main page
├── pages/                    # Streamlit sub-pages
│   ├── 1_📊_Markets.py       # Market analysis
│   ├── 2_🤖_Ask_AI.py        # RAG Q&A interface
│   ├── 3_📰_Articles.py      # Article browser
│   └── 4_⚠️_Alerts.py        # Alert management
├── ui/
│   └── shared.py             # Shared dashboard utilities
├── src/
│   ├── api/main.py           # FastAPI application
│   ├── config.py             # Settings & market whitelist
│   ├── models.py             # SQLAlchemy models
│   ├── scheduler.py          # Hourly ingestion scheduler
│   ├── ingestion/
│   │   ├── sources.py        # RSS & NewsAPI fetchers
│   │   └── collector.py      # HTML parsing
│   ├── extraction/
│   │   └── sentiment.py      # LLM sentiment extraction
│   ├── storage/
│   │   └── vector_store.py   # ChromaDB for RAG
│   ├── analysis/
│   │   └── trends.py         # Trend & anomaly detection
│   └── services/
│       ├── ingestion.py      # Pipeline orchestration
│       └── cache.py          # LLM response caching
└── data/                     # SQLite DB & ChromaDB (gitignored)
```

## 📰 Data Sources

**RSS Feeds:**
- CNBC Real Estate
- HousingWire
- Mortgage Reports
- Calculated Risk
- Wolf Street

**Optional:**
- NewsAPI (requires free API key)

## 🗺️ Tracked Markets

**Northeast:** New York, Boston, Philadelphia, Pittsburgh, Baltimore

**Southeast:** Miami, Atlanta, Tampa, Orlando, Charlotte, Nashville, Jacksonville, Raleigh

**Midwest:** Chicago, Detroit, Cleveland, Columbus, Indianapolis, Milwaukee, Minneapolis, St. Louis

**Southwest:** Phoenix, Dallas, Houston, San Antonio, Austin, Fort Worth, Albuquerque, Tucson

**West:** Los Angeles, San Francisco, San Diego, San Jose, Seattle, Portland, Denver, Las Vegas, Sacramento, Fresno

## 🛠️ Tech Stack

| Component | Technology |
|-----------|------------|
| Backend | FastAPI |
| Database | SQLite (WAL mode) |
| Vector DB | ChromaDB |
| LLM | Groq (Llama 3.1 8B) |
| Embeddings | sentence-transformers/all-MiniLM-L6-v2 |
| Frontend | Streamlit + Plotly |
| Scheduler | APScheduler |

## 📝 License

MIT License - see [LICENSE](LICENSE) for details.

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request
