# My Tool

PyQt5 application for Facebook group management and monitoring.

## Project Structure

```
my_tool/
├── app/              # Main application code
├── data/             # Data directory (database, cache, etc.)
├── logs/             # Log files
├── tests/            # Unit tests
├── scripts/          # Utility scripts
└── requirements.txt  # Project dependencies
```

## Installation

1. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Copy `.env.example` to `.env` and configure:
   ```bash
   cp .env.example .env
   ```

## Running the Application

```bash
python run.py
```

## Development

Install development dependencies:
```bash
pip install -r requirements-dev.txt
```

Run tests:
```bash
pytest
```

## License

MIT
