# How to Use the Trading Bot in Real Life

This guide explains how to deploy and manage a trading bot designed for Binance spot trading in a real-world setting. The bot uses technical indicators (SMA, ADX, ATR, Bollinger Bands, RSI) and supports multiple strategies (trend following, range trading, mean reversion, and an auto mode).

## 1. Set Up the Environment
- **Install Python**: Ensure Python 3.6 or higher is installed on your system.
- **Install Required Libraries**: Use pip to install the necessary dependencies:
  ```
  pip install ccxt pandas TA-Lib python-dotenv telegram
  ```
  - **Note on TA-Lib**: If installation fails (common on Windows), try `pip install talib-binary` or use precompiled binaries.
- **System Requirements**: For continuous operation, consider running the bot on a VPS or cloud server.

## 2. Configure the Bot
- **Secure API Keys**:
  - Create a `.env` file in the bot’s directory:
    ```
    BINANCE_API_KEY=your_api_key
    BINANCE_SECRET_KEY=your_secret_key
    ```
  - Generate these keys from your Binance account, enabling trading permissions but disabling withdrawals for security.
- **Adjust Parameters**: Modify the script’s configuration:
  - `SYMBOL`: Trading pair (e.g., `'BTC/USDT'`). Use multiple pairs like `'BTC/USDT ETH/USDT'` for diversification.
  - `TIMEFRAME`: Candlestick interval (e.g., `'5m'` for 5-minute candles).
  - `AMOUNT`: Maximum trade size (e.g., `0.001` BTC). Adjust based on your account size.
  - `STRATEGY`: Options are `'trend_following'`, `'range_trading'`, `'mean_reversion'`, or `'auto'`.

## 3. Understand the Strategies
- **Trend Following**: Buys on short SMA crossing above long SMA, sells on the reverse (ADX confirms trend strength).
- **Range Trading**: Uses Bollinger Bands to trade within a range, adjusted by ATR.
- **Mean Reversion**: Buys when RSI is oversold, sells when overbought.
- **Auto**: Dynamically selects trend following or range trading based on ADX.

## 4. Risk Management
- **Position Sizing**: Risks 1% of your account per trade by default (`RISK_PER_TRADE = 0.01`).
- **Stop-Loss**: Uses a dynamic ATR-based stop-loss (e.g., `ATR_MULTIPLIER = 2`) alongside a base 2% stop-loss.
- **Customization**: Adjust these parameters to match your risk tolerance.

## 5. Backtest the Strategy
- **Run a Backtest**:
  ```
  python trading_bot.py --symbols BTC/USDT --strategy trend_following --backtest
  ```
- **Evaluate Results**: Check profitability, win rate, and drawdown using historical data (default is 1000 candles, ~3.5 days on 5m timeframe).
- **Fine-Tune**: Adjust parameters like SMA periods or RSI thresholds based on results.

## 6. Live Trading
- **Fund Your Account**: Ensure your Binance spot wallet has enough funds (e.g., USDT for BTC/USDT trades).
- **Start Small**: Begin with a small `AMOUNT` (e.g., `0.001` BTC) to test live performance.
- **Run the Bot**:
  ```
  python trading_bot.py --symbols BTC/USDT --strategy auto
  ```
- **Order Type**: The bot defaults to limit orders at the last close price. For immediate execution, modify `order_type` to `'market'` in the `place_order` call.

## 7. Monitoring
- **Logs**: Check `trading_bot.log` for trade details and errors.
- **Alerts (Optional)**: Configure Telegram notifications by adding your bot token and chat ID to the `.env` file.
- **Performance**: Regularly review trades to ensure the bot operates as expected.

## 8. Maintenance
- **Adapt to Markets**: Adjust strategies or parameters (e.g., TIMEFRAME, AMOUNT) as market conditions change.
- **API Updates**: Stay updated on Binance API changes or fee adjustments.
- **Reliability**: Use a process manager (e.g., Supervisor) to restart the bot if it crashes.

## Example Usage
To trade BTC/USDT and ETH/USDT with auto strategy:
```
python trading_bot.py --symbols BTC/USDT ETH/USDT --strategy auto
```

## Tips
- Start with a single symbol and strategy to simplify initial testing.
- Monitor fees and slippage, especially with frequent 5-minute trades.
- Consider adding a cooldown period or profit threshold to reduce over-trading.

By following these steps, you can effectively deploy and manage the trading bot in a real-world environment.