
import os
import requests
import logging
from typing import Protocol, List, Dict, Optional, Any
from bs4 import BeautifulSoup
import urllib.parse

logger = logging.getLogger(__name__)

class SearchProvider(Protocol):
    def search(self, query: str, max_results: int = 5) -> tuple[List[Dict[str, str]], Optional[str]]:
        ...

class DuckDuckGoSearchProvider:
    """
    Scrapes DuckDuckGo HTML version to avoid API keys.
    Ported from whatsapp-agent (search.ts).
    """
    def search(self, query: str, max_results: int = 5) -> tuple[List[Dict[str, str]], Optional[str]]:
        try:
            # Enforce limit
            max_results = min(max_results, 10)
            
            encoded_query = urllib.parse.quote(query)
            url = f"https://html.duckduckgo.com/html/?q={encoded_query}"
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code != 200:
                return [], f"bad_status:{response.status_code}"

            soup = BeautifulSoup(response.text, 'html.parser')
            results: List[Dict[str, str]] = []
            
            # Select results
            # DDG HTML structure usually has class='result'
            for result_elem in soup.select('.result'):
                if len(results) >= max_results:
                    break
                    
                title_elem = result_elem.select_one('.result__title')
                snippet_elem = result_elem.select_one('.result__snippet')
                url_elem = result_elem.select_one('.result__url')
                
                if title_elem and snippet_elem:
                    title = title_elem.get_text(strip=True)
                    snippet = snippet_elem.get_text(strip=True)
                    raw_url = url_elem.get('href') if url_elem else None
                    
                    if not raw_url:
                        # Sometimes the anchor inside title has the link
                        anchor = title_elem.find('a')
                        if anchor:
                            raw_url = anchor.get('href')

                    final_url = ""
                    if raw_url:
                        # Extract actual URL from DDG redirect (uddg parameter)
                        # raw_url might look like /l/?kh=-1&uddg=https%3A%2F%2Fexample.com%2F
                        if 'uddg=' in raw_url:
                            parsed = urllib.parse.urlparse(raw_url)
                            qs = urllib.parse.parse_qs(parsed.query)
                            if 'uddg' in qs:
                                final_url = qs['uddg'][0]
                        else:
                            final_url = raw_url

                    results.append({
                        "title": title,
                        "description": snippet,
                        "url": final_url
                    })

            if not results:
                # Could be a layout change or blocking
                logger.warning(f"DuckDuckGo search returned no results for query: {query}")
                return [], "no_results_found"

            return results, None

        except Exception as e:
            logger.error(f"DuckDuckGo search failed: {e}")
            return [], str(e)

class BraveSearchProvider:
    """
    Uses Brave Search API.
    """
    def search(self, query: str, max_results: int = 5) -> tuple[List[Dict[str, str]], Optional[str]]:
        api_key = os.getenv("BRAVE_SEARCH_API_KEY")
        if not api_key:
            return [], "missing_brave_api_key"
            
        base_url = os.getenv("BRAVE_SEARCH_API_BASE", "https://api.search.brave.com/res/v1/web/search")
        params = {
            "q": query,
            "count": max_results,
        }
        headers = {
            "Accept": "application/json",
            "X-Subscription-Token": api_key,
        }
        
        try:
            response = requests.get(
                base_url,
                headers=headers,
                params=params,
                timeout=10,
            )
        except requests.RequestException as exc:
            return [], f"request_error:{exc}"
            
        if response.status_code != 200:
            return [], f"bad_status:{response.status_code}"
            
        try:
            payload = response.json()
        except ValueError:
            return [], "invalid_json"
            
        results = payload.get("web", {}).get("results", [])
        if not isinstance(results, list):
            return [], "invalid_results"
            
        normalized: List[Dict[str, str]] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            url = item.get("url") or item.get("link")
            if not isinstance(url, str) or not url:
                continue
                
            normalized.append({
                "url": url,
                "title": str(item.get("title") or ""),
                "description": str(item.get("description") or ""),
            })
            
            if len(normalized) >= max_results:
                break
                
        return normalized, None

def get_search_provider() -> SearchProvider:
    # Default to DuckDuckGo as requested to replace Brave
    # Can control via env var if needed
    provider_name = os.getenv("SEARCH_PROVIDER", "duckduckgo").lower()
    
    if provider_name == "brave":
        return BraveSearchProvider()
    
    return DuckDuckGoSearchProvider()
