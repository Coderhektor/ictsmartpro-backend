# ========================================================================================================
# STARTUP & SHUTDOWN
# ========================================================================================================
@app.on_event("startup")
async def startup():
    logger.info("=" * 70)
    logger.info("🚀 ICTSMARTPRO ML Production API Started")
    logger.info("=" * 70)
    logger.info(f"Environment: {Config.ENV}")
    logger.info(f"Models loaded: {len(ml_trainer.models)}")
    logger.info(f"Patterns: ICT(8), Classical(5), Candlestick(10+)")
    logger.info(f"Auto-retrain: {Config.ML_AUTO_RETRAIN}")
    logger.info("=" * 70)
    
    # Initialize data fetcher session
    await data_fetcher.ensure_session()
    logger.info("✅ Data fetcher session initialized")


@app.on_event("shutdown")
async def shutdown():
    logger.info("Shutting down...")
    
    # Close data fetcher session
    await data_fetcher.close_session()
    logger.info("✅ Data fetcher session closed")
