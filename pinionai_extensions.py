import json
import httpx
import logging
import random
from google.genai import types as google_genai_types
from google.genai.types import (FunctionDeclaration, GenerateContentConfig,
                                GoogleSearch, HarmBlockThreshold, HarmCategory,
                                Part, SafetySetting, ThinkingConfig, Tool)

# This page is used to add pinionai function extensions so they can be be used in the PinionAIClient. 
# Add functions here and can call them by creating functional declarations for each in the administration Tools page.

# Stock Market Tool
async def get_stock_data(
    stock_lookup_function: str | None = None,
    stock_symbol: str | None = None,
    alphavantage_key: str | None = None,
    interval: str | None = None,
) -> dict:
    """
    Fetches stock data from the Alpha Vantage API.
    """
    # Filter out None values from parameters
    params = {
        "function": stock_lookup_function,
        "symbol": stock_symbol,
        "apikey": alphavantage_key,
        "interval": interval,
    }
    params = {k: v for k, v in params.items() if v is not None}
    try:
        async with httpx.AsyncClient() as client:
            base_url = 'https://www.alphavantage.co/query'
            response = await client.get(base_url, params=params, headers={"User-Agent": "none"})
            logging.debug(f"Stock check Response URL: {response.url}")
            response.raise_for_status()
            # convert to markdown
            stock_data = response.json()
            return await format_stock_data_as_markdown(stock_data)
    except httpx.HTTPStatusError as http_err:
        logging.error(f"HTTP error occurred: {http_err} - {http_err.response.text}")
        return {"error": f"HTTP error: {http_err.response.status_code}", "message": http_err.response.text}
    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}")
        return {"error": "An unexpected error occurred.", "message": str(e)}

# Generate Password Tool    
async def generate_password(length: int = 12) -> str:
        if length < 6: length = 6 # Ensure space for all char types
        digits_chars = '0123456789'
        locase_chars = 'abcdefghijklmnopqrstuvwxyz'
        upcase_chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
        symbols_chars = '$%?!' # Simplified from original
        combined_list = list(digits_chars + locase_chars + upcase_chars + symbols_chars)

        password_chars = [
            random.choice(digits_chars),
            random.choice(locase_chars),
            random.choice(upcase_chars),
            random.choice(symbols_chars)
        ]
        for _ in range(length - 4):
            password_chars.append(random.choice(combined_list))
        
        random.shuffle(password_chars)
        return f"Your new password is: {''.join(password_chars)}"
    
# Makes stock output pretty
async def format_stock_data_as_markdown(stock_data: dict) -> str:
    """
    Formats the JSON/dict response from the get_stock_data function into a
    human-readable markdown string.
    """
    if not isinstance(stock_data, dict):
        return "Error: Invalid data format. Expected a dictionary."

    # Handle potential error messages from the API
    if "Error Message" in stock_data:
        return f"**API Error:** {stock_data['Error Message']}"
    if "Information" in stock_data:
        return f"**API Info:** {stock_data['Information']}"
    if "error" in stock_data:
        return f"**Client Error:** {stock_data.get('message', 'An unknown error occurred.')}"

    markdown_parts = []

    # Case 1: Global Quote
    if "Global Quote" in stock_data:
        quote = stock_data["Global Quote"]
        symbol = quote.get("01. symbol", "N/A")
        price = quote.get("05. price", "N/A")
        change = quote.get("09. change", "N/A")
        change_percent = quote.get("10. change percent", "N/A")
        
        markdown_parts.append(f"### Quote for {symbol}")
        markdown_parts.append(f"**Price:** ${price}")
        markdown_parts.append(f"**Change:** {change} ({change_percent})")
        markdown_parts.append(f"**Open:** {quote.get('02. open', 'N/A')}")
        markdown_parts.append(f"**High:** {quote.get('03. high', 'N/A')}")
        markdown_parts.append(f"**Low:** {quote.get('04. low', 'N/A')}")
        markdown_parts.append(f"**Volume:** {quote.get('06. volume', 'N/A')}")
        markdown_parts.append(f"**Latest Trading Day:** {quote.get('07. latest trading day', 'N/A')}")
        
        return "\n\n".join(markdown_parts)

    # Case 2: Company Overview
    if "Symbol" in stock_data and "Name" in stock_data:
        name = stock_data.get("Name", "N/A")
        symbol = stock_data.get("Symbol", "N/A")
        description = stock_data.get("Description", "No description available.")
        exchange = stock_data.get("Exchange", "N/A")
        sector = stock_data.get("Sector", "N/A")
        
        markdown_parts.append(f"### {name} ({symbol})")
        markdown_parts.append(f"**Exchange:** {exchange} | **Sector:** {sector}")
        markdown_parts.append("\n---\n")
        markdown_parts.append(description)
        return "\n\n".join(markdown_parts)

    # Case 3: Time Series Data (shows the most recent entry)
    time_series_key = next((key for key in stock_data if "Time Series" in key), None)
    if time_series_key:
        time_series_data = stock_data[time_series_key]
        try:
            latest_timestamp = sorted(time_series_data.keys(), reverse=True)[0]
            latest_data = time_series_data[latest_timestamp]
            
            markdown_parts.append(f"### Latest Data for {time_series_key} at {latest_timestamp}")
            markdown_parts.append(f"- **Open:** {latest_data.get('1. open')} | **High:** {latest_data.get('2. high')} | **Low:** {latest_data.get('3. low')} | **Close:** {latest_data.get('4. close')} | **Volume:** {latest_data.get('5. volume')}")
            return "\n\n".join(markdown_parts)
        except (IndexError, KeyError) as e:
            logging.warning(f"Could not parse time series data: {e}")

    # Fallback for any other JSON structures
    markdown_parts.append("### Raw Data")
    markdown_parts.append("```json")
    markdown_parts.append(json.dumps(stock_data, indent=2))
    markdown_parts.append("```")
    
    return "\n".join(markdown_parts)