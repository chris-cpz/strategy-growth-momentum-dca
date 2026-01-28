"""
Backtesting script for Growth Momentum DCA

This script provides a framework for backtesting the strategy using Backtrader.
Comprehensive metrics including benchmark comparison and alpha calculation.

IMPORTANT: This script imports from strategy.py which must define:
  - SYMBOLS: List of ticker symbols to trade
  - generate_signal(data: dict, state: dict) -> dict: Signal generation function
    Returns dict of symbol -> weight (-1.0 to 1.0)
"""

import backtrader as bt
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta

# ============================================================================
# Import strategy functions from strategy.py
# ============================================================================
# The strategy.py file MUST define:
#   - SYMBOLS: List of ticker symbols
#   - generate_signal(data: dict, state: dict) -> dict: Returns weights per symbol

try:
    from strategy import generate_signal, SYMBOLS
except ImportError:
    # Fallback if strategy.py doesn't define these
    print("=" * 60)
    print("WARNING: Could not import generate_signal or SYMBOLS from strategy.py")
    print("Make sure your strategy.py defines:")
    print("  - SYMBOLS = ['SPY', 'QQQ', ...]  # List of symbols")
    print("  - def generate_signal(data, state): return {'SPY': 0.1, ...}")
    print("=" * 60)
    print("Using default SYMBOLS and placeholder generate_signal")
    SYMBOLS = ['SPY', 'QQQ']
    def generate_signal(current_data, state, **kwargs):
        return {s: 0.0 for s in SYMBOLS}

# Set random seed for reproducible backtests
np.random.seed(42)

# ============================================================================
# Backtest Configuration
# ============================================================================

END_DATE = datetime.now().strftime('%Y-%m-%d')
START_DATE = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')

INITIAL_CASH = 100_000
RISK_FREE_RATE = 0.05  # 5% annual risk-free rate

# Transaction costs
SLIPPAGE_BPS = 5
COMMISSION_BPS = 3

# ============================================================================
# Context class for strategy execution
# ============================================================================

class Context:
    """Context object for strategy execution"""
    def __init__(self, strategy):
        self.strategy = strategy
        self.positions = {}
    
    def target_weights(self, weights: dict):
        """Set target portfolio weights."""
        if not weights:
            return
        
        total_weight = sum(abs(w) for w in weights.values())
        if total_weight > 1.0:
            weights = {k: v / total_weight for k, v in weights.items()}
        
        for symbol, target_weight in weights.items():
            feed = next((d for d in self.strategy.datas if d._name == symbol), None)
            if feed is None:
                continue

            price = feed.close[0]
            if price <= 0:
                continue
                
            portfolio_value = self.strategy.broker.getvalue()
            target_value = portfolio_value * target_weight

            position = self.strategy.broker.getposition(feed)
            current_value = position.size * price

            order_size = (target_value - current_value) / price
            size = int(round(order_size))

            if size > 0:
                self.strategy.buy(data=feed, size=size)
            elif size < 0:
                self.strategy.sell(data=feed, size=abs(size))

# ============================================================================
# Backtrader Strategy Wrapper
# ============================================================================

class StrategyWrapper(bt.Strategy):
    """Wraps your strategy code for Backtrader"""
    
    params = (
        ('slippage_bps', SLIPPAGE_BPS),
        ('commission_bps', COMMISSION_BPS),
    )
    
    def __init__(self):
        self.ctx = Context(self)
        self.data_map = {d._name or "SYMBOL": d for d in self.datas}
        self.strategy_state = {}
        self.daily_values = []
    
    def next(self):
        # Record daily portfolio value
        self.daily_values.append(self.broker.getvalue())
        
        # Build current data snapshot for generate_signals
        current_data = {}
        for d in self.datas:
            name = d._name or "SYMBOL"
            current_data[name] = pd.DataFrame({
                'open': [d.open[0]],
                'high': [d.high[0]],
                'low': [d.low[0]],
                'close': [d.close[0]],
                'volume': [d.volume[0]],
            })
        
        # Call generate_signal from strategy.py
        try:
            weights = generate_signal(current_data, self.strategy_state)
            if isinstance(weights, dict) and len(weights) > 0:
                self.ctx.target_weights(weights)
        except Exception as e:
            print("Error in generate_signal: %s" % str(e))

