"""
P&L RECONCILIATION AI AGENT - COMPLETE WORKING VERSION
Reads ALL sheets and provides accurate answers
"""

import streamlit as st
import pandas as pd
import json
import gspread
from google.oauth2.service_account import Credentials
import google.generativeai as genai
from datetime import datetime
import time
import re

# Page config
st.set_page_config(
    page_title="P&L Reconciliation AI Agent",
    page_icon="🤖",
    layout="wide"
)

# Custom CSS
st.markdown("""
<style>
    .main-header {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 30px;
        border-radius: 15px;
        color: white;
        text-align: center;
        margin-bottom: 30px;
    }
    .chat-message {
        padding: 15px;
        border-radius: 10px;
        margin: 10px 0;
    }
    .user-message {
        background: #e3f2fd;
        border-left: 4px solid #2196F3;
        margin-left: 50px;
    }
    .ai-message {
        background: #f3e5f5;
        border-left: 4px solid #9c27b0;
        margin-right: 50px;
    }
    .metric-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 20px;
        border-radius: 10px;
        color: white;
        text-align: center;
    }
</style>
""", unsafe_allow_html=True)

# Initialize session state
if "messages" not in st.session_state:
    st.session_state.messages = []
if "all_data" not in st.session_state:
    st.session_state.all_data = {}
if "connected" not in st.session_state:
    st.session_state.connected = False

@st.cache_resource
def init_services(spreadsheet_id, creds_dict, gemini_key):
    """Initialize Google Sheets and Gemini"""
    try:
        scopes = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]
        credentials = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(credentials)
        spreadsheet = client.open_by_key(spreadsheet_id)
        
        genai.configure(api_key=gemini_key)
        model = genai.GenerativeModel('gemini-1.5-flash-latest')
        
        return spreadsheet, model, None
    except Exception as e:
        return None, None, str(e)

def load_all_sheets(spreadsheet):
    """Load ALL sheets into memory"""
    try:
        all_data = {}
        
        # Define sheets to load
        sheets_to_load = {
            "01_Expected": "B:U",
            "02_Payouts": "B:AE", 
            "03_MCFExport": "C:CE",
            "04_Invoice": "A:J",
            "Master Reconciliation": "A:W"
        }
        
        for sheet_name, range_notation in sheets_to_load.items():
            try:
                ws = spreadsheet.worksheet(sheet_name)
                data = ws.get_all_values()
                
                if data and len(data) > 1:
                    df = pd.DataFrame(data[1:], columns=data[0])
                    df.columns = df.columns.str.strip()
                    all_data[sheet_name] = df
                    st.success(f"✅ Loaded {sheet_name}: {len(df)} rows")
                else:
                    st.warning(f"⚠️ {sheet_name} is empty")
                    
            except Exception as e:
                st.error(f"❌ Error loading {sheet_name}: {e}")
        
        return all_data
        
    except Exception as e:
        st.error(f"Error loading sheets: {e}")
        return {}

def smart_search(df, search_term, columns_to_search):
    """Smart search across multiple columns"""
    if df is None or df.empty:
        return pd.DataFrame()
    
    search_lower = str(search_term).lower().strip()
    
    # Try exact match first
    for col in columns_to_search:
        if col in df.columns:
            exact = df[df[col].astype(str).str.lower() == search_lower]
            if not exact.empty:
                return exact
    
    # Try contains match
    for col in columns_to_search:
        if col in df.columns:
            contains = df[df[col].astype(str).str.lower().str.contains(search_lower, na=False, regex=False)]
            if not contains.empty:
                return contains
    
    # Try partial word match
    words = search_lower.split()
    if len(words) > 1:
        for col in columns_to_search:
            if col in df.columns:
                mask = df[col].astype(str).str.lower().apply(
                    lambda x: all(word in x for word in words)
                )
                word_match = df[mask]
                if not word_match.empty:
                    return word_match
    
    return pd.DataFrame()

