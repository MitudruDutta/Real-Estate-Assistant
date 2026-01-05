"""Sentiment extraction - strict market validation"""
import json
import re
import asyncio
import logging
from groq import AsyncGroq
from src.services.cache import get_cached, set_cached

logger = logging.getLogger(__name__)

PROMPT = """Extract real estate sentiment from this article.

RULES:
1. Only extract US cities/markets from this list: {markets}
2. If no specific US market mentioned, use "National"
3. Sentiment: -1.0 (very bearish) to +1.0 (very bullish)
4. Confidence: 0.0 to 1.0 based on how clear the sentiment is

Article:
{content}

Respond ONLY with valid JSON:
{{"extractions": [{{"market": "CityName", "sentiment": 0.0, "confidence": 0.8, "topics": ["topic1"]}}]}}"""


def _safe_float(value, default: float) -> float:
    """Safely convert value to float, returning default on failure."""
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


class SentimentExtractor:
    def __init__(self):
        from src.config import get_global_settings
        settings = get_global_settings()
        self.client = AsyncGroq(api_key=settings.groq_api_key)
        self.valid_markets = set(settings.valid_markets)
    
    async def extract(self, content: str) -> list[dict]:
        from src.config import get_global_settings
        settings = get_global_settings()
        
        content = content[:settings.max_content_length]
        
        # Check cache
        cached = get_cached(content)
        if cached:
            return cached
        
        # Retry with backoff
        for attempt in range(3):
            try:
                response = await self.client.chat.completions.create(
                    model=settings.groq_model,
                    messages=[{
                        "role": "user",
                        "content": PROMPT.format(
                            # Use sorted list for deterministic ordering
                            markets=", ".join(sorted(self.valid_markets)[:20]),
                            content=content
                        )
                    }],
                    temperature=0.1,
                    max_tokens=800
                )
                result = self._parse(response.choices[0].message.content)
                set_cached(content, result)
                return result
            except Exception as e:
                if "rate_limit" in str(e).lower():
                    await asyncio.sleep(5 * (attempt + 1))
                else:
                    logger.warning(f"Extraction failed (attempt {attempt+1}): {e}")
                    await asyncio.sleep(2 ** attempt)
        
        return [{"market": "National", "sentiment": 0.0, "confidence": 0.2, "topics": []}]
    
    def _parse(self, text: str) -> list[dict]:
        try:
            # Try direct parse
            data = json.loads(text)
            return self._validate(data.get("extractions", []))
        except json.JSONDecodeError:
            # Extract JSON from text
            match = re.search(r'\{[\s\S]*\}', text)
            if match:
                try:
                    data = json.loads(match.group())
                    return self._validate(data.get("extractions", []))
                except Exception:
                    pass
        return [{"market": "National", "sentiment": 0.0, "confidence": 0.2, "topics": []}]
    
    def _validate(self, extractions: list) -> list[dict]:
        validated = []
        seen_markets = set()
        
        for ext in extractions:
            market = str(ext.get("market", "National")).strip()
            
            # Normalize market name
            market = self._normalize_market(market)
            
            # Skip invalid or duplicate markets
            if market not in self.valid_markets or market in seen_markets:
                continue
            
            seen_markets.add(market)
            
            # Safe float conversion with clamping
            sentiment_val = _safe_float(ext.get("sentiment", 0), 0.0)
            sentiment_val = max(-1.0, min(1.0, sentiment_val))
            
            confidence_val = _safe_float(ext.get("confidence", 0.5), 0.5)
            confidence_val = max(0.0, min(1.0, confidence_val))
            
            validated.append({
                "market": market,
                "sentiment": sentiment_val,
                "confidence": confidence_val,
                "topics": [str(t)[:50] for t in ext.get("topics", [])][:3],
            })
        
        # Always include National if nothing else
        if not validated:
            validated.append({"market": "National", "sentiment": 0.0, "confidence": 0.2, "topics": []})
        
        return validated
    
    def _normalize_market(self, market: str) -> str:
        """Normalize market aliases to canonical names."""
        aliases = {
            "NYC": "New York", "New York City": "New York", "Manhattan": "New York",
            "LA": "Los Angeles", "L.A.": "Los Angeles",
            "SF": "San Francisco", "Bay Area": "San Francisco",
            "DC": "Washington DC", "D.C.": "Washington DC", "Washington": "Washington DC",
            "Philly": "Philadelphia", "Vegas": "Las Vegas",
            "DFW": "Dallas", "Dallas-Fort Worth": "Dallas",
        }
        return aliases.get(market, market)
