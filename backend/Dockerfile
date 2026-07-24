FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app \
    && mkdir -p /app/data/raw \
    && chown -R app:app /app

COPY pyproject.toml README.md alembic.ini ./
RUN mkdir -p src/gold_intel \
    && printf '__version__ = "0.1.0"\n' > src/gold_intel/__init__.py \
    && pip install --no-cache-dir . \
    && rm -rf src

COPY migrations ./migrations
COPY src ./src
RUN pip install --no-cache-dir --no-deps .

USER app

EXPOSE 8000

CMD ["uvicorn", "gold_intel.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM runtime AS test
USER root
COPY tests ./tests
RUN pip install --no-cache-dir \
    "hypothesis>=6.120,<7" \
    "mypy>=1.14,<2" \
    "pytest>=8.3,<9" \
    "pytest-asyncio>=0.25,<1" \
    "pytest-cov>=6,<7" \
    "ruff>=0.9,<1"
USER app
CMD ["pytest", "-q"]
