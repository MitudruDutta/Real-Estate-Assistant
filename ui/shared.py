"""Shared utilities for Streamlit pages"""
import os
import streamlit as st
import requests

API_URL = os.getenv("API_URL", "http://localhost:8000/api")


def apply_theme():
    """Apply dark theme CSS."""
    st.markdown("""
    <style>
        .stApp {background-color: #0f172a;}
        .main .block-container {padding: 1.5rem 2rem; max-width: 1400px;}
        h1, h2, h3, p, span, label, li, a {color: #f1f5f9 !important;}
        
        [data-testid="stSidebar"] {background-color: #1e293b !important;}
        [data-testid="stSidebar"] * {color: #f1f5f9 !important;}
        
        .stat-card {
            background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
            border: 1px solid #334155; border-radius: 0.75rem; padding: 1.25rem;
            text-align: center; margin-bottom: 0.5rem;
        }
        .stat-value {font-size: 1.75rem; font-weight: 700; color: #f8fafc !important;}
        .stat-label {font-size: 0.8rem; color: #64748b !important;}
        
        .card {
            background: #1e293b; border: 1px solid #334155;
            border-radius: 0.75rem; padding: 1rem; margin-bottom: 0.75rem;
        }
        
        .stButton button {
            background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%) !important;
            color: white !important; border: none !important;
        }
        .stTextInput input, .stSelectbox > div > div {
            background-color: #1e293b !important; color: #f1f5f9 !important;
        }
    </style>
    """, unsafe_allow_html=True)


@st.cache_data(ttl=60)
def fetch_stats(_refresh_count: int = 0):
    """Fetch system stats. _refresh_count is used for cache busting."""
    try:
        resp = requests.get(f"{API_URL}/stats", timeout=5)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        st.warning(f"Failed to fetch stats: {e}")
        return {"articles": 0, "markets": 0, "sentiments": 0, "alerts": 0, "chunks": 0}
    except ValueError as e:
        st.warning(f"Invalid stats response: {e}")
        return {"articles": 0, "markets": 0, "sentiments": 0, "alerts": 0, "chunks": 0}


@st.cache_data(ttl=60)
def fetch_markets(_refresh_count: int = 0):
    """Fetch all markets with trends in ONE call."""
    try:
        resp = requests.get(f"{API_URL}/markets", timeout=10)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        st.warning(f"Failed to fetch markets: {e}")
        return []
    except ValueError as e:
        st.warning(f"Invalid markets response: {e}")
        return []


@st.cache_data(ttl=60)
def fetch_market_history(market: str, days: int = 30, _refresh_count: int = 0):
    """Fetch market history."""
    try:
        resp = requests.get(f"{API_URL}/markets/{market}/history?days={days}", timeout=5)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        st.warning(f"Failed to fetch market history: {e}")
        return []
    except ValueError as e:
        st.warning(f"Invalid market history response: {e}")
        return []


@st.cache_data(ttl=60)
def fetch_articles(limit: int = 20, _refresh_count: int = 0):
    """Fetch articles."""
    try:
        resp = requests.get(f"{API_URL}/articles?limit={limit}", timeout=5)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        st.warning(f"Failed to fetch articles: {e}")
        return []
    except ValueError as e:
        st.warning(f"Invalid articles response: {e}")
        return []


@st.cache_data(ttl=60)
def fetch_alerts(_refresh_count: int = 0):
    """Fetch alerts."""
    try:
        resp = requests.get(f"{API_URL}/alerts", timeout=5)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        st.warning(f"Failed to fetch alerts: {e}")
        return []
    except ValueError as e:
        st.warning(f"Invalid alerts response: {e}")
        return []


def query_ai(question: str):
    """Query the RAG endpoint."""
    try:
        resp = requests.post(f"{API_URL}/query", json={"question": question}, timeout=60)
        if resp.status_code == 200:
            return resp.json()
        return {"answer": f"Error: {resp.status_code}", "sources": [], "error": True}
    except requests.exceptions.Timeout:
        return {"answer": "Request timed out", "sources": [], "error": True}
    except requests.RequestException as e:
        return {"answer": f"Request error: {e}", "sources": [], "error": True}


def trigger_ingestion():
    """Trigger auto-ingestion."""
    try:
        resp = requests.post(f"{API_URL}/ingest/auto", timeout=5)
        resp.raise_for_status()
        return True
    except requests.RequestException as e:
        st.warning(f"Failed to trigger ingestion: {e}")
        return False


def process_question(question: str):
    """Process a question through the AI and update session state."""
    # Add user message
    st.session_state.messages.append({"role": "user", "content": question})
    
    # Query AI
    result = query_ai(question)
    
    answer = result.get("answer", "No answer")
    sources = result.get("sources", [])
    
    # Add assistant response
    st.session_state.messages.append({
        "role": "assistant",
        "content": answer,
        "sources": sources
    })
