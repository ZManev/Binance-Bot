import os
import time
import ccxt
import pandas as pd
import talib
from dotenv import load_dotenv
import logging
import argparse
import asyncio
from telegram import Bot  # For alerts (optional)
import numpy as np

# Load environment variables
load_dotenv()
API_KEY = os.getenv('BINANCE_API_KEY')
API_SECRET = os.getenv('BINANCE_SECRET_KEY')

# Initialize Binance exchange
exchange = ccxt.binance({
    'apiKey': API_KEY,
    'secret': API_SECRET,
    'enableRateLimit': True,
})

# Configuration
TIMEFRAME = '5m'
AMOUNT = 0.001  # Amount to trade (in base currency)
BASE_STOP_LOSS_PERCENT = 0.02  # Base 2% stop-loss
ADX_PERIOD = 14  # Period for ADX calculation
ADX_THRESHOLD = 25  # Threshold to determine trending market
ATR_PERIOD = 14  # Period for ATR calculation
ATR_MULTIPLIER = 2  # Multiplier for dynamic stop-loss
FEE_RATE = 0.001  # 0.1% trading fee (adjust based on Binance fee structure)
RISK_PER_TRADE = 0.01  # Risk 1% of account per trade

# Strategy-specific parameters
STRATEGY_PARAMS = {
    'trend_following': {'sma_short': 10, 'sma_long': 30, 'adx_period': ADX_PERIOD},
    'range_trading': {'bb_period': 20, 'bb_nbdev': 2, 'atr_period': ATR_PERIOD},
    'mean_reversion': {'rsi_period': 14, 'rsi_overbought': 70, 'rsi_oversold': 30},
}

# Logging setup
logging.basicConfig(filename='trading_bot.log', level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# Telegram alert setup (optional)
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
async def send_alert(message):
    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        bot = Bot(token=TELEGRAM_TOKEN)
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)

def fetch_data(symbol, timeframe, limit=100):
    """Fetch OHLCV data from Binance."""
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    return df

def calculate_indicators(df, strategy):
    """Calculate indicators based on the selected strategy."""
    if strategy == 'trend_following':
        df['sma_short'] = talib.SMA(df['close'], timeperiod=STRATEGY_PARAMS['trend_following']['sma_short'])
        df['sma_long'] = talib.SMA(df['close'], timeperiod=STRATEGY_PARAMS['trend_following']['sma_long'])
        df['adx'] = talib.ADX(df['high'], df['low'], df['close'], timeperiod=STRATEGY_PARAMS['trend_following']['adx_period'])
        df['atr'] = talib.ATR(df['high'], df['low'], df['close'], timeperiod=ATR_PERIOD)
    elif strategy == 'range_trading':
        df['bb_upper'], df['bb_middle'], df['bb_lower'] = talib.BBANDS(
            df['close'], timeperiod=STRATEGY_PARAMS['range_trading']['bb_period'],
            nbdevup=STRATEGY_PARAMS['range_trading']['bb_nbdev'], nbdevdn=STRATEGY_PARAMS['range_trading']['bb_nbdev'])
        df['atr'] = talib.ATR(df['high'], df['low'], df['close'], timeperiod=STRATEGY_PARAMS['range_trading']['atr_period'])
    elif strategy == 'mean_reversion':
        df['rsi'] = talib.RSI(df['close'], timeperiod=STRATEGY_PARAMS['mean_reversion']['rsi_period'])
        df['atr'] = talib.ATR(df['high'], df['low'], df['close'], timeperiod=ATR_PERIOD)
    return df

def place_order(symbol, side, amount, price, order_type='market'):
    """Place an order on Binance with fee consideration."""
    try:
        fee = amount * price * FEE_RATE if side == 'buy' else amount * FEE_RATE
        if order_type == 'market':
            if side == 'buy':
                order = exchange.create_market_buy_order(symbol, amount)
            elif side == 'sell':
                order = exchange.create_market_sell_order(symbol, amount)
        elif order_type == 'limit':
            order = exchange.create_limit_order(symbol, side, amount, price)
        logging.info(f"{order_type.capitalize()} {side} order placed for {symbol}: {order}, Fee: {fee}")
        asyncio.run(send_alert(f"{order_type.capitalize()} {side} order placed for {amount} {symbol}, Fee: {fee}"))
        return fee
    except Exception as e:
        logging.error(f"Error placing {side} {order_type} order for {symbol}: {e}")
        asyncio.run(send_alert(f"Error placing {side} {order_type} order for {symbol}: {e}"))
        return 0

