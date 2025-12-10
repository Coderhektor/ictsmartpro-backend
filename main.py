# main.py
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import os
from datetime import datetime
from utils.ict_strategy import ICT_Pro_Strategy

# Kalıcı klasör (Railway’de çalışır)
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

st.set_page_config(page_title="ICT PRO 2025", page_icon="rocket", layout="wide")

# Tema
st.markdown("""
<style>
    .big-font {font-size:55px !important; font-weight:bold; color:#00ff9d;}
    .signal-buy {background:linear-gradient(90deg,#003d26,#00ff88); padding:15px; border-radius:15px; color:white; font-size:18px; margin:10px 0;}
    .signal-sell {background:linear-gradient(90deg,#3d0000,#ff0066); padding:15px; border-radius:15px; color:white; font-size:18px; margin:10px 0;}
    .css-1d391kg {padding-top: 1rem;}
</style>
""", unsafe_allow_html=True)

st.markdown('<p class="big-font">ICT PRO STRATEGY 2025</p>', unsafe_allow_html=True)
st.markdown("### Order Block • FVG • Liquidity • Breaker • Killzone • HTF Bias")

# Sidebar
with st.sidebar:
    st.header("Kontrol Paneli")
    uploaded_file = st.file_uploader("CSV Yükle (Date, open, high, low, close)", type="csv")
    htf_bias = st.selectbox("Higher Timeframe Bias", ["neutral", "bull", "bear"], index=0)
    
    if st.button("ANALİZİ BAŞLAT", type="primary", use_container_width=True):
        if uploaded_file:
            with st.spinner("ICT motor çalışıyor..."):
                # Dosyayı kalıcı kaydet
                file_path = os.path.join(DATA_DIR, uploaded_file.name)
                with open(file_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())
                
                df = pd.read_csv(file_path)
                if 'Date' not in df.columns:
                    st.error("CSV'de 'Date' sütunu olmalı!")
                    st.stop()
                df['Date'] = pd.to_datetime(df['Date'])
                df = df.sort_values('Date').reset_index(drop=True)

                strategy = ICT_Pro_Strategy(df, htf_bias=htf_bias)
                result_df = strategy.run()

                st.session_state.result = result_df
                st.session_state.filename = uploaded_file.name
                st.success(f"Analiz tamamlandı! {len(result_df[result_df['BUY'] | result_df['SELL']])} sinyal bulundu.")
        else:
            st.error("Lütfen CSV dosyası yükleyin!")

# Ana ekran
if 'result' in st.session_state:
    df = st.session_state.result

    c1, c2, c3, c4 = st.columns(4)
    total_signals = len(df[df['BUY'] | df['SELL']])
    with c1: st.metric("Toplam Sinyal", total_signals)
    with c2: st.metric("BUY", len(df[df['BUY']]))
    with c3: st.metric("SELL", len(df[df['SELL']]))
    with c4: st.metric("Dosya", st.session_state.filename.split('.')[0])

    # Son sinyaller
    signals = df[df['BUY'] | df['SELL']].tail(10)
    if not signals.empty:
        st.subheader("Son Sinyaller")
        for _, row in signals.iterrows():
            if row['BUY']:
                st.markdown(f"<div class='signal-buy'>BUY → {row['Date'].strftime('%Y-%m-%d %H:%M')} @ {row['ENTRY']:.5f} | Score: {row['BUY_SCORE']:.2f}</div>", unsafe_allow_html=True)
            else:
                st.markdown(f"<div class='signal-sell'>SELL → {row['Date'].strftime('%Y-%m-%d %H:%M')} @ {row['ENTRY']:.5f} | Score: {row['SELL_SCORE']:.2f}</div>", unsafe_allow_html=True)

    # Grafik
    st.subheader("Chart")
    fig = go.Figure()
    fig.add_trace(go.Candlestick(x=df['Date'], open=df['open'], high=df['high'], low=df['low'], close=df['close'], name="Price"))

    buys = df[df['BUY']]
    if not buys.empty:
        fig.add_trace(go.Scatter(x=buys['Date'], y=buys['ENTRY'], mode='markers',
                                 marker=dict(color='lime', size=14, symbol='triangle-up', line=dict(width=3, color='white')),
                                 name='BUY Signal'))

    sells = df[df['SELL']]
    if not sells.empty:
        fig.add_trace(go.Scatter(x=sells['Date'], y=sells['ENTRY'], mode='markers',
                                 marker=dict(color='red', size=14, symbol='triangle-down', line=dict(width=3, color='white')),
                                 name='SELL Signal'))

    fig.update_layout(height=700, xaxis_rangeslider_visible=False, template="plotly_dark")
    st.plotly_chart(fig, use_container_width=True)

else:
    st.info("CSV dosyasını yükleyip 'ANALİZİ BAŞLAT' butonuna bas!")
    st.lottie("https://assets5.lottiefiles.com/packages/lf20_jcikwtux.json", height=300)