# ============================================================================
# Benchmark Strategy (SPY Buy & Hold)
# ============================================================================

class BuyAndHoldSPY(bt.Strategy):
    """Simple buy and hold SPY for benchmark comparison"""
    
    def __init__(self):
        self.daily_values = []
        self.bought = False
    
    def next(self):
        if not self.bought:
            size = int(self.broker.getcash() * 0.99 / self.datas[0].close[0])
            if size > 0:
                self.buy(data=self.datas[0], size=size)
                self.bought = True
        
        self.daily_values.append(self.broker.getvalue())

# ============================================================================
# Calculate Comprehensive Metrics
# ============================================================================

def calculate_metrics(daily_values, initial_cash, trading_days=252):
    """Calculate all performance metrics with high precision"""
    
    if len(daily_values) < 2:
        return {}
    
    values = np.array(daily_values)
    
    # Daily returns
    daily_returns = np.diff(values) / values[:-1]
    
    # Total Return
    total_return = (values[-1] - initial_cash) / initial_cash * 100
    
    # Annualized Return
    num_days = len(daily_values)
    annualized_return = ((values[-1] / initial_cash) ** (trading_days / num_days) - 1) * 100
    
    # Volatility (annualized standard deviation)
    volatility = np.std(daily_returns) * np.sqrt(trading_days) * 100
    
    # Sharpe Ratio (annualized)
    excess_returns = daily_returns - (RISK_FREE_RATE / trading_days)
    if np.std(daily_returns) > 0:
        sharpe_ratio = (np.mean(excess_returns) / np.std(daily_returns)) * np.sqrt(trading_days)
    else:
        sharpe_ratio = 0.0
    
    # Maximum Drawdown
    peak = np.maximum.accumulate(values)
    drawdown = (peak - values) / peak * 100
    max_drawdown = np.max(drawdown)
    
    return {
        'total_return': total_return,
        'annualized_return': annualized_return,
        'volatility': volatility,
        'sharpe_ratio': sharpe_ratio,
        'max_drawdown': max_drawdown,
        'final_value': values[-1],
        'num_days': num_days
    }

def calculate_trade_stats(trade_analyzer):
    """Extract trade statistics from Backtrader analyzer"""
    try:
        total_trades = trade_analyzer.total.closed if hasattr(trade_analyzer.total, 'closed') else 0
        won_trades = trade_analyzer.won.total if hasattr(trade_analyzer.won, 'total') else 0
        
        if total_trades > 0:
            win_rate = (won_trades / total_trades) * 100
        else:
            win_rate = 0.0
            
        return {
            'total_trades': total_trades,
            'won_trades': won_trades,
            'win_rate': win_rate
        }
    except:
        return {'total_trades': 0, 'won_trades': 0, 'win_rate': 0.0}

# ============================================================================
# Backtest Execution
# ============================================================================