def check_balance(symbol, amount, side, price):
    """Check if sufficient balance is available, including fees."""
    try:
        balance = exchange.fetch_balance()
        base, quote = symbol.split('/')
        total_cost = amount * price * (1 + FEE_RATE) if side == 'buy' else amount * price
        if side == 'buy' and balance[quote]['free'] < total_cost:
            logging.error(f"Insufficient {quote} balance for buy order on {symbol} (including fees)")
            return False
        if side == 'sell' and balance[base]['free'] < amount:
            logging.error(f"Insufficient {base} balance for sell order on {symbol}")
            return False
        return True
    except Exception as e:
        logging.error(f"Error checking balance for {symbol}: {e}")
        return False

def calculate_position_size(symbol, price, atr):
    """Calculate position size based on risk management."""
    balance = exchange.fetch_balance()
    quote = symbol.split('/')[1]
    account_balance = balance[quote]['free']
    risk_amount = account_balance * RISK_PER_TRADE
    stop_loss_distance = atr * ATR_MULTIPLIER
    position_size = risk_amount / stop_loss_distance
    return min(position_size, AMOUNT)  # Cap at configured AMOUNT

def calculate_stop_loss(entry_price, atr, side='buy'):
    """Calculate dynamic stop-loss based on ATR."""
    stop_loss_distance = atr * ATR_MULTIPLIER
    if side == 'buy':
        return entry_price - stop_loss_distance
    return entry_price + stop_loss_distance

def check_stop_loss(entry_price, current_price, atr, side='buy'):
    """Check if dynamic stop-loss condition is met."""
    stop_loss_price = calculate_stop_loss(entry_price, atr, side)
    if side == 'buy' and current_price <= stop_loss_price:
        return True
    if side == 'sell' and current_price >= stop_loss_price:
        return True
    return False

def determine_market_condition(df):
    """Determine market condition using ADX."""
    latest_adx = df['adx'].iloc[-1]
    if pd.isna(latest_adx):
        return 'ranging'  # Default to ranging if ADX is not yet calculated
    return 'trending' if latest_adx > ADX_THRESHOLD else 'ranging'

def trend_following_strategy(df):
    latest = df.iloc[-1]
    prev = df.iloc[-2]
    if pd.isna(prev['sma_short']) or pd.isna(latest['sma_short']):
        return None
    if prev['sma_short'] < prev['sma_long'] and latest['sma_short'] > latest['sma_long']:
        return 'buy'
    elif prev['sma_short'] > prev['sma_long'] and latest['sma_short'] < latest['sma_long']:
        return 'sell'
    return None

def range_trading_strategy(df):
    latest = df.iloc[-1]
    atr = latest['atr']
    if pd.isna(latest['bb_lower']) or pd.isna(atr):
        return None
    if latest['close'] <= latest['bb_lower'] + atr:
        return 'buy'
    elif latest['close'] >= latest['bb_upper'] - atr:
        return 'sell'
    return None

def mean_reversion_strategy(df):
    latest = df.iloc[-1]
    if pd.isna(latest['rsi']):
        return None
    if latest['rsi'] <= STRATEGY_PARAMS['mean_reversion']['rsi_oversold']:
        return 'buy'
    elif latest['rsi'] >= STRATEGY_PARAMS['mean_reversion']['rsi_overbought']:
        return 'sell'
    return None

def backtest_strategy(symbol, strategy, start_date, end_date):
    """Backtest the strategy on historical data."""
    historical_data = fetch_data(symbol, TIMEFRAME, limit=1000)
    historical_data = calculate_indicators(historical_data, strategy)
    
    position_open = False
    entry_price = None
    total_profit = 0
    trades = []
    total_fees = 0
    
    for i in range(1, len(historical_data)):
        df = historical_data.iloc[:i+1]
        action = strategy_functions[strategy](df)
        latest = df.iloc[-1]
        current_price = latest['close']
        atr = latest['atr']
        
        if pd.isna(atr):
            continue
        
        if position_open and entry_price:
            if check_stop_loss(entry_price, current_price, atr):
                profit = (current_price - entry_price) * AMOUNT - (2 * AMOUNT * current_price * FEE_RATE)
                total_profit += profit
                total_fees += 2 * AMOUNT * current_price * FEE_RATE
                trades.append({'action': 'sell', 'price': current_price, 'profit': profit})
                position_open = False
                entry_price = None
                continue
        
        if action == 'buy' and not position_open:
            entry_price = current_price
            position_open = True
            trades.append({'action': 'buy', 'price': current_price})
        elif action == 'sell' and position_open:
            profit = (current_price - entry_price) * AMOUNT - (2 * AMOUNT * current_price * FEE_RATE)
            total_profit += profit
            total_fees += 2 * AMOUNT * current_price * FEE_RATE
            trades.append({'action': 'sell', 'price': current_price, 'profit': profit})
            position_open = False
            entry_price = None
    
    logging.info(f"Backtest results for {symbol} with {strategy}: Total Profit: {total_profit}, Trades: {len(trades)}, Total Fees: {total_fees}")
    return total_profit, trades, total_fees

