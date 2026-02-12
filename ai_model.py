// ========== AI DEĞERLENDİRME ==========
async function evaluateAI() {
    const symbol = document.getElementById('symbolSelect').value;
    const price = document.getElementById('currentPrice').innerHTML;
    
    showNotification('🤖 AI fiyatı değerlendiriyor...', 'info');
    
    try {
        const response = await fetch(`/api/ai-evaluate/${symbol}`, {
            method: 'GET',
            headers: { 'Content-Type': 'application/json' }
        });
        
        if (!response.ok) throw new Error('API hatası');
        
        const data = await response.json();
        
        if (data.success) {
            const chatDiv = document.getElementById('chatMessages');
            const aiMessage = document.createElement('div');
            aiMessage.className = 'chat-message chat-bot mt-2';
            
            const signalColor = 
                data.ai_evaluation.action.includes('BUY') ? 'var(--accent-green)' : 
                data.ai_evaluation.action.includes('SELL') ? 'var(--accent-red)' : 
                'var(--accent-purple)';
            
            aiMessage.innerHTML = `
                <strong style="font-size: 1.3rem; color: var(--accent-cyan); text-shadow: 0 0 20px var(--accent-cyan);">🤖 AI DEĞERLENDİRME:</strong><br>
                <span style="font-size: 1.2rem; font-weight: 700;">📈 ${data.symbol} - $${data.current_price.toFixed(4)}</span><br>
                <span style="font-size: 1.2rem; font-weight: 800; color: ${signalColor}; text-shadow: 0 0 20px currentColor;">
                    🎯 SİNYAL: ${data.ai_evaluation.action.replace('_', ' ')}
                </span><br>
                <span style="font-size: 1.2rem; font-weight: 700;">⚡ GÜVEN: %${data.ai_evaluation.confidence}</span><br>
                <span style="font-size: 1.1rem; font-weight: 600;">📊 SKOR: ${data.ai_evaluation.score}</span><br>
                <span style="font-size: 1rem;">🔮 ${data.ai_evaluation.recommendation}</span><br>
                <span style="font-size: 0.95rem; color: var(--text-secondary); margin-top: 8px; display: block;">
                    ⭐ Destek: $${data.levels.support.toFixed(4)} | Direnç: $${data.levels.resistance.toFixed(4)}<br>
                    🕐 ${new Date().toLocaleTimeString('tr-TR')}
                </span>
            `;
            
            chatDiv.appendChild(aiMessage);
            chatDiv.scrollTop = chatDiv.scrollHeight;
            
            showNotification('✅ AI değerlendirmesi tamamlandı', 'success');
        }
        
    } catch (error) {
        console.error('AI değerlendirme hatası:', error);
        showNotification('❌ AI değerlendirmesi başarısız', 'error');
    }
}
