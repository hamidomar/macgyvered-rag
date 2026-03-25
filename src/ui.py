import streamlit as st
import requests
import json
import time

# Configuration
API_URL = "http://localhost:8000"

st.set_page_config(page_title="TurboRefi LOA Portal", layout="wide")

st.title("🏦 TurboRefi Loan Officer Agent")
st.markdown("---")

# Session state initialization
if "session_id" not in st.session_state:
    st.session_state.session_id = None
if "messages" not in st.session_state:
    st.session_state.messages = []
if "current_phase" not in st.session_state:
    st.session_state.current_phase = "New Application"

# Sidebar for session info and uploads
with st.sidebar:
    st.header("Session Management")
    if st.button("Start New Session"):
        st.session_state.session_id = None
        st.session_state.messages = []
        st.session_state.current_phase = "New Application"
        st.rerun()

    if st.session_state.session_id:
        st.info(f"Session ID: {st.session_state.session_id}")
        st.success(f"Phase: {st.session_state.current_phase}")
        
        # Poll status directly to get actual extracted data
        try:
            status_resp = requests.get(f"{API_URL}/session/{st.session_state.session_id}/status")
            if status_resp.status_code == 200:
                s_data = status_resp.json()
                md = s_data.get("mortgage_data")
                if md:
                    with st.expander("📄 Extracted Mortgage Data", expanded=True):
                        st.json(md)
                idocs = s_data.get("income_docs")
                if idocs:
                    with st.expander("📄 Extracted Income Data", expanded=True):
                        st.json(idocs)
                # Keep local phase in sync with backend
                st.session_state.current_phase = s_data.get("current_phase", st.session_state.current_phase)
        except Exception:
            pass
        
        st.header("Document Upload")
        doc_type = st.selectbox("Document Type", ["paystub", "w2", "schedule_c"])
        uploaded_file = st.file_uploader(f"Upload {doc_type}", type=["pdf", "jpg", "png"])
        
        if uploaded_file and st.button("Upload Document to Mem"):
            with st.spinner(f"Extracting {doc_type}..."):
                files = {"file": (uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type)}
                data = {"doc_type": doc_type}
                resp = requests.post(f"{API_URL}/session/{st.session_state.session_id}/upload", files=files, data=data)
                if resp.status_code == 200:
                    st.success("Document parsed and saved! Upload more or conclude.")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error(f"Error: {resp.text}")
                    
        if st.button("✅ Done Uploading: Begin Assessment"):
            with st.spinner("Agent is analyzing documents and performing RAG verification..."):
                resp = requests.post(f"{API_URL}/session/{st.session_state.session_id}/resume")
                if resp.status_code == 200:
                    result = resp.json()
                    st.session_state.messages.append({"role": "assistant", "content": result["response"]})
                    st.session_state.current_phase = result.get("current_phase", st.session_state.current_phase)
                    st.rerun()
                else:
                    st.error(f"Error: {resp.text}")

# Main Chat Interface
if not st.session_state.session_id:
    st.subheader("Start by uploading your Mortgage Statement")
    initial_file = st.file_uploader("Mortgage Statement (PDF/Image)", type=["pdf", "jpg", "png"])
    if initial_file and st.button("Begin Application"):
        with st.spinner("Initializing session and extracting data..."):
            files = {"file": (initial_file.name, initial_file.getvalue(), initial_file.type)}
            resp = requests.post(f"{API_URL}/session", files=files)
            if resp.status_code == 200:
                data = resp.json()
                st.session_state.session_id = data["session_id"]
                st.session_state.messages.append({"role": "assistant", "content": data["response"]})
                st.session_state.current_phase = data.get("current_phase", "greeting")
                st.rerun()
            else:
                st.error(f"Failed to start session: {resp.text}")
else:
    # Display chat history
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Chat input
    if prompt := st.chat_input("Say something to your Loan Officer..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
            
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                resp = requests.post(
                    f"{API_URL}/session/{st.session_state.session_id}/message", 
                    json={"message": prompt}
                )
                if resp.status_code == 200:
                    response_text = resp.json()["response"]
                    st.markdown(response_text)
                    st.session_state.messages.append({"role": "assistant", "content": response_text})
                else:
                    st.error("API error. Ensure the server is running.")

    # Show result button if in assessment/complete phase
    if st.session_state.current_phase in ["assessment", "complete"]:
        if st.button("🔍 Get Final Recommendation Packet"):
             resp = requests.get(f"{API_URL}/session/{st.session_state.session_id}/result")
             if resp.status_code == 200:
                 st.json(resp.json())
             else:
                 st.warning("Recommendation packet not yet complete.")