def run_backtest():
    print("=" * 70)
    print("GROWTH MOMENTUM DCA STRATEGY BACKTEST")
    print("=" * 70)
    print("Period: %s to %s" % (START_DATE, END_DATE))
    print("Initial Capital: $%s" % "{:,.2f}".format(INITIAL_CASH))
    print("Symbols: %s" % ', '.join(SYMBOLS))
    print("-" * 70)

    # Download data
    all_data = {}
    for symbol in SYMBOLS:
        print("Downloading %s..." % symbol)
        df = yf.download(symbol, start=START_DATE, end=END_DATE, progress=False)
        if not df.empty:
            if isinstance(df.columns, pd.MultiIndex):
                df = df.xs(symbol, level=1, axis=1)
            all_data[symbol] = df
            print("  %s: %d bars" % (symbol, len(df)))

    if not all_data:
        print("Error: No data loaded.")
        return None

    # ========== RUN STRATEGY BACKTEST ==========
    print("")
    print("-" * 70)
    print("Running Strategy Backtest...")
    
    cerebro = bt.Cerebro()
    cerebro.broker.setcash(INITIAL_CASH)
    cerebro.broker.setcommission(commission=COMMISSION_BPS / 10000)
    
    for symbol, df in all_data.items():
                    data = bt.feeds.PandasData(
                        dataname=df,
            open=0, high=1, low=2, close=3, volume=4,
                        openinterest=-1
                    )
                    cerebro.adddata(data, name=symbol)

    cerebro.addstrategy(StrategyWrapper)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    
    results = cerebro.run()
    strat = results[0]
    
    strategy_metrics = calculate_metrics(strat.daily_values, INITIAL_CASH)
    trade_stats = calculate_trade_stats(strat.analyzers.trades.get_analysis())

    # ========== RUN BENCHMARK BACKTEST (SPY Buy & Hold) ==========
    print("Running Benchmark (SPY Buy & Hold)...")
    
    cerebro_bench = bt.Cerebro()
    cerebro_bench.broker.setcash(INITIAL_CASH)
    cerebro_bench.broker.setcommission(commission=COMMISSION_BPS / 10000)

    if 'SPY' in all_data:
        data = bt.feeds.PandasData(
            dataname=all_data['SPY'],
            open=0, high=1, low=2, close=3, volume=4,
            openinterest=-1
        )
        cerebro_bench.adddata(data, name='SPY')
        cerebro_bench.addstrategy(BuyAndHoldSPY)
        
        bench_results = cerebro_bench.run()
        bench_strat = bench_results[0]
        benchmark_metrics = calculate_metrics(bench_strat.daily_values, INITIAL_CASH)
    else:
        benchmark_metrics = {
            'total_return': 0, 'annualized_return': 0, 'volatility': 0,
            'sharpe_ratio': 0, 'max_drawdown': 0
        }

    # ========== CALCULATE ALPHA ==========
    alpha = strategy_metrics.get('total_return', 0) - benchmark_metrics.get('total_return', 0)
    annualized_alpha = strategy_metrics.get('annualized_return', 0) - benchmark_metrics.get('annualized_return', 0)

    # ========== PRINT RESULTS ==========
    print("")
    print("=" * 70)
    print("BACKTEST RESULTS")
    print("=" * 70)
    
    print("")
    print("%-25s %-20s %-20s %-15s" % ('Metric', 'Strategy', 'Benchmark (SPY)', 'Alpha'))
    print("-" * 80)
    
    print("%-25s %18.2f%% %18.2f%% %13.2f%%" % (
        'Total Return (%)', 
        strategy_metrics.get('total_return', 0), 
        benchmark_metrics.get('total_return', 0), 
        alpha
    ))
    print("%-25s %18.2f%% %18.2f%% %13.2f%%" % (
        'Annualized Return (%)', 
        strategy_metrics.get('annualized_return', 0), 
        benchmark_metrics.get('annualized_return', 0), 
        annualized_alpha
    ))
    print("%-25s %18.2f%% %18.2f%% %13s" % (
        'Volatility (Stdev %)', 
        strategy_metrics.get('volatility', 0), 
        benchmark_metrics.get('volatility', 0), 
        '--'
    ))
    print("%-25s %19.2f %19.2f %13s" % (
        'Sharpe Ratio', 
        strategy_metrics.get('sharpe_ratio', 0), 
        benchmark_metrics.get('sharpe_ratio', 0), 
        '--'
    ))
    print("%-25s %18.2f%% %18.2f%% %13s" % (
        'Maximum Drawdown (%)', 
        strategy_metrics.get('max_drawdown', 0), 
        benchmark_metrics.get('max_drawdown', 0), 
        '--'
    ))
    print("%-25s %18.2f%% %19s %13s" % (
        'Winning Trades (%)', 
        trade_stats.get('win_rate', 0), 
        '--', 
        '--'
    ))
    
    print("")
    print("-" * 70)
    print("Total Trades: %d" % trade_stats.get('total_trades', 0))
    print("Winning Trades: %d" % trade_stats.get('won_trades', 0))
    print("Trading Days: %d" % strategy_metrics.get('num_days', 0))
    print("Final Portfolio Value: $%s" % "{:,.2f}".format(strategy_metrics.get('final_value', 0)))
    print("=" * 70)

    # Return metrics for external use
    return {
        'strategy': strategy_metrics,
        'benchmark': benchmark_metrics,
        'trades': trade_stats,
        'alpha': alpha,
        'annualized_alpha': annualized_alpha
    }

if __name__ == '__main__':
        run_backtest()
