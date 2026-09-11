<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10+-blue.svg" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/License-MIT-green.svg" alt="License MIT">
  <img src="https://img.shields.io/github/actions/workflow/status/yourusername/ghostly/ci.yml?branch=main" alt="CI Status">
  <img src="https://img.shields.io/badge/PRs-Welcome-brightgreen.svg" alt="PRs Welcome">
  <img src="https://img.shields.io/badge/Powered_by-Privacy_&_AIOHTTP-ff69b4.svg" alt="Powered by Privacy">
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Conventional%20Commits-1.0.0-yellow.svg" alt="Conventional Commits">
  <img src="https://img.shields.io/badge/Code%20Style-Ruff-000000.svg" alt="Code Style Ruff">
</p>

<br>

```
   _____ _               _                    _
  / ____| |             | |                  | |
 | |  __| |__   ___  ___| | __ _ _   _  __ _| |
 | | |_ | '_ \ / _ \/ __| |/ _` | | | |/ _` | |
 | |__| | | | |  __/ (__| | (_| | |_| | (_| | |
  \_____|_| |_|\___|\___|_|\__,_|\__, |\__, |_|
                                   __/ | __/ |
                                  |___/ |___/
```

<br>

<div align="center">
  <h1>Privacy-first web analytics. No cookies. No tracking. Just truth.</h1>
  <p>
    A lightweight, self-hosted alternative to Google Analytics that respects your visitors' privacy.<br>
    GDPR compliant out of the box. No cookie consent banners needed.
  </p>
</div>

<br>

---

## Features

- **Privacy First** - No cookies, no fingerprinting, no personal data collection
- **GDPR Compliant** - No cookie consent banner required in the EU
- **Real-Time Dashboard** - Live visitor tracking with sub-second updates
- **Self-Hosted** - Your data stays on your server, always
- **Lightweight** - < 3KB tracking script, zero impact on page speed
- **Open Source** - MIT licensed, inspect the code yourself
- **Single Binary** - One EXE, no dependencies to install
- **SQLite Backend** - Zero configuration database
- **API Access** - Full REST API for custom integrations
- **Beautiful UI** - Clean, modern dashboard design

## Comparison

| Feature | Ghostly | Google Analytics | Plausible | Umami |
|---------|---------|------------------|-----------|-------|
| Privacy-focused | **Yes** | No | Yes | Yes |
| Self-hosted | **Yes** | No | Yes | Yes |
| Open source | **Yes** | No | Yes | Yes |
| No cookies | **Yes** | No | Yes | Yes |
| GDPR compliant | **Yes** | No | Yes | Yes |
| Real-time | **Yes** | No | Yes | Yes |
| API access | **Yes** | Limited | Yes | Yes |
| Single binary | **Yes** | N/A | No | No |
| Free forever | **Yes** | Free tier | Paid | Paid |
| No vendor lock-in | **Yes** | No | No | No |

## Quick Start

### Option 1: pip install (Recommended)

```bash
# Install from PyPI
pip install ghostly-analytics

# Or install from source
git clone https://github.com/yourusername/ghostly.git
cd ghostly
pip install -e .

# Run Ghostly
ghostly
```

### Option 2: Single EXE (No Python needed)

Download the latest release for your OS:

- [Windows](https://github.com/yourusername/ghostly/releases/latest) - `ghostly-windows.exe`
- [macOS](https://github.com/yourusername/ghostly/releases/latest) - `ghostly-macos`
- [Linux](https://github.com/yourusername/ghostly/releases/latest) - `ghostly-linux`

Double-click to run or from terminal:
```bash
./ghostly-windows.exe --port 8080
```

### Option 3: Docker

```bash
docker run -d -p 8080:8080 -v ghostly-data:/app ghostly/analytics
```

## Configuration

| Option | Default | Description |
|--------|---------|-------------|
| `--port` | 8080 | Server port |
| `--host` | 127.0.0.1 | Bind address |
| `--db` | ghostly.db | Database file path |
| `--no-browser` | false | Disable auto-open browser |

Environment variables:
```bash
GHOSTLY_PORT=8080
GHOSTLY_HOST=127.0.0.1
GHOSTLY_DB=/path/to/ghostly.db
```

## Tracking Installation

### HTML

Add this snippet before the closing `</head>` tag:

```html
<script
  async
  data-id="YOUR_SITE_ID"
  src="http://your-ghostly-host:8080/collect.js">
</script>
```

### WordPress

Add to your theme's `functions.php`:

```php
function add_ghostly_analytics() {
    echo '<script async data-id="YOUR_SITE_ID" src="http://your-ghostly-host:8080/collect.js"></script>';
}
add_action('wp_head', 'add_ghostly_analytics');
```

### Next.js / React

```jsx
// In _app.js or layout.js
import Script from 'next/script'

export default function RootLayout({ children }) {
  return (
    <html>
      <head>
        <Script
          src="http://your-ghostly-host:8080/collect.js"
          data-id="YOUR_SITE_ID"
          strategy="afterInteractive"
        />
      </head>
      <body>{children}</body>
    </html>
  )
}
```

## Dashboard

Ghostly provides a beautiful, real-time dashboard showing:

- **Visitor Count** - Unique visitors today, this week, this month
- **Page Views** - Total page views with trends
- **Top Pages** - Most visited pages
- **Referrers** - Where your traffic comes from
- **Devices** - Desktop vs mobile breakdown
- **Browsers** - Browser distribution
- **Countries** - Geographic distribution
- **Real-Time** - Live visitor activity

All metrics update in real-time without page refreshes.

## API Documentation

### Track a Pageview

```http
POST /collect
Content-Type: application/json

{
  "id": "site_id",
  "page": "/blog/my-post",
  "referrer": "https://google.com",
  "width": 1920,
  "height": 1080
}
```

### Get Analytics

```http
GET /api/stats?period=7d
```

Response:
```json
{
  "visitors": 1234,
  "pageviews": 5678,
  "pages": [
    {"path": "/blog/post-1", "views": 456},
    {"path": "/blog/post-2", "views": 321}
  ]
}
```

### API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/collect` | Track a pageview |
| `GET` | `/api/stats` | Get analytics summary |
| `GET` | `/api/pages` | Get page statistics |
| `GET` | `/api/referrers` | Get referrer data |
| `GET` | `/api/realtime` | Get real-time visitors |

## Architecture

```
┌─────────────────────────────────────────────────┐
│                   Browser                       │
│  ┌──────────────────────────────────────────┐  │
│  │           collect.js (< 3KB)             │  │
│  └──────────────────────────────────────────┘  │
└─────────────────────────────────────────────────┘
                        │
                        │ HTTP POST /collect
                        ▼
┌─────────────────────────────────────────────────┐
│              Ghostly Server (Python)            │
│  ┌─────────────┐  ┌─────────────┐  ┌────────┐  │
│  │   aiohttp   │  │   Handler   │  │  API   │  │
│  └─────────────┘  └─────────────┘  └────────┘  │
│                        │                        │
│                        ▼                        │
│  ┌──────────────────────────────────────────┐  │
│  │           SQLite Database                │  │
│  └──────────────────────────────────────────┘  │
│                        │                        │
│                        ▼                        │
│  ┌──────────────────────────────────────────┐  │
│  │           Dashboard (Web UI)             │  │
│  └──────────────────────────────────────────┘  │
└─────────────────────────────────────────────────┘
```

## Project Structure

```
ghostly/
├── ghostly/
│   ├── __init__.py
│   ├── __main__.py          # CLI entry point
│   ├── core/
│   │   ├── __init__.py
│   │   └── server.py        # aiohttp server
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes.py        # API endpoints
│   ├── dashboard/
│   │   ├── __init__.py
│   │   └── routes.py        # Dashboard routes
│   ├── static/              # CSS, JS, images
│   └── templates/           # HTML templates
├── frontend/                # Frontend source
├── scripts/                 # Build scripts
├── tests/                   # Test suite
├── launch.py                # Double-click launcher
├── setup.py                 # Package setup
├── pyproject.toml           # Modern config
├── requirements.txt         # Dependencies
├── build_exe.bat            # Windows EXE builder
├── README.md
├── LICENSE
└── .github/
    └── workflows/
        └── ci.yml           # CI/CD pipeline
```

## Development

```bash
# Clone the repo
git clone https://github.com/yourusername/ghostly.git
cd ghostly

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
.venv\Scripts\activate     # Windows

# Install in dev mode
pip install -e ".[dev]"

# Run tests
pytest

# Run linter
ruff check .

# Format code
ruff format .

# Run mypy
mypy ghostly/

# Start development server
ghostly --port 3000
```

## Contributing

Contributions are welcome! Please read our [Contributing Guide](CONTRIBUTING.md) first.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing`)
3. Commit your changes (`git commit -m 'feat: add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing`)
5. Open a Pull Request

## Roadmap

- [ ] User accounts and authentication
- [ ] Multiple site support
- [ ] Custom event tracking
- [ ] Funnel analysis
- [ ] A/B testing support
- [ ] Email reports
- [ ] Slack/Discord webhooks
- [ ] Export to CSV/JSON
- [ ] Mobile app
- [ ] Chrome extension

## License

MIT License - see [LICENSE](LICENSE) for details.

## Support

- **Documentation**: [Wiki](https://github.com/yourusername/ghostly/wiki)
- **Issues**: [GitHub Issues](https://github.com/yourusername/ghostly/issues)
- **Discussions**: [GitHub Discussions](https://github.com/yourusername/ghostly/discussions)

---

<div align="center">
  <p>
    <strong>Ghostly Analytics</strong> - Your analytics, your data, your privacy.
  </p>
  <p>
    Made with care for privacy-conscious developers.
  </p>
</div>