def chat_with_agent(user_message, all_data):
    """Intelligent agent that understands and helps"""
    
    if not all_data or "Master Reconciliation" not in all_data:
        return {
            "type": "error",
            "message": "⚠️ No data loaded. Please reload the data."
        }
    
    master_df = all_data["Master Reconciliation"]
    user_lower = user_message.lower().strip()
    
    # Extract MCF numbers
    mcf_pattern = r'MCF-\d{8}-\d{4}'
    mcfs_found = re.findall(mcf_pattern, user_message.upper())
    
    # ============================================================
    # QUERY 1: CP1/CP2 Information
    # ============================================================
    if any(word in user_lower for word in ["cp1", "cp2", "channel partner", "partner"]):
        
        # If MCF is specified
        if mcfs_found:
            mcf = mcfs_found[0]
            
            # Search in Master Reconciliation
            mcf_data = smart_search(master_df, mcf, ['MCF Number'])
            
            if mcf_data.empty:
                return {
                    "type": "answer",
                    "message": f"❌ **MCF {mcf} not found in Master Reconciliation.**\n\n"
                               f"💡 The sheet has {len(master_df)} MCFs loaded.\n"
                               f"Try: 'Show me all MCFs' to see what's available."
                }
            
            row = mcf_data.iloc[0]
            
            # Check what user is asking
            asking_cp1_only = "cp1" in user_lower and "cp2" not in user_lower
            asking_cp2_only = "cp2" in user_lower and "cp1" not in user_lower
            
            if asking_cp1_only:
                # Show only CP1
                cp1_name = row.get('CP1 Name', 'Not available')
                cp1_code = row.get('CP1 Code', 'N/A')
                
                message = f"**🤝 CP1 for {mcf}:**\n\n"
                message += f"👤 **Name:** {cp1_name}\n"
                message += f"🔖 **Code:** {cp1_code}\n"
                
                if 'Expected CP1 Payout' in row.index:
                    message += f"💰 **Expected Payout:** ₹{pd.to_numeric(row.get('Expected CP1 Payout', 0), errors='coerce'):,.0f}\n"
                if 'Actual CP1 Payout' in row.index:
                    message += f"💰 **Actual Payout:** ₹{pd.to_numeric(row.get('Actual CP1 Payout', 0), errors='coerce'):,.0f}\n"
                
                message += f"\n📦 **Customer:** {row.get('Customer Name', 'N/A')}\n"
                message += f"💵 **Deal P&L:** ₹{pd.to_numeric(row.get('Net Profit/Loss', 0), errors='coerce'):,.0f}\n"
                
                return {"type": "answer", "message": message}
            
            elif asking_cp2_only:
                # Show only CP2
                cp2_name = row.get('CP2 Name', 'Not available')
                cp2_code = row.get('CP2 Code', 'N/A')
                
                message = f"**🤝 CP2 for {mcf}:**\n\n"
                message += f"👤 **Name:** {cp2_name}\n"
                message += f"🔖 **Code:** {cp2_code}\n"
                
                if cp2_name and cp2_name != 'Not available' and str(cp2_name).strip():
                    if 'Expected CP2 Payout' in row.index:
                        message += f"💰 **Expected Payout:** ₹{pd.to_numeric(row.get('Expected CP2 Payout', 0), errors='coerce'):,.0f}\n"
                    if 'Actual CP2 Payout' in row.index:
                        message += f"💰 **Actual Payout:** ₹{pd.to_numeric(row.get('Actual CP2 Payout', 0), errors='coerce'):,.0f}\n"
                else:
                    message += f"\nℹ️ **Note:** This MCF doesn't have a CP2 partner.\n"
                
                message += f"\n📦 **Customer:** {row.get('Customer Name', 'N/A')}\n"
                
                return {"type": "answer", "message": message}
            
            else:
                # Show both CP1 and CP2
                message = f"**🤝 Channel Partners for {mcf}:**\n\n"
                
                message += f"**👥 CP1 (Channel Partner 1):**\n"
                message += f"• Name: {row.get('CP1 Name', 'Not available')}\n"
                message += f"• Code: {row.get('CP1 Code', 'N/A')}\n"
                if 'Expected CP1 Payout' in row.index:
                    message += f"• Expected: ₹{pd.to_numeric(row.get('Expected CP1 Payout', 0), errors='coerce'):,.0f}\n"
                if 'Actual CP1 Payout' in row.index:
                    message += f"• Actual: ₹{pd.to_numeric(row.get('Actual CP1 Payout', 0), errors='coerce'):,.0f}\n"
                
                message += f"\n**👥 CP2 (Channel Partner 2):**\n"
                cp2_name = row.get('CP2 Name', '')
                if cp2_name and str(cp2_name).strip():
                    message += f"• Name: {cp2_name}\n"
                    message += f"• Code: {row.get('CP2 Code', 'N/A')}\n"
                    if 'Expected CP2 Payout' in row.index:
                        message += f"• Expected: ₹{pd.to_numeric(row.get('Expected CP2 Payout', 0), errors='coerce'):,.0f}\n"
                    if 'Actual CP2 Payout' in row.index:
                        message += f"• Actual: ₹{pd.to_numeric(row.get('Actual CP2 Payout', 0), errors='coerce'):,.0f}\n"
                else:
                    message += f"• ℹ️ No CP2 for this MCF\n"
                
                message += f"\n**📦 Customer:** {row.get('Customer Name', 'N/A')}\n"
                message += f"**💵 Deal P&L:** ₹{pd.to_numeric(row.get('Net Profit/Loss', 0), errors='coerce'):,.0f}\n"
                
                return {"type": "answer", "message": message}
        
        else:
            # Looking for partner by name
            quoted = re.findall(r'["\']([^"\']+)["\']', user_message)
            if quoted:
                partner_name = quoted[0]
            else:
                stop_words = ['show', 'me', 'all', 'mcf', 'mcfs', 'for', 'partner', 'cp1', 'cp2', 'named', 'is']
                words = [w for w in user_message.split() if w.lower() not in stop_words and len(w) > 2]
                partner_name = ' '.join(words).strip()
            
            if partner_name:
                # Search in both CP1 and CP2
                cp1_matches = smart_search(master_df, partner_name, ['CP1 Name'])
                cp2_matches = smart_search(master_df, partner_name, ['CP2 Name'])
                
                all_matches = pd.concat([cp1_matches, cp2_matches]).drop_duplicates(subset=['MCF Number'])
                
                if not all_matches.empty:
                    message = f"**🔍 Found {len(all_matches)} MCF(s) for partner '{partner_name}':**\n\n"
                    
                    for i, (_, row) in enumerate(all_matches.head(15).iterrows(), 1):
                        message += f"**{i}. {row['MCF Number']}**\n"
                        message += f"   👤 Customer: {row.get('Customer Name', 'N/A')}\n"
                        
                        # Check which role
                        if row['MCF Number'] in cp1_matches['MCF Number'].values:
                            message += f"   🤝 Role: CP1 - {row.get('CP1 Name', 'N/A')}\n"
                            message += f"   💰 Payout: ₹{pd.to_numeric(row.get('Actual CP1 Payout', 0), errors='coerce'):,.0f}\n"
                        
                        if row['MCF Number'] in cp2_matches['MCF Number'].values:
                            message += f"   🤝 Role: CP2 - {row.get('CP2 Name', 'N/A')}\n"
                            message += f"   💰 Payout: ₹{pd.to_numeric(row.get('Actual CP2 Payout', 0), errors='coerce'):,.0f}\n"
                        
                        message += f"   📊 P&L: ₹{pd.to_numeric(row.get('Net Profit/Loss', 0), errors='coerce'):,.0f}\n\n"
                    
                    if len(all_matches) > 15:
                        message += f"... and {len(all_matches) - 15} more MCFs\n"
                    
                    return {"type": "answer", "message": message}
                else:
                    # Suggest similar names
                    all_cp1 = master_df['CP1 Name'].dropna().unique()
                    all_cp2 = master_df['CP2 Name'].dropna().unique()
                    all_partners = list(set(list(all_cp1) + list(all_cp2)))
                    
                    similar = [p for p in all_partners if partner_name.lower() in str(p).lower()][:5]
                    
                    message = f"❌ **No MCFs found for partner '{partner_name}'.**\n\n"
                    
                    if similar:
                        message += f"💡 **Did you mean:**\n"
                        for p in similar:
                            message += f"• {p}\n"
                    else:
                        message += f"💡 Try: 'Show all partners' to see available names"
                    
                    return {"type": "answer", "message": message}
            else:
                return {
                    "type": "answer",
                    "message": "🤔 **I can help you with partner information!**\n\n"
                               "**Please specify:**\n"
                               "• MCF number: 'Who is CP1 for MCF-20250428-0588?'\n"
                               "• Partner name: 'Show MCFs for partner Kaushalya'\n\n"
                               "**Examples:**\n"
                               "• 'CP1 name for MCF-20250428-0588'\n"
                               "• 'Show all deals for partner \"Kaushalya\"'"
                }
    
    # ============================================================
    # QUERY 2: Show Lists
    # ============================================================
    elif "show" in user_lower and ("profit" in user_lower or "loss" in user_lower):
        
        if 'Net Profit/Loss' not in master_df.columns:
            return {"type": "error", "message": "Net Profit/Loss column not found in data"}
        
        # Convert to numeric
        master_df['Net Profit/Loss'] = pd.to_numeric(master_df['Net Profit/Loss'], errors='coerce').fillna(0)
        
        if "profit" in user_lower:
            profit_df = master_df[master_df['Net Profit/Loss'] > 0].sort_values('Net Profit/Loss', ascending=False)
            
            if profit_df.empty:
                return {"type": "answer", "message": "✅ No profitable MCFs found in data."}
            
            message = f"**📈 Profitable MCFs ({len(profit_df)} found):**\n\n"
            
            for i, (_, row) in enumerate(profit_df.head(20).iterrows(), 1):
                message += f"**{i}. {row['MCF Number']}**\n"
                message += f"   👤 {row.get('Customer Name', 'N/A')}\n"
                message += f"   💰 Profit: **₹{row['Net Profit/Loss']:,.0f}**\n"
                message += f"   🤝 CP1: {row.get('CP1 Name', 'N/A')}\n\n"
            
            if len(profit_df) > 20:
                message += f"... and {len(profit_df) - 20} more\n"
            
            return {"type": "answer", "message": message}
        
        elif "loss" in user_lower:
            loss_df = master_df[master_df['Net Profit/Loss'] < 0].sort_values('Net Profit/Loss')
            
            if loss_df.empty:
                return {"type": "answer", "message": "✅ No loss-making MCFs!"}
            
            message = f"**📉 Loss-Making MCFs ({len(loss_df)} found):**\n\n"
            
            for i, (_, row) in enumerate(loss_df.head(20).iterrows(), 1):
                message += f"**{i}. {row['MCF Number']}**\n"
                message += f"   👤 {row.get('Customer Name', 'N/A')}\n"
                message += f"   🔴 Loss: **₹{row['Net Profit/Loss']:,.0f}**\n"
                message += f"   🤝 CP1: {row.get('CP1 Name', 'N/A')}\n\n"
            
            if len(loss_df) > 20:
                message += f"... and {len(loss_df) - 20} more\n"
            
            return {"type": "answer", "message": message}
    
    # ============================================================
    # QUERY 3: Summary
    # ============================================================
    elif "summary" in user_lower:
        master_df['Net Profit/Loss'] = pd.to_numeric(master_df['Net Profit/Loss'], errors='coerce').fillna(0)
        
        total_pl = master_df['Net Profit/Loss'].sum()
        profitable = len(master_df[master_df['Net Profit/Loss'] > 0])
        losses = len(master_df[master_df['Net Profit/Loss'] < 0])
        
        message = f"""**📊 P&L Summary:**

**Overall:**
• Total MCFs: {len(master_df)}
• Total P&L: **₹{total_pl:,.0f}** {'✅' if total_pl > 0 else '🔴'}

**Breakdown:**
• Profitable: {profitable} MCFs
• Losses: {losses} MCFs

💡 Ask me about specific MCFs or partners!
"""
        return {"type": "answer", "message": message}
    
    # ============================================================
    # FALLBACK: Help
    # ============================================================
    else:
        return {
            "type": "answer",
            "message": f"""🤔 **I'm here to help! Try asking:**

**🔍 Find Partners:**
• "Who is CP1 for MCF-20250428-0588?"
• "Show all MCFs for partner Kaushalya"
• "CP1 and CP2 for MCF-20250428-0588"

**📊 View Data:**
• "Show profitable MCFs"
• "Show loss MCFs"
• "Give me a summary"

**Current Data:** {len(master_df)} MCFs loaded

**What would you like to know?**
"""
        }

