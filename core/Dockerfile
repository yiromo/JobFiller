FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        texlive-latex-base \
        texlive-latex-recommended \
        texlive-latex-extra \
        texlive-fonts-recommended \
        lmodern \
        curl \
        unzip \
    && rm -rf /var/lib/apt/lists/*

RUN set -eu; \
    if curl -fsSL --retry 3 -o /tmp/fontawesome5.zip \
        https://mirrors.ctan.org/fonts/fontawesome5.zip; then \
        unzip -qo /tmp/fontawesome5.zip -d /tmp/fontawesome5; \
        src=/tmp/fontawesome5/fontawesome5; \
        install -d /usr/share/texmf/tex/latex/fontawesome5 \
            /usr/share/texmf/fonts/type1/public/fontawesome5 \
            /usr/share/texmf/fonts/tfm/public/fontawesome5 \
            /usr/share/texmf/fonts/enc/dvips/fontawesome5 \
            /usr/share/texmf/fonts/map/dvips/fontawesome5; \
        cp "$src"/tex/* /usr/share/texmf/tex/latex/fontawesome5/; \
        cp "$src"/type1/*.pfb /usr/share/texmf/fonts/type1/public/fontawesome5/; \
        cp "$src"/tfm/*.tfm /usr/share/texmf/fonts/tfm/public/fontawesome5/; \
        cp "$src"/enc/*.enc /usr/share/texmf/fonts/enc/dvips/fontawesome5/; \
        cp "$src"/map/*.map /usr/share/texmf/fonts/map/dvips/fontawesome5/; \
        mktexlsr; \
        updmap-sys --enable Map=fontawesome5.map; \
        mktexlsr; \
        rm -rf /tmp/fontawesome5 /tmp/fontawesome5.zip; \
    else \
        echo "fontawesome5 unavailable from CTAN; generated CVs will render without icons"; \
    fi

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src/ ./

EXPOSE 8000

CMD ["sh", "-c", "uv run --no-sync python manage.py migrate --noinput && uv run --no-sync gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 2 --threads 4 --timeout 180 --access-logfile - --error-logfile -"]
