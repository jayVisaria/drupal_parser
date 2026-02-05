# Drupal Site Parser

A generic Python parser that extracts structured content from any Drupal website.

## Features

- Works with any Drupal site (7, 8, 9, 10)
- No hardcoded selectors or site-specific configuration
- Automatically detects: forms, tables, hero banners, lists, media galleries, rich text
- Extracts global header and footer components
- Categorizes internal/external links
- Detects and removes duplicate pages

## Installation

```bash
pip install beautifulsoup4 lxml requests
```

## Usage

### Basic Usage

```bash
python3 drupal_parser.py https://example.com
```

### Specify Output File

```bash
python3 drupal_parser.py https://example.com -o output.json
```

### Custom Timeout

```bash
python3 drupal_parser.py https://example.com --timeout 30
```

## Arguments

| Argument | Short | Description | Default |
|----------|-------|-------------|---------|
| `url` | - | Website URL to parse | Required |
| `--output` | `-o` | Output JSON file | Auto-generated |
| `--timeout` | `-t` | Request timeout (seconds) | 20 |

## Output Structure

```json
{
  "website": {
    "name": "Website Name",
    "url": "https://example.com",
    "description": "Meta description",
    "global_components": {
      "header": {
        "logo": "Logo text",
        "navigation": ["Home", "About", "Contact"],
        "contact": {"email": "...", "phone": "..."}
      },
      "footer": {
        "address": {...},
        "email": "...",
        "phone": "...",
        "footer_links": [...],
        "social_links": ["twitter", "linkedin"]
      }
    },
    "pages": [
      {
        "page_slug": "home",
        "page_title": "Homepage",
        "path": "/",
        "components": [
          {"type": "hero_banner", "title": "...", "subtitle": "..."},
          {"type": "form", "fields": ["Name", "Email"]},
          {"type": "table", "columns": [...], "sample_data": [...]},
          {"type": "list", "items": [...]},
          {"type": "media_gallery", "images": [...]},
          {"type": "rich_text", "heading": "...", "content_preview": "..."},
          {"type": "text_block", "content": "..."}
        ],
        "links": {
          "internal": ["https://example.com/about"],
          "external": ["https://twitter.com/..."]
        }
      }
    ]
  }
}
```

## Component Types

- **hero_banner** - Hero sections with title and subtitle
- **form** - Forms with extracted field names
- **table** - Tables with columns and sample data
- **list** - Ordered/unordered lists with items
- **media_gallery** - Image galleries with alt text and sources
- **rich_text** - Content blocks with headings
- **text_block** - Plain text content

## How It Works

1. **Discovery**: Fetches sitemap.xml and crawls internal links
2. **Deduplication**: Removes duplicate pages by content hash
3. **Component Detection**: Uses generic patterns (form, table, hero|banner, etc.)
4. **Content Extraction**: Identifies structure without site-specific selectors
5. **Link Categorization**: Separates internal and external links

## Programmatic Usage

```python
from drupal_parser import DrupalParser

parser = DrupalParser("https://example.com")
result = parser.run()

print(f"Found {len(result['website']['pages'])} pages")
```

## Limitations

- Static HTML only (no JavaScript execution)
- Cannot access content behind authentication
- May be rate-limited by target server

## License

MIT
