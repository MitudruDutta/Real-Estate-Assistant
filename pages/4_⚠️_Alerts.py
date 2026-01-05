"""Alerts Page"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import requests
from ui.shared import apply_theme, fetch_alerts, API_URL

st.set_page_config(page_title="Alerts", page_icon="⚠️", layout="wide")
apply_theme()

st.title("⚠️ Alerts")

# Initialize refresh counter for per-session cache invalidation
if "refresh_count" not in st.session_state:
    st.session_state.refresh_count = 0

col1, _ = st.columns([1, 5])
with col1:
    if st.button("🔄 Refresh"):
        # Per-session cache invalidation instead of global clear
        st.session_state.refresh_count += 1
        st.rerun()

alerts = fetch_alerts(_refresh_count=st.session_state.refresh_count)

if not alerts:
    st.success("✅ No active alerts")
    st.balloons()
    st.stop()

st.warning(f"⚠️ {len(alerts)} active alerts")

for a in alerts:
    # Validate alert has required 'id' field
    alert_id = a.get("id")
    if not alert_id:
        # Skip alerts without id or show disabled UI
        st.warning("Alert missing ID - cannot acknowledge")
        continue
    
    severity = a.get("severity", "medium")
    icon = "🔴" if severity == "high" else "🟡" if severity == "medium" else "🔵"
    
    col1, col2 = st.columns([6, 1])
    
    with col1:
        with st.expander(f"{icon} **{a.get('type', 'Alert')}** - {a.get('message', '')[:60]}..."):
            st.write(f"**Message:** {a.get('message', 'N/A')}")
            st.write(f"**Severity:** {severity.upper()}")
            st.write(f"**Triggered:** {a.get('triggered_at', 'N/A')}")
    
    with col2:
        if st.button("✓", key=alert_id, help="Acknowledge"):
            try:
                resp = requests.post(f"{API_URL}/alerts/{alert_id}/acknowledge", timeout=5)
                resp.raise_for_status()
                # Only clear cache and rerun on successful response
                st.session_state.refresh_count += 1
                st.rerun()
            except requests.RequestException as e:
                error_detail = ""
                if hasattr(e, 'response') and e.response is not None:
                    error_detail = f" (Status: {e.response.status_code})"
                st.error(f"Failed to acknowledge alert{error_detail}: {e}")