# Main App
st.markdown("""
<div class="main-header">
    <h1>🤖 P&L Reconciliation AI Agent</h1>
    <p>Chat with AI about your data</p>
</div>
""", unsafe_allow_html=True)

# Sidebar
with st.sidebar:
    st.header("⚙️ Configuration")
    
    if not st.session_state.connected:
        spreadsheet_id = st.text_input("📊 Google Sheet ID", type="password")
        gemini_key = st.text_input("🔑 Gemini API Key", type="password")
        creds_json = st.text_area("🔐 Credentials JSON", height=150)
        
        if st.button("🔌 Connect"):
            if spreadsheet_id and gemini_key and creds_json:
                try:
                    creds_dict = json.loads(creds_json)
                    
                    with st.spinner("Connecting..."):
                        spreadsheet, model, error = init_services(spreadsheet_id, creds_dict, gemini_key)
                    
                    if error:
                        st.error(f"❌ {error}")
                    else:
                        st.session_state.spreadsheet = spreadsheet
                        st.session_state.model = model
                        st.session_state.connected = True
                        
                        # Load ALL sheets
                        with st.spinner("Loading all sheets..."):
                            all_data = load_all_sheets(spreadsheet)
                            st.session_state.all_data = all_data
                        
                        st.success("✅ Connected!")
                        st.rerun()
                
                except Exception as e:
                    st.error(f"❌ Error: {str(e)}")
            else:
                st.warning("Fill all fields")
    else:
        st.success("✅ Connected")
        
        if st.session_state.all_data:
            st.markdown("### 📊 Loaded Sheets")
            for sheet_name, df in st.session_state.all_data.items():
                st.write(f"• {sheet_name}: {len(df)} rows")
        
        st.markdown("---")
        
        if st.button("🔄 Reload Data"):
            with st.spinner("Reloading..."):
                all_data = load_all_sheets(st.session_state.spreadsheet)
                st.session_state.all_data = all_data
            st.success("Reloaded!")
            st.rerun()
        
        if st.button("🗑️ Clear Chat"):
            st.session_state.messages = []
            st.rerun()
        
        if st.button("🔌 Disconnect"):
            st.session_state.connected = False
            st.session_state.all_data = {}
            st.session_state.messages = []
            st.rerun()

