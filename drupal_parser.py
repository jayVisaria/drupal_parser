import json
import re
import hashlib
import requests
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from typing import Dict, List, Set, Optional


class DrupalParser:
    """Universal Drupal site parser that extracts structured content from any Drupal website"""
    
    def __init__(self, base_url: str, timeout: int = 20):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        self.internal_domain = urlparse(self.base_url).netloc
        self.visited = set()
        self.seen_content_hashes = set()  # Avoid duplicate pages
        
    # =================================================================
    # URL Fetching & Discovery
    # =================================================================
    
    def fetch(self, url: str) -> Optional[str]:
        try:
            response = self.session.get(url, timeout=self.timeout)
            if response.status_code == 200:
                if "text/html" in response.headers.get("Content-Type", ""):
                    return response.text
        except Exception as e:
            print(f"Error fetching {url}: {e}")
        return None

    def normalize_url(self, url: str) -> str:
        """Clean and normalize URLs"""
        parsed = urlparse(url)
        # Remove fragment, query params
        clean = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        # Remove trailing slash except for root
        if len(parsed.path) > 1:
            clean = clean.rstrip("/")
        return clean

    def is_internal_link(self, url: str) -> bool:
        """Check if URL is internal to domain"""
        parsed = urlparse(url)
        # Handle relative URLs
        if not parsed.netloc:
            return True
        # Compare domains
        return parsed.netloc == self.internal_domain

    def fetch_sitemap_urls(self) -> Set[str]:
        """Extract URLs from sitemap"""
        sitemap_paths = ["/sitemap.xml", "/sitemap_index.xml", "/sitemap"]
        urls = set()

        for path in sitemap_paths:
            try:
                response = self.session.get(self.base_url + path, timeout=self.timeout)
                if response.status_code == 200 and "<loc>" in response.text:
                    soup = BeautifulSoup(response.text, "xml")
                    for loc in soup.find_all("loc"):
                        url = self.normalize_url(loc.text.strip())
                        urls.add(url)
            except Exception:
                pass

        return urls

    def crawl_internal_links(self, html: str) -> Set[str]:
        """Extract internal links from HTML"""
        soup = BeautifulSoup(html, "lxml")
        urls = set()

        for a in soup.find_all("a", href=True):
            href = a["href"]
            # Skip anchor links, javascript, mailto, tel
            if href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue
                
            absolute = urljoin(self.base_url, href)
            
            if self.is_internal_link(absolute):
                clean = self.normalize_url(absolute)
                # Skip PDFs and media files
                if not re.search(r'\.(pdf|jpg|jpeg|png|gif|zip|doc|docx)$', clean, re.I):
                    urls.add(clean)

        return urls

    def discover_all_pages(self) -> List[str]:
        """Discover all pages via sitemap and crawling"""
        all_urls = set()
        
        # Get sitemap URLs
        sitemap_urls = self.fetch_sitemap_urls()
        all_urls.update(sitemap_urls)
        all_urls.add(self.base_url)
        
        print(f"Found {len(sitemap_urls)} URLs from sitemap")

        # Crawl for additional URLs
        queue = list(all_urls)
        
        while queue:
            url = queue.pop(0)
            if url in self.visited:
                continue

            html = self.fetch(url)
            if not html:
                continue

            self.visited.add(url)
            
            found_links = self.crawl_internal_links(html)
            for link in found_links:
                if link not in all_urls:
                    all_urls.add(link)
                    queue.append(link)

        print(f"Total discovered: {len(all_urls)} pages")
        return sorted(all_urls)

    # =================================================================
    # Global Component Extraction
    # =================================================================
    
    def extract_website_metadata(self, soup: BeautifulSoup) -> Dict:
        """Extract website name and description"""
        name = ""
        description = ""
        
        # Try to get name from title or meta
        title_tag = soup.find("title")
        if title_tag:
            name = title_tag.get_text(strip=True)
            # Clean up common patterns
            name = re.sub(r'\s*[-|–]\s*.*$', '', name)
        
        # Try meta description
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc:
            description = meta_desc.get("content", "").strip()
        
        return {
            "name": name,
            "url": self.base_url,
            "description": description
        }

    def extract_header(self, soup: BeautifulSoup) -> Dict:
        """Extract clean header navigation"""
        # Make a copy to avoid modifying original
        soup_copy = BeautifulSoup(str(soup), "lxml")
        header = soup_copy.find("header")
        if not header:
            header = soup_copy.find(["nav", "div"], class_=re.compile(r"header|navbar|navigation|menu", re.I))
        
        navigation = []
        contact = {}
        logo = ""
        
        if header:
            # Extract logo
            logo_img = header.find("img")
            if logo_img and logo_img.get("alt"):
                logo = logo_img.get("alt")
            
            # Extract main navigation - look for meaningful link text
            for a in header.find_all("a", href=True):
                href = a["href"]
                text = a.get_text(strip=True)
                
                # Skip empty, emails, external social, PDFs, very long text
                if not text or len(text) > 50 or len(text) < 3:
                    continue
                if "@" in text or "@" in href:
                    continue
                if any(x in href.lower() for x in ["twitter", "facebook", "linkedin", "youtube", "instagram"]):
                    continue
                if href.endswith(".pdf") or "policy" in href.lower():
                    continue
                if any(x in text.lower() for x in ["cookie", "consent", "refuse"]):
                    continue
                    
                # Main navigation items
                if text and text not in navigation:
                    navigation.append(text)
            
            # Extract contact info from header
            header_text = header.get_text(" ", strip=True)
            emails = re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}", header_text)
            phones = re.findall(r"\+?\d[\d\s\-()]{7,15}", header_text)
            
            if emails:
                contact["email"] = emails[0]
            if phones:
                contact["phone"] = phones[0].strip()
        
        return {
            "logo": logo,
            "navigation": navigation[:10],  # Limit to 10 items
            "contact": contact if contact else None
        }

    def extract_footer(self, soup: BeautifulSoup) -> Dict:
        """Extract footer information"""
        footer = soup.find("footer")
        if not footer:
            return {}
        
        footer_text = footer.get_text(" ", strip=True)
        
        # Extract address
        address = {}
        address_patterns = [
            r"Plot\s+No\.?\s*[\w\-,\s]+",
            r"Sector[\-\s]\d+",
            r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*,\s*\d{6}",
        ]
        
        for pattern in address_patterns:
            match = re.search(pattern, footer_text)
            if match:
                address_text = match.group(0)
                if "Plot" in address_text:
                    address["street"] = address_text
                elif "Sector" in address_text:
                    address["street"] = address.get("street", "") + " " + address_text
        
        # Extract location
        if "Gurugram" in footer_text:
            address["city"] = "Gurugram"
        if "Haryana" in footer_text:
            address["state"] = "Haryana"
        if "India" in footer_text:
            address["country"] = "India"
        
        # Extract contact details
        emails = re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}", footer_text)
        phones = re.findall(r"\+?\d[\d\s\-/()]{10,20}", footer_text)
        
        # Extract footer links (only meaningful ones)
        footer_links = []
        for a in footer.find_all("a", href=True):
            text = a.get_text(strip=True)
            href = a["href"]
            
            # Include only internal navigation links
            if (self.is_internal_link(href) and text and 
                not href.endswith(".pdf") and
                len(text) < 30):
                footer_links.append(text)
        
        # Extract social links
        social_links = []
        for a in footer.find_all("a", href=True):
            href = a["href"]
            for platform in ["twitter", "facebook", "linkedin", "youtube", "instagram"]:
                if platform in href.lower():
                    social_links.append(platform)
                    break
        
        result = {
            "address": address if address else None,
            "phone": phones[0].strip() if phones else None,
            "email": emails[0] if emails else None,
            "footer_links": list(dict.fromkeys(footer_links))[:10],  # Limit to 10
            "social_links": list(dict.fromkeys(social_links))
        }
        
        # Clean None values
        return {k: v for k, v in result.items() if v}

    # =================================================================
    # Page Parsing & Component Identification
    # =================================================================
    
    def generate_page_slug(self, url: str) -> str:
        """Generate clean page slug from URL"""
        path = urlparse(url).path.strip("/")
        if not path:
            return "home"
        
        # Remove file extensions
        path = re.sub(r'\.(php|html|htm)$', '', path)
        
        # Get last segment
        segments = path.split("/")
        slug = segments[-1] if segments else "home"
        
        # Clean slug
        slug = re.sub(r'[^a-z0-9\-]', '-', slug.lower())
        slug = re.sub(r'-+', '-', slug).strip('-')
        
        return slug or "home"

    def identify_component_type(self, element) -> Optional[Dict]:
        """Identify specific component types"""
        
        if not element or not hasattr(element, 'name'):
            return None
        
        # Skip if too small
        text = element.get_text(" ", strip=True)
        if len(text) < 20:
            return None
        
        # Check element's own classes
        element_classes = " ".join(element.get("class", [])).lower()
        
        # Hero Banner / Slider - check element itself or children
        if (re.search(r"hero|banner|slider|carousel|jumbotron", element_classes, re.I) or 
            element.find(class_=re.compile(r"hero|banner|slider|carousel", re.I))):
            title = ""
            subtitle = ""
            
            h1 = element.find(["h1", "h2", "h3"])
            if h1:
                title = h1.get_text(strip=True)
            
            # Find paragraphs that aren't too long
            for p in element.find_all("p", limit=3):
                p_text = p.get_text(strip=True)
                if 20 < len(p_text) < 200:
                    subtitle = p_text
                    break
            
            if title or subtitle:
                return {
                    "type": "hero_banner",
                    "title": title,
                    "subtitle": subtitle
                }
        
        # Form - check if element IS a form or contains one
        form = element if element.name == "form" else element.find("form")
        if form:
            fields = []
            for inp in form.find_all(["input", "textarea", "select"]):
                field_type = inp.get("type", "text")
                if field_type in ["submit", "button", "hidden"]:
                    continue
                    
                name = inp.get("placeholder") or inp.get("name") or inp.get("id", "")
                if name:
                    # Clean up field name
                    name = name.replace("_", " ").replace("-", " ").strip()
                    if name and len(name) < 50:
                        fields.append(name.title())
            
            if fields:
                return {
                    "type": "form",
                    "fields": list(dict.fromkeys(fields))  # Remove duplicates
                }
        
        # Table
        table = element if element.name == "table" else element.find("table")
        if table:
            columns = []
            rows = []
            
            # Get headers
            ths = table.find_all("th")
            if ths:
                columns = [th.get_text(strip=True) for th in ths if th.get_text(strip=True)]
            
            # Get sample data rows (limit to 5)
            trs = table.find_all("tr")[:6]
            for tr in trs:
                tds = tr.find_all(["td", "th"])
                if tds:
                    row_data = [td.get_text(strip=True) for td in tds]
                    if any(row_data):  # Not empty
                        rows.append(row_data)
            
            if columns or (rows and len(rows) > 1):
                return {
                    "type": "table",
                    "columns": columns if columns else None,
                    "sample_data": rows[:5]
                }
        
        # List - structured lists
        ul = element.find(["ul", "ol"])
        if ul and element.name not in ["nav", "header", "footer"]:
            items = []
            for li in ul.find_all("li", recursive=False)[:10]:
                item_text = li.get_text(strip=True)
                if item_text and len(item_text) < 200:
                    items.append(item_text)
            
            if len(items) >= 3:
                return {
                    "type": "list",
                    "items": items
                }
        
        # Media Gallery / Images
        images = element.find_all("img")
        if len(images) >= 2:
            image_info = []
            for img in images[:5]:
                alt = img.get("alt", "Image")
                src = img.get("src", "")
                if src:
                    image_info.append({"alt": alt, "src": src})
            
            if image_info:
                return {
                    "type": "media_gallery",
                    "image_count": len(images),
                    "images": image_info
                }
        
        # Rich Text / Content Block with headings
        if len(text) > 100:
            headings = element.find_all(["h1", "h2", "h3", "h4", "h5"])
            if headings:
                heading_text = headings[0].get_text(strip=True)
                # Get text excluding heading
                content = text.replace(heading_text, "", 1).strip()
                
                return {
                    "type": "rich_text",
                    "heading": heading_text,
                    "content_preview": content[:300] + "..." if len(content) > 300 else content
                }
            
            # Plain text block
            # Clean up excessive whitespace
            text = re.sub(r'\s+', ' ', text).strip()
            if len(text) > 50:
                return {
                    "type": "text_block",
                    "content": text[:400] + "..." if len(text) > 400 else text
                }
        
        return None

    def extract_page_components(self, soup: BeautifulSoup) -> Dict:
        """Extract and identify UI components from page"""
        # Make a copy to avoid destructive operations
        soup_copy = BeautifulSoup(str(soup), "lxml")
        
        # Remove global elements from copy
        for tag in soup_copy.find_all(["header", "footer"]):
            tag.decompose()
        
        # Find main content area
        main = soup_copy.find("main") or soup_copy.find("div", id=re.compile(r"content|main", re.I)) or soup_copy.find("div", class_=re.compile(r"content|main", re.I))
        if not main:
            main = soup_copy.body
        
        components = []
        
        # Look for hero/banner first (usually at top)
        hero = main.find(["div", "section"], class_=re.compile(r"hero|banner|slider|jumbotron|intro", re.I))
        if hero:
            hero_comp = self.identify_component_type(hero)
            if hero_comp:
                components.append(hero_comp)
        
        # Look for forms
        for form in main.find_all("form"):
            form_comp = self.identify_component_type(form)
            if form_comp:
                components.append(form_comp)
        
        # Look for tables
        for table in main.find_all("table"):
            table_comp = self.identify_component_type(table)
            if table_comp:
                components.append(table_comp)
        
        # Look for major content sections - be more flexible
        sections = main.find_all(["section", "article"], recursive=True)
        if not sections:
            # Try divs with classes suggesting content blocks
            sections = main.find_all("div", class_=re.compile(r"section|block|component|paragraph|content-block|region", re.I))
        
        for section in sections[:10]:  # Limit to prevent overwhelming output
            component = self.identify_component_type(section)
            if component and component not in components:
                components.append(component)
        
        # If still no components, look for any structured content
        if len(components) == 0:
            # Look for headings and paragraphs
            for heading in main.find_all(["h1", "h2", "h3"])[:5]:
                parent = heading.parent
                if parent:
                    comp = self.identify_component_type(parent)
                    if comp and comp not in components:
                        components.append(comp)
        
        # Last resort: extract text blocks
        if len(components) == 0:
            text = main.get_text(" ", strip=True)
            # Remove excessive whitespace
            text = re.sub(r'\s+', ' ', text).strip()
            if len(text) > 50:
                components.append({
                    "type": "text_block",
                    "content": text[:600] + "..." if len(text) > 600 else text
                })
        
        return {"components": components}

    def extract_page_links(self, soup: BeautifulSoup) -> Dict:
        """Extract and categorize internal/external links"""
        internal = []
        external = []
        
        # Make a copy and remove header, footer, nav
        soup_copy = BeautifulSoup(str(soup), "lxml")
        for tag in soup_copy.find_all(["header", "footer", "nav"]):
            tag.decompose()
        
        # Focus on main content
        content = soup_copy.find("main") or soup_copy.body
        
        for a in (content or soup_copy).find_all("a", href=True):
            href = a["href"]
            
            # Skip anchors, javascript, mailto, tel, cookies
            if href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue
            if "cookie" in href.lower():
                continue
            
            absolute = urljoin(self.base_url, href)
            
            if self.is_internal_link(absolute):
                clean = self.normalize_url(absolute)
                if clean not in internal and not clean.endswith(".pdf"):
                    internal.append(clean)
            else:
                if absolute not in external and not absolute.endswith(".pdf"):
                    external.append(absolute)
        
        return {
            "internal": internal[:20],  # Limit
            "external": external[:10]
        }

    def parse_page(self, url: str, html: str) -> Optional[Dict]:
        """Parse a single page"""
        soup = BeautifulSoup(html, "lxml")
        
        # Check for duplicate content
        main_content = soup.find("main") or soup.body
        if main_content:
            content_hash = hashlib.md5(main_content.get_text().encode()).hexdigest()
            if content_hash in self.seen_content_hashes:
                return None  # Skip duplicate
            self.seen_content_hashes.add(content_hash)
        
        # Extract page data
        title = soup.title.get_text(strip=True) if soup.title else ""
        slug = self.generate_page_slug(url)
        path = urlparse(url).path or "/"
        
        components = self.extract_page_components(soup)
        links = self.extract_page_links(soup)
        
        return {
            "page_slug": slug,
            "page_title": title,
            "path": path,
            "components": components["components"],
            "links": links
        }

    # =================================================================
    # Main Execution
    # =================================================================
    
    def run(self) -> Dict:
        """Main execution - crawl and parse site"""
        print(f"\n🚀 Starting Drupal parser for: {self.base_url}\n")
        
        # Discover all pages
        all_urls = self.discover_all_pages()
        
        # Fetch homepage for global components
        print("\n📊 Extracting global components...")
        homepage_html = self.fetch(self.base_url)
        if not homepage_html:
            print("Error: Could not fetch homepage")
            return {}
        
        homepage_soup = BeautifulSoup(homepage_html, "lxml")
        
        # Extract metadata and global components
        metadata = self.extract_website_metadata(homepage_soup)
        header = self.extract_header(homepage_soup)
        footer = self.extract_footer(homepage_soup)
        
        # Build output structure
        output = {
            "website": {
                "name": metadata["name"],
                "url": metadata["url"],
                "description": metadata["description"],
                "global_components": {
                    "header": header,
                    "footer": footer
                },
                "pages": []
            }
        }
        
        # Parse all pages
        print(f"\n📄 Parsing {len(all_urls)} pages...\n")
        for i, url in enumerate(all_urls, 1):
            print(f"  [{i}/{len(all_urls)}] {url}")
            
            html = self.fetch(url)
            if not html:
                print(f"    ↪ Skipped (fetch failed)")
                continue
            
            page_data = self.parse_page(url, html)
            if page_data:  # Only add non-duplicate pages
                output["website"]["pages"].append(page_data)
            else:
                print(f"    ↪ Skipped (duplicate content)")
        
        print(f"\n✅ Parsing complete!")
        print(f"   - Total pages parsed: {len(output['website']['pages'])}")
        print(f"   - Global components: Header + Footer")
        
        return output


