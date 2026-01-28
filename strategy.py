"""
Growth Momentum DCA Strategy
============================
Smart DCA into high-growth tech stocks with momentum and market risk filters.

Universe: NVDA, TSLA, AMD, QBTS, RKLB
- Only buys stocks trading ABOVE their 20-day SMA (confirms uptrend)
- Pauses all buying when SPY RSI > 75 OR VIX > 25 (risk-off)
- Executes 3-5 times daily during market hours
- Equal weight, $100 per qualifying stock per execution
"""

import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from cpz.clients.sync import CPZClient

# High-growth universe (no mega-caps)
SYMBOLS = ["NVDA", "TSLA", "AMD", "QBTS", "RKLB"]
DCA_AMOUNT = 100  # $ per stock per execution
SMA_PERIOD = 20
RSI_PERIOD = 14
RSI_THRESHOLD = 75
VIX_THRESHOLD = 25


def initialize_client():
    """Initialize CPZ client with broker connection."""
    strategy_id = os.environ.get("CPZ_AI_API_STRATEGY_ID", "demo")
    os.environ["CPZ_ENABLE_FILL_POLLING"] = "false"
    
    client = CPZClient()
    client.execution.use_broker("alpaca", account_id="PA3AFDYNOT4A")
    return client, strategy_id


def calculate_rsi(prices: list, period: int = 14) -> float:
    """Calculate RSI from a list of closing prices."""
    if len(prices) < period + 1:
        return 50.0
    
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    
    avg_gain = np.mean(gains[-period:])
    avg_loss = np.mean(losses[-period:])
    
    if avg_loss == 0:
        return 100.0
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def calculate_sma(prices: list, period: int = 20) -> float:
    """Calculate Simple Moving Average."""
    if len(prices) < period:
        return prices[-1] if prices else 0
    return np.mean(prices[-period:])


def get_historical_closes(client, symbol: str, days: int = 30) -> list:
    """Get historical closing prices for a symbol."""
    try:
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=days + 10)).strftime("%Y-%m-%d")
        
        bars = client.market_data.get_bars(
            symbol=symbol,
            timeframe="1Day",
            start=start_date,
            end=end_date
        )
        
        if bars and len(bars) > 0:
            return [bar.close for bar in bars]
        return []
    except Exception as e:
        print(f"Error getting bars for {symbol}: {e}")
        return []


def is_market_risky(client) -> bool:
    """Check if market conditions are risky (skip buying)."""
    try:
        spy_closes = get_historical_closes(client, "SPY", days=30)
        if spy_closes:
            spy_rsi = calculate_rsi(spy_closes, RSI_PERIOD)
            if spy_rsi > RSI_THRESHOLD:
                print(f"SPY RSI is {spy_rsi:.1f} (> {RSI_THRESHOLD}) - Market overextended")
                return True
        
        try:
            vix_quote = client.market_data.get_latest_quote("VIX")
            vix_level = vix_quote.last_price if vix_quote else 0
            if vix_level > VIX_THRESHOLD:
                print(f"VIX is {vix_level:.1f} (> {VIX_THRESHOLD}) - High volatility")
                return True
        except:
            pass
        
        return False
    except Exception as e:
        print(f"Error checking market risk: {e}")
        return False


def is_in_uptrend(client, symbol: str) -> bool:
    """Check if stock is trading above its 20-day SMA."""
    try:
        closes = get_historical_closes(client, symbol, days=30)
        if not closes or len(closes) < SMA_PERIOD:
            print(f"{symbol}: Not enough data for SMA calculation")
            return False
        
        current_price = closes[-1]
        sma = calculate_sma(closes, SMA_PERIOD)
        
        in_uptrend = current_price > sma
        trend_label = "UPTREND" if in_uptrend else "DOWNTREND"
        print(f"{symbol}: Price ${current_price:.2f}, SMA({SMA_PERIOD}) ${sma:.2f} - {trend_label}")
        return in_uptrend
    except Exception as e:
        print(f"Error checking uptrend for {symbol}: {e}")
        return False


def run():
    """Main strategy execution."""
    print("=" * 60)
    print(f"Growth Momentum DCA Strategy - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    client, strategy_id = initialize_client()
    print(f"Strategy ID: {strategy_id}")
    print(f"Universe: {", ".join(SYMBOLS)}")
    print(f"DCA Amount: ${DCA_AMOUNT} per qualifying stock")
    print()
    
    print("Checking market conditions...")
    if is_market_risky(client):
        print("\n[SKIP] Market risk elevated - skipping all DCA buys")
        return
    
    print("\nMarket conditions OK - proceeding with DCA...")
    print("-" * 40)
    
    orders_placed = 0
    for symbol in SYMBOLS:
        print(f"\nAnalyzing {symbol}...")
        
        if not is_in_uptrend(client, symbol):
            print(f"  [SKIP] {symbol} below SMA - not in uptrend")
            continue
        
        try:
            quote = client.market_data.get_latest_quote(symbol)
            if not quote:
                print(f"  [ERROR] Could not get quote for {symbol}")
                continue
            
            current_price = quote.last_price or quote.ask_price or quote.bid_price
            if not current_price or current_price <= 0:
                print(f"  [ERROR] Invalid price for {symbol}")
                continue
            
            shares = int(DCA_AMOUNT / current_price)
            if shares <= 0:
                print(f"  [SKIP] ${DCA_AMOUNT} not enough for 1 share at ${current_price:.2f}")
                continue
            
            print(f"  [BUY] {shares} shares of {symbol} at ~${current_price:.2f} (${shares * current_price:.2f})")
            
            order = client.execution.order(
                symbol=symbol,
                qty=shares,
                side="buy",
                order_type="market"
            )
            
            if order:
                order_id = order.id if hasattr(order, 'id') else 'submitted'
                print(f"  [OK] Order placed: {order_id}")
                orders_placed += 1
            else:
                print(f"  [ERROR] Order failed for {symbol}")
                
        except Exception as e:
            print(f"  [ERROR] Failed to process {symbol}: {e}")
            continue
    
    print("\n" + "=" * 60)
    print(f"DCA Complete: {orders_placed}/{len(SYMBOLS)} orders placed")
    print("=" * 60)


if __name__ == "__main__":
    run()
