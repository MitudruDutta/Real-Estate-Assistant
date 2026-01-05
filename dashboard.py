"""Real Estate Sentiment Tracker - Dashboard"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from ui.shared import apply_theme, fetch_stats, fetch_markets, trigger_ingestion

st.set_page_config(
    page_title="Real Estate Sentiment",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded"
)
apply_theme()

# Header
st.title("🏠 Real Estate Sentiment Tracker")
st.caption("AI-powered market sentiment analysis from real estate news")

# Controls
col1, col2, col3 = st.columns([1, 1, 4])
with col1:
    if st.button("🔄 Refresh"):
        st.cache_data.clear()
        st.rerun()
with col2:
    if st.button("📥 Ingest"):
        if trigger_ingestion():
            st.toast("Ingestion started!", icon="✅")
        else:
            st.toast("Failed to start", icon="❌")

# Stats
stats = fetch_stats()
cols = st.columns(5)
metrics = [
    ("📰 Articles", stats["articles"]),
    ("🌍 Markets", stats["markets"]),
    ("📊 Sentiments", stats["sentiments"]),
    ("⚠️ Alerts", stats["alerts"]),
    ("🧩 Chunks", stats["chunks"]),
]
for col, (label, value) in zip(cols, metrics):
    col.markdown(f'<div class="stat-card"><div class="stat-value">{value}</div><div class="stat-label">{label}</div></div>', unsafe_allow_html=True)

st.markdown("---")

# Market Rankings - uses batch endpoint (no N+1!)
markets = fetch_markets()

if markets:
    df = pd.DataFrame(markets)
    df = df.sort_values("avg_sentiment", ascending=True).tail(20)
    
    colors = ['#22c55e' if x > 0.05 else '#ef4444' if x < -0.05 else '#64748b' for x in df["avg_sentiment"]]
    
    fig = go.Figure(go.Bar(
        x=df["avg_sentiment"],
        y=df["market"],
        orientation='h',
        marker_color=colors,
        text=[f"{x:+.0%}" for x in df["avg_sentiment"]],
        textposition='outside',
        hovertemplate="<b>%{y}</b><br>Sentiment: %{x:.1%}<br>Articles: %{customdata}<extra></extra>",
        customdata=df["article_count"]
    ))
    
    fig.update_layout(
        title="Market Sentiment Rankings (30 days)",
        height=500,
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)',
        font=dict(color='#94a3b8'),
        margin=dict(l=0, r=60, t=40, b=20),
        xaxis=dict(range=[-0.5, 0.5], gridcolor='#334155', zerolinecolor='#475569', tickformat='.0%'),
        yaxis=dict(gridcolor='#334155')
    )
    st.plotly_chart(fig, use_container_width=True)
    
    # Summary stats
    col1, col2, col3 = st.columns(3)
    bullish = len([m for m in markets if m["avg_sentiment"] > 0.05])
    bearish = len([m for m in markets if m["avg_sentiment"] < -0.05])
    neutral = len(markets) - bullish - bearish
    
    col1.metric("🟢 Bullish Markets", bullish)
    col2.metric("🔴 Bearish Markets", bearish)
    col3.metric("⚪ Neutral Markets", neutral)
else:
    st.info("No market data yet. Click 'Ingest' to fetch news articles.")
