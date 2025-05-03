import os
import time
import ccxt
import pandas as pd
import talib
from dotenv import load_dotenv
import logging
import asyncio
from telegram import Bot  # For alerts (optional)

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
SYMBOL = 'BTC/USDT'
TIMEFRAME = '5m'
AMOUNT = 0.001  # Amount to trade (in BTC)
BASE_STOP_LOSS_PERCENT = 0.02  # Base 2% stop-loss
ADX_PERIOD = 14  # Period for ADX calculation
ADX_THRESHOLD = 25  # Threshold to determine trending market
ATR_PERIOD = 14  # Period for ATR calculation
ATR_MULTIPLIER = 2  # Multiplier for dynamic stop-loss
FEE_RATE = 0.001  # 0.1% trading fee (adjust based on Binance fee structure)

# Strategy-specific parameters
STRATEGY_PARAMS = {
    'trend_following': {'sma_short': 10, 'sma_long': 30, 'adx_period': ADX_PERIOD},
    'range_trading': {'bb_period': 20, 'bb_nbdev': 2, 'atr_period': ATR_PERIOD},
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
    return df

def place_order(side, amount, price):
    """Place a market order on Binance with fee consideration."""
    try:
        fee = amount * price * FEE_RATE if side == 'buy' else amount * FEE_RATE
        if side == 'buy':
            order = exchange.create_market_buy_order(SYMBOL, amount)
            logging.info(f"Buy order placed: {order}, Fee: {fee}")
            asyncio.run(send_alert(f"Buy order placed for {amount} {SYMBOL}, Fee: {fee}"))
        elif side == 'sell':
            order = exchange.create_market_sell_order(SYMBOL, amount)
            logging.info(f"Sell order placed: {order}, Fee: {fee}")
            asyncio.run(send_alert(f"Sell order placed for {amount} {SYMBOL}, Fee: {fee}"))
        return fee
    except Exception as e:
        logging.error(f"Error placing {side} order: {e}")
        asyncio.run(send_alert(f"Error placing {side} order: {e}"))
        return 0

def check_balance(symbol, amount, side, price):
    """Check if sufficient balance is available, including fees."""
    try:
        balance = exchange.fetch_balance()
        base, quote = symbol.split('/')
        total_cost = amount * price * (1 + FEE_RATE) if side == 'buy' else amount * price
        if side == 'buy' and balance[quote]['free'] < total_cost:
            logging.error(f"Insufficient {quote} balance for buy order (including fees)")
            return False
        if side == 'sell' and balance[base]['free'] < amount:
            logging.error(f"Insufficient {base} balance for sell order")
            return False
        return True
    except Exception as e:
        logging.error(f"Error checking balance: {e}")
        return False

def calculate_stop_loss(entry_price, atr):
    """Calculate dynamic stop-loss based on ATR."""
    stop_loss_distance = atr * ATR_MULTIPLIER
    return entry_price - stop_loss_distance

def check_stop_loss(entry_price, current_price, atr):
    """Check if dynamic stop-loss condition is met."""
    stop_loss_price = calculate_stop_loss(entry_price, atr)
    if current_price <= stop_loss_price:
        return True
    return False

def determine_market_condition(df):
    """Determine market condition using ADX."""
    latest_adx = df['adx'].iloc[-1]
    if latest_adx > ADX_THRESHOLD:
        return 'trending'
    else:
        return 'ranging'

def trend_following_strategy(df):
    latest = df.iloc[-1]
    prev = df.iloc[-2]
    if prev['sma_short'] < prev['sma_long'] and latest['sma_short'] > latest['sma_long']:
        return 'buy'
    elif prev['sma_short'] > prev['sma_long'] and latest['sma_short'] < latest['sma_long']:
        return 'sell'
    return None

def range_trading_strategy(df):
    latest = df.iloc[-1]
    atr = latest['atr']
    if latest['close'] <= latest['bb_lower'] + atr:
        return 'buy'
    elif latest['close'] >= latest['bb_upper'] - atr:
        return 'sell'
    return None

def main():
    logging.info(f"Starting trading bot for {SYMBOL}")
    position_open = False
    entry_price = None
    total_fees = 0

    while True:
        try:
            data = fetch_data(SYMBOL, TIMEFRAME)
            # Calculate ADX for market condition
            data['adx'] = talib.ADX(data['high'], data['low'], data['close'], timeperiod=ADX_PERIOD)
            market_condition = determine_market_condition(data)
            
            if market_condition == 'trending':
                strategy = 'trend_following'
            else:
                strategy = 'range_trading'
            
            data = calculate_indicators(data, strategy)
            latest = data.iloc[-1]
            current_price = latest['close']
            atr = latest['atr']
            
            # Select strategy function
            strategy_functions = {
                'trend_following': trend_following_strategy,
                'range_trading': range_trading_strategy,
            }
            action = strategy_functions[strategy](data)
            
            # Check stop-loss if position is open
            if position_open and entry_price:
                if check_stop_loss(entry_price, current_price, atr):
                    fee = place_order('sell', AMOUNT, current_price)
                    total_fees += fee
                    position_open = False
                    entry_price = None
                    logging.info(f"Total fees paid: {total_fees}")
                    continue
            
            # Execute trades
            if action == 'buy' and not position_open:
                if check_balance(SYMBOL, AMOUNT, 'buy', current_price):
                    fee = place_order('buy', AMOUNT, current_price)
                    total_fees += fee
                    position_open = True
                    entry_price = current_price
            elif action == 'sell' and position_open:
                if check_balance(SYMBOL, AMOUNT, 'sell', current_price):
                    fee = place_order('sell', AMOUNT, current_price)
                    total_fees += fee
                    position_open = False
                    entry_price = None
                    logging.info(f"Total fees paid: {total_fees}")
            
            time.sleep(300)  # 5-minute interval
        except Exception as e:
            logging.error(f"Error in main loop: {e}")
            asyncio.run(send_alert(f"Error in main loop: {e}"))
            time.sleep(60)

if __name__ == "__main__":
    main()