def main(symbols, strategy):
    logging.info(f"Starting trading bot for {symbols} with strategy: {strategy}")
    positions = {symbol: {'open': False, 'entry_price': None, 'total_fees': 0, 'side': None} for symbol in symbols}
    strategy_functions = {
        'trend_following': trend_following_strategy,
        'range_trading': range_trading_strategy,
        'mean_reversion': mean_reversion_strategy,
    }
    
    while True:
        try:
            for symbol in symbols:
                data = fetch_data(symbol, TIMEFRAME)
                data['adx'] = talib.ADX(data['high'], data['low'], data['close'], timeperiod=ADX_PERIOD)
                market_condition = determine_market_condition(data)
                
                # Dynamically select strategy based on market condition if not specified
                selected_strategy = strategy if strategy != 'auto' else (
                    'trend_following' if market_condition == 'trending' else 'range_trading'
                )
                
                data = calculate_indicators(data, selected_strategy)
                latest = data.iloc[-1]
                current_price = latest['close']
                atr = latest['atr']
                
                if pd.isna(atr):
                    continue
                
                action = strategy_functions[selected_strategy](data)
                
                # Check stop-loss if position is open
                if positions[symbol]['open'] and positions[symbol]['entry_price']:
                    if check_stop_loss(positions[symbol]['entry_price'], current_price, atr, positions[symbol]['side']):
                        side = 'sell' if positions[symbol]['side'] == 'buy' else 'buy'
                        fee = place_order(symbol, side, AMOUNT, current_price)
                        positions[symbol]['total_fees'] += fee
                        positions[symbol]['open'] = False
                        positions[symbol]['entry_price'] = None
                        positions[symbol]['side'] = None
                        logging.info(f"Total fees paid for {symbol}: {positions[symbol]['total_fees']}")
                        continue
                
                # Adjust position size based on risk
                position_size = calculate_position_size(symbol, current_price, atr)
                
                # Execute trades
                if action == 'buy' and not positions[symbol]['open']:
                    if check_balance(symbol, position_size, 'buy', current_price):
                        fee = place_order(symbol, 'buy', position_size, current_price, order_type='limit')
                        positions[symbol]['total_fees'] += fee
                        positions[symbol]['open'] = True
                        positions[symbol]['entry_price'] = current_price
                        positions[symbol]['side'] = 'buy'
                elif action == 'sell' and not positions[symbol]['open']:
                    if check_balance(symbol, position_size, 'sell', current_price):
                        fee = place_order(symbol, 'sell', position_size, current_price, order_type='limit')
                        positions[symbol]['total_fees'] += fee
                        positions[symbol]['open'] = True
                        positions[symbol]['entry_price'] = current_price
                        positions[symbol]['side'] = 'sell'
            
            time.sleep(300)  # 5-minute interval
        except Exception as e:
            logging.error(f"Error in main loop: {e}")
            asyncio.run(send_alert(f"Error in main loop: {e}"))
            time.sleep(60)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Binance Trading Bot")
    parser.add_argument('--symbols', nargs='+', default=['BTC/USDT'], help='List of trading pairs')
    parser.add_argument('--strategy', default='auto', help='Trading strategy (trend_following, range_trading, mean_reversion, auto)')
    parser.add_argument('--backtest', action='store_true', help='Run backtest on historical data')
    args = parser.parse_args()
    
    if args.backtest:
        for symbol in args.symbols:
            total_profit, trades, total_fees = backtest_strategy(symbol, args.strategy, '2023-01-01', '2023-12-31')
            print(f"Backtest results for {symbol}: Total Profit: {total_profit}, Trades: {len(trades)}, Total Fees: {total_fees}")
    else:
        main(args.symbols, args.strategy)