# Main Chat
if st.session_state.connected and st.session_state.all_data:
    
    # Display chat
    for msg in st.session_state.messages:
        if msg["role"] == "user":
            st.markdown(f'<div class="chat-message user-message"><strong>You:</strong><br>{msg["content"]}</div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="chat-message ai-message"><strong>🤖 AI:</strong><br>{msg["content"]}</div>', unsafe_allow_html=True)
    
    # Quick actions
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("📉 Show Losses"):
            st.session_state.messages.append({"role": "user", "content": "Show me all loss MCFs"})
            st.rerun()
    with col2:
        if st.button("📈 Show Profits"):
            st.session_state.messages.append({"role": "user", "content": "Show me all profitable MCFs"})
            st.rerun()
    with col3:
        if st.button("📊 Summary"):
            st.session_state.messages.append({"role": "user", "content": "Give me a summary"})
            st.rerun()
    
    # Chat input
    user_input = st.chat_input("Ask me anything...")
    
    if user_input:
        st.session_state.messages.append({"role": "user", "content": user_input})
        
        with st.spinner("🤔 Thinking..."):
            response = chat_with_agent(user_input, st.session_state.all_data)
        
        st.session_state.messages.append({"role": "assistant", "content": response["message"]})
        st.rerun()

else:
    st.info("👈 Connect using sidebar to get started")