# =================================================================
# Entry Point
# =================================================================

if __name__ == "__main__":
    import sys
    import argparse
    
    # Setup command line argument parser
    parser_args = argparse.ArgumentParser(
        description="Parse any Drupal website and extract structured content",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 drupal_parser_corrected.py https://example.com
  python3 drupal_parser_corrected.py https://example.com -o output.json
  python3 drupal_parser_corrected.py https://example.com --timeout 30
        """
    )
    
    parser_args.add_argument(
        "url",
        help="Website URL to parse (e.g., https://example.com)"
    )
    
    parser_args.add_argument(
        "-o", "--output",
        default=None,
        help="Output JSON file path (default: auto-generated from domain name)"
    )
    
    parser_args.add_argument(
        "-t", "--timeout",
        type=int,
        default=20,
        help="Request timeout in seconds (default: 20)"
    )
    
    args = parser_args.parse_args()
    
    # Validate URL
    website_url = args.url
    if not website_url.startswith(("http://", "https://")):
        website_url = "https://" + website_url
    
    # Auto-generate output filename from domain if not specified
    if args.output:
        output_file = args.output
    else:
        # Extract domain name for filename
        domain = urlparse(website_url).netloc
        domain = domain.replace("www.", "").replace(".", "_")
        output_file = f"{domain}_analysis.json"
    
    print(f"\n🌐 Target Website: {website_url}")
    print(f"📁 Output File: {output_file}")
    print(f"⏱️  Timeout: {args.timeout}s\n")
    
    # Create parser and run
    parser = DrupalParser(website_url, timeout=args.timeout)
    result = parser.run()
    
    # Save output
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    
    print(f"\n💾 Output saved to: {output_file}")
    print(f"\n📊 Summary:")
    print(f"   • Website: {result['website']['name']}")
    print(f"   • Pages parsed: {len(result['website']['pages'])}")
    print(f"   • Navigation items: {len(result['website']['global_components']['header']['navigation'])}")
    
    # Count components by type
    component_counts = {}
    for page in result['website']['pages']:
        for comp in page['components']:
            comp_type = comp['type']
            component_counts[comp_type] = component_counts.get(comp_type, 0) + 1
    
    if component_counts:
        print(f"\n   • Components found:")
        for comp_type, count in sorted(component_counts.items()):
            print(f"     - {comp_type}: {count}")
    
    print(f"\n✅ Parsing complete!")
