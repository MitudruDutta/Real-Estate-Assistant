"""Ask AI Page - RAG Q&A"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
from ui.shared import apply_theme, query_ai, process_question

st.set_page_config(page_title="Ask AI", page_icon="🤖", layout="wide")
apply_theme()

st.title("🤖 Ask AI")
st.caption("Ask questions about real estate market sentiment")

# Chat history
if "messages" not in st.session_state:
    st.session_state.messages = []

# Display history
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg.get("sources"):
            with st.expander(f"📚 {len(msg['sources'])} sources"):
                for src in msg["sources"]:
                    st.markdown(f"- [{src[:60]}...]({src})")

# Chat input
if question := st.chat_input("Ask about real estate markets..."):
    # Add user message
    st.session_state.messages.append({"role": "user", "content": question})
    
    with st.chat_message("user"):
        st.markdown(question)
    
    with st.chat_message("assistant"):
        with st.spinner("Analyzing..."):
            result = query_ai(question)
        
        answer = result.get("answer", "No answer")
        sources = result.get("sources", [])
        
        st.markdown(answer)
        
        if sources:
            with st.expander(f"📚 {len(sources)} sources"):
                for src in sources:
                    st.markdown(f"- [{src[:60]}...]({src})")
        
        st.session_state.messages.append({
            "role": "assistant",
            "content": answer,
            "sources": sources
        })

# Sidebar with examples
with st.sidebar:
    st.subheader("Example Questions")
    
    examples = [
        "Which markets are most bullish right now?",
        "What's happening with mortgage rates?",
        "Are home prices dropping anywhere?",
        "What are the main concerns for buyers?",
    ]
    
    for ex in examples:
        if st.button(ex, key=ex, use_container_width=True):
            # Process the example question through the full chat flow
            process_question(ex)
            st.rerun()
    
    st.markdown("---")
    
    if st.button("🗑️ Clear Chat", use_container_width=True):
        st.session_state.messages = []
        st.rerun()
