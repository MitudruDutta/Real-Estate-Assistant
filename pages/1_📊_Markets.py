"""Market Analysis Page"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from ui.shared import apply_theme, fetch_markets, fetch_market_history

st.set_page_config(page_title="Markets", page_icon="📊", layout="wide")
apply_theme()

st.title("📊 Market Analysis")

# Initialize refresh counter for per-session cache invalidation
if "refresh_count" not in st.session_state:
    st.session_state.refresh_count = 0

markets = fetch_markets(_refresh_count=st.session_state.refresh_count)
if not markets:
    st.warning("No markets found. Ingest some news first.")
    st.stop()

# Market selector
market_names = [m["market"] for m in markets]
selected = st.selectbox("Select Market", market_names)

if selected:
    # Find market data
    market_data = next((m for m in markets if m["market"] == selected), None)
    
    if market_data:
        # Stats row
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Sentiment", f"{market_data['avg_sentiment']:+.1%}")
        c2.metric("Confidence", f"{market_data['confidence']:.0%}")
        c3.metric("Articles", market_data["article_count"])
        c4.metric("Region", market_data.get("region", "N/A"))
        
        st.markdown("---")
        
        # History chart
        history = fetch_market_history(selected, 60, _refresh_count=st.session_state.refresh_count)
        
        if history:
            df = pd.DataFrame(history)
            
            # Compute dynamic x-axis range from sentiment data
            sentiment_values = df["sentiment"].tolist()
            if sentiment_values:
                min_sentiment = min(sentiment_values)
                max_sentiment = max(sentiment_values)
                # Add 10% buffer on each side
                buffer = max(0.05, (max_sentiment - min_sentiment) * 0.1)
                y_range = [min_sentiment - buffer, max_sentiment + buffer]
            else:
                y_range = [-0.5, 0.5]  # Default range
            
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=df["date"],
                y=df["sentiment"],
                mode='lines+markers',
                line=dict(color='#3b82f6', width=2),
                marker=dict(size=8),
                fill='tozeroy',
                fillcolor='rgba(59,130,246,0.1)',
                hovertemplate="<b>%{x}</b><br>Sentiment: %{y:.1%}<br>Articles: %{customdata}<extra></extra>",
                customdata=df.get("articles", [0] * len(df))
            ))
            
            fig.add_hline(y=0, line_dash="dash", line_color="#475569")
            
            fig.update_layout(
                title=f"Sentiment Trend - {selected}",
                height=400,
                plot_bgcolor='rgba(0,0,0,0)',
                paper_bgcolor='rgba(0,0,0,0)',
                font=dict(color='#94a3b8'),
                margin=dict(l=0, r=0, t=40, b=20),
                xaxis=dict(gridcolor='#334155'),
                yaxis=dict(range=y_range, gridcolor='#334155', tickformat='.0%')
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No historical data for this market yet.")
        
        # Compare with other markets in same region
        if market_data.get("region"):
            st.markdown("---")
            st.subheader(f"Other {market_data['region']} Markets")
            
            regional = [m for m in markets if m.get("region") == market_data["region"] and m["market"] != selected]
            if regional:
                for m in sorted(regional, key=lambda x: x["avg_sentiment"], reverse=True)[:5]:
                    sentiment = m["avg_sentiment"]
                    color = "🟢" if sentiment > 0.05 else "🔴" if sentiment < -0.05 else "⚪"
                    st.write(f"{color} **{m['market']}**: {sentiment:+.1%} ({m['article_count']} articles)")
            else:
                st.write("No other markets in this region.")
