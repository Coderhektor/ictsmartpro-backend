'use client';

import { SignedIn, SignedOut, UserButton, useUser, RedirectToSignIn } from '@clerk/nextjs';
import { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';

interface Signal { id: number; symbol: string; direction: 'BUY' | 'SELL'; price: number; strength: string; reasons: string; time: string; tf: string; }

export default function Home() {
  const { isLoaded, isSignedIn } = useUser();
  const [signals, setSignals] = useState<Signal[]>([]);
  const [nextScan, setNextScan] = useState(15);

  useEffect(() => {
    if (!isSignedIn) return;

    const audio = new Audio('https://assets.mixkit.co/sfx/preview/mixkit-arcade-game-jump-coin-216.mp3');
    const ws = new WebSocket('wss://ictsmartpro-backend.up.railway.app/ws/signals');

    ws.onmessage = (e) => {
      const data = JSON.parse(e.data);
      const newSignal: Signal = { id: Date.now(), symbol: data.symbol, direction: data.direction === 'BUY' ? 'BUY' : 'SELL', price: data.price, strength: data.strength, reasons: data.reasons, time: data.time, tf: data.tf || '15m' };
      audio.play().catch(() => {});
      if ('vibrate' in navigator) navigator.vibrate([200, 100, 200]);
      setSignals(prev => [newSignal, ...prev].slice(0, 30));
    };

    const timer = setInterval(() => setNextScan(s => s <= 1 ? 15 : s - 1), 1000);
    return () => { ws.close(); clearInterval(timer); };
  }, [isSignedIn]);

  // Geri sayım
  useEffect(() => {
    const t = setInterval(() => setNextScan(s => s <= 1 ? 15 : s - 1), 1000);
    return () => clearInterval(t);
  }, []);

  return (
    <>
      <SignedOut>
        <div className="min-h-screen bg-gradient-to-br from-gray-950 to-black flex items-center justify-center p-6">
          <div className="text-center max-w-md">
            <h1 className="text-6xl font-black bg-gradient-to-r from-emerald-400 to-teal-500 bg-clip-text text-transparent">ICT SMART PRO</h1>
            <p className="text-xl text-gray-400 mt-4">En güçlü ICT sinyalleri artık sadece üyelerimize</p>
            <div className="mt-10">
              <RedirectToSignIn />
            </div>
            <p className="text-sm text-gray-500 mt-8">Giriş yap veya üye ol → anında sinyaller başlasın</p>
          </div>
        </div>
      </SignedOut>

      <SignedIn>
        {/* BURASI TAM ÖNCEKİ GÜZEL DASHBOARD – sadece üyelere görünür */}
        <div className="min-h-screen bg-gradient-to-br from-gray-950 via-black to-gray-900 text-white">
          <header className="border-b border-gray-800 backdrop-blur-xl bg-black/60 sticky top-0 z-50">
            <div className="max-w-7xl mx-auto px-6 py-5 flex justify-between items-center">
              <div className="flex items-center gap-4">
                <div className="w-12 h-12 bg-gradient-to-br from-emerald-500 to-teal-600 rounded-2xl flex items-center justify-center text-2xl font-black">ICT</div>
                <div>
                  <h1 className="text-2xl font-black">SMART PRO v13</h1>
                  <p className="text-xs text-gray-400">Hoş geldin, şampiyon</p>
                </div>
              </div>
              <div className="flex items-center gap-6">
                <div className="text-right">
                  <div className="text-sm text-gray-400">Sonraki tarama</div>
                  <div className="text-2xl font-bold text-emerald-400">{nextScan}s</div>
                </div>
                <UserButton afterSignOutUrl="/" />
              </div>
            </div>
          </header>

          <main className="max-w-5xl mx-auto p-6">
            <AnimatePresence>
              {signals.map((s) => (
                <motion.div key={s.id} initial={{ opacity: 0, y: -50 }} animate={{ opacity: 1, y: 0 }} className={`mb-5 p-6 rounded-3xl border backdrop-blur-xl ${s.direction === 'BUY' ? 'bg-gradient-to-r from-emerald-950/50 to-emerald-900/30 border-emerald-700/50' : 'bg-gradient-to-r from-red-950/50 to-red-900/30 border-red-700/50'}`}>
                  <div className="flex justify-between items-start">
                    <div>
                      <div className="flex items-center gap-4">
                        <span className={`text-5xl font-black ${s.direction === 'BUY' ? 'text-emerald-400' : 'text-red-400'}`}>{s.direction === 'BUY' ? 'ALIŞ' : 'SATIŞ'}</span>
                        <span className="text-4xl font-bold">{s.symbol}</span>
                      </div>
                      <div className="mt-4 flex flex-wrap gap-3">
                        <span className={`px-5 py-2 rounded-full font-bold text-sm ${s.strength === 'ULTRA GÜÇLÜ' ? 'bg-yellow-500/20 text-yellow-300 border border-yellow-600/50' : 'bg-blue-500/20 text-blue-300'}`}>
                          {s.strength}
                        </span>
                        {s.reasons.split(' | ').map(r => <span key={r} className="px-4 py-2 bg-white/5 rounded-full text-sm">{r}</span>)}
                      </div>
                    </div>
                    <div className="text-right">
                      <div className="text-4xl font-black">${s.price.toLocaleString()}</div>
                      <div className="text-sm text-gray-400">{s.time}</div>
                    </div>
                  </div>
                </motion.div>
              ))}
            </AnimatePresence>

            {signals.length === 0 && (
              <div className="text-center py-32 text-3xl text-gray-500">
                Sinyaller yükleniyor... Birazdan başlıyoruz
              </div>
            )}
          </main>
        </div>
      </SignedIn>
    </>
  );
}