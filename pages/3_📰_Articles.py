"""Articles Page"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
from ui.shared import apply_theme, fetch_articles

st.set_page_config(page_title="Articles", page_icon="📰", layout="wide")
apply_theme()

st.title("📰 Articles")

# Initialize refresh counter for per-session cache invalidation
if "refresh_count" not in st.session_state:
    st.session_state.refresh_count = 0

# Controls - only capture the used column
col1, _ = st.columns([1, 3])
with col1:
    limit = st.selectbox("Show", [25, 50, 100], index=0)

articles = fetch_articles(limit, _refresh_count=st.session_state.refresh_count)

if not articles:
    st.warning("No articles found. Ingest some news first.")
    st.stop()

st.caption(f"Showing {len(articles)} most recent articles")

# Group by source
sources = {}
for a in articles:
    src = a.get("source", "Unknown")
    if src not in sources:
        sources[src] = []
    sources[src].append(a)

# Display
for source, items in sorted(sources.items(), key=lambda x: -len(x[1])):
    with st.expander(f"**{source}** ({len(items)} articles)", expanded=len(sources) <= 3):
        for a in items:
            # Validate required keys before rendering
            title = a.get("title")
            url = a.get("url")
            
            # Skip entries missing required url
            if not url:
                continue
            
            # Use fallback for missing title
            if not title:
                title = "(no title)"
            
            # Truncate title only if needed (>80 chars)
            if len(title) > 80:
                displayed_title = title[:80] + "..."
            else:
                displayed_title = title
            
            # Handle created_at safely
            date = a.get("created_at", "")[:10] if a.get("created_at") else ""
            
            st.markdown(
                f"- [{displayed_title}]({url}) <small style='color:#64748b'>({date})</small>",
                unsafe_allow_html=True
            )
