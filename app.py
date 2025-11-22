"""
P&L RECONCILIATION AI AGENT - WEB APP
Standalone application with public URL

Deploy to: Streamlit Cloud (free)
Access from: Any device with internet
"""

import streamlit as st
import pandas as pd
import json
import gspread
from google.oauth2.service_account import Credentials
import google.generativeai as genai
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import time

# Page config
st.set_page_config(
    page_title="P&L Reconciliation AI Agent",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
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
        box-shadow: 0 10px 30px rgba(0,0,0,0.2);
    }
    .chat-message {
        padding: 20px;
        border-radius: 15px;
        margin: 15px 0;
        animation: fadeIn 0.5s;
    }
    @keyframes fadeIn {
        from { opacity: 0; transform: translateY(10px); }
        to { opacity: 1; transform: translateY(0); }
    }
    .user-message {
        background: linear-gradient(135deg, #e3f2fd 0%, #bbdefb 100%);
        border-left: 5px solid #2196F3;
        margin-left: 50px;
    }
    .ai-message {
        background: linear-gradient(135deg, #f3e5f5 0%, #e1bee7 100%);
        border-left: 5px solid #9c27b0;
        margin-right: 50px;
    }
    .action-result {
        background: linear-gradient(135deg, #d4edda 0%, #c3e6cb 100%);
        border: 3px solid #28a745;
        padding: 20px;
        border-radius: 15px;
        margin: 15px 0;
    }
    .metric-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 25px;
        border-radius: 15px;
        color: white;
        text-align: center;
        box-shadow: 0 5px 15px rgba(0,0,0,0.2);
    }
    .stButton>button {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        border: none;
        padding: 12px 30px;
        border-radius: 25px;
        font-weight: bold;
        box-shadow: 0 4px 10px rgba(0,0,0,0.2);
        transition: all 0.3s;
    }
    .stButton>button:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 15px rgba(0,0,0,0.3);
    }
</style>
""", unsafe_allow_html=True)

# Initialize session state
if "messages" not in st.session_state:
    st.session_state.messages = []
if "spreadsheet" not in st.session_state:
    st.session_state.spreadsheet = None
if "model" not in st.session_state:
    st.session_state.model = None
if "results_df" not in st.session_state:
    st.session_state.results_df = None
if "connected" not in st.session_state:
    st.session_state.connected = False

# Functions
@st.cache_resource
def init_services(spreadsheet_id, creds_dict, gemini_key):
    """Initialize Google Sheets and Gemini"""
    try:
        # Google Sheets
        scopes = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]
        credentials = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(credentials)
        spreadsheet = client.open_by_key(spreadsheet_id)
        
        # Gemini
        genai.configure(api_key=gemini_key)
        model = genai.GenerativeModel('gemini-1.5-flash-latest')
        
        return spreadsheet, model, None
    except Exception as e:
        return None, None, str(e)

def load_master_reconciliation(spreadsheet):
    """Load data from Master Reconciliation sheet"""
    try:
        ws = spreadsheet.worksheet("Master Reconciliation")
        data = ws.get_all_records()
        df = pd.DataFrame(data)
        
        # Clean column names
        df.columns = df.columns.str.strip()
        
        # Convert numeric columns
        numeric_cols = ['Net Profit/Loss', 'Expected CP1 Payout', 'Actual CP1 Payout', 
                       'Expected CP2 Payout', 'Actual CP2 Payout', 'Taxable Amount (Invoice)']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
        
        return df
    except Exception as e:
        st.error(f"Error loading data: {e}")
        return None

def execute_sheet_action(action_type, params, spreadsheet, results_df):
    """Execute actions on Google Sheets based on AI commands"""
    
    results = []
    
    try:
        ws = spreadsheet.worksheet("Master Reconciliation")
        all_data = ws.get_all_values()
        headers = all_data[0]
        
        if action_type == "cover_loss":
            loss_mcf = params.get("loss_mcf")
            profit_mcf = params.get("profit_mcf")
            
            # Get amounts
            loss_row = results_df[results_df['MCF Number'] == loss_mcf]
            profit_row = results_df[results_df['MCF Number'] == profit_mcf]
            
            if loss_row.empty or profit_row.empty:
                return [{"status": "error", "message": f"❌ MCF numbers not found: {loss_mcf} or {profit_mcf}"}]
            
            loss_amount = abs(float(loss_row.iloc[0]['Net Profit/Loss']))
            profit_amount = float(profit_row.iloc[0]['Net Profit/Loss'])
            
            # Add adjustment columns if needed
            if "Adjusted P&L" not in headers:
                adj_col = len(headers) + 1
                note_col = len(headers) + 2
                ws.update_cell(1, adj_col, "Adjusted P&L")
                ws.update_cell(1, note_col, "Adjustment Note")
            else:
                adj_col = headers.index("Adjusted P&L") + 1
                note_col = headers.index("Adjustment Note") + 1
            
            # Find row indices
            loss_idx = profit_idx = None
            for i, row in enumerate(all_data, 1):
                if row[0] == loss_mcf:
                    loss_idx = i
                if row[0] == profit_mcf:
                    profit_idx = i
            
            if loss_idx and profit_idx:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
                
                if profit_amount >= loss_amount:
                    # Full coverage
                    ws.update_cell(loss_idx, adj_col, 0)
                    ws.update_cell(loss_idx, note_col, f"✅ Covered by {profit_mcf} on {timestamp}")
                    ws.update_cell(profit_idx, adj_col, profit_amount - loss_amount)
                    ws.update_cell(profit_idx, note_col, f"📤 Covered {loss_mcf} on {timestamp}")
                    
                    results.append({
                        "status": "success",
                        "message": f"✅ Successfully covered loss of ₹{loss_amount:,.0f} from **{loss_mcf}** using profit from **{profit_mcf}**",
                        "details": {
                            "Loss MCF": loss_mcf,
                            "Loss Amount": f"₹{loss_amount:,.0f}",
                            "Profit MCF": profit_mcf,
                            "Profit Used": f"₹{loss_amount:,.0f}",
                            "Remaining Profit": f"₹{profit_amount - loss_amount:,.0f}"
                        }
                    })
                else:
                    # Partial coverage
                    remaining = loss_amount - profit_amount
                    ws.update_cell(loss_idx, adj_col, -remaining)
                    ws.update_cell(loss_idx, note_col, f"⚠️ Partially covered by {profit_mcf} on {timestamp}")
                    ws.update_cell(profit_idx, adj_col, 0)
                    ws.update_cell(profit_idx, note_col, f"📤 Partially covered {loss_mcf} on {timestamp}")
                    
                    results.append({
                        "status": "warning",
                        "message": f"⚠️ Partially covered ₹{profit_amount:,.0f} out of ₹{loss_amount:,.0f}. Remaining loss: ₹{remaining:,.0f}",
                        "details": {
                            "Loss MCF": loss_mcf,
                            "Total Loss": f"₹{loss_amount:,.0f}",
                            "Covered Amount": f"₹{profit_amount:,.0f}",
                            "Remaining Loss": f"₹{remaining:,.0f}"
                        }
                    })
        
        elif action_type == "mark_reviewed":
            mcf = params.get("mcf")
            
            if "Review Status" not in headers:
                status_col = len(headers) + 1
                date_col = len(headers) + 2
                ws.update_cell(1, status_col, "Review Status")
                ws.update_cell(1, date_col, "Review Date")
            else:
                status_col = headers.index("Review Status") + 1
                date_col = status_col + 1
            
            for i, row in enumerate(all_data, 1):
                if row[0] == mcf:
                    ws.update_cell(i, status_col, "✅ Reviewed")
                    ws.update_cell(i, date_col, datetime.now().strftime("%Y-%m-%d %H:%M"))
                    results.append({
                        "status": "success",
                        "message": f"✅ Marked **{mcf}** as reviewed"
                    })
                    break
        
        elif action_type == "update_value":
            mcf = params.get("mcf")
            column = params.get("column")
            value = params.get("value")
            
            if column not in headers:
                results.append({"status": "error", "message": f"❌ Column '{column}' not found"})
            else:
                col_idx = headers.index(column) + 1
                for i, row in enumerate(all_data, 1):
                    if row[0] == mcf:
                        ws.update_cell(i, col_idx, value)
                        results.append({
                            "status": "success",
                            "message": f"✅ Updated {column} to **{value}** for {mcf}"
                        })
                        break
        
        return results
    
    except Exception as e:
        return [{"status": "error", "message": f"❌ Error: {str(e)}"}]

def chat_with_ai(user_message, results_df, spreadsheet, model):
    """Enhanced chat with smart pattern matching and AI fallback"""
    
    if results_df is None or results_df.empty:
        return {
            "type": "error",
            "message": "No data loaded. Please ensure Master Reconciliation sheet exists."
        }
    
    import re
    user_lower = user_message.lower()
    
    # ===== PATTERN 1: Find MCF by Customer Name =====
    if any(word in user_lower for word in ["customer", "client", "name"]) and any(word in user_lower for word in ["mcf", "number", "deal"]):
        # Extract potential customer name
        # Look for quoted text or capitalized words
        quoted = re.findall(r'["\']([^"\']+)["\']', user_message)
        
        if quoted:
            customer_query = quoted[0].lower()
        else:
            # Try to extract name from message
            stop_words = ['what', 'is', 'the', 'mcf', 'number', 'for', 'customer', 'client', 'named', 'called', 'of', 'with', 'name']
            words = [w for w in user_message.split() if w.lower() not in stop_words and len(w) > 2]
            customer_query = ' '.join(words[:3]).lower() if words else ''
        
        if customer_query:
            # Search in customer name column
            matches = results_df[results_df['Customer Name'].str.lower().str.contains(customer_query, na=False)]
            
            if not matches.empty:
                message = f"**Found {len(matches)} MCF(s) for customer matching '{customer_query}':**\n\n"
                for _, row in matches.iterrows():
                    message += f"📋 **MCF Number:** {row['MCF Number']}\n"
                    message += f"   👤 **Customer:** {row.get('Customer Name', 'N/A')}\n"
                    message += f"   💰 **P&L:** ₹{row['Net Profit/Loss']:,.0f}\n"
                    message += f"   📦 **Product:** {row.get('Loan Product', 'N/A')}\n\n"
                
                return {"type": "answer", "message": message}
            else:
                return {"type": "answer", "message": f"❌ No MCFs found for customer containing '{customer_query}'"}
    
    # ===== PATTERN 2: Find Customer by MCF Number =====
    mcf_pattern = r'MCF-\d{8}-\d{4}'
    mcfs = re.findall(mcf_pattern, user_message.upper())
    
    if mcfs and any(word in user_lower for word in ["customer", "client", "who", "name"]):
        mcf = mcfs[0]
        row = results_df[results_df['MCF Number'] == mcf]
        
        if not row.empty:
            row = row.iloc[0]
            message = f"**MCF Details: {mcf}**\n\n"
            message += f"👤 **Customer:** {row.get('Customer Name', 'Not available')}\n"
            message += f"📦 **Loan Product:** {row.get('Loan Product', 'Not available')}\n"
            message += f"💰 **Loan Amount:** ₹{row.get('Loan Amount', 0):,.0f}\n"
            message += f"📊 **Net P&L:** ₹{row['Net Profit/Loss']:,.0f}\n"
            
            return {"type": "answer", "message": message}
        else:
            return {"type": "answer", "message": f"❌ MCF {mcf} not found in data"}
    
    # ===== PATTERN 3: Get CP1/CP2 for MCF =====
    if mcfs and any(word in user_lower for word in ["cp1", "cp2", "channel partner", "partner", "who is"]):
        mcf = mcfs[0]
        row = results_df[results_df['MCF Number'] == mcf]
        
        if not row.empty:
            row = row.iloc[0]
            message = f"**Channel Partners for {mcf}:**\n\n"
            
            # CP1 Details
            message += f"**👥 CP1 (Channel Partner 1):**\n"
            message += f"   • Name: {row.get('CP1 Name', 'Not available')}\n"
            message += f"   • Code: {row.get('CP1 Code', 'N/A')}\n"
            message += f"   • Expected Payout: ₹{row.get('Expected CP1 Payout', 0):,.0f}\n"
            message += f"   • Actual Payout: ₹{row.get('Actual CP1 Payout', 0):,.0f}\n"
            
            if 'CP1 Payout Variance' in row.index:
                variance = row.get('CP1 Payout Variance', 0)
                if variance != 0:
                    message += f"   • Variance: ₹{variance:,.0f} {'⚠️' if abs(variance) > 1000 else ''}\n"
            
            message += f"\n**👥 CP2 (Channel Partner 2):**\n"
            message += f"   • Name: {row.get('CP2 Name', 'Not available')}\n"
            message += f"   • Code: {row.get('CP2 Code', 'N/A')}\n"
            message += f"   • Expected Payout: ₹{row.get('Expected CP2 Payout', 0):,.0f}\n"
            message += f"   • Actual Payout: ₹{row.get('Actual CP2 Payout', 0):,.0f}\n"
            
            if 'CP2 Payout Variance' in row.index:
                variance = row.get('CP2 Payout Variance', 0)
                if variance != 0:
                    message += f"   • Variance: ₹{variance:,.0f} {'⚠️' if abs(variance) > 1000 else ''}\n"
            
            message += f"\n**📦 Customer:** {row.get('Customer Name', 'N/A')}\n"
            message += f"**💰 Total Deal P&L:** ₹{row['Net Profit/Loss']:,.0f}\n"
            
            return {"type": "answer", "message": message}
        else:
            return {"type": "answer", "message": f"❌ MCF {mcf} not found"}
    
    # ===== PATTERN 4: Full MCF Details =====
    if mcfs and any(word in user_lower for word in ["details", "info", "information", "about", "tell me"]):
        mcf = mcfs[0]
        row = results_df[results_df['MCF Number'] == mcf]
        
        if not row.empty:
            row = row.iloc[0]
            message = f"**📋 Complete Details for {mcf}**\n\n"
            
            message += f"**👤 Customer Information:**\n"
            message += f"   • Name: {row.get('Customer Name', 'N/A')}\n"
            message += f"   • Product: {row.get('Loan Product', 'N/A')}\n"
            message += f"   • Loan Amount: ₹{row.get('Loan Amount', 0):,.0f}\n\n"
            
            message += f"**💰 Revenue Details:**\n"
            message += f"   • Expected Gross Revenue: ₹{row.get('Expected Disbursed Gross Revenue', 0):,.0f}\n"
            message += f"   • Actual Gross Revenue: ₹{row.get('Disbursed Gross Revenue', 0):,.0f}\n"
            if 'Revenue Variance' in row.index:
                message += f"   • Variance: ₹{row.get('Revenue Variance', 0):,.0f}\n"
            message += f"   • Taxable Amount: ₹{row.get('Taxable Amount (Invoice)', 0):,.0f}\n\n"
            
            message += f"**👥 Channel Partners:**\n"
            message += f"   • CP1: {row.get('CP1 Name', 'N/A')} (₹{row.get('Actual CP1 Payout', 0):,.0f})\n"
            message += f"   • CP2: {row.get('CP2 Name', 'N/A')} (₹{row.get('Actual CP2 Payout', 0):,.0f})\n\n"
            
            message += f"**📊 Bottom Line:**\n"
            pl = row['Net Profit/Loss']
            pl_status = "✅ Profit" if pl > 0 else "🔴 Loss" if pl < 0 else "⚪ Break-even"
            message += f"   • Net P&L: **₹{pl:,.0f}** {pl_status}\n"
            
            if 'Payout Status' in row.index and row.get('Payout Status'):
                message += f"   • Payout Status: {row.get('Payout Status')}\n"
            
            return {"type": "answer", "message": message}
        else:
            return {"type": "answer", "message": f"❌ MCF {mcf} not found"}
    
    # ===== PATTERN 5: Find MCFs by CP1/CP2 Name =====
    if any(word in user_lower for word in ["cp1", "cp2", "partner"]) and any(word in user_lower for word in ["mcf", "deals", "how many", "show"]):
        # Extract potential partner name
        quoted = re.findall(r'["\']([^"\']+)["\']', user_message)
        
        if quoted:
            partner_query = quoted[0].lower()
        else:
            # Try to extract from message
            stop_words = ['show', 'me', 'all', 'mcf', 'for', 'cp1', 'cp2', 'partner', 'named', 'called', 'is', 'the']
            words = [w for w in user_message.split() if w.lower() not in stop_words and len(w) > 2]
            partner_query = ' '.join(words[:3]).lower() if words else ''
        
        if partner_query:
            # Search in both CP1 and CP2
            cp1_matches = results_df[results_df['CP1 Name'].str.lower().str.contains(partner_query, na=False)]
            cp2_matches = results_df[results_df['CP2 Name'].str.lower().str.contains(partner_query, na=False)]
            
            all_matches = pd.concat([cp1_matches, cp2_matches]).drop_duplicates()
            
            if not all_matches.empty:
                message = f"**Found {len(all_matches)} MCF(s) with partner matching '{partner_query}':**\n\n"
                
                for _, row in all_matches.head(15).iterrows():
                    message += f"📋 **{row['MCF Number']}**\n"
                    message += f"   👤 Customer: {row.get('Customer Name', 'N/A')}\n"
                    
                    if partner_query in row.get('CP1 Name', '').lower():
                        message += f"   👥 Role: CP1 - {row.get('CP1 Name', 'N/A')}\n"
                        message += f"   💰 Payout: ₹{row.get('Actual CP1 Payout', 0):,.0f}\n"
                    
                    if partner_query in row.get('CP2 Name', '').lower():
                        message += f"   👥 Role: CP2 - {row.get('CP2 Name', 'N/A')}\n"
                        message += f"   💰 Payout: ₹{row.get('Actual CP2 Payout', 0):,.0f}\n"
                    
                    message += f"   📊 P&L: ₹{row['Net Profit/Loss']:,.0f}\n\n"
                
                if len(all_matches) > 15:
                    message += f"... and {len(all_matches) - 15} more MCFs\n"
                
                return {"type": "answer", "message": message}
            else:
                return {"type": "answer", "message": f"❌ No MCFs found with partner matching '{partner_query}'"}
    
    # ===== PATTERN 6: Show Profitable MCFs =====
    if "profit" in user_lower and "show" in user_lower:
        profit_df = results_df[results_df['Net Profit/Loss'] > 0].sort_values('Net Profit/Loss', ascending=False)
        
        if profit_df.empty:
            message = "No profitable MCFs found."
        else:
            message = f"**📈 Found {len(profit_df)} profitable MCFs:**\n\n"
            for i, (_, row) in enumerate(profit_df.head(20).iterrows(), 1):
                message += f"{i}. **{row['MCF Number']}** - {row.get('Customer Name', 'N/A')}\n"
                message += f"   💰 P&L: **₹{row['Net Profit/Loss']:,.0f}**\n"
                message += f"   👥 CP1: {row.get('CP1 Name', 'N/A')}\n\n"
            
            if len(profit_df) > 20:
                message += f"... and {len(profit_df) - 20} more profitable MCFs\n"
        
        return {"type": "answer", "message": message}
    
    # ===== PATTERN 7: Show Loss MCFs =====
    elif "loss" in user_lower and "show" in user_lower:
        loss_df = results_df[results_df['Net Profit/Loss'] < 0].sort_values('Net Profit/Loss')
        
        if loss_df.empty:
            message = "✅ No loss-making MCFs found!"
        else:
            message = f"**📉 Found {len(loss_df)} loss-making MCFs:**\n\n"
            for i, (_, row) in enumerate(loss_df.head(20).iterrows(), 1):
                message += f"{i}. **{row['MCF Number']}** - {row.get('Customer Name', 'N/A')}\n"
                message += f"   🔴 Loss: **₹{row['Net Profit/Loss']:,.0f}**\n"
                message += f"   👥 CP1: {row.get('CP1 Name', 'N/A')}\n\n"
            
            if len(loss_df) > 20:
                message += f"... and {len(loss_df) - 20} more loss MCFs\n"
        
        return {"type": "answer", "message": message}
    
    # ===== PATTERN 8: Summary =====
    elif "summary" in user_lower or ("total" in user_lower and "pl" in user_lower):
        total_pl = results_df['Net Profit/Loss'].sum()
        profitable = len(results_df[results_df['Net Profit/Loss'] > 0])
        losses = len(results_df[results_df['Net Profit/Loss'] < 0])
        avg_pl = results_df['Net Profit/Loss'].mean()
        max_profit = results_df['Net Profit/Loss'].max()
        max_loss = results_df['Net Profit/Loss'].min()
        
        message = f"""**📊 P&L Summary Report:**

**Overall Performance:**
• Total MCFs: {len(results_df)}
• Total P&L: **₹{total_pl:,.0f}** {'✅' if total_pl > 0 else '🔴'}
• Average P&L: ₹{avg_pl:,.0f}

**Deal Breakdown:**
• Profitable Deals: {profitable} MCFs ({profitable/len(results_df)*100:.1f}%)
• Loss-Making Deals: {losses} MCFs ({losses/len(results_df)*100:.1f}%)

**Extremes:**
• Highest Profit: ₹{max_profit:,.0f}
• Highest Loss: ₹{max_loss:,.0f}
"""
        return {"type": "answer", "message": message}
    
    # ===== PATTERN 9: Cover Loss =====
    elif "cover" in user_lower and "loss" in user_lower:
        if len(mcfs) >= 2:
            loss_mcf = mcfs[0]
            profit_mcf = mcfs[1]
        else:
            loss_df = results_df[results_df['Net Profit/Loss'] < 0].sort_values('Net Profit/Loss')
            profit_df = results_df[results_df['Net Profit/Loss'] > 0].sort_values('Net Profit/Loss', ascending=False)
            
            if loss_df.empty:
                return {"type": "answer", "message": "✅ No losses to cover!"}
            if profit_df.empty:
                return {"type": "answer", "message": "❌ No profitable MCFs available."}
            
            loss_mcf = loss_df.iloc[0]['MCF Number']
            profit_mcf = profit_df.iloc[0]['MCF Number']
        
        action_results = execute_sheet_action(
            "cover_loss",
            {"loss_mcf": loss_mcf, "profit_mcf": profit_mcf},
            spreadsheet,
            results_df
        )
        
        return {
            "type": "action",
            "explanation": f"Covering loss from **{loss_mcf}** with profit from **{profit_mcf}**",
            "results": action_results
        }
    
    # ===== PATTERN 10: Mark as Reviewed =====
    elif "mark" in user_lower and "review" in user_lower:
        if not mcfs:
            return {"type": "error", "message": "Please specify an MCF number"}
        
        mcf = mcfs[0]
        action_results = execute_sheet_action(
            "mark_reviewed",
            {"mcf": mcf},
            spreadsheet,
            results_df
        )
        
        return {
            "type": "action",
            "explanation": f"Marking **{mcf}** as reviewed",
            "results": action_results
        }
    
    # ===== FALLBACK: Help Message =====
    else:
        return {
            "type": "answer",
            "message": f"""I can help you with:

**🔍 Find Information:**
• "What is the MCF number for customer ABC Ltd?"
• "Who is the customer for MCF-20250404-1026?"
• "Who is CP1 and CP2 for MCF-20250428-0588?"
• "Show me details of MCF-20250505-1264"
• "Show all MCFs for partner Kaushalya"

**📊 View Data:**
• "Show me all profitable MCFs"
• "Show me all loss MCFs"
• "Give me a summary"

**✏️ Make Changes:**
• "Cover loss from MCF-XXX with MCF-YYY"
• "Mark MCF-XXX as reviewed"

**Current Stats:**
• Total MCFs: {len(results_df)}
• Total P&L: ₹{results_df['Net Profit/Loss'].sum():,.0f}

Try asking me something!"""
        }

# Main App UI
st.markdown("""
<div class="main-header">
    <h1>🤖 P&L Reconciliation AI Agent</h1>
    <p>Chat with AI to analyze and modify your Google Sheets data</p>
</div>
""", unsafe_allow_html=True)

# Sidebar
with st.sidebar:
    st.header("⚙️ Configuration")
    
    if not st.session_state.connected:
        st.info("👈 Configure your credentials to get started")
        
        spreadsheet_id = st.text_input(
            "📊 Google Sheet ID",
            type="password",
            help="Found in your sheet URL"
        )
        
        gemini_key = st.text_input(
            "🔑 Gemini API Key",
            type="password",
            help="Get from Google AI Studio"
        )
        
        creds_json = st.text_area(
            "🔐 Google Credentials JSON",
            height=200,
            help="Paste entire service account JSON"
        )
        
        if st.button("🔌 Connect", use_container_width=True):
            if spreadsheet_id and gemini_key and creds_json:
                try:
                    creds_dict = json.loads(creds_json)
                    
                    with st.spinner("Connecting..."):
                        spreadsheet, model, error = init_services(
                            spreadsheet_id, creds_dict, gemini_key
                        )
                    
                    if error:
                        st.error(f"❌ {error}")
                    else:
                        st.session_state.spreadsheet = spreadsheet
                        st.session_state.model = model
                        st.session_state.connected = True
                        
                        # Load data
                        df = load_master_reconciliation(spreadsheet)
                        st.session_state.results_df = df
                        
                        st.success("✅ Connected!")
                        st.rerun()
                
                except json.JSONDecodeError:
                    st.error("❌ Invalid JSON format")
                except Exception as e:
                    st.error(f"❌ Error: {str(e)}")
            else:
                st.warning("Please fill all fields")
    else:
        st.success("✅ Connected")
        
        if st.session_state.results_df is not None:
            df = st.session_state.results_df
            
            st.markdown("---")
            st.subheader("📊 Quick Stats")
            
            total_pl = df['Net Profit/Loss'].sum() if 'Net Profit/Loss' in df.columns else 0
            profitable = len(df[df['Net Profit/Loss'] > 0]) if 'Net Profit/Loss' in df.columns else 0
            losses = len(df[df['Net Profit/Loss'] < 0]) if 'Net Profit/Loss' in df.columns else 0
            
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Total MCFs", len(df))
                st.metric("Profitable", profitable, delta="Good")
            with col2:
                pl_color = "normal" if total_pl >= 0 else "inverse"
                st.metric("Total P&L", f"₹{total_pl:,.0f}", delta_color=pl_color)
                st.metric("Losses", losses, delta="Bad" if losses > 0 else "Good")
        
        st.markdown("---")
        
        if st.button("🔄 Reload Data", use_container_width=True):
            df = load_master_reconciliation(st.session_state.spreadsheet)
            st.session_state.results_df = df
            st.success("Data reloaded!")
            time.sleep(1)
            st.rerun()
        
        if st.button("🗑️ Clear Chat", use_container_width=True):
            st.session_state.messages = []
            st.rerun()
        
        if st.button("🔌 Disconnect", use_container_width=True):
            st.session_state.connected = False
            st.session_state.spreadsheet = None
            st.session_state.model = None
            st.session_state.results_df = None
            st.session_state.messages = []
            st.rerun()

# Main chat area
if st.session_state.connected and st.session_state.results_df is not None:
    
    # Display metrics
    df = st.session_state.results_df
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.markdown('<div class="metric-card"><h3>Total MCFs</h3><h2>' + str(len(df)) + '</h2></div>', unsafe_allow_html=True)
    with col2:
        total_pl = df['Net Profit/Loss'].sum()
        st.markdown(f'<div class="metric-card"><h3>Total P&L</h3><h2>₹{total_pl:,.0f}</h2></div>', unsafe_allow_html=True)
    with col3:
        profitable = len(df[df['Net Profit/Loss'] > 0])
        st.markdown(f'<div class="metric-card"><h3>Profitable</h3><h2>{profitable}</h2></div>', unsafe_allow_html=True)
    with col4:
        losses = len(df[df['Net Profit/Loss'] < 0])
        st.markdown(f'<div class="metric-card"><h3>Losses</h3><h2>{losses}</h2></div>', unsafe_allow_html=True)
    
    st.markdown("---")
    
    # Chat interface
    st.subheader("💬 Chat with AI Agent")
    
    # Display chat history
    for msg in st.session_state.messages:
        if msg["role"] == "user":
            st.markdown(f"""
            <div class="chat-message user-message">
                <strong>You:</strong><br>{msg["content"]}
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown(f"""
            <div class="chat-message ai-message">
                <strong>🤖 AI:</strong><br>{msg["content"]}
            </div>
            """, unsafe_allow_html=True)
            
            # Show action results
            if "results" in msg:
                for result in msg["results"]:
                    status_class = "action-result" if result["status"] == "success" else "chat-message"
                    st.markdown(f'<div class="{status_class}">{result["message"]}</div>', unsafe_allow_html=True)
                    
                    if "details" in result:
                        st.json(result["details"])
    
    # Quick action buttons
    st.markdown("#### 💡 Quick Actions")
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        if st.button("📉 Show Losses"):
            st.session_state.current_input = "Show me all loss-making MCFs"
            st.rerun()
    with col2:
        if st.button("📈 Show Profits"):
            st.session_state.current_input = "Show me all profitable MCFs"
            st.rerun()
    with col3:
        if st.button("🔄 Cover Loss"):
            st.session_state.current_input = "Cover the biggest loss with the biggest profit"
            st.rerun()
    with col4:
        if st.button("📊 Summary"):
            st.session_state.current_input = "Give me a complete summary"
            st.rerun()
    
    # Chat input
    user_input = st.chat_input("Type your message... (e.g., 'Cover loss from MCF-001 with MCF-002')")
    
    if "current_input" in st.session_state:
        user_input = st.session_state.current_input
        del st.session_state.current_input
    
    if user_input:
        # Add user message
        st.session_state.messages.append({
            "role": "user",
            "content": user_input
        })
        
        # Get AI response
        with st.spinner("🤔 AI is thinking..."):
            time.sleep(1)  # Rate limit protection
            response = chat_with_ai(
                user_input,
                st.session_state.results_df,
                st.session_state.spreadsheet,
                st.session_state.model
            )
        
        # Add AI response
        if response["type"] == "action":
            ai_msg = {
                "role": "assistant",
                "content": response.get("explanation", "Action completed"),
                "results": response.get("results", [])
            }
            
            # Reload data after action
            df = load_master_reconciliation(st.session_state.spreadsheet)
            st.session_state.results_df = df
        else:
            ai_msg = {
                "role": "assistant",
                "content": response.get("message", "I couldn't process that.")
            }
        
        st.session_state.messages.append(ai_msg)
        st.rerun()

else:
    st.info("👈 Please connect using the sidebar configuration")
    
    st.markdown("""
    ### 🚀 Getting Started
    
    1. **Get your credentials:**
       - Google Sheet ID (from URL)
       - Gemini API key ([Get here](https://makersuite.google.com/app/apikey))
       - Service Account JSON ([Guide](https://console.cloud.google.com))
    
    2. **Enter in sidebar**
    
    3. **Start chatting!**
    
    ### 💬 Example Commands:
    - "Show me all loss-making MCFs"
    - "Cover loss from MCF-20250404-1026 with MCF-20250325-0148"
    - "Mark MCF-20250428-0588 as reviewed"
    - "What's the total P&L?"
    - "Show me top 5 profitable MCFs"
    """)

# Footer
st.markdown("---")
st.markdown("""
<div style="text-align: center; color: #666; padding: 20px;">
    <p>🤖 P&L Reconciliation AI Agent v1.0</p>
    <p style="font-size: 12px;">Built with ❤️ for Urban Money Pvt Ltd | Powered by Gemini AI</p>
</div>
""", unsafe_allow_html=True)
