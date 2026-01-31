
import logging
import requests
import re
from typing import Optional, Dict, Any
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

class ContentFetcher:
    """
    Fetches and cleans web content using BeautifulSoup.
    Ported from whatsapp-agent (webFetchTool).
    """
    def fetch(self, url: str, max_chars: int = 20000) -> tuple[Dict[str, Any] | None, Optional[str]]:
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            response = requests.get(
                url, 
                headers=headers, 
                timeout=15, 
                allow_redirects=True,
                stream=True 
            )
            
            if response.status_code != 200:
                return None, f"bad_status:{response.status_code}"
                
            content_type = response.headers.get('Content-Type', '').lower()
            
            # Read content (limit size)
            # 5MB limit
            max_bytes = 5 * 1024 * 1024
            data = response.raw.read(max_bytes, decode_content=True)
            
            if 'text/html' in content_type:
                text = self._parse_html(data, max_chars)
                return {
                    "url": url,
                    "content_type": content_type,
                    "content_length": len(data),
                    "text": text
                }, None
                
            elif content_type.startswith('text/'):
                # Plain text or similar
                text = data.decode('utf-8', errors='replace')
                if len(text) > max_chars:
                    text = text[:max_chars] + "..."
                return {
                    "url": url,
                    "content_type": content_type,
                    "content_length": len(data),
                    "text": text
                }, None
            
            else:
                return {
                    "url": url,
                    "content_type": content_type,
                    "content_length": len(data),
                    "text": "",
                    "error": "unsupported_content_type"
                }, None
                
        except Exception as e:
            return None, f"fetch_error:{str(e)}"

    def _parse_html(self, content: bytes, max_chars: int) -> str:
        try:
            html = content.decode('utf-8', errors='replace')
            soup = BeautifulSoup(html, 'html.parser')
            
            # Remove clutter
            for tag in soup(['script', 'style', 'noscript', 'svg', 'header', 'footer', 'nav', 'aside', 'iframe', 'ads']):
                tag.decompose()
                
            # Extract title
            title = ""
            if soup.title:
                title = soup.title.get_text(strip=True)
            elif soup.h1:
                title = soup.h1.get_text(strip=True)
            else:
                title = "Untitled"
                
            # Extract body text
            # get_text with separator ' ' is better than default
            text = soup.body.get_text(separator=' ', strip=True) if soup.body else ""
            
            # Collapse whitespace
            text = re.sub(r'\s+', ' ', text).strip()
            
            # Formatting
            result = f"TITLE: {title}\n\n{text}"
            
            if len(result) > max_chars:
                result = result[:max_chars] + "..."
                
            return result
            
        except Exception as e:
            logger.error(f"HTML parsing failed: {e}")
            return ""

# Singleton/Factory usage if needed, or just instantiate
fetcher = ContentFetcher()
