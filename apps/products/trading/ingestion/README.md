# Trading: Ingestion

Worker Python: connector CEX (CCXT+native WS) & DEX (Hyperliquid, dYdX v4, GMX, Vertex, Drift, Meteora DLMM, new-pair listener) -> normalizer -> fallback chain -> writer ke Neon. Lihat PRD Section B.11 utk rekomendasi sumber data.

See `docs/prd.md` (PRD + Rencana Teknis: Kinetiq) for full context and design decisions.
